import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = "0.1"
CONTAINER_ROOT = "/opt/CROCO_EXPERIMENTS"
DEFAULT_DOCKER_IMAGE = "domarcroco/images-for-croco:base_croco_msot-1.0.0"
PRIMARY_ARTIFACTS = ("croco.in", "cppdefs.h", "param.h")
DATA_SUFFIXES = {".nc", ".nc4", ".cdf", ".netcdf"}
CONFIG_SUFFIXES = {".in", ".h", ".F", ".F90", ".f", ".f90", ".txt", ".env"}


class CrocoexpError(Exception):
    def __init__(self, message, exit_code=1, failure_category="general"):
        super().__init__(message)
        self.exit_code = exit_code
        self.failure_category = failure_category


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def repo_root():
    override = os.environ.get("CROCOEXP_REPO_ROOT")
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parent


def setup_paths():
    base = repo_root() / ".crocoexp"
    return {
        "dir": base,
        "config": base / "config.json",
        "report": base / "setup_report.md",
        "sources": base / "sources.json",
    }


def experiments_root(args):
    root = Path(args.experiments_root)
    if not root.is_absolute():
        root = repo_root() / root
    return root.resolve()


def experiment_paths(args):
    exp_root = experiments_root(args) / args.experiment_name
    return {
        "experiments_root": experiments_root(args),
        "experiment_root": exp_root,
        "input": exp_root / "input",
        "metadata": exp_root / "metadata",
        "build": exp_root / "build",
        "runs": exp_root / "runs",
        "manifest": exp_root / "metadata" / "manifest.json",
    }


def sources_root(args):
    return experiments_root(args) / "sources"


def rel_to(path, root):
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def container_path(path, exps_root):
    rel = rel_to(path, exps_root)
    return f"{CONTAINER_ROOT}/{rel}"


def sha256_file(path, max_bytes=None):
    h = hashlib.sha256()
    total = 0
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            total += len(chunk)
            if max_bytes is not None and total > max_bytes:
                return None
            h.update(chunk)
    return h.hexdigest()


def sha256_tree(path):
    h = hashlib.sha256()
    for item in sorted(p for p in path.rglob("*") if p.is_file()):
        if ".git" in item.parts:
            continue
        rel = rel_to(item, path)
        h.update(rel.encode("utf-8", errors="replace"))
        h.update(b"\0")
        with item.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
    return h.hexdigest()


def git_value(path, args):
    try:
        proc = subprocess.run(["git", "-C", str(path)] + args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    except FileNotFoundError:
        return None
    if proc.returncode != 0:
        return None
    value = proc.stdout.strip()
    return value or None


def detect_source_layout(path):
    if (path / "OCEAN" / "jobcomp").is_file():
        return "croco_ocean_subdir"
    if (path / "jobcomp").is_file():
        return "jobcomp_at_root"
    if (path / "OCEAN").is_dir():
        return "ocean_subdir_without_jobcomp"
    return "unknown"


def file_kind(path):
    if path.name in PRIMARY_ARTIFACTS:
        return "primary_artifact"
    if path.name == "analytical.F":
        return "compile_code"
    if path.suffix in DATA_SUFFIXES:
        return "runtime_data"
    if path.suffix in CONFIG_SUFFIXES:
        return "config_or_code"
    return "other_user_file"


def role_for(path):
    if path.name == "croco.in":
        return "croco_in"
    if path.name == "cppdefs.h":
        return "cppdefs_h"
    if path.name == "param.h":
        return "param_h"
    if path.name == "analytical.F":
        return "analytical_f"
    if path.suffix in DATA_SUFFIXES:
        return "runtime_asset"
    return "other_user_file"


def read_text_best_effort(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def referenced_names(input_dir):
    refs, warnings = referenced_asset_refs(input_dir)
    return {ref["name"] for ref in refs}, warnings


def referenced_asset_refs(input_dir):
    croco_in = input_dir / "croco.in"
    text = read_text_best_effort(croco_in)
    refs = []
    warnings = []
    if not text:
        return refs, ["croco.in could not be parsed as text; asset reference detection is partial."]
    output_keys = {"HISNAME", "AVGNAME", "RSTNAME", "DIANAME", "STANAME", "FLTNAME"}
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "!")):
            continue
        key = None
        value_text = stripped
        if "==" in stripped:
            key, value_text = stripped.split("==", 1)
            key = key.strip().upper()
        if key in output_keys:
            continue
        for match in re.finditer(r"([A-Za-z0-9_./@+-]+\.(?:nc|nc4|cdf|netcdf))", value_text, re.IGNORECASE):
            raw = match.group(1).strip().strip("'\"")
            refs.append(
                {
                    "artifact": "input/croco.in",
                    "line": lineno,
                    "key": key,
                    "value": raw,
                    "name": Path(raw).name,
                    "placeholder": "@" in raw,
                }
            )
    return refs, warnings


def evidence_item(path, input_dir, exps_root):
    stat = path.stat()
    is_data = path.suffix in DATA_SUFFIXES
    return {
        "id": f"evidence.{rel_to(path, input_dir).replace(os.sep, '.')}",
        "role": role_for(path),
        "host_path": str(path),
        "container_path": container_path(path, exps_root),
        "relative_path_from_input": rel_to(path, input_dir),
        "exists": True,
        "kind": file_kind(path),
        "size_bytes": stat.st_size,
        "content_hash": None if is_data else sha256_file(path),
        "last_modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).replace(microsecond=0).isoformat(),
        "provenance": ["input_scan"],
    }


def classify_asset(path, input_dir, referenced):
    name = path.name
    kind = file_kind(path)
    is_data = path.suffix in DATA_SUFFIXES
    if name in PRIMARY_ARTIFACTS:
        classification = "required"
        reason = "Primary artifact required for builder import and metadata generation."
        copy_policy = "stage_copy_allowed"
    elif name == "analytical.F":
        classification = "optional"
        reason = "Optional compile code artifact; staged for compile when present."
        copy_policy = "stage_copy_allowed"
    elif is_data and name in referenced:
        classification = "required"
        reason = "Parser-level croco.in reference selected this runtime data asset for staging/mounting metadata."
        copy_policy = "remain_in_input"
    elif is_data:
        classification = "optional"
        reason = "Runtime data asset discovered in input/ but not selected by first-pass croco.in parsing."
        copy_policy = "remain_in_input"
    else:
        classification = "ignored"
        reason = "User-provided file not selected for staging/mounting in this builder attempt."
        copy_policy = "metadata_only"
    return classification, reason, copy_policy, kind


def asset_item(path, input_dir, exps_root, referenced):
    classification, reason, copy_policy, kind = classify_asset(path, input_dir, referenced)
    is_data = path.suffix in DATA_SUFFIXES
    return {
        "id": f"asset.{rel_to(path, input_dir).replace(os.sep, '.')}",
        "role": role_for(path),
        "source": "input_scan",
        "host_path": str(path),
        "container_path": container_path(path, exps_root),
        "relative_path_from_input": rel_to(path, input_dir),
        "referenced_by": [{"artifact": "input/croco.in"}] if path.name in referenced else [],
        "compile_time_relevance": "compile_artifact" if path.name in {"cppdefs.h", "param.h", "analytical.F"} else "not_selected",
        "runtime_relevance": "referenced" if path.name in referenced else "not_selected",
        "classification": classification,
        "classification_reason": reason,
        "provenance": ["input_scan", "first_pass_croco_in_parse"],
        "exists": True,
        "content_hash": None if is_data else sha256_file(path),
        "large_data": is_data,
        "copy_policy": copy_policy,
    }


