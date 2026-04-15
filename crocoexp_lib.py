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
    return Path(__file__).resolve().parent


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
    croco_in = input_dir / "croco.in"
    text = read_text_best_effort(croco_in)
    names = set()
    if not text:
        return names, ["croco.in could not be parsed as text; asset reference detection is partial."]
    for match in re.finditer(r"([A-Za-z0-9_./@+-]+\.(?:nc|nc4|cdf|netcdf))", text, re.IGNORECASE):
        names.add(Path(match.group(1)).name)
    return names, []


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
            "docker_mount_policy": "mount_entire_CROCO_EXPERIMENTS",
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


def refresh_manifest(args, command_name="import"):
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
            "mode": "rw",
            "purpose": "compile_backend_mount",
        }
    ]
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
    )
    write_manifest(manifest, paths["manifest"])
    return manifest, paths


def append_command(manifest, command, arguments, inputs_used, staging_decisions, mappings, logs, reports, warnings, findings, failure_category, exit_code, docker_image=None):
    entry = {
        "id": f"command.{len(manifest.get('commands', [])) + 1}",
        "timestamp": utc_now(),
        "command": command,
        "arguments": arguments,
        "inputs_used": inputs_used,
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


def write_compile_script(paths, stage, output):
    script = stage / "compile_inside_docker.sh"
    exps_root = paths["experiments_root"]
    rel_stage = rel_to(stage, exps_root)
    rel_output = rel_to(output, exps_root)
    text = f"""#!/usr/bin/env bash
set -euo pipefail
cd "{CONTAINER_ROOT}/{rel_stage}"
CROCO_SRC="${{CROCO_SRC:-{CONTAINER_ROOT}/croco-v2.1.2/OCEAN}}"
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


def cmd_compile(args):
    paths = experiment_paths(args)
    try:
        if not paths["manifest"].exists():
            manifest, paths = refresh_manifest(args, "import")
            write_import_report(manifest, paths["metadata"] / "import_report.md")
        else:
            ensure_importable(paths)
            manifest = load_manifest(paths["manifest"])
        stage, logs, output, staged = stage_compile_inputs(paths)
        script = write_compile_script(paths, stage, output)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = logs / f"compile_{args.experiment_name}_{ts}.log"
        report_path = paths["metadata"] / "compile_report.md"
        docker_cmd = [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{paths['experiments_root']}:{CONTAINER_ROOT}",
            "-w",
            f"{CONTAINER_ROOT}/{rel_to(stage, paths['experiments_root'])}",
            "-e",
            f"NPROCS={args.jobs}",
            args.image,
            "bash",
            str(Path(container_path(script, paths["experiments_root"]))),
        ]
        findings = ["Compile is an attempted Docker-backed build; runtime semantic findings do not block it by default."]
        manifest["compile_time"]["staged_inputs"] = staged
        manifest["docker_backend"]["image"] = args.image
        manifest["docker_backend"]["working_directory"] = container_path(stage, paths["experiments_root"])
        manifest["docker_backend"]["compile_command_summary"] = " ".join(docker_cmd)
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
            inputs_used=[s["source"] for s in staged],
            staging_decisions=staged + [{"source": str(script), "destination": str(script), "reason": "generated_compile_wrapper"}],
            mappings=manifest["docker_backend"]["mounts"],
            logs=[str(log_path)],
            reports=[str(report_path)],
            warnings=manifest.get("reporting", {}).get("warnings", []),
            findings=findings,
            failure_category=failure_category,
            exit_code=exit_code,
            docker_image=args.image,
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