def empty_manifest(name, paths):
    now = utc_now()
    exps_root = paths["experiments_root"]
    exp_root = paths["experiment_root"]
    return {
        "schema_version": {"version": SCHEMA_VERSION, "created_by": "crocoexp"},
        "experiment": {"name": name, "root_host_path": str(exp_root), "created_at": now, "updated_at": now},
        "paths": {
            "experiments_root_host_path": str(exps_root),
            "experiment_root_host_path": str(exp_root),
            "input_host_path": str(paths["input"]),
            "metadata_host_path": str(paths["metadata"]),
            "build_host_path": str(paths["build"]),
            "runs_host_path": str(paths["runs"]),
            "experiments_root_container_path": CONTAINER_ROOT,
            "experiment_root_container_path": container_path(exp_root, exps_root),
            "input_container_path": container_path(paths["input"], exps_root),
            "metadata_container_path": container_path(paths["metadata"], exps_root),
            "build_container_path": container_path(paths["build"], exps_root),
            "runs_container_path": container_path(paths["runs"], exps_root),
            "docker_mount_policy": "mount_CROCO_EXPERIMENTS_read_only_with_managed_writable_overlays",
        },
        "input_evidence": [],
        "compile_time": {},
        "runtime": {},
        "capabilities": [],
        "assets": {"inventory": [], "classification_counts": {}, "selected_mounts": []},
        "overrides": [],
        "reporting": {},
        "docker_backend": {"mounts": [], "image": None, "working_directory": None, "backend_findings": []},
        "commands": [],
        "snapshots": {"policy": "config_code_only; runtime_data_referenced_not_copied", "snapshot_records": []},
        "history": [],
    }


def load_manifest(path):
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_manifest(manifest, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest["experiment"]["updated_at"] = utc_now()
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")
    tmp.replace(path)


def ensure_importable(paths):
    if not paths["experiment_root"].is_dir():
        raise CrocoexpError(f"missing experiment directory: {paths['experiment_root']}", 3, "missing_artifact")
    if not paths["input"].is_dir():
        raise CrocoexpError(f"missing input directory: {paths['input']}", 3, "missing_artifact")
    missing = [name for name in PRIMARY_ARTIFACTS if not (paths["input"] / name).is_file()]
    if missing:
        raise CrocoexpError(f"missing required input artifact(s): {', '.join(missing)}", 3, "missing_artifact")


def refresh_manifest(args, command_name="import", record_command=True):
    paths = experiment_paths(args)
    ensure_importable(paths)
    paths["metadata"].mkdir(parents=True, exist_ok=True)
    paths["build"].mkdir(parents=True, exist_ok=True)
    paths["runs"].mkdir(parents=True, exist_ok=True)

    old = load_manifest(paths["manifest"])
    manifest = empty_manifest(args.experiment_name, paths)
    if old:
        manifest["experiment"]["created_at"] = old.get("experiment", {}).get("created_at", manifest["experiment"]["created_at"])
        manifest["commands"] = old.get("commands", [])
        manifest["history"] = old.get("history", [])
        manifest["overrides"] = old.get("overrides", [])
        manifest["snapshots"] = old.get("snapshots", manifest["snapshots"])

    old_source_ref = old.get("compile_time", {}).get("source_ref") if old else None
    source_id = getattr(args, "source_id", None)
    if source_id:
        source_ref = resolve_registered_source(source_id, f"{command_name} --source")
    else:
        source_ref = old_source_ref

    referenced, parse_findings = referenced_names(paths["input"])
    files = sorted([p for p in paths["input"].rglob("*") if p.is_file()])
    evidence = [evidence_item(p, paths["input"], paths["experiments_root"]) for p in files]
    assets = [asset_item(p, paths["input"], paths["experiments_root"], referenced) for p in files]
    counts = {}
    for asset in assets:
        counts[asset["classification"]] = counts.get(asset["classification"], 0) + 1

    analytical = paths["input"] / "analytical.F"
    warnings = list(parse_findings)
    findings = []
    if analytical.exists():
        findings.append("input/analytical.F is present and will be staged for compile attempts.")
    else:
        findings.append("input/analytical.F is absent; compile staging will proceed without it.")

    selected_mounts = [
        {
            "host_path": a["host_path"],
            "container_path": a["container_path"],
            "mode": "ro",
            "purpose": "runtime_data_reference",
        }
        for a in assets
        if a["copy_policy"] == "remain_in_input" and a["classification"] in {"required", "optional"}
    ]
    manifest["input_evidence"] = evidence
    manifest["compile_time"] = {
        "source_ref": source_ref,
        "source_artifacts": ["input/cppdefs.h", "input/param.h"] + (["input/analytical.F"] if analytical.exists() else []),
        "parsed_symbols": [],
        "detected_flags": [],
        "dimensions": {},
        "analytical_finding": "present_in_input" if analytical.exists() else "not_present",
        "staged_inputs": [],
        "warnings": [],
        "findings": findings,
    }
    manifest["runtime"] = {
        "source_artifacts": ["input/croco.in"],
        "parsed_keys": {},
        "referenced_assets": sorted(referenced),
        "runtime_requests": [],
        "warnings": warnings,
        "findings": ["croco.in parsing is first-pass and limited to obvious data-file references."],
    }
    manifest["capabilities"] = []
    manifest["assets"] = {
        "inventory": assets,
        "classification_counts": counts,
        "selected_mounts": selected_mounts,
    }
    manifest["reporting"] = {
        "status": "reported_with_warnings" if warnings else "reported_clean",
        "last_reported_at": utc_now(),
        "manifest_hash": None,
        "checks": [],
        "warnings": warnings,
        "ambiguities": [],
        "possible_mismatches": [],
        "contradictions": [],
        "infrastructural_blockers": [],
        "backend_outcome": None,
        "compile_outcome": None,
        "run_outcome": None,
        "strict_policy_result": None,
    }
    manifest["docker_backend"]["mounts"] = [
        {
            "host_path": str(paths["experiments_root"]),
            "container_path": CONTAINER_ROOT,
            "mode": "ro",
            "purpose": "readonly_experiments_root_mount",
        }
    ]
    if record_command:
        append_command(
            manifest,
            command_name,
            [args.experiment_name],
            inputs_used=[f"input/{name}" for name in PRIMARY_ARTIFACTS],
            staging_decisions=[],
            mappings=selected_mounts,
            logs=[],
            reports=[str(paths["metadata"] / "import_report.md")] if command_name == "import" else [],
            warnings=warnings,
            findings=findings,
            failure_category="none",
            exit_code=0,
            source_ref=source_ref,
        )
    write_manifest(manifest, paths["manifest"])
    return manifest, paths


def append_command(manifest, command, arguments, inputs_used, staging_decisions, mappings, logs, reports, warnings, findings, failure_category, exit_code, docker_image=None, source_ref=None):
    entry = {
        "id": f"command.{len(manifest.get('commands', [])) + 1}",
        "timestamp": utc_now(),
        "command": command,
        "arguments": arguments,
        "inputs_used": inputs_used,
        "source_ref": source_ref,
        "staging_decisions": staging_decisions,
        "host_container_mappings": mappings,
        "docker_image": docker_image,
        "logs_produced": logs,
        "reports_produced": reports,
        "snapshots_produced": [],
        "warnings": warnings,
        "findings": findings,
        "failure_category": failure_category,
        "exit_code": exit_code,
    }
    manifest.setdefault("commands", []).append(entry)
    manifest.setdefault("history", []).append(
        {
            "timestamp": entry["timestamp"],
            "command": command,
            "result": failure_category,
            "exit_code": exit_code,
            "manifest_hash_after": None,
        }
    )
    return entry


def write_import_report(manifest, path):
    exp = manifest["experiment"]
    counts = manifest["assets"]["classification_counts"]
    lines = [
        "# Import Report",
        "",
        f"- Experiment: {exp['name']}",
        f"- Root: {exp['root_host_path']}",
        f"- Manifest: {path.parent / 'manifest.json'}",
        f"- Evidence count: {len(manifest['input_evidence'])}",
        f"- analytical.F: {manifest['compile_time']['analytical_finding']}",
        f"- Compile source: {manifest['compile_time'].get('source_ref') or 'none'}",
        f"- Asset classifications: {counts}",
        "",
        "## Warnings",
    ]
    warnings = manifest["reporting"].get("warnings", [])
    lines.extend([f"- {w}" for w in warnings] or ["- none"])
    lines.extend(["", "## Findings"])
    findings = manifest["compile_time"].get("findings", []) + manifest["runtime"].get("findings", [])
    lines.extend([f"- {f}" for f in findings] or ["- none"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def print_or_json(summary, as_json):
    if as_json:
        print(json.dumps(summary, indent=2, sort_keys=True))
        return
    for key, value in summary.items():
        print(f"{key}: {value}")


def load_setup_config():
    path = setup_paths()["config"]
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def configured_default_image():
    config = load_setup_config()
    if config and config.get("default_docker_image"):
        return config["default_docker_image"]
    return DEFAULT_DOCKER_IMAGE


def load_source_registry():
    path = setup_paths()["sources"]
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "sources": {}}
    try:
        with path.open("r", encoding="utf-8") as f:
            registry = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise CrocoexpError(f"unable to read source registry {path}: {e}", 4, "metadata_or_staging")
    if "sources" not in registry or not isinstance(registry["sources"], dict):
        raise CrocoexpError(f"invalid source registry shape: {path}", 4, "metadata_or_staging")
    registry.setdefault("schema_version", SCHEMA_VERSION)
    return registry


def write_source_registry(registry):
    path = setup_paths()["sources"]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(registry, f, indent=2, sort_keys=True)
            f.write("\n")
        tmp.replace(path)
    except OSError as e:
        raise CrocoexpError(f"unable to write source registry {path}: {e}", 4, "metadata_or_staging")


def validate_source_id(source_id):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", source_id or ""):
        raise CrocoexpError(f"invalid source id: {source_id}", 2, "invalid_usage")


def source_ref_from_record(record, selection_source):
    return {
        "source_id": record["source_id"],
        "flavor": record.get("flavor"),
        "declared_version": record.get("declared_version"),
        "host_path": record.get("host_path"),
        "container_path": record.get("container_path"),
        "registry_path": str(setup_paths()["sources"]),
        "origin_path": record.get("origin_path"),
        "git_commit": record.get("git_commit"),
        "git_branch": record.get("git_branch"),
        "detected_layout": record.get("detected_layout"),
        "content_hash": record.get("content_hash"),
        "selected_at": utc_now(),
        "selection_source": selection_source,
    }


def resolve_registered_source(source_id, selection_source):
    validate_source_id(source_id)
    registry = load_source_registry()
    record = registry["sources"].get(source_id)
    if record is None:
        raise CrocoexpError(f"unknown registered source id: {source_id}; install it with 'crocoexp source install'", 4, "metadata_or_staging")
    host_path = Path(record.get("host_path", ""))
    if not host_path.is_dir():
        raise CrocoexpError(f"registered source tree is missing on disk: {host_path}", 3, "missing_artifact")
    return source_ref_from_record(record, selection_source)


def source_compile_host_path(source_ref):
    root = Path(source_ref["host_path"])
    if (root / "OCEAN" / "jobcomp").is_file() or source_ref.get("detected_layout") == "croco_ocean_subdir":
        return root / "OCEAN"
    return root


def summarize_source_registry(registry):
    return [
        {
            "source_id": source_id,
            "flavor": record.get("flavor"),
            "declared_version": record.get("declared_version"),
            "host_path": record.get("host_path"),
            "installed_at": record.get("installed_at"),
        }
        for source_id, record in sorted(registry.get("sources", {}).items())
    ]


def run_docker_command(args):
    return subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def docker_image_status(image):
    proc = run_docker_command(["docker", "image", "inspect", image, "--format", "{{.Id}}"])
    if proc.returncode == 0:
        return True, proc.stdout.strip()
    return False, None


def write_setup_report(config, report_path):
    lines = [
        "# Setup Report",
        "",
        f"- Repo root: {repo_root()}",
        f"- Docker CLI detected: {config['docker_cli_detected']}",
        f"- Docker daemon available: {config['docker_daemon_ok']}",
        f"- Selected image: {config['default_docker_image']}",
        f"- Previous default image: {config.get('previous_default_docker_image') or 'none'}",
        f"- Image present locally: {config['image_present_locally']}",
        f"- Pull attempted: {config.get('pull_attempted', False)}",
        f"- Pull result: {config.get('pull_result') or 'not_attempted'}",
        f"- Config path: {setup_paths()['config']}",
        f"- Report path: {report_path}",
        f"- Setup status: {config['setup_status']}",
        f"- Failure category: {config.get('failure_category') or 'none'}",
        "",
        "## Warnings",
    ]
    warnings = config.get("warnings", [])
    lines.extend([f"- {w}" for w in warnings] or ["- none"])
    lines.extend(["", "## Next Suggested Command"])
    if config["setup_status"].startswith("blocked_"):
        lines.append("- Resolve the backend infrastructure issue above, then rerun `crocoexp setup`.")
    else:
        lines.append("- Import an experiment with `crocoexp import <experiment_name>` or compile an imported experiment with `crocoexp compile <experiment_name>`.")
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_setup_state(config, check_only=False):
    paths = setup_paths()
    try:
        paths["dir"].mkdir(parents=True, exist_ok=True)
        if paths["dir"].exists() and not paths["dir"].is_dir():
            raise OSError(f"not a directory: {paths['dir']}")
        if not check_only:
            tmp = paths["config"].with_suffix(".json.tmp")
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, sort_keys=True)
                f.write("\n")
            tmp.replace(paths["config"])
        write_setup_report(config, paths["report"])
    except OSError as e:
        raise CrocoexpError(f"unable to write setup config/report: {e}", 4, "config_write_failed")


def setup_summary(config):
    return {
        "repo_root": str(repo_root()),
        "config_path": str(setup_paths()["config"]),
        "report_path": str(setup_paths()["report"]),
        "default_docker_image": config["default_docker_image"],
        "docker_cli_detected": config["docker_cli_detected"],
        "docker_daemon_ok": config["docker_daemon_ok"],
        "image_present_locally": config["image_present_locally"],
        "image_pulled": config.get("image_pulled", False),
        "setup_status": config["setup_status"],
        "failure_category": config.get("failure_category"),
        "warnings_count": len(config.get("warnings", [])),
    }


def cmd_setup(args):
    selected_image = args.image or DEFAULT_DOCKER_IMAGE
    previous = load_setup_config()
    previous_image = previous.get("default_docker_image") if previous else None
    warnings = []
    if previous_image and previous_image != selected_image:
        warnings.append(f"previous default image differs from selected image: {previous_image}")

    docker_path = shutil.which("docker")
    docker_cli_detected = docker_path is not None
    docker_version = None
    daemon_ok = False
    image_present = False
    image_id = None
    image_pulled = False
    pull_attempted = False
    pull_result = None
    failure_category = "none"
    setup_status = "ready"
    commands = []

    if docker_cli_detected:
        version_proc = run_docker_command(["docker", "--version"])
        commands.append({"command": "docker --version", "exit_code": version_proc.returncode})
        if version_proc.returncode == 0:
            docker_version = version_proc.stdout.strip()
        info_proc = run_docker_command(["docker", "info"])
        commands.append({"command": "docker info", "exit_code": info_proc.returncode})
        daemon_ok = info_proc.returncode == 0
    else:
        setup_status = "blocked_docker_cli_missing"
        failure_category = "docker_cli_missing"

    if docker_cli_detected and not daemon_ok:
        setup_status = "blocked_docker_daemon"
        failure_category = "docker_daemon_unavailable"

    if docker_cli_detected and daemon_ok:
        image_present, image_id = docker_image_status(selected_image)
        commands.append({"command": f"docker image inspect {selected_image}", "exit_code": 0 if image_present else 1})
        if not image_present and args.pull:
            pull_attempted = True
            pull_proc = run_docker_command(["docker", "pull", selected_image])
            commands.append({"command": f"docker pull {selected_image}", "exit_code": pull_proc.returncode})
            pull_result = "succeeded" if pull_proc.returncode == 0 else "failed"
            if pull_proc.returncode == 0:
                image_pulled = True
                warnings.append("image was newly pulled; compile has not been tested yet")
                image_present, image_id = docker_image_status(selected_image)
                commands.append({"command": f"docker image inspect {selected_image}", "exit_code": 0 if image_present else 1})
            else:
                setup_status = "blocked_image_pull_failed"
                failure_category = "image_pull_failed"
        elif not image_present:
            setup_status = "blocked_image_missing"
            failure_category = "image_missing"

    if setup_status == "ready" and warnings:
        setup_status = "ready_with_warnings"
    if setup_status == "ready":
        warnings.append("backend ready but compile has not been tested yet")
        setup_status = "ready_with_warnings"

    config = {
        "schema_version": SCHEMA_VERSION,
        "default_docker_image": selected_image,
        "previous_default_docker_image": previous_image,
        "docker_cli_detected": docker_cli_detected,
        "docker_cli_path": docker_path,
        "docker_version": docker_version,
        "docker_daemon_ok": daemon_ok,
        "image_present_locally": image_present,
        "image_id": image_id,
        "image_checked_at": utc_now(),
        "image_pulled": image_pulled,
        "pull_attempted": pull_attempted,
        "pull_result": pull_result,
        "last_setup_at": utc_now(),
        "setup_status": setup_status,
        "warnings": warnings,
        "failure_category": failure_category,
        "check_only": bool(args.check_only),
        "force": bool(args.force),
        "commands": commands,
    }

    try:
        write_setup_state(config, check_only=args.check_only)
    except CrocoexpError as e:
        print(f"ERROR: {e}", file=os.sys.stderr)
        return e.exit_code

    summary = setup_summary(config)
    print_or_json(summary, args.json)
    if failure_category in {"docker_cli_missing", "docker_daemon_unavailable", "image_missing", "image_pull_failed"}:
        return 7
    return 0


def cmd_source_install(args):
    try:
        validate_source_id(args.source_id)
        origin = Path(args.path)
        if not origin.is_absolute():
            origin = (Path.cwd() / origin).resolve()
        if not origin.exists():
            raise CrocoexpError(f"missing source path: {origin}", 3, "missing_artifact")
        if not origin.is_dir():
            raise CrocoexpError(f"source path is not a directory: {origin}", 3, "missing_artifact")

        dest = sources_root(args) / args.source_id
        registry = load_source_registry()
        if args.source_id in registry["sources"] and not args.force:
            raise CrocoexpError(f"source id already registered: {args.source_id}; rerun with --force to replace it", 4, "metadata_or_staging")
        if dest.exists():
            if not args.force:
                raise CrocoexpError(f"source destination already exists: {dest}; rerun with --force to replace it", 4, "metadata_or_staging")
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copytree(origin, dest, symlinks=False)
        except OSError as e:
            raise CrocoexpError(f"unable to copy source tree to {dest}: {e}", 4, "metadata_or_staging")

        record = {
            "source_id": args.source_id,
            "host_path": str(dest),
            "container_path": container_path(dest, experiments_root(args)),
            "flavor": args.flavor,
            "declared_version": args.declared_version,
            "installed_at": utc_now(),
            "origin_path": str(origin),
            "notes": args.notes,
            "git_commit": git_value(origin, ["rev-parse", "HEAD"]),
            "git_branch": git_value(origin, ["rev-parse", "--abbrev-ref", "HEAD"]),
            "content_hash": sha256_tree(dest),
            "detected_layout": detect_source_layout(dest),
        }
        registry["sources"][args.source_id] = record
        write_source_registry(registry)
        summary = {
            "source_id": args.source_id,
            "flavor": record["flavor"],
            "declared_version": record["declared_version"],
            "origin_path": record["origin_path"],
            "host_path": record["host_path"],
            "registry_path": str(setup_paths()["sources"]),
            "detected_layout": record["detected_layout"],
        }
        print_or_json(summary, args.json)
        return 0
    except CrocoexpError as e:
        print(f"ERROR: {e}", file=os.sys.stderr)
        return e.exit_code
    except OSError as e:
        print(f"ERROR: source install failed: {e}", file=os.sys.stderr)
        return 4


def cmd_source_list(args):
    try:
        registry = load_source_registry()
        summary = {"registry_path": str(setup_paths()["sources"]), "sources": summarize_source_registry(registry)}
        print_or_json(summary, args.json)
        return 0
    except CrocoexpError as e:
        print(f"ERROR: {e}", file=os.sys.stderr)
        return e.exit_code


def cmd_source_inspect(args):
    try:
        validate_source_id(args.source_id)
        registry = load_source_registry()
        record = registry["sources"].get(args.source_id)
        if record is None:
            raise CrocoexpError(f"unknown registered source id: {args.source_id}", 3, "missing_artifact")
        print_or_json(record, args.json)
        return 0
    except CrocoexpError as e:
        print(f"ERROR: {e}", file=os.sys.stderr)
        return e.exit_code


def cmd_import(args):
    try:
        manifest, paths = refresh_manifest(args, "import")
        report = paths["metadata"] / "import_report.md"
        write_import_report(manifest, report)
        summary = manifest_summary(manifest)
        summary["import_report"] = str(report)
        print_or_json(summary, args.json)
        return 0
    except CrocoexpError as e:
        print(f"ERROR: {e}", file=os.sys.stderr)
        return e.exit_code
    except OSError as e:
        print(f"ERROR: unable to write metadata: {e}", file=os.sys.stderr)
        return 4


def manifest_summary(manifest):
    commands = manifest.get("commands", [])
    last = commands[-1] if commands else None
    primary = {item["role"]: item["exists"] for item in manifest.get("input_evidence", []) if item["role"] in {"croco_in", "cppdefs_h", "param_h"}}
    return {
        "experiment_root": manifest["experiment"]["root_host_path"],
        "primary_artifacts": primary,
        "analytical_F": manifest.get("compile_time", {}).get("analytical_finding"),
        "compile_source": manifest.get("compile_time", {}).get("source_ref"),
        "evidence_count": len(manifest.get("input_evidence", [])),
        "asset_classification_counts": manifest.get("assets", {}).get("classification_counts", {}),
        "warnings_count": len(manifest.get("reporting", {}).get("warnings", [])),
        "findings_count": len(manifest.get("compile_time", {}).get("findings", [])) + len(manifest.get("runtime", {}).get("findings", [])),
        "last_command_status": None if last is None else {"command": last["command"], "failure_category": last["failure_category"], "exit_code": last["exit_code"]},
    }


def cmd_inspect(args):
    paths = experiment_paths(args)
    manifest = load_manifest(paths["manifest"])
    if manifest is None:
        print(f"ERROR: missing manifest: {paths['manifest']}", file=os.sys.stderr)
        return 4
    print_or_json(manifest_summary(manifest), args.json)
    return 0


def stage_compile_inputs(paths):
    stage = paths["build"] / "stage"
    logs = paths["build"] / "logs"
    output = paths["build"] / "output"
    stage.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    staged = []
    for name in ("cppdefs.h", "param.h", "analytical.F"):
        src = paths["input"] / name
        if src.exists():
            dest = stage / name
            shutil.copy2(src, dest)
            staged.append({"source": str(src), "destination": str(dest), "reason": "compile_staging"})
    missing = [name for name in ("cppdefs.h", "param.h") if not (stage / name).exists()]
    if missing:
        raise CrocoexpError(f"missing compile artifact(s): {', '.join(missing)}", 3, "missing_artifact")
    return stage, logs, output, staged


def resolve_compile_source(args, manifest):
    requested = getattr(args, "source_id", None)
    if requested:
        return resolve_registered_source(requested, "compile --source")
    existing = manifest.get("compile_time", {}).get("source_ref")
    if not existing or not existing.get("source_id"):
        raise CrocoexpError("missing compile source; import with '--source <source_id>' or provide compile --source", 3, "missing_artifact")
    return resolve_registered_source(existing["source_id"], "manifest compile_time.source_ref")


def write_compile_script(paths, stage, output, source_ref):
    script = stage / "compile_inside_docker.sh"
    exps_root = paths["experiments_root"]
    rel_stage = rel_to(stage, exps_root)
    rel_output = rel_to(output, exps_root)
    source_compile_path = source_compile_host_path(source_ref)
    source_container = container_path(source_compile_path, exps_root)
    text = f"""#!/usr/bin/env bash
set -euo pipefail
cd "{CONTAINER_ROOT}/{rel_stage}"
CROCO_SRC="${{CROCO_SRC:-{source_container}}}"
if [[ ! -d "${{CROCO_SRC}}" ]]; then
  echo "ERROR: CROCO source directory not found: ${{CROCO_SRC}}"
  exit 70
fi
if [[ ! -f "${{CROCO_SRC}}/jobcomp" ]]; then
  echo "ERROR: CROCO jobcomp not found: ${{CROCO_SRC}}/jobcomp"
  exit 70
fi
cp -f "${{CROCO_SRC}}/jobcomp" ./jobcomp
chmod +x ./jobcomp
if ! command -v nf-config >/dev/null 2>&1; then
  sed -i \\
    -e 's|^NETCDFLIB=$(nf-config --flibs).*|NETCDFLIB="${{CROCO_NETCDFLIB-$NETCDFLIB}}"|g' \\
    -e 's|^NETCDFINC=-I$(nf-config --includedir).*|NETCDFINC="${{CROCO_NETCDFINC-$NETCDFINC}}"|g' \\
    ./jobcomp || true
fi
export CROCO_NETCDFLIB="${{CROCO_NETCDFLIB:--L/opt/intel/netcdf/lib -L/opt/intel/netcdff/lib -lnetcdff -lnetcdf}}"
export CROCO_NETCDFINC="${{CROCO_NETCDFINC:--I/opt/intel/netcdf/include -I/opt/intel/netcdff/include}}"
if [[ -z "${{CROCO_CFT1:-}}" ]]; then
  if command -v ifort >/dev/null 2>&1; then
    export CROCO_CFT1="ifort"
    export CROCO_FFLAGS1="${{CROCO_FFLAGS1:--O3 -fno-alias -i4 -r8 -fp-model precise}}"
  else
    export CROCO_CFT1="gfortran"
    export CROCO_FFLAGS1="${{CROCO_FFLAGS1:--O3 -fdefault-real-8 -fdefault-double-8 -std=legacy}}"
  fi
fi
./jobcomp --src "${{CROCO_SRC}}" --jobs "${{NPROCS:-1}}"
mkdir -p "{CONTAINER_ROOT}/{rel_output}"
find . -maxdepth 2 -type f \\( -name 'croco' -o -name 'croco.exe' -o -name '*.exe' \\) -exec cp -f {{}} "{CONTAINER_ROOT}/{rel_output}/" \\; || true
"""
    script.write_text(text, encoding="utf-8")
    script.chmod(0o755)
    return script


def write_compile_report(manifest, report_path, log_path, failure_category, exit_code):
    lines = [
        "# Compile Report",
        "",
        f"- Experiment: {manifest['experiment']['name']}",
        f"- Status: {failure_category}",
        f"- Exit code: {exit_code}",
        f"- Log: {log_path}",
        f"- Docker image: {manifest.get('docker_backend', {}).get('image')}",
        f"- Compile source: {manifest.get('compile_time', {}).get('source_ref') or 'none'}",
        "",
        "## Staged Inputs",
    ]
    staged = manifest.get("compile_time", {}).get("staged_inputs", [])
    lines.extend([f"- {s['source']} -> {s['destination']}" for s in staged] or ["- none"])
    lines.extend(["", "## Findings"])
    commands = manifest.get("commands", [])
    findings = commands[-1].get("findings", []) if commands else []
    lines.extend([f"- {f}" for f in findings] or ["- none"])
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def generated_run_id():
    return f"dryrun_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def binary_status(paths):
    output = paths["build"] / "output"
    candidates = []
    if output.exists():
        for pattern in ("croco", "croco.exe", "*.exe"):
            candidates.extend(sorted(output.glob(pattern)))
    candidates = [p for p in candidates if p.is_file()]
    return {
        "present": bool(candidates),
        "candidates": [str(p) for p in candidates],
        "message": "binary found" if candidates else "no binary found under build/output; compile may be needed before run",
    }


def select_binary(paths):
    status = binary_status(paths)
    if not status["present"]:
        return None, status
    return sorted(Path(p) for p in status["candidates"])[0], status


def classify_dry_run_assets(paths):
    input_dir = paths["input"]
    exps_root = paths["experiments_root"]
    refs, parse_warnings = referenced_asset_refs(input_dir)
    known_input_keys = {
        "GRDNAME",
        "GRD_FILE",
        "ININAME",
        "INI_FILE",
        "FRCNAME",
        "FRC_FILE",
        "CLMNAME",
        "CLM_FILE",
        "BRYNAME",
        "BRY_FILE",
        "TIDENAME",
        "TIDE_FILE",
        "RSTNAME_IN",
        "RST_FILE",
    }
    files_by_name = {p.name: p for p in input_dir.rglob("*") if p.is_file()}
    inventory = []
    selected_mounts = []
    warnings = list(parse_warnings)
    ambiguities = []
    blockers = []
    seen = set()

    for ref in refs:
        if ref["placeholder"]:
            ambiguities.append(
                {
                    "id": f"ambiguity.placeholder.{ref['line']}",
                    "scope": "runtime",
                    "description": f"Placeholder-like runtime data reference was not selected for staging/mounting: {ref['value']}",
                    "evidence": ref,
                }
            )
            continue
        path = Path(ref["value"])
        host_path = path if path.is_absolute() else input_dir / path
        if not host_path.exists() and ref["name"] in files_by_name:
            host_path = files_by_name[ref["name"]]
        known_key = ref["key"] in known_input_keys if ref["key"] else False
        if known_key:
            classification = "required"
            reason = "Known runtime input key selected this file for staging/mounting in the builder attempt."
        else:
            classification = "ambiguous"
            reason = "Runtime data reference was parsed from an unrecognized key; not treated as CROCO semantic truth."
            ambiguities.append(
                {
                    "id": f"ambiguity.reference.{ref['line']}",
                    "scope": "runtime",
                    "description": f"Unrecognized runtime data key for {ref['value']}",
                    "evidence": ref,
                }
            )
        exists = host_path.exists()
        if classification == "required" and not exists:
            blockers.append(
                {
                    "id": f"blocker.missing_asset.{ref['line']}",
                    "category": "missing_artifact",
                    "description": f"Required staging/mounting asset is missing: {ref['value']}",
                    "evidence": ref,
                    "required_resolution": f"Provide {host_path} under input/ or adjust croco.in.",
                }
            )
        item = {
            "id": f"asset.dryrun.{ref['line']}.{ref['name']}",
            "role": "runtime_asset",
            "source": "croco_in_reference",
            "host_path": str(host_path),
            "container_path": container_path(host_path, exps_root),
            "relative_path_from_input": rel_to(host_path, input_dir),
            "referenced_by": [ref],
            "compile_time_relevance": "not_selected",
            "runtime_relevance": "referenced",
            "classification": classification,
            "classification_reason": reason,
            "provenance": ["input/croco.in", "dry_run_first_pass_parse"],
            "exists": exists,
            "content_hash": None,
            "large_data": host_path.suffix in DATA_SUFFIXES,
            "copy_policy": "remain_in_input" if host_path.suffix in DATA_SUFFIXES else "metadata_only",
        }
        inventory.append(item)
        seen.add(host_path.resolve() if exists else host_path)
        if classification == "required" and exists:
            selected_mounts.append(
                {
                    "host_path": str(host_path),
                    "container_path": container_path(host_path, exps_root),
                    "mode": "ro",
                    "purpose": "dry_run_selected_runtime_asset",
                }
            )

    for path in sorted(p for p in input_dir.rglob("*") if p.is_file()):
        key = path.resolve()
        if key in seen or path.name in PRIMARY_ARTIFACTS or path.name == "analytical.F":
            continue
        if path.suffix in DATA_SUFFIXES:
            classification = "optional"
            reason = "Runtime data asset exists in input/ but was not selected by first-pass dry-run parsing."
            copy_policy = "remain_in_input"
        else:
            classification = "ignored"
            reason = "User-provided file not selected for staging/mounting in this dry-run attempt."
            copy_policy = "metadata_only"
        inventory.append(
            {
                "id": f"asset.dryrun.{rel_to(path, input_dir).replace(os.sep, '.')}",
                "role": role_for(path),
                "source": "input_scan",
                "host_path": str(path),
                "container_path": container_path(path, exps_root),
                "relative_path_from_input": rel_to(path, input_dir),
                "referenced_by": [],
                "compile_time_relevance": "not_selected",
                "runtime_relevance": "not_selected",
                "classification": classification,
                "classification_reason": reason,
                "provenance": ["input_scan", "dry_run_first_pass_parse"],
                "exists": True,
                "content_hash": None if path.suffix in DATA_SUFFIXES else sha256_file(path),
                "large_data": path.suffix in DATA_SUFFIXES,
                "copy_policy": copy_policy,
            }
        )

    counts = {}
    for item in inventory:
        counts[item["classification"]] = counts.get(item["classification"], 0) + 1
    return inventory, counts, selected_mounts, warnings, ambiguities, blockers


def docker_readiness(image):
    docker_path = shutil.which("docker")
    if docker_path is None:
        return False, "docker_backend", "Docker CLI not found on host PATH.", []
    commands = []
    info = run_docker_command(["docker", "info"])
    commands.append({"command": "docker info", "exit_code": info.returncode})
    if info.returncode != 0:
        return False, "docker_backend", "Docker daemon unavailable.", commands
    present, image_id = docker_image_status(image)
    commands.append({"command": f"docker image inspect {image}", "exit_code": 0 if present else 1})
    if not present:
        return False, "docker_backend", f"Docker image not present locally: {image}", commands
    return True, "none", f"Docker backend ready; image id {image_id}", commands


def snapshot_dry_run(paths, manifest, run_dir, inventory, selected_mounts):
    snapshots = run_dir / "snapshots"
    snapshots.mkdir(parents=True, exist_ok=True)
    included = []
    for name in ("croco.in", "cppdefs.h", "param.h", "analytical.F"):
        src = paths["input"] / name
        if src.exists():
            dest = snapshots / name
            shutil.copy2(src, dest)
            included.append(str(dest))
    asset_path = snapshots / "asset_inventory.json"
    asset_path.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    mappings_path = snapshots / "host_container_mappings.json"
    mappings_path.write_text(json.dumps(selected_mounts, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest_path = snapshots / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    included.extend([str(asset_path), str(mappings_path), str(manifest_path)])
    return {
        "id": f"snapshot.{run_dir.name}",
        "run_id": run_dir.name,
        "kind": "dry_run",
        "host_path": str(snapshots),
        "created_at": utc_now(),
        "included_artifacts": included,
        "asset_inventory_ref": str(asset_path),
        "manifest_hash": None,
    }


def write_run_script(paths, run_dir, binary):
    snapshots = run_dir / "snapshots"
    script = snapshots / "run_inside_docker.sh"
    binary_container = container_path(binary, paths["experiments_root"])
    output_container = container_path(run_dir / "output", paths["experiments_root"])
    croco_in_container = container_path(snapshots / "croco.in", paths["experiments_root"])
    text = f"""#!/usr/bin/env bash
set -euo pipefail
mkdir -p "{output_container}"
cd "{output_container}"
if [[ ! -x "{binary_container}" ]]; then
  echo "ERROR: selected binary is not executable: {binary_container}"
  exit 70
fi
"{binary_container}" < "{croco_in_container}"
"""
    script.write_text(text, encoding="utf-8")
    script.chmod(0o755)
    return script


def write_metadata_report(manifest, path):
    lines = [
        "# Experiment Report",
        "",
        f"- Experiment: {manifest['experiment']['name']}",
        f"- Reporting status: {manifest.get('reporting', {}).get('status')}",
        f"- Warnings: {len(manifest.get('reporting', {}).get('warnings', []))}",
        f"- Ambiguities: {len(manifest.get('reporting', {}).get('ambiguities', []))}",
        f"- Possible mismatches: {len(manifest.get('reporting', {}).get('possible_mismatches', []))}",
        f"- Infrastructural blockers: {len(manifest.get('reporting', {}).get('infrastructural_blockers', []))}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_dry_run_report(path, manifest, run_id, image, mode, binary, counts, inventory, mappings, warnings, findings, blockers, outcome):
    def section(title, items):
        lines = ["", f"## {title}"]
        lines.extend(items or ["- none"])
        return lines

    primary = {item["role"]: item["exists"] for item in manifest.get("input_evidence", []) if item["role"] in {"croco_in", "cppdefs_h", "param_h"}}
    lines = [
        "# Dry-Run Report",
        "",
        f"- Experiment root: {manifest['experiment']['root_host_path']}",
        f"- Run id: {run_id}",
        f"- Selected Docker image: {image}",
        f"- Mode: {mode}",
        f"- Primary artifacts: {primary}",
        f"- analytical.F: {manifest.get('compile_time', {}).get('analytical_finding')}",
        f"- Binary present: {binary['present']}",
        f"- Binary candidates: {binary['candidates']}",
        f"- Asset classifications: {counts}",
        f"- Final outcome: {outcome}",
    ]
    lines += section(
        "Required Assets Selected For Staging/Mounting",
        [f"- {a['host_path']} -> {a['container_path']} ({a['classification_reason']})" for a in inventory if a["classification"] == "required"],
    )
    lines += section("Optional Assets", [f"- {a['host_path']} ({a['classification_reason']})" for a in inventory if a["classification"] == "optional"])
    lines += section("Ignored Assets", [f"- {a['host_path']} ({a['classification_reason']})" for a in inventory if a["classification"] == "ignored"])
    lines += section("Ambiguous Assets", [f"- {a['host_path']} ({a['classification_reason']})" for a in inventory if a["classification"] == "ambiguous"])
    lines += section("Host To Container Mappings", [f"- {m['host_path']} -> {m['container_path']} [{m['mode']}]" for m in mappings])
    lines += section("Warnings And Findings", [f"- {w}" for w in warnings + findings])
    lines += section("Infrastructural Blockers", [f"- {b['category']}: {b['description']}" for b in blockers])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_run_report(path, manifest, run_id, image, binary, dry_run_found, counts, inventory, mappings, warnings, findings, blockers, docker_cmd, log_path, output_path, snapshot_path, exit_code, failure_category):
    def section(title, items):
        lines = ["", f"## {title}"]
        lines.extend(items or ["- none"])
        return lines

    primary = {item["role"]: item["exists"] for item in manifest.get("input_evidence", []) if item["role"] in {"croco_in", "cppdefs_h", "param_h"}}
    lines = [
        "# Run Report",
        "",
        f"- Experiment root: {manifest['experiment']['root_host_path']}",
        f"- Run id: {run_id}",
        f"- Selected Docker image: {image}",
        f"- Selected binary: {binary}",
        f"- Primary artifacts: {primary}",
        f"- Dry-run required/found: {dry_run_found}",
        f"- Asset classifications: {counts}",
        f"- Docker command: {docker_cmd}",
        f"- Logs path: {log_path}",
        f"- Output path: {output_path}",
        f"- Snapshot path: {snapshot_path}",
        f"- Final exit status: {exit_code}",
        f"- Failure category: {failure_category}",
    ]
    lines += section(
        "Required Assets Selected For Staging/Mounting",
        [f"- {a['host_path']} -> {a['container_path']} ({a['classification_reason']})" for a in inventory if a["classification"] == "required"],
    )
    lines += section("Host To Container Mappings", [f"- {m['host_path']} -> {m['container_path']} [{m['mode']}]" for m in mappings])
    lines += section("Warnings And Findings", [f"- {w}" for w in warnings + findings])
    lines += section("Infrastructural Blockers", [f"- {b['category']}: {b['description']}" for b in blockers])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def cmd_dry_run(args):
    paths = experiment_paths(args)
    try:
        if not paths["manifest"].exists():
            raise CrocoexpError(
                f"missing manifest: {paths['manifest']}; run 'crocoexp import {args.experiment_name}' first",
                4,
                "metadata_or_staging",
            )
        manifest, paths = refresh_manifest(args, "internal_refresh", record_command=False)
        run_id = args.run_id or generated_run_id()
        run_dir = paths["runs"] / run_id
        reports_dir = run_dir / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        inventory, counts, selected_mounts, warnings, ambiguities, blockers = classify_dry_run_assets(paths)
        binary = binary_status(paths)
        findings = [binary["message"], "Dry-run is artifact-level reporting and does not prove CROCO semantic compatibility."]
        if manifest.get("compile_time", {}).get("analytical_finding") == "present_in_input" and counts.get("required", 0):
            manifest["reporting"].setdefault("possible_mismatches", []).append(
                {
                    "id": "finding.analytical_with_external_data",
                    "description": "analytical.F is present while external runtime data assets are selected for staging/mounting.",
                    "impact": "reported only; not a default blocker",
                }
            )
        docker_image = args.image or configured_default_image()
        docker_mode = "host-only" if args.no_docker else "docker-backed-readiness"
        if args.no_docker:
            docker_ok = True
            docker_failure_category = "none"
            docker_message = "Docker readiness checks skipped by --no-docker."
            docker_commands = []
        else:
            docker_ok, docker_failure_category, docker_message, docker_commands = docker_readiness(docker_image)
            if not docker_ok:
                blockers.append(
                    {
                        "id": "blocker.docker_backend",
                        "category": "docker_backend",
                        "description": docker_message,
                        "evidence": docker_commands,
                        "required_resolution": "Make Docker available or rerun with --no-docker for host-only reporting.",
                    }
                )
        warnings.append(docker_message)
        if not binary["present"]:
            warnings.append(binary["message"])
        report_path = reports_dir / "dry_run_report.md"
        metadata_report = paths["metadata"] / "report.md"
        failure_category = "none"
        exit_code = 0
        if any(b["category"] == "missing_artifact" for b in blockers):
            failure_category = "missing_artifact"
            exit_code = 3
        elif not docker_ok:
            failure_category = docker_failure_category
            exit_code = 7
        status = "reported_with_warnings" if warnings or ambiguities else "reported_clean"
        if exit_code != 0:
            status = "blocked_missing_artifact" if failure_category == "missing_artifact" else "blocked_backend"
        manifest["assets"]["inventory"] = inventory
        manifest["assets"]["classification_counts"] = counts
        manifest["assets"]["selected_mounts"] = selected_mounts
        manifest["reporting"].update(
            {
                "status": status,
                "last_reported_at": utc_now(),
                "warnings": warnings,
                "ambiguities": ambiguities,
                "infrastructural_blockers": blockers,
                "backend_outcome": {"mode": docker_mode, "ok": docker_ok, "message": docker_message},
            }
        )
        manifest["docker_backend"]["image"] = docker_image
        manifest["docker_backend"]["mounts"] = [
            {
                "host_path": str(paths["experiments_root"]),
                "container_path": CONTAINER_ROOT,
                "mode": "ro",
                "purpose": "dry_run_readonly_mapping",
            }
        ] + selected_mounts
        snapshot_record = snapshot_dry_run(paths, manifest, run_dir, inventory, selected_mounts)
        manifest.setdefault("snapshots", {}).setdefault("snapshot_records", []).append(snapshot_record)
        manifest["snapshots"]["latest_dry_run_snapshot"] = snapshot_record
        write_dry_run_report(report_path, manifest, run_id, docker_image, docker_mode, binary, counts, inventory, selected_mounts, warnings, findings, blockers, failure_category)
        write_metadata_report(manifest, metadata_report)
        append_command(
            manifest,
            "dry-run",
            [args.experiment_name],
            inputs_used=[f"input/{name}" for name in PRIMARY_ARTIFACTS],
            staging_decisions=[],
            mappings=selected_mounts,
            logs=[],
            reports=[str(report_path), str(metadata_report)],
            warnings=warnings,
            findings=findings,
            failure_category=failure_category,
            exit_code=exit_code,
            docker_image=docker_image,
            source_ref=manifest.get("compile_time", {}).get("source_ref"),
        )
        write_manifest(manifest, paths["manifest"])
        summary = manifest_summary(manifest)
        summary.update(
            {
                "run_id": run_id,
                "dry_run_report": str(report_path),
                "snapshot": str(run_dir / "snapshots"),
                "mode": docker_mode,
                "binary_present": binary["present"],
                "failure_category": failure_category,
            }
        )
        print_or_json(summary, args.json)
        return exit_code
    except CrocoexpError as e:
        print(f"ERROR: {e}", file=os.sys.stderr)
        return e.exit_code
    except OSError as e:
        print(f"ERROR: metadata_or_staging: {e}", file=os.sys.stderr)
        return 4


def cmd_run(args):
    paths = experiment_paths(args)
    try:
        if not paths["manifest"].exists():
            raise CrocoexpError(
                f"missing manifest: {paths['manifest']}; run 'crocoexp import {args.experiment_name}' first",
                4,
                "metadata_or_staging",
            )
        selected_binary, bin_status = select_binary(paths)
        if selected_binary is None:
            raise CrocoexpError("missing binary/build product under build/output; run 'crocoexp compile' first", 3, "missing_binary")
        manifest, paths = refresh_manifest(args, "internal_refresh", record_command=False)
        run_id = args.run_id or generated_run_id().replace("dryrun_", "run_")
        run_dir = paths["runs"] / run_id
        logs_dir = run_dir / "logs"
        output_dir = run_dir / "output"
        reports_dir = run_dir / "reports"
        snapshots_dir = run_dir / "snapshots"
        for directory in (logs_dir, output_dir, reports_dir, snapshots_dir):
            directory.mkdir(parents=True, exist_ok=True)
        if args.require_dry_run and not (reports_dir / "dry_run_report.md").exists():
            raise CrocoexpError(f"missing required dry-run report: {reports_dir / 'dry_run_report.md'}", 4, "metadata_or_staging")

        inventory, counts, selected_mounts, warnings, ambiguities, blockers = classify_dry_run_assets(paths)
        findings = ["Run is an execution attempt and does not prove CROCO semantic compatibility."]
        if manifest.get("compile_time", {}).get("analytical_finding") == "present_in_input" and counts.get("required", 0):
            manifest["reporting"].setdefault("possible_mismatches", []).append(
                {
                    "id": "finding.run.analytical_with_external_data",
                    "description": "analytical.F is present while external runtime data assets are selected for staging/mounting.",
                    "impact": "reported only; not a default blocker",
                }
            )
        failure_category = "none"
        exit_code = 0
        if any(b["category"] == "missing_artifact" for b in blockers):
            failure_category = "missing_artifact"
            exit_code = 3

        docker_image = args.image or configured_default_image()
        snapshot_record = snapshot_dry_run(paths, manifest, run_dir, inventory, selected_mounts)
        snapshot_record["kind"] = "run"
        manifest.setdefault("snapshots", {}).setdefault("snapshot_records", []).append(snapshot_record)
        manifest["snapshots"]["latest_run_snapshot"] = snapshot_record
        run_script = write_run_script(paths, run_dir, selected_binary)
        log_path = logs_dir / "run.log"
        report_path = reports_dir / "run_report.md"
        metadata_report = paths["metadata"] / "report.md"
        docker_mounts = [
            {
                "host_path": str(paths["experiments_root"]),
                "container_path": CONTAINER_ROOT,
                "mode": "ro",
                "purpose": "readonly_experiments_root_mount",
            },
            {
                "host_path": str(paths["build"]),
                "container_path": container_path(paths["build"], paths["experiments_root"]),
                "mode": "rw",
                "purpose": "read_build_products",
            },
            {
                "host_path": str(paths["metadata"]),
                "container_path": container_path(paths["metadata"], paths["experiments_root"]),
                "mode": "rw",
                "purpose": "run_metadata_reports",
            },
            {
                "host_path": str(paths["runs"]),
                "container_path": container_path(paths["runs"], paths["experiments_root"]),
                "mode": "rw",
                "purpose": "run_logs_outputs_snapshots",
            },
        ]
        docker_cmd = [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{paths['experiments_root']}:{CONTAINER_ROOT}:ro",
            "-v",
            f"{paths['build']}:{container_path(paths['build'], paths['experiments_root'])}:rw",
            "-v",
            f"{paths['metadata']}:{container_path(paths['metadata'], paths['experiments_root'])}:rw",
            "-v",
            f"{paths['runs']}:{container_path(paths['runs'], paths['experiments_root'])}:rw",
            "-w",
            container_path(output_dir, paths["experiments_root"]),
            docker_image,
            "bash",
            container_path(run_script, paths["experiments_root"]),
        ]
        if exit_code == 0:
            try:
                with log_path.open("w", encoding="utf-8") as log:
                    proc = subprocess.run(docker_cmd, stdout=log, stderr=subprocess.STDOUT, text=True)
                if proc.returncode in {125, 126, 127}:
                    failure_category = "docker_backend"
                    exit_code = 7
                elif proc.returncode != 0:
                    failure_category = "run_failure"
                    exit_code = 9
            except FileNotFoundError:
                log_path.write_text("ERROR: docker executable not found on host PATH.\n", encoding="utf-8")
                failure_category = "docker_backend"
                exit_code = 7
        else:
            log_path.write_text("Run was not attempted because required staging/mounting assets are missing.\n", encoding="utf-8")

        status = "reported_with_warnings" if warnings or ambiguities else "reported_clean"
        if failure_category == "missing_artifact":
            status = "blocked_missing_artifact"
        elif failure_category == "missing_binary":
            status = "blocked_missing_binary"
        elif failure_category == "docker_backend":
            status = "blocked_backend"
        elif failure_category == "run_failure":
            status = "blocked_run_failure"
        manifest["assets"]["inventory"] = inventory
        manifest["assets"]["classification_counts"] = counts
        manifest["assets"]["selected_mounts"] = selected_mounts
        manifest["reporting"].update(
            {
                "status": status,
                "last_reported_at": utc_now(),
                "warnings": warnings,
                "ambiguities": ambiguities,
                "infrastructural_blockers": blockers,
                "run_outcome": {"failure_category": failure_category, "exit_code": exit_code, "log": str(log_path)},
            }
        )
        manifest["docker_backend"]["image"] = docker_image
        manifest["docker_backend"]["mounts"] = docker_mounts
        manifest["docker_backend"]["run_command_summary"] = " ".join(docker_cmd)
        dry_run_found = (reports_dir / "dry_run_report.md").exists()
        write_run_report(
            report_path,
            manifest,
            run_id,
            docker_image,
            selected_binary,
            dry_run_found,
            counts,
            inventory,
            selected_mounts,
            warnings,
            findings,
            blockers,
            " ".join(docker_cmd),
            log_path,
            output_dir,
            snapshots_dir,
            exit_code,
            failure_category,
        )
        write_metadata_report(manifest, metadata_report)
        append_command(
            manifest,
            "run",
            [args.experiment_name],
            inputs_used=[f"input/{name}" for name in PRIMARY_ARTIFACTS] + [str(selected_binary)],
            staging_decisions=[{"source": str(run_script), "destination": str(run_script), "reason": "generated_run_wrapper"}],
            mappings=docker_mounts + selected_mounts,
            logs=[str(log_path)],
            reports=[str(report_path), str(metadata_report)],
            warnings=warnings,
            findings=findings,
            failure_category=failure_category,
            exit_code=exit_code,
            docker_image=docker_image,
            source_ref=manifest.get("compile_time", {}).get("source_ref"),
        )
        write_manifest(manifest, paths["manifest"])
        summary = manifest_summary(manifest)
        summary.update(
            {
                "run_id": run_id,
                "run_report": str(report_path),
                "run_log": str(log_path),
                "output_path": str(output_dir),
                "snapshot": str(snapshots_dir),
                "binary": str(selected_binary),
                "failure_category": failure_category,
            }
        )
        print_or_json(summary, args.json)
        return exit_code
    except CrocoexpError as e:
        print(f"ERROR: {e}", file=os.sys.stderr)
        return e.exit_code
    except OSError as e:
        print(f"ERROR: metadata_or_staging: {e}", file=os.sys.stderr)
        return 4


def cmd_compile(args):
    paths = experiment_paths(args)
    try:
        if not paths["manifest"].exists():
            raise CrocoexpError(
                f"missing manifest: {paths['manifest']}; run 'crocoexp import {args.experiment_name}' first",
                4,
                "metadata_or_staging",
            )
        ensure_importable(paths)
        manifest = load_manifest(paths["manifest"])
        source_ref = resolve_compile_source(args, manifest)
        manifest["compile_time"]["source_ref"] = source_ref
        stage, logs, output, staged = stage_compile_inputs(paths)
        script = write_compile_script(paths, stage, output, source_ref)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = logs / f"compile_{args.experiment_name}_{ts}.log"
        report_path = paths["metadata"] / "compile_report.md"
        docker_image = args.image or configured_default_image()
        docker_mounts = [
            {
                "host_path": str(paths["experiments_root"]),
                "container_path": CONTAINER_ROOT,
                "mode": "ro",
                "purpose": "readonly_experiments_root_mount",
            },
            {
                "host_path": source_ref["host_path"],
                "container_path": source_ref["container_path"],
                "mode": "ro",
                "purpose": "registered_compile_source_via_readonly_root_mount",
            },
            {
                "host_path": str(paths["build"]),
                "container_path": container_path(paths["build"], paths["experiments_root"]),
                "mode": "rw",
                "purpose": "compile_build_outputs",
            },
            {
                "host_path": str(paths["metadata"]),
                "container_path": container_path(paths["metadata"], paths["experiments_root"]),
                "mode": "rw",
                "purpose": "compile_metadata_reports",
            },
            {
                "host_path": str(paths["runs"]),
                "container_path": container_path(paths["runs"], paths["experiments_root"]),
                "mode": "rw",
                "purpose": "future_run_records",
            },
        ]
        docker_cmd = [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{paths['experiments_root']}:{CONTAINER_ROOT}:ro",
            "-v",
            f"{paths['build']}:{container_path(paths['build'], paths['experiments_root'])}:rw",
            "-v",
            f"{paths['metadata']}:{container_path(paths['metadata'], paths['experiments_root'])}:rw",
            "-v",
            f"{paths['runs']}:{container_path(paths['runs'], paths['experiments_root'])}:rw",
            "-w",
            f"{CONTAINER_ROOT}/{rel_to(stage, paths['experiments_root'])}",
            "-e",
            f"NPROCS={args.jobs}",
            docker_image,
            "bash",
            str(Path(container_path(script, paths["experiments_root"]))),
        ]
        findings = [
            "Compile is an attempted Docker-backed build; runtime semantic findings do not block it by default.",
            f"Registered compile source selected: {source_ref['source_id']}",
        ]
        manifest["compile_time"]["staged_inputs"] = staged
        manifest["docker_backend"]["image"] = docker_image
        manifest["docker_backend"]["working_directory"] = container_path(stage, paths["experiments_root"])
        manifest["docker_backend"]["compile_command_summary"] = " ".join(docker_cmd)
        manifest["docker_backend"]["mounts"] = docker_mounts
        failure_category = "none"
        exit_code = 0
        try:
            with log_path.open("w", encoding="utf-8") as log:
                proc = subprocess.run(docker_cmd, stdout=log, stderr=subprocess.STDOUT, text=True)
            if proc.returncode == 125 or proc.returncode == 126 or proc.returncode == 127:
                failure_category = "docker_backend"
                exit_code = 7
            elif proc.returncode != 0:
                failure_category = "compile_failure"
                exit_code = 8
        except FileNotFoundError:
            log_path.write_text("ERROR: docker executable not found on host PATH.\n", encoding="utf-8")
            failure_category = "docker_backend"
            exit_code = 7
        append_command(
            manifest,
            "compile",
            [args.experiment_name],
            inputs_used=[source_ref["host_path"]] + [s["source"] for s in staged],
            staging_decisions=staged + [{"source": str(script), "destination": str(script), "reason": "generated_compile_wrapper"}],
            mappings=docker_mounts,
            logs=[str(log_path)],
            reports=[str(report_path)],
            warnings=manifest.get("reporting", {}).get("warnings", []),
            findings=findings,
            failure_category=failure_category,
            exit_code=exit_code,
            docker_image=docker_image,
            source_ref=source_ref,
        )
        manifest["reporting"]["compile_outcome"] = {"failure_category": failure_category, "exit_code": exit_code, "log": str(log_path)}
        write_compile_report(manifest, report_path, log_path, failure_category, exit_code)
        write_manifest(manifest, paths["manifest"])
        summary = manifest_summary(manifest)
        summary.update({"compile_report": str(report_path), "compile_log": str(log_path), "failure_category": failure_category})
        print_or_json(summary, args.json)
        return exit_code
    except CrocoexpError as e:
        print(f"ERROR: {e}", file=os.sys.stderr)
        return e.exit_code
    except OSError as e:
        print(f"ERROR: metadata_or_staging: {e}", file=os.sys.stderr)
        return 4
