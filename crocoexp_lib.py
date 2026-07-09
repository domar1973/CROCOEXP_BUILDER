import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path


SCHEMA_VERSION = "0.1"
SOURCE_REGISTRY_SCHEMA_VERSION = 1
CONTAINER_ROOT = "/opt/CROCO_EXPERIMENTS"
DEFAULT_DOCKER_IMAGE = "domarcroco/images-for-croco:base_croco-1.0.1"
DOCKER_NETCDFLIB = "-L/opt/intel/netcdf/lib -L/opt/intel/netcdff/lib  -lnetcdff -lnetcdf"
DOCKER_NETCDFINC = "-I/opt/intel/netcdf/include -I/opt/intel/netcdff/include"
DOCKER_NETCDF_LD_LIBRARY_PATH = "/opt/intel/netcdf/lib:/opt/intel/netcdff/lib"
PRIMARY_ARTIFACTS = ("croco.in", "cppdefs.h", "param.h")
DATA_SUFFIXES = {".nc", ".nc4", ".cdf", ".netcdf"}
CONFIG_SUFFIXES = {".in", ".h", ".F", ".F90", ".f", ".f90", ".txt", ".env"}
BACKEND_SYMBOLS = ("OPENMP", "MPI", "OPENACC", "XIOS", "OASIS", "AGRIF")
PARALLEL_PARAMS = ("NPP", "NSUB_X", "NSUB_E", "NP_XI", "NP_ETA", "NNODES")


class CrocoexpError(Exception):
    def __init__(self, message, exit_code=1, failure_category="general"):
        super().__init__(message)
        self.exit_code = exit_code
        self.failure_category = failure_category


@dataclass(frozen=True)
class RepoContext:
    repo_root: Path
    invocation_cwd: Path

    def relpath(self, path):
        path = Path(path)
        abs_path = path if path.is_absolute() else self.repo_root / path
        abs_path = abs_path.resolve()
        try:
            return abs_path.relative_to(self.repo_root).as_posix()
        except ValueError:
            return None

    def display_path(self, path):
        rel = self.relpath(path)
        return rel if rel is not None else str(Path(path))

    def resolve_repo_path(self, value, field, command="path resolution", must_exist=False):
        path = Path(value)
        if not path.is_absolute():
            path = self.repo_root / path
        try:
            resolved = path.resolve(strict=must_exist)
        except OSError as e:
            raise CrocoexpError(f"unable to resolve path for {field} in {command}: {value}: {e}", 4, "metadata_or_staging")
        if self.relpath(resolved) is None:
            raise_external_path_error(resolved, field, command)
        return resolved


_ACTIVE_REPO_CONTEXT = None
_ALLOW_EXTERNAL_OPERATIONAL_PATHS = False


def raise_external_path_error(path, field, command):
    raise CrocoexpError(
        "path externo detectado: "
        f"{path}; campo o archivo: {field}; comando: {command}; "
        "decision humana requerida: copiar dentro del repo o redisenar politica de montaje.",
        4,
        "external_path_detected",
    )


def _has_repo_marker(path):
    return (path / ".crocoexp").exists() or (path / "CROCO_EXPERIMENTS").exists()


def detect_repo_root(start=None):
    override = os.environ.get("CROCOEXP_REPO_ROOT")
    if override:
        return Path(override).resolve()
    current = Path(start or Path.cwd()).resolve()
    for candidate in [current] + list(current.parents):
        if _has_repo_marker(candidate):
            return candidate
    try:
        proc = subprocess.run(
            ["git", "-C", str(current), "rev-parse", "--show-toplevel"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return Path(proc.stdout.strip()).resolve()
    except FileNotFoundError:
        pass
    return Path(__file__).resolve().parent


def initialize_repo_context(args=None):
    global _ACTIVE_REPO_CONTEXT, _ALLOW_EXTERNAL_OPERATIONAL_PATHS
    context = RepoContext(repo_root=detect_repo_root(), invocation_cwd=Path.cwd().resolve())
    _ACTIVE_REPO_CONTEXT = context
    _ALLOW_EXTERNAL_OPERATIONAL_PATHS = False
    if args is not None:
        args.repo_context = context
    return context


def current_repo_context():
    global _ACTIVE_REPO_CONTEXT
    if _ACTIVE_REPO_CONTEXT is None:
        _ACTIVE_REPO_CONTEXT = RepoContext(repo_root=detect_repo_root(), invocation_cwd=Path.cwd().resolve())
    return _ACTIVE_REPO_CONTEXT


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def repo_root():
    return current_repo_context().repo_root


def setup_paths():
    base = repo_root() / ".crocoexp"
    return {
        "dir": base,
        "config": base / "config.json",
        "report": base / "setup_report.md",
        "sources": base / "sources.json",
    }


def experiments_root(args):
    global _ALLOW_EXTERNAL_OPERATIONAL_PATHS
    context = getattr(args, "repo_context", None) or current_repo_context()
    root = Path(args.experiments_root)
    explicit_external = root.is_absolute() and args.experiments_root != "CROCO_EXPERIMENTS"
    if not root.is_absolute():
        root = context.repo_root / root
    root = root.resolve()
    if explicit_external and context.relpath(root) is None:
        _ALLOW_EXTERNAL_OPERATIONAL_PATHS = True
    elif _has_repo_marker(context.repo_root) and context.relpath(root) is None:
        raise_external_path_error(root, "--experiments-root", getattr(args, "command", "command"))
    return root


def experiment_paths(args):
    validate_experiment_name(args.experiment_name)
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


def repo_rel(path):
    rel = current_repo_context().relpath(path)
    return rel if rel is not None else str(path)


def posix_rel_to(path, root):
    try:
        return Path(path).relative_to(root).as_posix()
    except ValueError:
        return str(path).replace(os.sep, "/")


INFORMATIONAL_PATH_KEYS = {"origin_path"}


def path_value_to_absolute(value, field, command):
    path = Path(value)
    if path.is_absolute():
        resolved = path.resolve()
        if current_repo_context().relpath(resolved) is None and not _ALLOW_EXTERNAL_OPERATIONAL_PATHS:
            raise_external_path_error(resolved, field, command)
        return resolved
    return current_repo_context().resolve_repo_path(path, field, command)


def normalize_persisted_paths(value, command="metadata write", key=None):
    if isinstance(value, dict):
        return {k: normalize_persisted_paths(v, command, k) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize_persisted_paths(v, command, key) for v in value]
    if not isinstance(value, str) or key in INFORMATIONAL_PATH_KEYS:
        return value
    if key and (key.endswith("_path") or key.endswith("_dir") or key in {"root", "path", "source", "destination", "asset_path", "link_path", "workdir", "output_dir"}):
        path = Path(value)
        if path.is_absolute():
            rel = current_repo_context().relpath(path)
            if rel is not None:
                return rel
        return value.replace(os.sep, "/")
    return value


def strip_legacy_flavor(value):
    if isinstance(value, dict):
        return {k: strip_legacy_flavor(v) for k, v in value.items() if k != "flavor"}
    if isinstance(value, list):
        return [strip_legacy_flavor(v) for v in value]
    return value


def normalize_for_json_write(value, command):
    return normalize_persisted_paths(strip_legacy_flavor(value), command)


def validate_legacy_flavor(value, field, command):
    if value in (None, "croco"):
        return
    if value == "msot":
        raise CrocoexpError(
            f"unsupported legacy source flavor at {field}: msot. CROCOEXP v1.0.1 only supports CROCO sources; MSOT and other pipelines are outside CROCOEXP scope.",
            5,
            "unsupported_source_flavor",
        )
    raise CrocoexpError(
        f"unsupported legacy source flavor at {field}: {value}. CROCOEXP v1.0.1 only supports CROCO sources; migrate this source to a registered CROCO source installation.",
        5,
        "unsupported_source_flavor",
    )


def validate_legacy_flavors(value, field, command):
    if isinstance(value, dict):
        if "flavor" in value:
            validate_legacy_flavor(value.get("flavor"), f"{field}.flavor", command)
        for key, nested in value.items():
            validate_legacy_flavors(nested, f"{field}.{key}", command)
    elif isinstance(value, list):
        for idx, nested in enumerate(value):
            validate_legacy_flavors(nested, f"{field}[{idx}]", command)


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


def sha256_file_if_exists(path):
    try:
        return sha256_file(path)
    except OSError:
        return None


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


def source_tree_stats(path):
    files_count = 0
    bytes_count = 0
    for item in path.rglob("*"):
        if item.is_file():
            files_count += 1
            try:
                bytes_count += item.stat().st_size
            except OSError:
                pass
    return files_count, bytes_count


def detect_source_features(path):
    files = [p for p in path.rglob("*") if p.is_file()]
    lower_names = {p.name.lower() for p in files}
    return {
        "has_cppdefs": any(p.name == "cppdefs.h" for p in files),
        "has_param": any(p.name == "param.h" for p in files),
        "has_jobcomp": any(p.name == "jobcomp" for p in files),
        "has_makefile": "makefile" in lower_names,
    }


def file_kind(path):
    if path.name in PRIMARY_ARTIFACTS:
        return "primary_artifact"
    if path.name == "analytical.F":
        return "compile_code"
    if path.suffix.lower() in DATA_SUFFIXES:
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
    if path.name == "run.env":
        return "ignored_user_file"
    if path.suffix.lower() in DATA_SUFFIXES:
        return "runtime_data"
    return "other_user_file"


def read_text_best_effort(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def unresolved_template_tokens(input_dir):
    croco_in = input_dir / "croco.in"
    text = read_text_best_effort(croco_in)
    if not text:
        return [], ["croco.in could not be read as text; unresolved template token detection is partial."]
    tokens = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for match in re.finditer(r"\$\{[^}\s]+\}", line):
            tokens.append({"artifact": "input/croco.in", "line": lineno, "token": match.group(0)})
    warnings = [
        f"Unresolved template token in input/croco.in line {token['line']}: {token['token']}; CROCOEXP does not substitute it."
        for token in tokens
    ]
    return tokens, warnings


def parse_cppdefs_symbols(input_dir):
    text = read_text_best_effort(input_dir / "cppdefs.h")
    active = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("!", "/*", "*", "//")):
            continue
        match = re.match(r"^\s*#\s*(define|undef)\s+([A-Za-z_][A-Za-z0-9_]*)\b", line)
        if match:
            directive = match.group(1)
            symbol = match.group(2).upper()
            active[symbol] = directive == "define"
    return sorted(symbol for symbol, enabled in active.items() if enabled)


def parse_param_dimensions_from_text(text):
    dimensions = {name.lower(): None for name in PARALLEL_PARAMS}
    for name in PARALLEL_PARAMS:
        match = re.search(rf"\b{name}\b\s*=\s*([0-9]+)", text, re.IGNORECASE)
        if match:
            dimensions[name.lower()] = int(match.group(1))
    return dimensions


def parse_param_dimensions(input_dir):
    return parse_param_dimensions_from_text(read_text_best_effort(input_dir / "param.h"))


def cpp_command():
    return shutil.which("cpp")


def normalized_symbol_name(value):
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def expected_case_symbols_for(paths_or_input_dir):
    if not isinstance(paths_or_input_dir, dict):
        return []
    expected = normalized_symbol_name(paths_or_input_dir["experiment_root"].name)
    symbols = parse_cppdefs_symbols(paths_or_input_dir["input"])
    return [symbol for symbol in symbols if normalized_symbol_name(symbol) == expected]


def source_include_paths_from_manifest(manifest):
    if not manifest:
        return []
    source_ref = manifest.get("compile_time", {}).get("source_ref")
    if not source_ref or not source_ref.get("host_path"):
        return []
    root = path_value_to_absolute(source_ref["host_path"], "compile_time.source_ref.host_path", "source include resolution")
    paths = [root]
    if (root / "OCEAN").is_dir():
        paths.append(root / "OCEAN")
    return paths


def effective_cpp_symbols(input_dir, include_paths=None):
    cpp = cpp_command()
    include_paths = [Path(input_dir)] + [Path(p) for p in (include_paths or []) if Path(p) != Path(input_dir)]
    probe = f'#include "{(input_dir / "cppdefs.h").resolve()}"\n'
    command = [cpp or "cpp", "-traditional", "-dM", "-E", "-DLinux"]
    for include_path in include_paths:
        command.extend(["-I", str(include_path)])
    command.append("-")
    diagnostics = {
        "source": "freshly_preprocessed",
        "probe_file": "stdin",
        "probe_content": probe.strip(),
        "cpp_command": " ".join(command),
        "cpp_returncode": None,
        "cpp_stderr": "",
        "working_directory": str(input_dir),
        "include_paths": [str(p) for p in include_paths],
        "active_symbol_count": 0,
        "contains_OPENMP": False,
        "contains_MPI": False,
        "sample_symbols": [],
        "input_cppdefs_path": str(input_dir / "cppdefs.h"),
        "input_cppdefs_hash": sha256_file_if_exists(input_dir / "cppdefs.h"),
    }
    if cpp is None:
        diagnostics.update({"source": "raw_fallback", "cpp_stderr": "C preprocessor 'cpp' was not found."})
        return None, None, ["C preprocessor 'cpp' was not found; falling back to raw cppdefs.h parsing with low confidence."], diagnostics
    proc = subprocess.run(
        command,
        input=probe,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(input_dir),
    )
    diagnostics["cpp_returncode"] = proc.returncode
    diagnostics["cpp_stderr"] = proc.stderr.strip()
    if proc.returncode != 0:
        diagnostics["source"] = "raw_fallback"
        return None, None, [f"Unable to preprocess input/cppdefs.h; falling back to raw parsing with low confidence: {proc.stderr.strip()}"], diagnostics
    symbols = []
    for line in proc.stdout.splitlines():
        match = re.match(r"^#define\s+([A-Za-z_][A-Za-z0-9_]*)\b", line)
        if match:
            symbols.append(match.group(1).upper())
    symbols = sorted(set(symbols))
    diagnostics.update(
        {
            "active_symbol_count": len(symbols),
            "contains_OPENMP": "OPENMP" in symbols,
            "contains_MPI": "MPI" in symbols,
            "sample_symbols": symbols[:25],
        }
    )
    return symbols, proc.stdout, [], diagnostics


def effective_param_text(input_dir, active_symbols, include_paths=None):
    cpp = cpp_command()
    include_paths = [Path(input_dir)] + [Path(p) for p in (include_paths or []) if Path(p) != Path(input_dir)]
    command = [cpp or "cpp", "-traditional", "-E", "-P", "-DLinux"]
    for include_path in include_paths:
        command.extend(["-I", str(include_path)])
    command.extend([f"-D{symbol}" for symbol in sorted(active_symbols)])
    command.append(str(input_dir / "param.h"))
    diagnostics = {
        "source": "freshly_preprocessed",
        "cpp_command": " ".join(command),
        "returncode": None,
        "stderr": "",
        "working_directory": str(input_dir),
        "include_paths": [str(p) for p in include_paths],
        "input_param_path": str(input_dir / "param.h"),
        "input_param_hash": sha256_file_if_exists(input_dir / "param.h"),
        "parsed_NPP": None,
        "parsed_NSUB_X": None,
        "parsed_NSUB_E": None,
    }
    if cpp is None:
        diagnostics.update({"source": "raw_fallback", "stderr": "C preprocessor 'cpp' was not found."})
        return None, ["C preprocessor 'cpp' was not found; falling back to raw param.h parsing with low confidence."], diagnostics
    proc = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=str(input_dir))
    diagnostics["returncode"] = proc.returncode
    diagnostics["stderr"] = proc.stderr.strip()
    if proc.returncode != 0:
        diagnostics["source"] = "raw_fallback"
        return None, [f"Unable to preprocess input/param.h; falling back to raw parsing with low confidence: {proc.stderr.strip()}"], diagnostics
    return proc.stdout, [], diagnostics


def effective_compile_context(paths_or_input_dir, artifact_dir=None, include_paths=None, trust_rejection_reason=None):
    input_dir = paths_or_input_dir["input"] if isinstance(paths_or_input_dir, dict) else paths_or_input_dir
    expected_cases = expected_case_symbols_for(paths_or_input_dir)
    warnings = []
    active_symbols, symbol_dump, symbol_warnings, symbol_diag = effective_cpp_symbols(input_dir, include_paths=include_paths)
    warnings.extend(symbol_warnings)
    confidence = "effective_preprocessor"
    symbol_source = "cpp -traditional -dM -E -DLinux input/cppdefs.h"
    if active_symbols is None:
        active_symbols = parse_cppdefs_symbols(input_dir)
        symbol_dump = "\n".join(f"#define {symbol} 1" for symbol in active_symbols) + ("\n" if active_symbols else "")
        confidence = "raw_fallback_low"
        symbol_source = "raw_cppdefs_parse_low_confidence"
        symbol_diag.update(
            {
                "active_symbol_count": len(active_symbols),
                "contains_OPENMP": "OPENMP" in active_symbols,
                "contains_MPI": "MPI" in active_symbols,
                "sample_symbols": active_symbols[:25],
            }
        )

    param_text, param_warnings, param_diag = effective_param_text(input_dir, active_symbols, include_paths=include_paths)
    warnings.extend(param_warnings)
    dimension_source = "cpp -traditional -E -P input/param.h with active cppdefs symbols"
    if param_text is None:
        param_text = read_text_best_effort(input_dir / "param.h")
        confidence = "raw_fallback_low"
        dimension_source = "raw_param_parse_low_confidence"
    dimensions = parse_param_dimensions_from_text(param_text)
    param_diag.update(
        {
            "parsed_NPP": dimensions.get("npp"),
            "parsed_NSUB_X": dimensions.get("nsub_x"),
            "parsed_NSUB_E": dimensions.get("nsub_e"),
        }
    )

    active_symbols_path = None
    effective_param_path = None
    provenance_path = None
    provenance = {
        "generated_from_cppdefs_host_path": str((input_dir / "cppdefs.h").resolve()),
        "generated_from_cppdefs_hash": sha256_file_if_exists(input_dir / "cppdefs.h"),
        "generated_from_param_host_path": str((input_dir / "param.h").resolve()),
        "generated_from_param_hash": sha256_file_if_exists(input_dir / "param.h"),
        "cpp_command": symbol_diag.get("cpp_command"),
        "param_cpp_command": param_diag.get("cpp_command"),
        "working_directory": str(input_dir),
        "include_paths": symbol_diag.get("include_paths", []),
        "probe_content": symbol_diag.get("probe_content"),
        "expected_case_symbols": expected_cases,
        "generated_at": utc_now(),
    }
    if artifact_dir is not None:
        artifact_dir.mkdir(parents=True, exist_ok=True)
        active_symbols_path = artifact_dir / "active_cpp_symbols.txt"
        active_symbols_path.write_text(symbol_dump or "", encoding="utf-8")
        effective_param_path = artifact_dir / "effective_param.h"
        effective_param_path.write_text(param_text or "", encoding="utf-8")
        provenance_path = artifact_dir / "effective_preprocessor_provenance.json"
        provenance_path.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    symbol_diag.update(
        {
            "contains_expected_case_symbols": {symbol: symbol in active_symbols for symbol in expected_cases},
            "compile_time_active_symbols_trusted": False,
            "trust_rejection_reason": trust_rejection_reason,
            "fresh_preprocessing_attempted": True,
        }
    )

    return {
        "active_cpp_symbols": active_symbols,
        "active_cpp_symbols_source": str(active_symbols_path) if active_symbols_path else symbol_source,
        "effective_param_source": str(effective_param_path) if effective_param_path else dimension_source,
        "dimensions": dimensions,
        "input_cppdefs_hash": sha256_file_if_exists(input_dir / "cppdefs.h"),
        "input_param_hash": sha256_file_if_exists(input_dir / "param.h"),
        "effective_preprocessor_provenance": provenance,
        "effective_preprocessor_provenance_source": str(provenance_path) if provenance_path else None,
        "active_symbol_resolution": symbol_diag,
        "effective_param_resolution": param_diag,
        "confidence": confidence,
        "warnings": warnings,
    }


def compile_context_rejection_reason(manifest, input_dir=None, expected_case_symbols=None):
    compile_time = manifest.get("compile_time", {})
    compile_outcome = manifest.get("reporting", {}).get("compile_outcome") or {}
    if compile_outcome.get("exit_code") != 0:
        return "compile outcome is missing or not successful"
    if input_dir is not None:
        current_cpp_hash = sha256_file_if_exists(input_dir / "cppdefs.h")
        current_param_hash = sha256_file_if_exists(input_dir / "param.h")
        if compile_time.get("input_cppdefs_hash") != current_cpp_hash or compile_time.get("input_param_hash") != current_param_hash:
            return "cppdefs.h or param.h hash mismatch"
    active = compile_time.get("active_cpp_symbols")
    dimensions = compile_time.get("dimensions")
    if not isinstance(active, list) or not isinstance(dimensions, dict):
        return "compile_time active symbols or dimensions are missing"
    source_path = compile_time.get("active_cpp_symbols_source")
    if source_path and source_path not in {"cpp -traditional -dM -E -DLinux input/cppdefs.h", "raw_cppdefs_parse_low_confidence"}:
        try:
            source_path = path_value_to_absolute(source_path, "compile_time.active_cpp_symbols_source", "compile context validation")
        except CrocoexpError as e:
            return str(e)
    if not source_path or (isinstance(source_path, Path) and not source_path.is_file()):
        return "active_cpp_symbols artifact is missing"
    provenance = compile_time.get("effective_preprocessor_provenance")
    if not isinstance(provenance, dict):
        return "missing effective preprocessor provenance"
    if input_dir is not None:
        cpp_path = str((input_dir / "cppdefs.h").resolve())
        param_path = str((input_dir / "param.h").resolve())
        recorded_cpp = provenance.get("generated_from_cppdefs_host_path")
        recorded_param = provenance.get("generated_from_param_host_path")
        if recorded_cpp:
            recorded_cpp = str(path_value_to_absolute(recorded_cpp, "effective_preprocessor_provenance.generated_from_cppdefs_host_path", "compile context validation"))
        if recorded_param:
            recorded_param = str(path_value_to_absolute(recorded_param, "effective_preprocessor_provenance.generated_from_param_host_path", "compile context validation"))
        if recorded_cpp != cpp_path:
            return "preprocessor provenance cppdefs path mismatch"
        if recorded_param != param_path:
            return "preprocessor provenance param path mismatch"
        if provenance.get("generated_from_cppdefs_hash") != sha256_file_if_exists(input_dir / "cppdefs.h"):
            return "preprocessor provenance cppdefs hash mismatch"
        if provenance.get("generated_from_param_hash") != sha256_file_if_exists(input_dir / "param.h"):
            return "preprocessor provenance param hash mismatch"
    for symbol in expected_case_symbols or []:
        if symbol not in active:
            return f"expected case symbol missing from active symbols: {symbol}"
    return None


def compile_context_from_manifest(manifest, input_dir=None, expected_case_symbols=None):
    reason = compile_context_rejection_reason(manifest, input_dir, expected_case_symbols)
    if reason:
        return None
    compile_time = manifest.get("compile_time", {})
    active = compile_time.get("active_cpp_symbols")
    dimensions = compile_time.get("dimensions")
    symbol_diag = {
        "source": "compile_time.active_cpp_symbols",
        "probe_file": compile_time.get("active_cpp_symbols_source"),
        "cpp_command": None,
        "cpp_returncode": 0,
        "cpp_stderr": "",
        "active_symbol_count": len(active),
        "contains_OPENMP": "OPENMP" in active,
        "contains_MPI": "MPI" in active,
        "sample_symbols": active[:25],
        "input_cppdefs_path": str(input_dir / "cppdefs.h") if input_dir is not None else None,
        "input_cppdefs_hash": compile_time.get("input_cppdefs_hash"),
        "contains_expected_case_symbols": {symbol: symbol in active for symbol in (expected_case_symbols or [])},
        "compile_time_active_symbols_trusted": True,
        "trust_rejection_reason": None,
        "fresh_preprocessing_attempted": False,
    }
    param_diag = {
        "source": compile_time.get("effective_param_source", "compile_time.dimensions"),
        "returncode": 0,
        "stderr": "",
        "input_param_path": str(input_dir / "param.h") if input_dir is not None else None,
        "input_param_hash": compile_time.get("input_param_hash"),
        "parsed_NPP": dimensions.get("npp"),
        "parsed_NSUB_X": dimensions.get("nsub_x"),
        "parsed_NSUB_E": dimensions.get("nsub_e"),
    }
    return {
        "active_cpp_symbols": active,
        "active_cpp_symbols_source": compile_time.get("active_cpp_symbols_source", "manifest compile_time.active_cpp_symbols"),
        "effective_param_source": compile_time.get("effective_param_source", "manifest compile_time.dimensions"),
        "dimensions": dimensions,
        "input_cppdefs_hash": compile_time.get("input_cppdefs_hash"),
        "input_param_hash": compile_time.get("input_param_hash"),
        "active_symbol_resolution": symbol_diag,
        "effective_param_resolution": param_diag,
        "effective_preprocessor_provenance": compile_time.get("effective_preprocessor_provenance"),
        "effective_preprocessor_provenance_source": compile_time.get("effective_preprocessor_provenance_source"),
        "confidence": "successful_compile_evidence",
        "warnings": [],
    }


def runtime_compile_context(paths, manifest=None):
    input_dir = paths["input"] if isinstance(paths, dict) else paths
    expected_cases = expected_case_symbols_for(paths)
    if manifest:
        reason = compile_context_rejection_reason(manifest, input_dir, expected_cases)
        stored = None if reason else compile_context_from_manifest(manifest, input_dir, expected_cases)
        if stored:
            return stored
    else:
        reason = "compile_time.active_cpp_symbols unavailable"
    include_paths = []
    if isinstance(paths, dict):
        include_paths.extend(source_include_paths_from_manifest(manifest))
    return effective_compile_context(paths, include_paths=include_paths, trust_rejection_reason=reason)


def runtime_execution_plan(paths_or_input_dir, compile_context=None):
    input_dir = paths_or_input_dir["input"] if isinstance(paths_or_input_dir, dict) else paths_or_input_dir
    context = compile_context or effective_compile_context(input_dir)
    symbols = set(context["active_cpp_symbols"])
    dimensions = context["dimensions"]
    backend = {name.lower(): name in symbols for name in BACKEND_SYMBOLS}
    warnings = list(context.get("warnings", []))
    blockers = []

    openmp_enabled = backend["openmp"]
    mpi_enabled = backend["mpi"]
    special = [name for name in ("openacc", "xios", "oasis", "agrif") if backend[name]]
    low_confidence = context.get("confidence") not in {"effective_preprocessor", "successful_compile_evidence"}
    if special and not low_confidence:
        for name in special:
            blockers.append(
                {
                    "id": f"blocker.runtime_backend.{name}",
                    "category": "unsupported_runtime_backend",
                    "description": f"{name.upper()} runtime launch profile is not implemented yet; this compiled capability requires specialized backend launch support.",
                    "required_resolution": "Use a supported compile profile or add an explicit runtime launch profile for this backend.",
                }
            )
        parallel_backend = "unsupported_complex"
    elif mpi_enabled and openmp_enabled and not low_confidence:
        blockers.append(
            {
                "id": "blocker.runtime_backend.hybrid",
                "category": "unsupported_runtime_backend",
                "description": "MPI+OPENMP hybrid runtime launch is not implemented yet; expected launcher would require NNODES ranks and OMP_NUM_THREADS=NPP.",
                "required_resolution": "Use serial/OpenMP for now or implement hybrid launch support.",
            }
        )
        parallel_backend = "hybrid"
    elif mpi_enabled and not low_confidence:
        nnodes = dimensions.get("nnodes")
        blockers.append(
            {
                "id": "blocker.runtime_backend.mpi",
                "category": "unsupported_runtime_backend",
                "description": f"MPI runtime launch is not implemented yet; expected launcher would require {nnodes if nnodes is not None else 'NNODES'} ranks.",
                "required_resolution": "Use serial/OpenMP for now or implement mpirun launch support.",
            }
        )
        parallel_backend = "mpi"
    elif openmp_enabled:
        parallel_backend = "openmp"
    else:
        parallel_backend = "serial"
    if low_confidence and (mpi_enabled or special):
        warnings.append("Runtime backend symbols came from low-confidence raw parsing; unsupported backend blockers were not applied.")

    npp = dimensions.get("npp")
    planned_threads = None
    if openmp_enabled:
        if npp is None:
            planned_threads = 1
            warnings.append("OPENMP is enabled but NPP could not be parsed from input/param.h; defaulting OMP_NUM_THREADS=1.")
        else:
            planned_threads = npp

    return {
        "parallel_backend": parallel_backend,
        "confidence": context.get("confidence"),
        "active_cpp_symbols_source": context.get("active_cpp_symbols_source"),
        "effective_param_source": context.get("effective_param_source"),
        "active_symbol_resolution": context.get("active_symbol_resolution", {}),
        "effective_param_resolution": context.get("effective_param_resolution", {}),
        "backend_symbols": {name: backend[name.lower()] for name in BACKEND_SYMBOLS},
        "openmp": {
            "enabled": openmp_enabled,
            "npp": npp,
            "nsub_x": dimensions.get("nsub_x"),
            "nsub_e": dimensions.get("nsub_e"),
            "planned_omp_num_threads": planned_threads,
            "source": "param.h" if openmp_enabled else None,
        },
        "mpi": {
            "enabled": mpi_enabled,
            "np_xi": dimensions.get("np_xi"),
            "np_eta": dimensions.get("np_eta"),
            "nnodes": dimensions.get("nnodes"),
            "planned_mpi_ranks": dimensions.get("nnodes") if mpi_enabled and not blockers else None,
        },
        "openacc": {"enabled": backend["openacc"]},
        "xios": {"enabled": backend["xios"]},
        "oasis": {"enabled": backend["oasis"]},
        "agrif": {"enabled": backend["agrif"]},
        "warnings": warnings,
        "blockers": blockers,
    }


def evidence_item(path, input_dir, exps_root):
    stat = path.stat()
    is_data = path.suffix.lower() in DATA_SUFFIXES
    return {
        "id": f"evidence.{posix_rel_to(path, input_dir).replace('/', '.')}",
        "role": role_for(path),
        "host_path": str(path),
        "container_path": container_path(path, exps_root),
        "relative_path_from_input": posix_rel_to(path, input_dir),
        "exists": True,
        "kind": file_kind(path),
        "size_bytes": stat.st_size,
        "content_hash": None if is_data else sha256_file(path),
        "last_modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).replace(microsecond=0).isoformat(),
        "provenance": ["input_scan"],
        "note": "run.env is ignored; CROCOEXP does not support environment-file substitution." if path.name == "run.env" else None,
    }


def asset_item(path, input_dir, exps_root):
    is_data = path.suffix.lower() in DATA_SUFFIXES
    if path.name in PRIMARY_ARTIFACTS:
        materialization_policy = "copy_config_when_running"
    elif is_data:
        materialization_policy = "symlink_into_work"
    else:
        materialization_policy = "metadata_only"
    return {
        "id": f"asset.{posix_rel_to(path, input_dir).replace('/', '.')}",
        "role": role_for(path),
        "source": "input_scan",
        "host_path": str(path),
        "container_path": container_path(path, exps_root),
        "relative_path_from_input": posix_rel_to(path, input_dir),
        "compile_time_relevance": "compile_artifact" if path.name in {"cppdefs.h", "param.h", "analytical.F"} else "not_selected",
        "runtime_relevance": "runtime_data_asset" if is_data else "not_interpreted",
        "classification": "runtime_data" if is_data else ("primary_artifact" if path.name in PRIMARY_ARTIFACTS else "other_user_file"),
        "classification_reason": "Input tree inventory; croco.in is not parsed for runtime asset staging.",
        "provenance": ["input_scan"],
        "exists": True,
        "content_hash": None if is_data else sha256_file(path),
        "large_data": is_data,
        "copy_policy": materialization_policy,
    }


def import_file_entry(path, experiment_root, kind):
    stat = path.stat()
    return {
        "path": posix_rel_to(path, experiment_root),
        "kind": kind,
        "size_bytes": stat.st_size,
        "sha256": sha256_file(path),
    }


def import_command_string(args):
    parts = ["crocoexp", "import", args.experiment_name]
    source_id = getattr(args, "source_id", None)
    if source_id:
        parts.extend(["--source", source_id])
    return " ".join(parts)


def empty_manifest(name, paths):
    now = utc_now()
    exps_root = paths["experiments_root"]
    exp_root = paths["experiment_root"]
    return {
        "schema_version": 1,
        "implementation_schema": {"version": SCHEMA_VERSION, "created_by": "crocoexp"},
        "experiment": {
            "name": name,
            "root": str(exp_root),
            "input_dir": str(paths["input"]),
            "root_host_path": str(exp_root),
            "created_at": now,
            "updated_at": now,
        },
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
        "runtime_materialization": {},
        "runtime_execution_plan": {},
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
        manifest = json.load(f)
    validate_legacy_flavors(manifest, str(path), "manifest read")
    return strip_legacy_flavor(manifest)


def write_manifest(manifest, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest["experiment"]["updated_at"] = utc_now()
    manifest = normalize_for_json_write(manifest, "manifest write")
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")
    tmp.replace(path)


def ensure_importable(paths):
    if not paths["experiment_root"].is_dir():
        raise CrocoexpError(f"missing experiment directory: {paths['experiment_root']}", 6, "missing_experiment_input")
    if not paths["input"].is_dir():
        raise CrocoexpError(f"missing input directory: {paths['input']}", 6, "missing_experiment_input")
    missing = [name for name in PRIMARY_ARTIFACTS if not (paths["input"] / name).is_file()]
    if missing:
        raise CrocoexpError(f"missing required input artifact(s): {', '.join(missing)}", 3, "missing_artifact")


def same_resolved_path(left, right):
    return Path(left).resolve(strict=False) == Path(right).resolve(strict=False)


def resolve_import_target(args):
    raw_value = getattr(args, "experiment_name")
    raw = Path(raw_value)
    context = getattr(args, "repo_context", None) or current_repo_context()
    if raw_value in {"", ".", ".."}:
        validate_experiment_name(raw_value)
    if raw.is_absolute():
        origin = raw.resolve(strict=False)
    else:
        cwd_candidate = (context.invocation_cwd / raw).resolve(strict=False)
        if cwd_candidate.exists():
            origin = cwd_candidate
        else:
            validate_experiment_name(raw_value)
            canonical_candidate = (experiments_root(args) / raw).resolve(strict=False)
            origin = canonical_candidate
    if not origin.exists():
        raise CrocoexpError(f"missing experiment directory: {origin}", 6, "missing_experiment_input")
    if not origin.is_dir():
        raise CrocoexpError(f"experiment path is not a directory: {origin}", 6, "missing_experiment_input")
    if not os.access(origin, os.R_OK | os.X_OK):
        raise CrocoexpError(f"experiment directory is not readable: {origin}", 6, "missing_experiment_input")
    experiment_name = origin.name
    validate_experiment_name(experiment_name)
    canonical = (experiments_root(args) / experiment_name).resolve(strict=False)
    in_place = same_resolved_path(origin, canonical)
    if canonical.exists() and not in_place:
        raise CrocoexpError(
            f"experiment name already exists: {experiment_name}\n"
            f"Canonical path already present: {repo_rel(canonical)}\n"
            "Choose a different folder name or remove/unimport the existing experiment.",
            4,
            "experiment_exists",
        )
    return {"origin": origin, "canonical": canonical, "experiment_name": experiment_name, "in_place": in_place}


def cleanup_partial_import_copy(path):
    try:
        resolved = Path(path).resolve(strict=False)
        resolved.relative_to(repo_root().resolve())
        if resolved.exists() and not resolved.is_symlink():
            shutil.rmtree(resolved)
            return None
    except (OSError, ValueError) as e:
        return str(e)
    return None


def materialize_import_target(args, target):
    args.experiment_name = target["experiment_name"]
    args.import_copied_from = None
    args.import_copied_to = None
    if target["in_place"]:
        return experiment_paths(args)
    try:
        target["canonical"].parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(target["origin"], target["canonical"], symlinks=True)
    except OSError as e:
        cleanup_error = cleanup_partial_import_copy(target["canonical"])
        cleanup_note = f"; additionally unable to clean partial copy: {cleanup_error}" if cleanup_error else ""
        raise CrocoexpError(f"unable to copy experiment into canonical location: {e}{cleanup_note}", 4, "metadata_or_staging")
    args.import_copied_from = str(target["origin"])
    args.import_copied_to = str(target["canonical"])
    return experiment_paths(args)


def refresh_manifest(args, command_name="import", record_command=True):
    target = resolve_import_target(args)
    args.experiment_name = target["experiment_name"]
    source_ref = resolve_import_source(args, command_name)
    paths = materialize_import_target(args, target)
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

    tokens, token_warnings = unresolved_template_tokens(paths["input"])
    compile_context = runtime_compile_context(paths, old)
    cpp_symbols = parse_cppdefs_symbols(paths["input"])
    execution_plan = runtime_execution_plan(paths["input"], compile_context)
    files = sorted([p for p in paths["input"].rglob("*") if p.is_file()])
    evidence = [evidence_item(p, paths["input"], paths["experiments_root"]) for p in files]
    assets = [asset_item(p, paths["input"], paths["experiments_root"]) for p in files]
    counts = {}
    for asset in assets:
        counts[asset["classification"]] = counts.get(asset["classification"], 0) + 1
    primary_entries = {
        "croco_in": None,
        "cppdefs_h": None,
        "param_h": None,
        "analytical_f": None,
    }
    runtime_data_entries = []
    ordinary_entries = []
    ignored_entries = []
    for path in files:
        role = role_for(path)
        if role in primary_entries:
            primary_entries[role] = import_file_entry(path, paths["experiment_root"], "primary_artifact")
        elif path.suffix.lower() in DATA_SUFFIXES:
            runtime_data_entries.append(import_file_entry(path, paths["experiment_root"], "runtime_data_asset"))
        elif path.name == "run.env":
            ignored_entries.append(import_file_entry(path, paths["experiment_root"], "ignored_user_file"))
        else:
            ordinary_entries.append(import_file_entry(path, paths["experiment_root"], "ordinary_user_file"))

    analytical = paths["input"] / "analytical.F"
    warnings = list(token_warnings)
    if (paths["input"] / "run.env").exists():
        warnings.append("input/run.env is ignored; CROCOEXP does not source env files or substitute croco.in.")
    findings = []
    if analytical.exists():
        findings.append("input/analytical.F is present and will be staged for compile attempts.")
    else:
        findings.append("input/analytical.F is absent; compile staging will proceed without it.")

    selected_mounts = []
    manifest["input_evidence"] = evidence
    manifest["compile_time"] = {
        "source_ref": source_ref,
        "source_artifacts": ["input/cppdefs.h", "input/param.h"] + (["input/analytical.F"] if analytical.exists() else []),
        "parsed_symbols": cpp_symbols,
        "active_cpp_symbols": compile_context["active_cpp_symbols"],
        "active_cpp_symbols_source": compile_context["active_cpp_symbols_source"],
        "active_symbol_resolution": compile_context["active_symbol_resolution"],
        "input_cppdefs_hash": compile_context["input_cppdefs_hash"],
        "input_param_hash": compile_context["input_param_hash"],
        "effective_preprocessor_provenance": compile_context["effective_preprocessor_provenance"],
        "effective_preprocessor_provenance_source": compile_context["effective_preprocessor_provenance_source"],
        "detected_flags": [],
        "dimensions": compile_context["dimensions"],
        "effective_param_source": compile_context["effective_param_source"],
        "effective_param_resolution": compile_context["effective_param_resolution"],
        "analytical_finding": "present_in_input" if analytical.exists() else "not_present",
        "staged_inputs": [],
        "warnings": [],
        "findings": findings,
    }
    manifest["runtime"] = {
        "source_artifacts": ["input/croco.in"],
        "croco_in_present": True,
        "unresolved_template_tokens": tokens,
        "suspicious_absolute_paths": [],
        "referenced_like_strings": [],
        "runtime_requests": [],
        "warnings": warnings,
        "findings": ["input/croco.in is treated as opaque; CROCOEXP does not infer runtime assets from it."],
    }
    manifest["runtime_materialization"] = runtime_materialization_plan(paths, None, None)
    manifest["runtime_materialization"]["status"] = "not_prepared"
    manifest["runtime_execution_plan"] = execution_plan
    manifest["runtime_execution_plan"]["status"] = "not_planned"
    manifest["capabilities"] = []
    manifest["assets"] = {
        "inventory": assets,
        "classification_counts": counts,
        "selected_mounts": selected_mounts,
    }
    manifest["import"] = {
        "imported_at": utc_now(),
        "command": import_command_string(args),
        "status": "imported",
        "warnings": warnings,
    }
    if getattr(args, "import_copied_from", None):
        manifest["import"]["origin_path"] = args.import_copied_from
        manifest["import"]["canonical_path"] = str(paths["experiment_root"])
    manifest["evidence"] = {
        "primary_artifacts": primary_entries,
        "runtime_data_assets": runtime_data_entries,
        "ordinary_user_files": ordinary_entries,
        "ignored_user_files": ignored_entries,
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
        "compile_outcome": old.get("reporting", {}).get("compile_outcome") if old else None,
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
        import_reports = []
        if command_name == "import":
            import_reports = [
                str(paths["metadata"] / "import_report.md"),
                str(paths["metadata"] / "report.md"),
            ]
        append_command(
            manifest,
            command_name,
            [args.experiment_name],
            inputs_used=[f"input/{name}" for name in PRIMARY_ARTIFACTS],
            staging_decisions=[],
            mappings=selected_mounts,
            logs=[],
            reports=import_reports,
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
    primary = manifest.get("evidence", {}).get("primary_artifacts", {})
    source_ref = manifest.get("compile_time", {}).get("source_ref") or {}
    source_id = source_ref.get("source_id") if isinstance(source_ref, dict) else None
    lines = [
        "# Import Report",
        "",
        f"- Experiment: {exp['name']}",
        f"- Root: {exp['root_host_path']}",
        f"- Input directory: {manifest['paths']['input_host_path']}",
        f"- Imported at: {manifest.get('import', {}).get('imported_at') or manifest['experiment']['updated_at']}",
        f"- Manifest: {path.parent / 'manifest.json'}",
        f"- Evidence count: {len(manifest['input_evidence'])}",
        f"- analytical.F: {manifest['compile_time']['analytical_finding']}",
        f"- Selected source ID: {source_id or 'none'}",
        f"- Runtime data asset count: {counts.get('runtime_data', 0)}",
        f"- Ordinary user file count: {len(manifest.get('evidence', {}).get('ordinary_user_files', []))}",
        f"- Ignored user file count: {len(manifest.get('evidence', {}).get('ignored_user_files', []))}",
        "",
        "## Primary Artifacts",
    ]
    for name, entry in primary.items():
        lines.append(f"- {name}: {'found' if entry else 'missing'}")
    lines.extend([
        "",
        "## Scope Disclaimer",
        "",
        "Import records artifact-level findings only. It does not prove scientific correctness, compile correctness, runtime semantic compatibility, or experiment well-posedness.",
        "",
        "## Warnings",
    ])
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
        return {"schema_version": SOURCE_REGISTRY_SCHEMA_VERSION, "sources": {}}
    try:
        with path.open("r", encoding="utf-8") as f:
            registry = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise CrocoexpError(f"unable to read source registry {path}: {e}", 4, "metadata_or_staging")
    if "sources" not in registry or not isinstance(registry["sources"], dict):
        raise CrocoexpError(f"invalid source registry shape: {path}", 4, "metadata_or_staging")
    validate_legacy_flavors(registry, str(path), "source registry read")
    registry = strip_legacy_flavor(registry)
    registry.setdefault("schema_version", SOURCE_REGISTRY_SCHEMA_VERSION)
    return registry


def write_source_registry(registry):
    path = setup_paths()["sources"]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(normalize_for_json_write(registry, "source registry write"), f, indent=2, sort_keys=True)
            f.write("\n")
        tmp.replace(path)
    except OSError as e:
        raise CrocoexpError(f"unable to write source registry {path}: {e}", 4, "metadata_or_staging")


def validate_source_id(source_id):
    if source_id in {".", ".."} or not re.fullmatch(r"[A-Za-z0-9_.-]+", source_id or ""):
        raise CrocoexpError(f"invalid source id: {source_id}", 2, "invalid_usage")


def validate_experiment_name(experiment_name):
    if experiment_name in {".", ".."} or not re.fullmatch(r"[A-Za-z0-9_.-]+", experiment_name or ""):
        raise CrocoexpError(f"invalid experiment name: {experiment_name}", 2, "invalid_usage")


def validate_run_id(run_id):
    if run_id in {".", ".."} or not re.fullmatch(r"[A-Za-z0-9_.-]+", run_id or ""):
        raise CrocoexpError(f"invalid run id: {run_id}", 2, "invalid_usage")


def source_ref_from_record(record, selection_source):
    return {
        "source_id": record["source_id"],
        "declared_version": record.get("declared_version"),
        "host_path": record.get("host_path"),
        "installed_path": record.get("installed_path") or record.get("host_path"),
        "container_path": record.get("container_path"),
        "registry_path": ".crocoexp/sources.json",
        "origin_path": record.get("origin_path"),
        "git_commit": record.get("git_commit"),
        "git_branch": record.get("git_branch"),
        "detected_layout": record.get("detected_layout"),
        "content_hash": record.get("content_hash"),
        "status": "registered",
        "selected_at": utc_now(),
        "selection_source": selection_source,
    }


def resolve_registered_source(source_id, selection_source):
    validate_source_id(source_id)
    registry = load_source_registry()
    record = registry["sources"].get(source_id)
    if record is None:
        raise CrocoexpError(f"unknown registered source id: {source_id}; run 'crocoexp source list' to see available sources", 5, "source_not_found")
    host_path = path_value_to_absolute(record.get("host_path", ""), f".crocoexp/sources.json sources.{source_id}.host_path", selection_source)
    if not host_path.is_dir():
        raise CrocoexpError(f"registered source tree is missing on disk: {host_path}", 5, "source_not_found")
    normalized = dict(record)
    normalized["host_path"] = str(host_path)
    normalized["installed_path"] = str(host_path)
    return source_ref_from_record(normalized, selection_source)


def available_source_records():
    registry = load_source_registry()
    return [(source_id, record) for source_id, record in sorted(registry.get("sources", {}).items())]


def no_sources_error():
    return CrocoexpError(
        "no registered CROCO sources found; install one with 'crocoexp source install /path/to/croco --id croco-v2.1.3'",
        5,
        "source_not_found",
    )


def missing_source_error(experiment_name):
    return CrocoexpError(
        "missing required import source; run 'crocoexp source list' and then "
        f"'crocoexp import {experiment_name} --source <source_id>'",
        5,
        "source_not_found",
    )


def prompt_for_source(args, command_name):
    records = available_source_records()
    if not records:
        raise no_sources_error()
    if not sys.stdin.isatty():
        raise missing_source_error(args.experiment_name)
    print("Available CROCO sources:", file=sys.stderr)
    for idx, (source_id, record) in enumerate(records, start=1):
        version = record.get("declared_version") or "unknown-version"
        path = record.get("host_path") or record.get("installed_path") or "unknown-path"
        print(f"{idx}. {source_id} ({version}) - {path}", file=sys.stderr)
    print("Select a source number, or 'q' to cancel.", file=sys.stderr)
    for _ in range(3):
        choice = input("Source: ").strip()
        if choice.lower() in {"q", "quit", "cancel"}:
            raise CrocoexpError("source selection cancelled; import aborted without writing metadata", 5, "source_not_found")
        try:
            index = int(choice)
        except ValueError:
            print("Invalid selection; enter a number from the list or 'q'.", file=sys.stderr)
            continue
        if 1 <= index <= len(records):
            return resolve_registered_source(records[index - 1][0], f"{command_name} interactive source selection")
        print("Invalid selection; enter a number from the list or 'q'.", file=sys.stderr)
    raise CrocoexpError("invalid source selection; import aborted without writing metadata", 5, "source_not_found")


def resolve_import_source(args, command_name):
    source_id = getattr(args, "source_id", None)
    if source_id:
        return resolve_registered_source(source_id, f"{command_name} --source")
    return prompt_for_source(args, command_name)


def source_compile_host_path(source_ref):
    root = path_value_to_absolute(source_ref["host_path"], "source_ref.host_path", "compile")
    if (root / "OCEAN" / "jobcomp").is_file() or source_ref.get("detected_layout") == "croco_ocean_subdir":
        return root / "OCEAN"
    return root


def summarize_source_registry(registry):
    return [
        {
            "source_id": source_id,
            "declared_version": record.get("declared_version"),
            "host_path": record.get("host_path"),
            "installed_at": record.get("installed_at"),
        }
        for source_id, record in sorted(registry.get("sources", {}).items())
    ]


def manifest_source_ids(manifest):
    ids = set()
    source_ref = manifest.get("compile_time", {}).get("source_ref")
    if isinstance(source_ref, dict) and source_ref.get("source_id"):
        ids.add(source_ref["source_id"])
    legacy_ref = manifest.get("source_ref")
    if isinstance(legacy_ref, dict) and legacy_ref.get("source_id"):
        ids.add(legacy_ref["source_id"])
    for key in ("source_id", "compile_source_id"):
        value = manifest.get(key)
        if isinstance(value, str) and value:
            ids.add(value)
    compile_attempt = manifest.get("compile", {}).get("last_attempt")
    if isinstance(compile_attempt, dict) and compile_attempt.get("source_id"):
        ids.add(compile_attempt["source_id"])
    return ids


def find_source_dependents(args, source_id):
    root = experiments_root(args)
    dependents = []
    manifest_errors = []
    if not root.exists():
        return dependents, manifest_errors
    for manifest_path in sorted(root.glob("*/metadata/manifest.json")):
        try:
            manifest = load_manifest(manifest_path)
        except (OSError, json.JSONDecodeError, CrocoexpError) as e:
            manifest_errors.append({"path": manifest_path, "error": str(e)})
            continue
        if manifest and source_id in manifest_source_ids(manifest):
            dependents.append({"experiment_name": manifest_path.parents[1].name, "manifest_path": manifest_path})
    return dependents, manifest_errors


def safe_source_tree_to_remove(args, record):
    raw_path = record.get("host_path") or record.get("installed_path")
    if not raw_path:
        return None, "source registry has no installed path"
    path = Path(raw_path)
    if not path.is_absolute():
        path = repo_root() / path
    path = path.resolve(strict=False)
    repo = repo_root().resolve()
    managed = sources_root(args).resolve()
    try:
        path.relative_to(repo)
    except ValueError:
        return None, f"registered source path is outside the repo and will not be removed: {path}"
    try:
        path.relative_to(managed)
    except ValueError:
        return None, f"registered source path is outside managed sources and will not be removed: {path}"
    if path.is_symlink():
        return None, f"registered source path is a symlink and will not be followed or removed: {path}"
    if not path.exists():
        return None, f"registered source tree is already absent: {path}"
    if not path.is_dir():
        return None, f"registered source path is not a directory and will not be removed: {path}"
    return path, None


def print_source_uninstall_success(source_id, removed_tree, warnings, dependents):
    print(f"Uninstalled source: {source_id}")
    if removed_tree:
        print(f"Removed installed tree: {repo_rel(removed_tree)}")
    for warning in warnings:
        print(f"WARNING: {warning}")
    if dependents:
        print("Orphaned experiment source references:")
        for item in dependents:
            print(f"  - {item['experiment_name']}")


def confirm_source_uninstall(source_id, dependents):
    print(f"Source {source_id} is used by {len(dependents)} experiment(s):")
    for item in dependents:
        print(f"  - {item['experiment_name']}")
    print("")
    print("Uninstalling it will leave those experiments with orphaned source references.")
    answer = input("Continue? [y/N] ").strip().lower()
    return answer in {"y", "yes"}


def experiment_list_records(args):
    registry = load_source_registry()
    records = []
    root = experiments_root(args)
    if not root.exists():
        return records
    for manifest_path in sorted(root.glob("*/metadata/manifest.json")):
        manifest = load_manifest(manifest_path)
        if not manifest:
            continue
        source_ref = manifest.get("compile_time", {}).get("source_ref")
        source_id = source_ref.get("source_id") if isinstance(source_ref, dict) else None
        if source_id and source_id in registry.get("sources", {}):
            source_status = "available"
        elif source_id:
            source_status = "orphaned"
        else:
            source_status = "missing"
        records.append(
            {
                "experiment_name": manifest_path.parents[1].name,
                "path": repo_rel(manifest_path.parents[1]),
                "manifest_path": repo_rel(manifest_path),
                "source_id": source_id,
                "source_status": source_status,
                "imported_at": manifest.get("import", {}).get("imported_at"),
                "updated_at": manifest.get("experiment", {}).get("updated_at"),
            }
        )
    return records


def print_experiment_list(records):
    if not records:
        print("No experiments registered.")
        print("Import one with:")
        print("  crocoexp import /path/to/experiment --source <source_id>")
        return
    print("Experiments:")
    for record in records:
        print(f"  {record['experiment_name']}")
        print(f"    path: {record['path']}")
        source = record["source_id"] or "none"
        print(f"    source: {source} ({record['source_status']})")
        timestamp = record.get("imported_at") or record.get("updated_at")
        if timestamp:
            print(f"    imported_at: {timestamp}")
        print("")


UNIMPORT_MANAGED_NAMES = ("metadata", "build", "runs", "reports", "snapshots", "logs")


def unimport_paths(args):
    validate_experiment_name(args.experiment_name)
    root = (experiments_root(args) / args.experiment_name).resolve(strict=False)
    repo = repo_root().resolve()
    try:
        root.relative_to(repo)
    except ValueError:
        raise_external_path_error(root, "experiment_name", "experiment unimport")
    return {
        "experiment_root": root,
        "manifest": root / "metadata" / "manifest.json",
    }


def ensure_safe_unimport_root(root):
    if not root.exists():
        raise CrocoexpError(
            f"experiment not found: {root.name}\nRun:\n  crocoexp experiment list",
            3,
            "missing_experiment_input",
        )
    if root.is_symlink():
        raise CrocoexpError(f"experiment path is a symlink and will not be modified: {repo_rel(root)}", 4, "metadata_or_staging")
    if not root.is_dir():
        raise CrocoexpError(f"experiment path is not a directory: {repo_rel(root)}", 6, "missing_experiment_input")


def ensure_imported_experiment_for_unimport(root, manifest_path):
    metadata_dir = root / "metadata"
    if metadata_dir.is_symlink() or manifest_path.is_symlink():
        raise CrocoexpError(f"experiment metadata is a symlink and will not be followed: {repo_rel(metadata_dir)}", 4, "metadata_or_staging")
    if not manifest_path.is_file():
        raise CrocoexpError(
            f"{repo_rel(root)} exists but is not an imported experiment.\nNo files were modified.",
            5,
            "not_imported",
        )
    load_manifest(manifest_path)


def remove_managed_unimport_path(path, experiment_root):
    resolved_parent = path.parent.resolve(strict=False)
    repo = repo_root().resolve()
    exp = experiment_root.resolve(strict=False)
    try:
        resolved_parent.relative_to(repo)
        resolved_parent.relative_to(exp)
    except ValueError:
        raise_external_path_error(path, path.name, "experiment unimport")
    if not path.exists() and not path.is_symlink():
        return False
    if path.is_symlink():
        return False
    if path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    return True


def unimport_experiment(args):
    paths = unimport_paths(args)
    root = paths["experiment_root"]
    ensure_safe_unimport_root(root)
    ensure_imported_experiment_for_unimport(root, paths["manifest"])
    removed = []
    for name in UNIMPORT_MANAGED_NAMES:
        path = root / name
        if remove_managed_unimport_path(path, root):
            removed.append(name)
    preserved = []
    for child in sorted(root.iterdir(), key=lambda item: item.name):
        if child.name not in UNIMPORT_MANAGED_NAMES:
            preserved.append(child.name)
    return {"experiment_name": args.experiment_name, "root": root, "removed": removed, "preserved": preserved}


def print_unimport_success(summary):
    print(f"Unimported experiment: {summary['experiment_name']}")
    input_path = summary["root"] / "input"
    if input_path.exists() or input_path.is_symlink():
        print(f"Preserved user input: {repo_rel(input_path)}")
    if summary["removed"]:
        print("Removed CROCOEXP metadata/build state:")
        for name in summary["removed"]:
            print(f"  {name}")
    else:
        print("Removed CROCOEXP metadata/build state: none")
    preserved = [name for name in summary["preserved"] if name != "input"]
    if preserved:
        print("Preserved possibly user-managed directory:")
        for name in preserved:
            print(f"  {name}")


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
        "previous_default_docker_image": config.get("previous_default_docker_image"),
        "docker_cli_detected": config["docker_cli_detected"],
        "docker_cli_path": config.get("docker_cli_path"),
        "docker_version": config.get("docker_version"),
        "docker_daemon_ok": config["docker_daemon_ok"],
        "image_present_locally": config["image_present_locally"],
        "image_id": config.get("image_id"),
        "image_checked_at": config.get("image_checked_at"),
        "image_pulled": config.get("image_pulled", False),
        "pull_attempted": config.get("pull_attempted", False),
        "pull_result": config.get("pull_result"),
        "setup_status": config["setup_status"],
        "failure_category": config.get("failure_category"),
        "warnings_count": len(config.get("warnings", [])),
        "commands": config.get("commands", []),
    }


def yes_no(value):
    return "yes" if bool(value) else "no"


def print_setup_summary(config):
    summary = setup_summary(config)
    print(f"Docker CLI detected: {yes_no(summary['docker_cli_detected'])}")
    print(f"Docker daemon available: {yes_no(summary['docker_daemon_ok'])}")
    print(f"Selected Docker image: {summary['default_docker_image']}")
    print(f"Previous default image: {summary['previous_default_docker_image'] or 'none'}")
    print(f"Image present locally: {yes_no(summary['image_present_locally'])}")
    print(f"Image pull attempted: {yes_no(summary['pull_attempted'])}")
    if summary["pull_attempted"]:
        print(f"Image pull result: {summary['pull_result'] or 'unknown'}")
    print(f"Setup config path: {summary['config_path']}")
    print(f"Setup report path: {summary['report_path']}")
    print(f"Warning count: {summary['warnings_count']}")
    print(f"Failure category: {summary['failure_category'] or 'none'}")
    print(f"Setup status: {summary['setup_status']}")


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

    if args.json:
        print(json.dumps(setup_summary(config), indent=2, sort_keys=True))
    else:
        print_setup_summary(config)
    if failure_category in {"docker_cli_missing", "docker_daemon_unavailable", "image_missing", "image_pull_failed"}:
        return 7
    return 0


def cmd_source_install(args):
    try:
        validate_source_id(args.source_id)
        origin = Path(args.path)
        if not origin.is_absolute():
            origin = (current_repo_context().invocation_cwd / origin).resolve()
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

        files_count, bytes_count = source_tree_stats(dest)
        detection = detect_source_features(dest)
        record = {
            "source_id": args.source_id,
            "host_path": str(dest),
            "container_path": container_path(dest, experiments_root(args)),
            "declared_version": args.declared_version,
            "installed_at": utc_now(),
            "origin_path": str(origin),
            "installed_from": str(origin),
            "installed_path": str(dest),
            "status": "installed",
            "files_count": files_count,
            "bytes_count": bytes_count,
            "detection": detection,
            "warnings": [],
            "notes": args.notes,
            "git_commit": git_value(origin, ["rev-parse", "HEAD"]),
            "git_branch": git_value(origin, ["rev-parse", "--abbrev-ref", "HEAD"]),
            "content_hash": sha256_tree(dest),
            "detected_layout": detect_source_layout(dest),
            "installed_by_command": "source install",
        }
        registry["sources"][args.source_id] = record
        write_source_registry(registry)
        summary = {
            "source_id": args.source_id,
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


def cmd_source_uninstall(args):
    try:
        validate_source_id(args.source_id)
        registry = load_source_registry()
        record = registry["sources"].get(args.source_id)
        if record is None:
            raise CrocoexpError(f"unknown registered source id: {args.source_id}; run 'crocoexp source list' to see available sources", 5, "source_not_found")

        dependents, manifest_errors = find_source_dependents(args, args.source_id)
        if manifest_errors:
            details = "; ".join(f"{item['path']}: {item['error']}" for item in manifest_errors)
            raise CrocoexpError(f"unable to verify source dependencies because manifest(s) could not be read: {details}", 4, "metadata_or_staging")

        if dependents and not args.force:
            if not sys.stdin.isatty():
                raise CrocoexpError(
                    f"source {args.source_id} is used by {len(dependents)} experiment(s). Re-run with --force to uninstall anyway.",
                    5,
                    "source_in_use",
                )
            if not confirm_source_uninstall(args.source_id, dependents):
                raise CrocoexpError("source uninstall cancelled; no changes made", 5, "source_in_use")

        tree_to_remove, tree_warning = safe_source_tree_to_remove(args, record)
        warnings = [tree_warning] if tree_warning else []
        removed_tree = None
        if tree_to_remove is not None:
            try:
                shutil.rmtree(tree_to_remove)
            except OSError as e:
                raise CrocoexpError(f"unable to remove installed source tree {tree_to_remove}: {e}", 4, "metadata_or_staging")
            removed_tree = tree_to_remove

        registry["sources"].pop(args.source_id)
        write_source_registry(registry)
        print_source_uninstall_success(args.source_id, removed_tree, warnings, dependents)
        return 0
    except CrocoexpError as e:
        print(f"ERROR: {e}", file=os.sys.stderr)
        return e.exit_code


def cmd_experiment_list(args):
    try:
        records = experiment_list_records(args)
        if args.json:
            print(json.dumps({"experiments": records}, indent=2, sort_keys=True))
        else:
            print_experiment_list(records)
        return 0
    except CrocoexpError as e:
        print(f"ERROR: {e}", file=os.sys.stderr)
        return e.exit_code
    except (OSError, json.JSONDecodeError) as e:
        print(f"ERROR: unable to list experiments: {e}", file=os.sys.stderr)
        return 4


def cmd_experiment_unimport(args):
    try:
        summary = unimport_experiment(args)
        print_unimport_success(summary)
        return 0
    except CrocoexpError as e:
        print(f"ERROR: {e}", file=os.sys.stderr)
        return e.exit_code
    except OSError as e:
        print(f"ERROR: unable to unimport experiment: {e}", file=os.sys.stderr)
        return 4


def cmd_import(args):
    try:
        manifest, paths = refresh_manifest(args, "import")
        report = paths["metadata"] / "import_report.md"
        canonical_report = paths["metadata"] / "report.md"
        write_import_report(manifest, report)
        write_import_report(manifest, canonical_report)
        summary = manifest_summary(manifest)
        summary["import_report"] = str(report)
        summary["report"] = str(canonical_report)
        if getattr(args, "import_copied_from", None):
            summary["copied_from"] = args.import_copied_from
            summary["copied_to"] = repo_rel(paths["experiment_root"])
            if not args.json:
                print("Copied experiment into canonical location:")
                print(f"  from: {args.import_copied_from}")
                print(f"  to:   {repo_rel(paths['experiment_root'])}")
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
    counts = manifest.get("assets", {}).get("classification_counts", {})
    return {
        "experiment_name": manifest["experiment"]["name"],
        "experiment_root": manifest["experiment"]["root_host_path"],
        "manifest_path": str(Path(manifest["paths"]["metadata_host_path"]) / "manifest.json"),
        "primary_artifacts": primary,
        "analytical_F": manifest.get("compile_time", {}).get("analytical_finding"),
        "compile_source": manifest.get("compile_time", {}).get("source_ref"),
        "evidence_count": len(manifest.get("input_evidence", [])),
        "netcdf_runtime_data_asset_count": counts.get("runtime_data", 0),
        "asset_classification_counts": counts,
        "warnings_count": len(manifest.get("reporting", {}).get("warnings", [])),
        "findings_count": len(manifest.get("compile_time", {}).get("findings", [])) + len(manifest.get("runtime", {}).get("findings", [])),
        "last_command_status": None if last is None else {"command": last["command"], "failure_category": last["failure_category"], "exit_code": last["exit_code"]},
    }


INSPECT_DISCLAIMER = (
    "Inspect reports recorded artifact-level findings only; it does not prove scientific correctness, "
    "compile correctness, runtime semantic compatibility, or experiment well-posedness."
)


def primary_artifact_summary(manifest):
    primary = manifest.get("evidence", {}).get("primary_artifacts", {})
    legacy = {
        item["role"]: item
        for item in manifest.get("input_evidence", [])
        if item.get("role") in {"croco_in", "cppdefs_h", "param_h", "analytical_f"}
    }
    result = {}
    for key in ("croco_in", "cppdefs_h", "param_h", "analytical_f"):
        entry = primary.get(key) or legacy.get(key)
        result[key] = {
            "present": entry is not None,
            "path": entry.get("path") or f"input/{entry.get('relative_path_from_input')}" if entry else None,
            "kind": entry.get("kind") if entry else None,
        }
    return result


def inspect_read_only_checks(manifest, paths):
    warnings = []

    if not paths["experiment_root"].is_dir():
        warnings.append(f"experiment root missing: {paths['experiment_root']}")
    if not paths["input"].is_dir():
        warnings.append(f"input directory missing: {paths['input']}")
    if not paths["manifest"].is_file():
        warnings.append(f"manifest missing: {paths['manifest']}")

    primary = manifest.get("evidence", {}).get("primary_artifacts", {})
    for name, entry in primary.items():
        if entry and not (paths["experiment_root"] / entry["path"]).exists():
            warnings.append(f"recorded primary artifact missing: {entry['path']} ({name})")

    for entry in manifest.get("evidence", {}).get("runtime_data_assets", []):
        if not (paths["experiment_root"] / entry["path"]).exists():
            warnings.append(f"recorded runtime data asset missing: {entry['path']}")

    source_ref = manifest.get("compile_time", {}).get("source_ref")
    if isinstance(source_ref, dict):
        installed_path = source_ref.get("installed_path") or source_ref.get("host_path")
        if installed_path:
            installed_path = path_value_to_absolute(installed_path, "compile_time.source_ref.installed_path", "inspect")
        if installed_path and not installed_path.exists():
            warnings.append(f"recorded source installed path missing: {installed_path}")

    return {"warnings": warnings}


def inspect_summary(manifest, paths):
    evidence = manifest.get("evidence", {})
    source_ref = manifest.get("compile_time", {}).get("source_ref")
    primary = primary_artifact_summary(manifest)
    reporting_warnings = manifest.get("reporting", {}).get("warnings", [])
    read_only_checks = inspect_read_only_checks(manifest, paths)
    ignored = evidence.get("ignored_user_files", [])
    run_env_ignored = any(entry.get("path") == "input/run.env" for entry in ignored)
    imported_at = manifest.get("import", {}).get("imported_at")
    return {
        "experiment_name": manifest.get("experiment", {}).get("name"),
        "experiment_root": str(paths["experiment_root"]),
        "input_dir": str(paths["input"]),
        "manifest_path": str(paths["manifest"]),
        "import_status": manifest.get("import", {}).get("status"),
        "imported_at": imported_at,
        "warning_count": len(reporting_warnings) + len(read_only_checks["warnings"]),
        "primary_artifacts": primary,
        "runtime_data_asset_count": len(evidence.get("runtime_data_assets", [])),
        "ordinary_user_file_count": len(evidence.get("ordinary_user_files", [])),
        "ignored_user_file_count": len(ignored),
        "run_env_ignored": run_env_ignored,
        "source_ref": source_ref,
        "runtime_materialization_status": manifest.get("runtime_materialization", {}).get("status"),
        "runtime_execution_plan_status": manifest.get("runtime_execution_plan", {}).get("status"),
        "read_only_checks": read_only_checks,
        "disclaimer": INSPECT_DISCLAIMER,
    }


def print_inspect_summary(summary):
    print(f"Experiment name: {summary['experiment_name']}")
    print(f"Experiment root: {summary['experiment_root']}")
    print(f"Input directory: {summary['input_dir']}")
    print(f"Manifest path: {summary['manifest_path']}")
    print(f"Import status: {summary['import_status'] or 'unknown'}")
    print(f"Import timestamp: {summary['imported_at'] or 'unknown'}")
    print(f"Warning count: {summary['warning_count']}")
    print("Primary artifacts:")
    labels = {
        "croco_in": "croco.in",
        "cppdefs_h": "cppdefs.h",
        "param_h": "param.h",
        "analytical_f": "analytical.F",
    }
    for key, label in labels.items():
        artifact = summary["primary_artifacts"][key]
        print(f"- {label}: {'found' if artifact['present'] else 'missing'}")
    print(f"Runtime data asset count: {summary['runtime_data_asset_count']}")
    print(f"Ordinary user file count: {summary['ordinary_user_file_count']}")
    print(f"Ignored user file count: {summary['ignored_user_file_count']}")
    print(f"run.env ignored: {'yes' if summary['run_env_ignored'] else 'no'}")
    source_ref = summary.get("source_ref")
    if isinstance(source_ref, dict) and source_ref.get("source_id"):
        print(f"Selected source ID: {source_ref['source_id']}")
        print(f"Source installed path: {source_ref.get('installed_path') or source_ref.get('host_path') or 'unknown'}")
    else:
        print("Selected source ID: none")
    print(f"Runtime materialization status: {summary['runtime_materialization_status'] or 'unknown'}")
    print(f"Runtime execution plan status: {summary['runtime_execution_plan_status'] or 'unknown'}")
    print("Read-only warnings:")
    for warning in summary["read_only_checks"]["warnings"]:
        print(f"- {warning}")
    if not summary["read_only_checks"]["warnings"]:
        print("- none")
    print(f"Disclaimer: {summary['disclaimer']}")


def cmd_inspect(args):
    try:
        paths = experiment_paths(args)
        if not paths["experiment_root"].is_dir():
            raise CrocoexpError(f"missing experiment directory: {paths['experiment_root']}", 6, "missing_experiment_input")
        if not paths["input"].is_dir():
            raise CrocoexpError(f"missing input directory: {paths['input']}", 6, "missing_experiment_input")
        if not paths["manifest"].is_file():
            raise CrocoexpError(f"missing manifest: {paths['manifest']}; run 'crocoexp import {args.experiment_name}' first", 3, "missing_manifest")
        try:
            manifest = load_manifest(paths["manifest"])
        except json.JSONDecodeError as e:
            raise CrocoexpError(f"malformed manifest JSON: {paths['manifest']}: {e}", 3, "malformed_manifest")
        except OSError as e:
            raise CrocoexpError(f"unable to read manifest: {paths['manifest']}: {e}", 3, "unreadable_manifest")
        summary = inspect_summary(manifest, paths)
        if args.json:
            print(json.dumps(summary, indent=2, sort_keys=True))
        else:
            print_inspect_summary(summary)
        return 0
    except CrocoexpError as e:
        print(f"ERROR: {e}", file=os.sys.stderr)
        return e.exit_code


def stage_compile_inputs(paths):
    stage = paths["build"] / "stage"
    logs = paths["build"] / "logs"
    output = paths["build"] / "output"
    stage.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    staged = []
    experiment_input = stage / "experiment_input"
    experiment_input.mkdir(parents=True, exist_ok=True)
    for name in ("cppdefs.h", "param.h", "analytical.F"):
        src = paths["input"] / name
        if src.exists():
            dest = stage / name
            shutil.copy2(src, dest)
            staged.append({"source": str(src), "destination": str(dest), "reason": "compile_staging"})
            nested_dest = experiment_input / name
            shutil.copy2(src, nested_dest)
            staged.append({"source": str(src), "destination": str(nested_dest), "reason": "compile_staging_experiment_input_copy"})
    croco_in = paths["input"] / "croco.in"
    if croco_in.exists():
        nested_dest = experiment_input / "croco.in"
        shutil.copy2(croco_in, nested_dest)
        staged.append({"source": str(croco_in), "destination": str(nested_dest), "reason": "compile_evidence_copy"})
    missing = [name for name in ("cppdefs.h", "param.h") if not (stage / name).exists()]
    if missing:
        raise CrocoexpError(f"missing compile artifact(s): {', '.join(missing)}", 3, "missing_artifact")
    return stage, logs, output, staged


COMPILE_METADATA_ARTIFACTS = ("compile_attempt.json", "compile_report.md")


def previous_compile_artifacts(paths, manifest):
    artifacts = []
    build = paths["build"]
    if build.exists() or build.is_symlink():
        if build.is_symlink():
            artifacts.append(build)
        elif build.is_dir():
            for child in sorted(build.iterdir(), key=lambda p: p.name):
                artifacts.append(child)
    for name in COMPILE_METADATA_ARTIFACTS:
        path = paths["metadata"] / name
        if path.exists() or path.is_symlink():
            artifacts.append(path)
    compile_attempt = manifest.get("compile", {}).get("last_attempt")
    if isinstance(compile_attempt, dict) and compile_attempt:
        artifacts.append(paths["manifest"])
    return artifacts


def summarize_compile_artifacts(paths, artifacts):
    summary = []
    for path in artifacts:
        if path == paths["manifest"]:
            label = "metadata/manifest.json compile.last_attempt"
        else:
            label = repo_rel(path)
            exp_root = paths["experiment_root"]
            try:
                label = path.relative_to(exp_root).as_posix()
            except ValueError:
                pass
            if path.is_dir() and not path.is_symlink():
                label = f"{label}/"
        if label not in summary:
            summary.append(label)
    return summary


def prompt_compile_clean_decision(args, artifacts_summary):
    print(f"Previous compile artifacts detected for experiment {args.experiment_name}:")
    for item in artifacts_summary[:10]:
        print(f"  {item}")
    if len(artifacts_summary) > 10:
        print(f"  ... {len(artifacts_summary) - 10} more")
    print("")
    print("Choose:")
    print("  [c] clean and continue")
    print("  [k] keep and continue")
    print("  [a] abort")
    answer = input("Selection [a]: ").strip().lower()
    if answer in {"c", "clean"}:
        return "clean"
    if answer in {"k", "keep"}:
        return "no-clean"
    return "abort"


def resolve_compile_clean_policy(args, paths, manifest):
    artifacts = previous_compile_artifacts(paths, manifest)
    summary = summarize_compile_artifacts(paths, artifacts)
    if args.clean:
        return "clean", artifacts, summary
    if args.no_clean:
        return "no-clean", artifacts, summary
    if not artifacts:
        return "none", artifacts, summary
    if not sys.stdin.isatty():
        raise CrocoexpError(
            f"previous compile artifacts detected for experiment {args.experiment_name}.\n"
            "Run one of:\n"
            f"  crocoexp compile {args.experiment_name} --clean\n"
            f"  crocoexp compile {args.experiment_name} --no-clean",
            5,
            "previous_compile_artifacts",
        )
    decision = prompt_compile_clean_decision(args, summary)
    if decision == "abort":
        raise CrocoexpError("compile aborted; previous compile artifacts were left unchanged", 5, "previous_compile_artifacts")
    return decision, artifacts, summary


def ensure_safe_build_path(path, paths):
    repo = repo_root().resolve()
    exps_root = paths["experiments_root"].resolve(strict=False)
    exp = paths["experiment_root"].resolve(strict=False)
    build = paths["build"].resolve(strict=False)
    target = Path(path)
    if target.is_symlink():
        lexical_parent = target.parent if target.is_absolute() else (paths["experiment_root"] / target).parent
        try:
            if not _ALLOW_EXTERNAL_OPERATIONAL_PATHS:
                lexical_parent.resolve(strict=False).relative_to(repo)
            lexical_parent.resolve(strict=False).relative_to(exps_root)
            lexical_parent.resolve(strict=False).relative_to(exp)
        except ValueError:
            raise_external_path_error(target, "compile clean symlink", "compile --clean")
        if target == paths["build"]:
            return
        try:
            target.parent.resolve(strict=False).relative_to(build)
        except ValueError:
            allowed_metadata = {paths["metadata"] / name for name in COMPILE_METADATA_ARTIFACTS}
            if target not in allowed_metadata:
                raise CrocoexpError(f"refusing to clean non-build symlink: {repo_rel(target)}", 4, "metadata_or_staging")
        return
    resolved = target.resolve(strict=False)
    try:
        if not _ALLOW_EXTERNAL_OPERATIONAL_PATHS:
            resolved.relative_to(repo)
        resolved.relative_to(exps_root)
        resolved.relative_to(exp)
    except ValueError:
        raise_external_path_error(target, "compile clean artifact", "compile --clean")
    if target == paths["manifest"] or target == paths["input"] or target == paths["metadata"]:
        raise CrocoexpError(f"refusing to clean protected path: {repo_rel(target)}", 4, "metadata_or_staging")
    if target == paths["build"]:
        return
    try:
        resolved.relative_to(build)
    except ValueError:
        allowed_metadata = {paths["metadata"] / name for name in COMPILE_METADATA_ARTIFACTS}
        if target not in allowed_metadata:
            raise CrocoexpError(f"refusing to clean non-build path: {repo_rel(target)}", 4, "metadata_or_staging")


def remove_compile_artifact(path, paths):
    path = Path(path)
    if path == paths["manifest"]:
        return False
    ensure_safe_build_path(path, paths)
    if not path.exists() and not path.is_symlink():
        return False
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    return True


def clean_previous_compile_artifacts(paths, artifacts):
    removed = []
    for path in artifacts:
        if remove_compile_artifact(path, paths):
            removed.append(repo_rel(path))
    if paths["build"].exists() and not paths["build"].is_symlink():
        paths["build"].mkdir(parents=True, exist_ok=True)
    paths["metadata"].mkdir(parents=True, exist_ok=True)
    return removed


def resolve_compile_source(args, manifest):
    requested = getattr(args, "source_id", None)
    if requested:
        return resolve_registered_source(requested, "compile --source")
    existing = manifest.get("compile_time", {}).get("source_ref")
    if not existing or not existing.get("source_id"):
        raise CrocoexpError("missing compile source; import with '--source <source_id>' before compile", 5, "source_not_found")
    try:
        return resolve_registered_source(existing["source_id"], "manifest compile_time.source_ref")
    except CrocoexpError as e:
        if e.failure_category == "source_not_found" and str(e).startswith("unknown registered source id"):
            raise CrocoexpError(
                f"orphaned compile source reference: {existing['source_id']}; run 'crocoexp source list' to see available sources. "
                "Reinstall the source or reimport the experiment with a valid source.",
                e.exit_code,
                e.failure_category,
            )
        raise


def detect_compile_entrypoints(source_path):
    candidates = []
    for rel in ("jobcomp", "OCEAN/jobcomp", "jobcomp_rsf", "OCEAN/jobcomp_rsf", "Makefile", "makefile", "OCEAN/Makefile", "OCEAN/makefile"):
        path = source_path / rel
        if path.exists():
            candidates.append({"path": str(path), "kind": path.name})
    return candidates


def copy_compile_source_to_stage(source_ref, stage):
    source_path = path_value_to_absolute(source_ref.get("host_path") or source_ref.get("installed_path", ""), "source_ref.host_path", "compile")
    staged_source = stage / "source"
    if staged_source.is_symlink() or staged_source.is_file():
        staged_source.unlink()
    elif staged_source.exists():
        shutil.rmtree(staged_source)
    shutil.copytree(source_path, staged_source, symlinks=False)
    return staged_source


def find_compile_binary(paths):
    candidates = []
    build = paths["build"]
    if build.exists():
        for name in ("croco", "croco.exe", "crocoM", "crocoO"):
            candidates.extend(sorted(build.rglob(name)))
    candidates = [p for p in candidates if p.is_file()]
    executable = [p for p in candidates if os.access(p, os.X_OK)]
    selected = (executable or candidates or [None])[0]
    if selected is None:
        return None
    return {"path": str(selected), "sha256": sha256_file(selected)}


def write_compile_attempt(path, attempt):
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(normalize_for_json_write(attempt, "compile attempt write"), f, indent=2, sort_keys=True)
        f.write("\n")
    tmp.replace(path)


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
export NETCDFLIB="${{CROCO_NETCDFLIB:-{DOCKER_NETCDFLIB}}}"
export NETCDFINC="${{CROCO_NETCDFINC:-{DOCKER_NETCDFINC}}}"
export CROCO_NETCDFLIB="${{NETCDFLIB}}"
export CROCO_NETCDFINC="${{NETCDFINC}}"
sed -i \\
  -e 's|^NETCDFLIB=.*|NETCDFLIB="${{CROCO_NETCDFLIB}}"|g' \\
  -e 's|^NETCDFINC=.*|NETCDFINC="${{CROCO_NETCDFINC}}"|g' \\
  ./jobcomp || true
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


def write_compile_report(manifest, report_path, log_path, failure_category, exit_code, attempt=None):
    attempt = attempt or {}
    logs = attempt.get("logs", {})
    binary = attempt.get("binary") or {}
    lines = [
        "# Compile Report",
        "",
        f"- Experiment: {manifest['experiment']['name']}",
        f"- Selected source ID: {attempt.get('source_id') or 'none'}",
        f"- Registered source path: {attempt.get('source_installed_path') or 'unknown'}",
        f"- Stage directory: {attempt.get('stage_dir') or 'unknown'}",
        f"- Docker image: {attempt.get('docker_image') or manifest.get('docker_backend', {}).get('image')}",
        f"- Docker command attempted: {' '.join(attempt.get('docker_command', [])) if attempt.get('docker_command') else 'not attempted'}",
        f"- Compile status: {attempt.get('status') or failure_category}",
        f"- Return code: {attempt.get('returncode', exit_code)}",
        f"- Warning count: {len(attempt.get('warnings', []))}",
        f"- Stdout log: {logs.get('stdout_path') or log_path}",
        f"- Stderr log: {logs.get('stderr_path') or log_path}",
        f"- Detected binary path: {binary.get('path') or 'none'}",
        "",
        "## Scope Disclaimer",
        "",
        "Compile records a build attempt. Compile success does not prove scientific correctness, runtime semantic compatibility, or experiment well-posedness.",
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


def generated_execution_run_id():
    return f"run-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"


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


def discover_runtime_data_assets(input_root):
    assets = []
    for path in sorted(p for p in input_root.rglob("*") if p.is_file() and p.suffix.lower() in DATA_SUFFIXES):
        stat = path.stat()
        assets.append(
            {
                "source_host_path": str(path),
                "source_relative_path_from_input": rel_to(path, input_root),
                "exists": True,
                "size_bytes": stat.st_size,
                "content_hash": None,
                "source": "input_tree_scan",
                "copy_policy": "symlink_into_work",
            }
        )
    return assets


def safe_resolved_inside(path, root):
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root.resolve(strict=True))
        return True
    except (OSError, ValueError):
        return False


def runtime_materialization_plan(paths, run_dir, binary_path):
    input_dir = paths["input"]
    exps_root = paths["experiments_root"]
    runtime_data_assets = discover_runtime_data_assets(input_dir)
    if run_dir is None:
        return {
            "policy": "copy_config_symlink_netcdf",
            "status": "not_planned_until_run_id",
            "input_root_host_path": str(input_dir),
            "workdir_host_path": None,
            "workdir_container_path": None,
            "binary_source_host_path": str(binary_path) if binary_path else None,
            "binary_workdir_relative_path": "croco",
            "runtime_data_assets": runtime_data_assets,
            "copied_files": [],
            "symlinked_runtime_data": [],
            "collected_outputs": [],
            "skipped_files": [],
            "warnings": [],
            "blockers": [],
            "docker_working_directory": None,
            "docker_mounts": [],
        }
    workdir = run_dir / "work" if run_dir else None
    symlinks = []
    warnings = []
    blockers = []
    copied_files = []
    croco_in = input_dir / "croco.in"
    if workdir:
        copied_files.append(
            {
                "source_host_path": str(croco_in),
                "destination_host_path": str(workdir / "croco.in"),
                "destination_relative_path_from_workdir": "croco.in",
                "reason": "primary runtime config copied into run workdir",
            }
        )
    for asset in runtime_data_assets:
        src = Path(asset["source_host_path"])
        rel = Path(asset["source_relative_path_from_input"])
        link = workdir / rel if workdir else None
        safe = safe_resolved_inside(src, input_dir) and safe_resolved_inside(src, exps_root)
        target = os.path.relpath(src, start=link.parent) if link else None
        if not safe:
            blockers.append(
                {
                    "id": f"blocker.unsafe_symlink_target.{asset['source_relative_path_from_input']}",
                    "category": "unsafe_symlink_target",
                    "description": f"Runtime data asset does not resolve safely inside input/: {src}",
                    "evidence": asset,
                    "required_resolution": "Keep runtime data files physically under the experiment input/ tree.",
                }
            )
        symlinks.append(
            {
                **asset,
                "link_host_path": str(link) if link else None,
                "link_relative_path_from_workdir": str(rel),
                "relative_symlink_target": target,
                "container_link_path": container_path(link, exps_root) if link else None,
                "container_target_path": container_path(src, exps_root),
                "safe_target": safe,
            }
        )
    if (input_dir / "run.env").exists():
        warnings.append("input/run.env is ignored; CROCOEXP does not source env files or substitute croco.in.")
    _, token_warnings = unresolved_template_tokens(input_dir)
    warnings.extend(token_warnings)
    return {
        "policy": "copy_config_symlink_netcdf",
        "status": "planned",
        "input_root_host_path": str(input_dir),
        "workdir_host_path": str(workdir) if workdir else None,
        "workdir_container_path": container_path(workdir, exps_root) if workdir else None,
        "binary_source_host_path": str(binary_path) if binary_path else None,
        "binary_workdir_relative_path": "croco",
        "runtime_data_assets": runtime_data_assets,
        "copied_files": copied_files,
        "symlinked_runtime_data": symlinks,
        "collected_outputs": [],
        "skipped_files": [],
        "warnings": warnings,
        "blockers": blockers,
        "docker_working_directory": container_path(workdir, exps_root) if workdir else None,
        "docker_mounts": [
            {
                "host_path": str(exps_root),
                "container_path": CONTAINER_ROOT,
                "mode": "rw",
                "purpose": "whole_experiments_root_mount",
            }
        ],
    }


def classify_dry_run_assets(paths, run_dir=None, binary_path=None):
    input_dir = paths["input"]
    inventory = []
    for path in sorted(p for p in input_dir.rglob("*") if p.is_file()):
        inventory.append(asset_item(path, input_dir, paths["experiments_root"]))
    counts = {}
    for item in inventory:
        counts[item["classification"]] = counts.get(item["classification"], 0) + 1
    plan = runtime_materialization_plan(paths, run_dir, binary_path)
    return inventory, counts, plan, plan["warnings"], [], plan["blockers"]


def prepare_run_workdir(paths, run_dir, binary_path):
    plan = runtime_materialization_plan(paths, run_dir, binary_path)
    if plan["blockers"]:
        return plan
    workdir = run_dir / "work"
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True)
    shutil.copy2(paths["input"] / "croco.in", workdir / "croco.in")
    shutil.copy2(binary_path, workdir / "croco")
    mode = binary_path.stat().st_mode
    (workdir / "croco").chmod(mode | 0o111)
    for record in plan["symlinked_runtime_data"]:
        link = Path(record["link_host_path"])
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.exists() or link.is_symlink():
            link.unlink()
        os.symlink(record["relative_symlink_target"], link)
    return plan


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


def snapshot_dry_run(paths, manifest, run_dir, inventory, materialization_plan):
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
    mappings_path.write_text(json.dumps(materialization_plan.get("docker_mounts", []), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    symlinks_path = snapshots / "runtime_symlink_plan.json"
    symlinks_path.write_text(json.dumps(materialization_plan.get("symlinked_runtime_data", []), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest_path = snapshots / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    included.extend([str(asset_path), str(mappings_path), str(symlinks_path), str(manifest_path)])
    return {
        "id": f"snapshot.{run_dir.name}",
        "run_id": run_dir.name,
        "kind": "dry_run",
        "host_path": str(snapshots),
        "created_at": utc_now(),
        "included_artifacts": included,
        "asset_inventory_ref": str(asset_path),
        "runtime_symlink_plan_ref": str(symlinks_path),
        "manifest_hash": None,
    }


def write_run_script(paths, run_dir, execution_plan):
    script = run_dir / "work" / "run_inside_docker.sh"
    script.parent.mkdir(parents=True, exist_ok=True)
    work_container = container_path(run_dir / "work", paths["experiments_root"])
    omp_threads = execution_plan.get("openmp", {}).get("planned_omp_num_threads")
    omp_export = f"export OMP_NUM_THREADS={omp_threads}\necho \"CROCOEXP: OMP_NUM_THREADS=${{OMP_NUM_THREADS}}\"\n" if omp_threads is not None else ""
    text = f"""#!/usr/bin/env bash
set -euo pipefail
cd "{work_container}"
export NETCDFLIB="${{CROCO_NETCDFLIB:-{DOCKER_NETCDFLIB}}}"
export NETCDFINC="${{CROCO_NETCDFINC:-{DOCKER_NETCDFINC}}}"
export LD_LIBRARY_PATH="{DOCKER_NETCDF_LD_LIBRARY_PATH}:${{LD_LIBRARY_PATH:-}}"
{omp_export}if [[ ! -x "./croco" ]]; then
  echo "ERROR: selected binary is not executable: ./croco"
  exit 70
fi
./croco croco.in
"""
    script.write_text(text, encoding="utf-8")
    script.chmod(0o755)
    return script


def collect_run_outputs(run_dir, output_dir, materialization_plan):
    workdir = run_dir / "work"
    output_dir.mkdir(parents=True, exist_ok=True)
    excluded = {"croco", "croco.in", "run_inside_docker.sh"}
    collected = []
    symlink_rels = {record["link_relative_path_from_workdir"] for record in materialization_plan.get("symlinked_runtime_data", [])}
    if not workdir.exists():
        return collected
    for path in sorted(p for p in workdir.rglob("*") if p.is_file() and not p.is_symlink()):
        rel = rel_to(path, workdir)
        if rel in excluded or rel in symlink_rels:
            continue
        dest = output_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            dest.unlink()
        shutil.copy2(path, dest)
        collected.append(
            {
                "source_host_path": str(path),
                "destination_host_path": str(dest),
                "relative_path_from_workdir": rel,
                "action": "copied_from_workdir",
            }
        )
    return collected


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


def write_dry_run_report(path, manifest, run_id, image, mode, binary, counts, inventory, materialization_plan, execution_plan, warnings, findings, blockers, outcome):
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
        f"- Planned workdir: {materialization_plan.get('workdir_host_path')}",
        f"- Materialization policy: {materialization_plan.get('policy')}",
        f"- Whole CROCO_EXPERIMENTS mount: {materialization_plan.get('docker_mounts', [{}])[0].get('host_path')} -> {materialization_plan.get('docker_mounts', [{}])[0].get('container_path')}",
        f"- Primary artifacts: {primary}",
        f"- analytical.F: {manifest.get('compile_time', {}).get('analytical_finding')}",
        f"- Binary present: {binary['present']}",
        f"- Binary candidates: {binary['candidates']}",
        f"- Input runtime data assets: {counts.get('runtime_data', 0)}",
        f"- Runtime backend: {execution_plan.get('parallel_backend')}",
        f"- Planned OMP_NUM_THREADS: {execution_plan.get('openmp', {}).get('planned_omp_num_threads')}",
        f"- Final outcome: {outcome}",
    ]
    lines += section("Runtime Data Assets", [f"- {a['host_path']} ({a['relative_path_from_input']})" for a in inventory if a["classification"] == "runtime_data"])
    lines += section(
        "Symlink Plan",
        [
            f"- {s['link_relative_path_from_workdir']} -> {s['relative_symlink_target']} (source: input/{s['source_relative_path_from_input']})"
            for s in materialization_plan.get("symlinked_runtime_data", [])
        ],
    )
    lines += section("Docker Mounts", [f"- {m['host_path']} -> {m['container_path']} [{m['mode']}]" for m in materialization_plan.get("docker_mounts", [])])
    lines += section(
        "Runtime Execution Plan",
        [
            f"- Backend symbols: {execution_plan.get('backend_symbols', {})}",
            f"- Compile-time active symbols trusted: {execution_plan.get('active_symbol_resolution', {}).get('compile_time_active_symbols_trusted')}",
            f"- Trust rejection reason: {execution_plan.get('active_symbol_resolution', {}).get('trust_rejection_reason')}",
            f"- Fresh preprocessing attempted: {execution_plan.get('active_symbol_resolution', {}).get('fresh_preprocessing_attempted')}",
            f"- Fresh preprocessing contains_OPENMP: {execution_plan.get('active_symbol_resolution', {}).get('contains_OPENMP')}",
            f"- Active symbol resolution: {execution_plan.get('active_symbol_resolution', {})}",
            f"- Effective param resolution: {execution_plan.get('effective_param_resolution', {})}",
            f"- MPI: {execution_plan.get('mpi', {})}",
            f"- OpenMP: {execution_plan.get('openmp', {})}",
        ],
    )
    lines += section("Warnings And Findings", [f"- {w}" for w in warnings + findings])
    lines += section("Infrastructural Blockers", [f"- {b['category']}: {b['description']}" for b in blockers])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_run_report(path, manifest, run_id, image, binary, dry_run_found, counts, inventory, materialization_plan, execution_plan, collected_outputs, warnings, findings, blockers, docker_cmd, log_path, output_path, snapshot_path, exit_code, failure_category):
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
        f"- Workdir: {materialization_plan.get('workdir_host_path')}",
        f"- Materialization policy: {materialization_plan.get('policy')}",
        f"- Primary artifacts: {primary}",
        f"- Dry-run required/found: {dry_run_found}",
        f"- Input runtime data assets: {counts.get('runtime_data', 0)}",
        f"- Runtime backend: {execution_plan.get('parallel_backend')}",
        f"- Planned OMP_NUM_THREADS: {execution_plan.get('openmp', {}).get('planned_omp_num_threads')}",
        f"- Docker command: {docker_cmd}",
        f"- Logs path: {log_path}",
        f"- Output path: {output_path}",
        f"- Snapshot path: {snapshot_path}",
        f"- Final exit status: {exit_code}",
        f"- Failure category: {failure_category}",
    ]
    lines += section(
        "Symlinked Runtime Data",
        [
            f"- {s['link_relative_path_from_workdir']} -> {s['relative_symlink_target']} (source: input/{s['source_relative_path_from_input']})"
            for s in materialization_plan.get("symlinked_runtime_data", [])
        ],
    )
    lines += section("Docker Mounts", [f"- {m['host_path']} -> {m['container_path']} [{m['mode']}]" for m in materialization_plan.get("docker_mounts", [])])
    lines += section(
        "Runtime Execution Plan",
        [
            f"- Backend symbols: {execution_plan.get('backend_symbols', {})}",
            f"- Compile-time active symbols trusted: {execution_plan.get('active_symbol_resolution', {}).get('compile_time_active_symbols_trusted')}",
            f"- Trust rejection reason: {execution_plan.get('active_symbol_resolution', {}).get('trust_rejection_reason')}",
            f"- Fresh preprocessing attempted: {execution_plan.get('active_symbol_resolution', {}).get('fresh_preprocessing_attempted')}",
            f"- Fresh preprocessing contains_OPENMP: {execution_plan.get('active_symbol_resolution', {}).get('contains_OPENMP')}",
            f"- Active symbol resolution: {execution_plan.get('active_symbol_resolution', {})}",
            f"- Effective param resolution: {execution_plan.get('effective_param_resolution', {})}",
            f"- MPI: {execution_plan.get('mpi', {})}",
            f"- OpenMP: {execution_plan.get('openmp', {})}",
        ],
    )
    lines += section(
        "Collected Outputs",
        [
            f"- {o['relative_path_from_workdir']} -> {o['destination_host_path']} ({o['action']})"
            for o in collected_outputs
        ],
    )
    lines += section("Warnings And Findings", [f"- {w}" for w in warnings + findings])
    lines += section("Infrastructural Blockers", [f"- {b['category']}: {b['description']}" for b in blockers])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_dry_run_plan(paths):
    plan_path = paths["metadata"] / "dry_run_plan.json"
    if not plan_path.is_file():
        raise CrocoexpError(f"missing dry-run plan: {plan_path}; run 'crocoexp dry-run' first", 3, "missing_dry_run_plan")
    try:
        return json.loads(plan_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise CrocoexpError(f"malformed dry-run plan JSON: {plan_path}: {e}", 3, "malformed_dry_run_plan")
    except OSError as e:
        raise CrocoexpError(f"unable to read dry-run plan: {plan_path}: {e}", 3, "unreadable_dry_run_plan")


def docker_image_for_run(plan):
    compile_attempt = plan.get("compile_attempt", {})
    if plan.get("docker_image"):
        return plan["docker_image"]
    if isinstance(compile_attempt, dict) and compile_attempt.get("docker_image"):
        return compile_attempt["docker_image"]
    return configured_default_image()


def resolve_run_plan(paths, plan, run_id):
    materialization = plan.get("runtime_materialization")
    execution = plan.get("runtime_execution_plan")
    if not isinstance(materialization, dict):
        raise CrocoexpError("dry-run plan has no runtime materialization plan", 12, "missing_dry_run_materialization")
    if not isinstance(execution, dict):
        raise CrocoexpError("dry-run plan has no runtime execution plan", 10, "missing_dry_run_execution_plan")
    if plan.get("status") not in {None, "planned"}:
        if execution.get("status") != "planned":
            raise CrocoexpError("dry-run runtime execution plan is blocked", 11, "unsupported_runtime_backend")
        raise CrocoexpError(f"dry-run plan status does not allow execution: {plan.get('status')}", 10, "blocked_dry_run_plan")
    if materialization.get("status") != "planned":
        raise CrocoexpError("dry-run runtime materialization plan is not executable", 12, "blocked_dry_run_materialization")
    if execution.get("status") != "planned":
        raise CrocoexpError("dry-run runtime execution plan is blocked", 11, "unsupported_runtime_backend")
    profile = execution.get("profile")
    if profile not in {"serial", "openmp"}:
        raise CrocoexpError(f"unsupported runtime execution profile for v1.0.0: {profile}", 11, "unsupported_runtime_backend")
    binary_path = execution.get("binary_path") or plan.get("binary_path")
    if not binary_path:
        raise CrocoexpError("dry-run plan has no binary path", 10, "missing_compile_binary")
    binary_path = path_value_to_absolute(binary_path, "dry_run_plan.binary_path", "run")
    if not binary_path.is_file():
        raise CrocoexpError(f"recorded binary path is missing on disk: {binary_path}", 10, "missing_compile_binary")
    if run_id != plan.get("run_id"):
        materialization = dry_run_materialization_plan(paths, run_id, planned_runtime_assets_from_manifest(plan, paths))
        execution = dict(execution)
        execution["working_directory"] = str(paths["runs"] / run_id / "work")
    return materialization, execution, binary_path


def symlink_relative(src, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() or dest.is_symlink():
        dest.unlink()
    target = os.path.relpath(src, start=dest.parent)
    if os.path.isabs(target):
        raise CrocoexpError(f"refusing to create absolute symlink target for {dest}", 12, "materialization_failed")
    os.symlink(target, dest)
    return target


def materialize_run_workdir_from_plan(paths, run_dir, materialization, execution, binary_path):
    workdir = run_dir / "work"
    output_dir = run_dir / "output"
    logs_dir = run_dir / "logs"
    snapshots_dir = run_dir / "snapshots"
    reports_dir = run_dir / "reports"
    for directory in (workdir, output_dir, logs_dir, snapshots_dir, reports_dir):
        directory.mkdir(parents=True, exist_ok=True)
    blockers = []
    warnings = []
    materialized = []
    binary_link = workdir / "croco"
    binary_target = symlink_relative(binary_path, binary_link)
    materialized.append({"kind": "binary", "link_path": rel_to(binary_link, paths["experiment_root"]), "target_path": binary_target, "asset_path": str(binary_path)})

    if "croco.in" in execution.get("argv", []):
        croco_in = paths["input"] / "croco.in"
        if not croco_in.is_file():
            blockers.append({"category": "missing_artifact", "description": f"planned croco.in is missing: {croco_in}"})
        else:
            croco_link = workdir / "croco.in"
            target = symlink_relative(croco_in, croco_link)
            materialized.append({"kind": "croco_in", "link_path": rel_to(croco_link, paths["experiment_root"]), "target_path": target, "asset_path": "input/croco.in"})

    for entry in materialization.get("symlinks", []):
        target = entry.get("target_path")
        if not target or os.path.isabs(target):
            blockers.append({"category": "invalid_symlink_plan", "description": f"invalid symlink target for {entry.get('asset_path')}: {target}"})
            continue
        asset = paths["experiment_root"] / entry["asset_path"]
        if not asset.is_file():
            blockers.append({"category": "missing_runtime_asset", "description": f"planned runtime data asset is missing: {asset}"})
            continue
        link = paths["experiment_root"] / entry["link_path"]
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.exists() or link.is_symlink():
            link.unlink()
        os.symlink(target, link)
        materialized.append(dict(entry))
    return {
        "workdir": str(workdir),
        "output_dir": str(output_dir),
        "logs_dir": str(logs_dir),
        "snapshots_dir": str(snapshots_dir),
        "reports_dir": str(reports_dir),
        "symlinks": materialized,
        "warnings": warnings,
        "blockers": blockers,
    }


def snapshot_run_inputs(paths, run_dir):
    snapshots = run_dir / "snapshots"
    snapshots.mkdir(parents=True, exist_ok=True)
    records = []
    for src in (paths["manifest"], paths["metadata"] / "dry_run_plan.json", paths["metadata"] / "compile_attempt.json"):
        if src.is_file():
            dest = snapshots / src.name
            shutil.copy2(src, dest)
            records.append({"source": str(src), "snapshot": str(dest), "kind": "metadata"})
    for name in ("croco.in", "cppdefs.h", "param.h", "analytical.F"):
        src = paths["input"] / name
        if src.is_file():
            dest = snapshots / name
            shutil.copy2(src, dest)
            records.append({"source": str(src), "snapshot": str(dest), "kind": "primary_input"})
    runtime_inventory = []
    for asset in sorted(paths["input"].rglob("*")):
        if asset.is_file() and asset.suffix.lower() in DATA_SUFFIXES:
            runtime_inventory.append({"path": rel_to(asset, paths["experiment_root"]), "size_bytes": asset.stat().st_size, "sha256": None})
    inv = snapshots / "runtime_data_inventory.json"
    inv.write_text(json.dumps(runtime_inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    records.append({"source": "input_runtime_data_scan", "snapshot": str(inv), "kind": "runtime_data_inventory"})
    return records


def write_run_wrapper(run_dir, execution):
    script = run_dir / "work" / "run_inside_docker.sh"
    env_lines = [f"export {key}={value}" for key, value in sorted(execution.get("environment", {}).items())]
    argv = execution.get("argv") or ["./croco", "croco.in"]
    text = "#!/usr/bin/env bash\nset -euo pipefail\n" + "\n".join(env_lines) + "\n" + " ".join(argv) + "\n"
    script.write_text(text, encoding="utf-8")
    script.chmod(0o755)
    return script


def inventory_run_outputs(run_dir):
    records = []
    for base_name in ("work", "output"):
        base = run_dir / base_name
        if not base.exists():
            continue
        for path in sorted(p for p in base.rglob("*") if p.is_file() and not p.is_symlink()):
            if path.name in {"run_inside_docker.sh"}:
                continue
            records.append({"path": rel_to(path, run_dir), "size_bytes": path.stat().st_size, "sha256": sha256_file(path)})
    return records


def write_run_attempt(path, attempt):
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(normalize_for_json_write(attempt, "run attempt write"), f, indent=2, sort_keys=True)
        f.write("\n")
    tmp.replace(path)


def write_v1_run_report(path, attempt):
    lines = [
        "# Run Report",
        "",
        f"- Experiment: {attempt['experiment_name']}",
        f"- Run ID: {attempt['run_id']}",
        f"- Run status: {attempt['status']}",
        f"- Selected profile: {attempt['profile']}",
        f"- Docker image: {attempt['docker_image']}",
        f"- Docker command attempted: {' '.join(attempt.get('docker_command', [])) if attempt.get('docker_command') else 'not attempted'}",
        f"- Workdir: {attempt['workdir']}",
        f"- Output directory: {attempt['output_dir']}",
        f"- Stdout log: {attempt['logs']['stdout_path']}",
        f"- Stderr log: {attempt['logs']['stderr_path']}",
        f"- Materialized symlink count: {len(attempt['materialization']['symlinks'])}",
        f"- Snapshot count: {len(attempt['materialization']['snapshots'])}",
        f"- Return code: {attempt['returncode']}",
        f"- Output inventory count: {len(attempt['outputs'])}",
        "",
        "## Blockers",
    ]
    lines.extend([f"- {b.get('category', 'blocker')}: {b.get('description', b)}" for b in attempt.get("blockers", [])] or ["- none"])
    lines.extend(["", "## Warnings"])
    lines.extend([f"- {w}" for w in attempt.get("warnings", [])] or ["- none"])
    lines.extend(["", "## Scope Disclaimer", "", "Run records an execution attempt. Run success does not prove scientific correctness, runtime semantic compatibility, or experiment well-posedness."])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_required_manifest_for_command(paths, experiment_name, command_name):
    if not paths["experiment_root"].is_dir():
        raise CrocoexpError(f"missing experiment directory: {paths['experiment_root']}", 6, "missing_experiment_input")
    if not paths["input"].is_dir():
        raise CrocoexpError(f"missing input directory: {paths['input']}", 6, "missing_experiment_input")
    if not paths["manifest"].is_file():
        raise CrocoexpError(
            f"missing manifest: {paths['manifest']}; run 'crocoexp import {experiment_name}' first",
            3,
            "missing_manifest",
        )
    try:
        return load_manifest(paths["manifest"])
    except json.JSONDecodeError as e:
        raise CrocoexpError(f"malformed manifest JSON: {paths['manifest']}: {e}", 3, "malformed_manifest")
    except OSError as e:
        raise CrocoexpError(f"unable to read manifest for {command_name}: {paths['manifest']}: {e}", 3, "unreadable_manifest")


def load_compile_attempt(paths, manifest):
    attempt = manifest.get("compile", {}).get("last_attempt")
    attempt_path = paths["metadata"] / "compile_attempt.json"
    if attempt is None and attempt_path.is_file():
        try:
            attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            attempt = None
    if attempt is None:
        raise CrocoexpError("missing successful compile attempt; run 'crocoexp compile' first", 10, "missing_compile_attempt")
    if attempt.get("status") != "success":
        raise CrocoexpError("latest compile attempt did not succeed; rerun 'crocoexp compile' successfully before dry-run", 10, "failed_compile_attempt")
    binary = attempt.get("binary")
    if not isinstance(binary, dict) or not binary.get("path"):
        raise CrocoexpError("latest compile attempt has no recorded binary path", 10, "missing_compile_binary")
    binary_path = path_value_to_absolute(binary["path"], "compile.last_attempt.binary.path", "dry-run")
    if not binary_path.is_file():
        raise CrocoexpError(f"recorded compile binary is missing on disk: {binary_path}", 10, "missing_compile_binary")
    return attempt, binary_path


def planned_runtime_assets_from_manifest(manifest, paths):
    assets = manifest.get("evidence", {}).get("runtime_data_assets", [])
    if not assets:
        assets = [
            {
                "path": f"input/{asset['source_relative_path_from_input']}",
                "kind": "runtime_data_asset",
                "size_bytes": asset.get("size_bytes"),
                "sha256": asset.get("content_hash"),
            }
            for asset in manifest.get("runtime_materialization", {}).get("runtime_data_assets", [])
        ]
    result = []
    for asset in assets:
        rel = asset["path"]
        abs_path = paths["experiment_root"] / rel
        result.append(
            {
                "asset_path": rel,
                "absolute_path": str(abs_path),
                "relative_from_input": str(Path(rel).relative_to("input")) if rel.startswith("input/") else rel,
                "kind": "netcdf_like",
                "size_bytes": asset.get("size_bytes"),
                "sha256": asset.get("sha256"),
            }
        )
    return result


def dry_run_materialization_plan(paths, run_id, runtime_assets):
    workdir = paths["runs"] / run_id / "work"
    symlinks = []
    legacy_symlinks = []
    warnings = []
    for asset in runtime_assets:
        rel_from_input = asset["relative_from_input"]
        link_abs = workdir / rel_from_input
        asset_abs = paths["experiment_root"] / asset["asset_path"]
        target = os.path.relpath(asset_abs, start=link_abs.parent)
        if os.path.isabs(target):
            warnings.append(f"planned symlink target is unexpectedly absolute for {asset['asset_path']}")
        symlinks.append(
            {
                "link_path": rel_to(link_abs, paths["experiment_root"]),
                "target_path": target,
                "asset_path": asset["asset_path"],
                "kind": asset["kind"],
                "size_bytes": asset.get("size_bytes"),
                "sha256": asset.get("sha256"),
            }
        )
        legacy_symlinks.append(
            {
                "source_host_path": str(asset_abs),
                "source_relative_path_from_input": rel_from_input,
                "link_host_path": str(link_abs),
                "link_relative_path_from_workdir": rel_from_input,
                "relative_symlink_target": target,
            }
        )
    return {
        "status": "planned",
        "policy": "copy_config_symlink_netcdf",
        "workdir": str(workdir),
        "workdir_host_path": str(workdir),
        "workdir_relative": rel_to(workdir, paths["experiment_root"]),
        "planned_workdir_template": "runs/<run_id>/work",
        "symlinks": symlinks,
        "symlinked_runtime_data": legacy_symlinks,
        "runtime_data_assets": [
            {
                "source_host_path": asset["absolute_path"],
                "source_relative_path_from_input": asset["relative_from_input"],
                "exists": Path(asset["absolute_path"]).exists(),
                "size_bytes": asset.get("size_bytes"),
                "content_hash": asset.get("sha256"),
                "source": "manifest_evidence",
                "copy_policy": "symlink_into_work",
            }
            for asset in runtime_assets
        ],
        "copied_files": [],
        "warnings": warnings,
        "blockers": [],
        "docker_mounts": [],
    }


def dry_run_execution_plan(paths, manifest, binary_path, workdir):
    compile_context = runtime_compile_context(paths, manifest)
    existing_plan = runtime_execution_plan(paths["input"], compile_context)
    profile = existing_plan.get("parallel_backend", "unknown")
    blockers = list(existing_plan.get("blockers", []))
    warnings = list(existing_plan.get("warnings", []))
    status = "blocked" if blockers else "planned"
    parsed = {
        "NPP": compile_context.get("dimensions", {}).get("npp", "unknown"),
        "NSUB_X": compile_context.get("dimensions", {}).get("nsub_x", "unknown"),
        "NSUB_E": compile_context.get("dimensions", {}).get("nsub_e", "unknown"),
        "NP_XI": compile_context.get("dimensions", {}).get("np_xi", "unknown"),
        "NP_ETA": compile_context.get("dimensions", {}).get("np_eta", "unknown"),
        "NNODES": compile_context.get("dimensions", {}).get("nnodes", "unknown"),
    }
    parsed = {key: ("unknown" if value is None else value) for key, value in parsed.items()}
    environment = {}
    argv = ["./croco", "croco.in"]
    if profile == "openmp":
        omp = existing_plan.get("openmp", {}).get("planned_omp_num_threads")
        if omp is None:
            omp = 1
            warnings.append("OPENMP detected but NPP could not be parsed; planning OMP_NUM_THREADS=1.")
        environment["OMP_NUM_THREADS"] = str(omp)
    return {
        "status": status,
        "profile": profile if profile in {"serial", "openmp"} else "unsupported",
        "binary_path": str(binary_path),
        "working_directory": str(workdir),
        "argv": argv,
        "environment": environment,
        "detected_capabilities": existing_plan.get("backend_symbols", {}),
        "parsed_parameters": parsed,
        "blockers": blockers,
        "warnings": warnings,
        "active_symbol_resolution": existing_plan.get("active_symbol_resolution", {}),
        "effective_param_resolution": existing_plan.get("effective_param_resolution", {}),
    }


def write_dry_run_plan(path, plan):
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(normalize_for_json_write(plan, "dry-run plan write"), f, indent=2, sort_keys=True)
        f.write("\n")
    tmp.replace(path)


def write_metadata_dry_run_report(path, plan):
    materialization = plan["runtime_materialization"]
    execution = plan["runtime_execution_plan"]
    lines = [
        "# Dry-Run Report",
        "",
        f"- Experiment: {plan['experiment_name']}",
        f"- Dry-run status: {plan['status']}",
        f"- Planned run ID: {plan['run_id']}",
        f"- Planned workdir: {materialization['workdir']}",
        f"- Binary path: {plan.get('binary_path') or 'none'}",
        f"- Runtime data asset count: {len(plan.get('runtime_data_assets', []))}",
        f"- Planned symlink count: {len(materialization.get('symlinks', []))}",
        f"- Selected execution profile: {execution.get('profile')}",
        f"- Detected capabilities: {execution.get('detected_capabilities')}",
        f"- Parsed parameters: {execution.get('parsed_parameters')}",
        "",
        "## Symlink Plan",
    ]
    lines.extend([f"- {s['link_path']} -> {s['target_path']} (source: {s['asset_path']})" for s in materialization.get("symlinks", [])] or ["- none"])
    lines.extend([
        "",
        "## Blockers",
    ])
    lines.extend([f"- {b.get('category', 'blocker')}: {b.get('description', b)}" for b in plan.get("blockers", [])] or ["- none"])
    lines.extend(["", "## Warnings"])
    lines.extend([f"- {w}" for w in plan.get("warnings", [])] or ["- none"])
    lines.extend(
        [
            "",
            "## Scope Disclaimer",
            "",
            "Dry-run does not launch CROCO. Dry-run records planning findings only; it does not prove scientific correctness, compile correctness, runtime semantic compatibility, or experiment well-posedness.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def cmd_dry_run(args):
    try:
        paths = experiment_paths(args)
        manifest = load_required_manifest_for_command(paths, args.experiment_name, "dry-run")
        compile_attempt, binary_path = load_compile_attempt(paths, manifest)
        run_id = args.run_id or generated_run_id()
        run_dir = paths["runs"] / run_id
        runtime_assets = planned_runtime_assets_from_manifest(manifest, paths)
        materialization_plan = dry_run_materialization_plan(paths, run_id, runtime_assets)
        execution_plan = dry_run_execution_plan(paths, manifest, binary_path, run_dir / "work")
        warnings = list(manifest.get("reporting", {}).get("warnings", []))
        warnings.extend(materialization_plan.get("warnings", []))
        warnings.extend(execution_plan.get("warnings", []))
        if any(entry.get("path") == "input/run.env" for entry in manifest.get("evidence", {}).get("ignored_user_files", [])):
            warnings.append("input/run.env is ignored; CROCOEXP does not source env files or substitute croco.in.")
        blockers = list(execution_plan.get("blockers", []))
        findings = ["Dry-run is host-side planning only and does not launch CROCO."]
        if manifest.get("compile_time", {}).get("analytical_finding") == "present_in_input" and runtime_assets:
            manifest["reporting"].setdefault("possible_mismatches", []).append(
                {
                    "id": "finding.analytical_with_external_data",
                    "description": "analytical.F is present while NetCDF-like runtime data assets exist under input/.",
                    "impact": "reported only; not a default blocker",
                }
            )
        status = "planned"
        exit_code = 0
        if blockers:
            status = "blocked"
            exit_code = 11
        plan_path = paths["metadata"] / "dry_run_plan.json"
        report_path = paths["metadata"] / "dry_run_report.md"
        legacy_report_path = run_dir / "reports" / "dry_run_report.md"
        plan = {
            "experiment_name": args.experiment_name,
            "run_id": run_id,
            "input_dir": str(paths["input"]),
            "manifest_path": str(paths["manifest"]),
            "compile_attempt_ref": str(paths["metadata"] / "compile_attempt.json"),
            "compile_attempt": compile_attempt,
            "binary_path": str(binary_path),
            "runtime_data_assets": runtime_assets,
            "runtime_materialization": materialization_plan,
            "runtime_execution_plan": execution_plan,
            "warnings": warnings,
            "blockers": blockers,
            "status": status,
        }
        write_dry_run_plan(plan_path, plan)
        write_metadata_dry_run_report(report_path, plan)
        if args.run_id:
            legacy_report_path.parent.mkdir(parents=True, exist_ok=True)
            write_metadata_dry_run_report(legacy_report_path, plan)
        manifest.setdefault("assets", {}).setdefault("classification_counts", {})["runtime_data"] = len(runtime_assets)
        manifest["assets"].setdefault("selected_mounts", [])
        manifest["runtime_materialization"] = materialization_plan
        manifest["runtime_execution_plan"] = execution_plan
        manifest["dry_run"] = {"last_attempt": plan}
        manifest["reporting"].update(
            {
                "status": "reported_with_warnings" if warnings else "reported_clean",
                "last_reported_at": utc_now(),
                "warnings": warnings,
                "infrastructural_blockers": blockers,
                "dry_run_outcome": {"status": status, "exit_code": exit_code, "plan": str(plan_path), "report": str(report_path)},
            }
        )
        append_command(
            manifest,
            "dry-run",
            [args.experiment_name],
            inputs_used=[f"input/{name}" for name in PRIMARY_ARTIFACTS],
            staging_decisions=[],
            mappings=materialization_plan["symlinks"],
            logs=[],
            reports=[str(plan_path), str(report_path)] + ([str(legacy_report_path)] if args.run_id else []),
            warnings=warnings,
            findings=findings,
            failure_category="none" if exit_code == 0 else "unsupported_runtime_backend",
            exit_code=exit_code,
            source_ref=manifest.get("compile_time", {}).get("source_ref"),
        )
        write_manifest(manifest, paths["manifest"])
        summary = manifest_summary(manifest)
        summary.update(
            {
                "run_id": run_id,
                "dry_run_report": str(report_path),
                "dry_run_plan": str(plan_path),
                "binary_path": str(binary_path),
                "status": status,
                "failure_category": "none" if exit_code == 0 else "unsupported_runtime_backend",
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
    try:
        paths = experiment_paths(args)
        if args.run_id:
            validate_run_id(args.run_id)
        manifest = load_required_manifest_for_command(paths, args.experiment_name, "run")
        dry_run_plan = load_dry_run_plan(paths)
        run_id = args.run_id or generated_execution_run_id()
        run_dir = paths["runs"] / run_id
        materialization_plan, execution_plan, binary_path = resolve_run_plan(paths, dry_run_plan, run_id)
        docker_image = docker_image_for_run(dry_run_plan)
        materialized = materialize_run_workdir_from_plan(paths, run_dir, materialization_plan, execution_plan, binary_path)
        snapshots = snapshot_run_inputs(paths, run_dir)
        stdout_path = run_dir / "logs" / "run_stdout.log"
        stderr_path = run_dir / "logs" / "run_stderr.log"
        attempt_path = run_dir / "reports" / "run_attempt.json"
        report_path = run_dir / "reports" / "run_report.md"
        run_script = None
        docker_cmd = []
        exit_code = 0
        returncode = None
        failure_category = "none"
        blockers = list(materialized.get("blockers", []))
        warnings = list(dry_run_plan.get("warnings", []))
        warnings.extend(materialization_plan.get("warnings", []))
        warnings.extend(execution_plan.get("warnings", []))
        warnings.extend(materialized.get("warnings", []))
        if blockers:
            failure_category = "materialization_failed"
            exit_code = 12
            stdout_path.write_text("", encoding="utf-8")
            stderr_path.write_text("Run was not attempted because runtime materialization failed.\n", encoding="utf-8")
        else:
            run_script = write_run_wrapper(run_dir, execution_plan)
            docker_cmd = [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{paths['experiments_root']}:{CONTAINER_ROOT}:rw",
                "-w",
                container_path(run_dir / "work", paths["experiments_root"]),
            ]
            for key, value in sorted(execution_plan.get("environment", {}).items()):
                docker_cmd.extend(["-e", f"{key}={value}"])
            docker_cmd.extend([docker_image, "bash", container_path(run_script, paths["experiments_root"])])
            docker_path = shutil.which("docker")
            if docker_path is None:
                failure_category = "docker_backend"
                exit_code = 7
                stdout_path.write_text("", encoding="utf-8")
                stderr_path.write_text("ERROR: docker executable not found on host PATH.\n", encoding="utf-8")
            else:
                info_proc = run_docker_command(["docker", "info"])
                if info_proc.returncode != 0:
                    failure_category = "docker_backend"
                    exit_code = 7
                    stdout_path.write_text(info_proc.stdout or "", encoding="utf-8")
                    stderr_path.write_text(info_proc.stderr or "ERROR: Docker daemon unavailable.\n", encoding="utf-8")
                else:
                    proc = subprocess.run(docker_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    returncode = proc.returncode
                    stdout_path.write_text(proc.stdout or "", encoding="utf-8")
                    stderr_path.write_text(proc.stderr or "", encoding="utf-8")
                    if proc.returncode in {125, 126, 127}:
                        failure_category = "docker_backend"
                        exit_code = 7
                    elif proc.returncode != 0:
                        failure_category = "run_failure"
                        exit_code = 13

        outputs = inventory_run_outputs(run_dir)
        attempt = {
            "schema_version": 1,
            "experiment_name": args.experiment_name,
            "run_id": run_id,
            "attempted_at": utc_now(),
            "status": "success" if exit_code == 0 else "failed",
            "failure_category": failure_category,
            "profile": execution_plan.get("profile"),
            "docker_image": docker_image,
            "docker_command": docker_cmd,
            "workdir": str(run_dir / "work"),
            "output_dir": str(run_dir / "output"),
            "binary": {
                "path": str(binary_path),
                "workdir_link": rel_to(run_dir / "work" / "croco", paths["experiment_root"]),
            },
            "croco_in": {
                "path": "input/croco.in",
                "workdir_link": rel_to(run_dir / "work" / "croco.in", paths["experiment_root"]),
            }
            if "croco.in" in execution_plan.get("argv", [])
            else None,
            "source_plan": {
                "dry_run_plan_path": str(paths["metadata"] / "dry_run_plan.json"),
                "manifest_path": str(paths["manifest"]),
            },
            "materialization": {
                "symlinks": materialized.get("symlinks", []),
                "snapshots": snapshots,
                "warnings": materialized.get("warnings", []),
                "blockers": blockers,
            },
            "runtime_execution_plan": execution_plan,
            "logs": {"stdout_path": str(stdout_path), "stderr_path": str(stderr_path)},
            "returncode": returncode if returncode is not None else exit_code,
            "outputs": outputs,
            "warnings": warnings,
            "blockers": blockers,
        }
        write_run_attempt(attempt_path, attempt)
        write_v1_run_report(report_path, attempt)
        manifest["runtime_materialization"] = materialization_plan
        manifest["runtime_execution_plan"] = execution_plan
        manifest.setdefault("docker_backend", {})["image"] = docker_image
        manifest["docker_backend"]["working_directory"] = container_path(run_dir / "work", paths["experiments_root"])
        manifest["docker_backend"]["run_command_summary"] = " ".join(docker_cmd) if docker_cmd else "not attempted; runtime materialization blocked"
        manifest.setdefault("runs", {})["last_run_id"] = run_id
        manifest["runs"]["last_attempt"] = {
            "run_id": run_id,
            "attempted_at": attempt["attempted_at"],
            "status": attempt["status"],
            "profile": execution_plan.get("profile"),
            "report_path": str(report_path),
            "attempt_path": str(attempt_path),
            "returncode": attempt["returncode"],
            "failure_category": failure_category,
        }
        manifest.setdefault("reporting", {})["run_outcome"] = {
            "failure_category": failure_category,
            "exit_code": exit_code,
            "stdout_log": str(stdout_path),
            "stderr_log": str(stderr_path),
            "output_path": str(run_dir / "output"),
            "attempt": str(attempt_path),
            "outputs": outputs,
        }
        append_command(
            manifest,
            "run",
            [args.experiment_name],
            inputs_used=[str(paths["metadata"] / "dry_run_plan.json"), str(binary_path)],
            staging_decisions=[{"source": str(run_script), "destination": str(run_script), "reason": "generated_run_wrapper"}] if run_script else [],
            mappings=[{"host_path": str(paths["experiments_root"]), "container_path": CONTAINER_ROOT, "mode": "rw"}] + materialized.get("symlinks", []),
            logs=[str(stdout_path), str(stderr_path)],
            reports=[str(report_path), str(attempt_path)],
            warnings=warnings,
            findings=["Run records an execution attempt and does not prove scientific correctness."],
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
                "run_attempt": str(attempt_path),
                "run_stdout": str(stdout_path),
                "run_stderr": str(stderr_path),
                "output_path": str(run_dir / "output"),
                "snapshot": str(run_dir / "snapshots"),
                "binary": str(binary_path),
                "failure_category": failure_category,
                "status": attempt["status"],
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
    try:
        paths = experiment_paths(args)
        if not paths["experiment_root"].is_dir():
            raise CrocoexpError(f"missing experiment directory: {paths['experiment_root']}", 6, "missing_experiment_input")
        if not paths["input"].is_dir():
            raise CrocoexpError(f"missing input directory: {paths['input']}", 6, "missing_experiment_input")
        if not paths["manifest"].exists():
            raise CrocoexpError(
                f"missing manifest: {paths['manifest']}; run 'crocoexp import {args.experiment_name}' first",
                3,
                "missing_manifest",
            )
        ensure_importable(paths)
        try:
            manifest = load_manifest(paths["manifest"])
        except json.JSONDecodeError as e:
            raise CrocoexpError(f"malformed manifest JSON: {paths['manifest']}: {e}", 3, "malformed_manifest")
        except OSError as e:
            raise CrocoexpError(f"unable to read manifest: {paths['manifest']}: {e}", 3, "unreadable_manifest")

        source_ref = resolve_compile_source(args, manifest)
        manifest["compile_time"]["source_ref"] = source_ref
        clean_policy, previous_artifacts, previous_artifact_summary = resolve_compile_clean_policy(args, paths, manifest)
        cleaned_artifacts = []
        if clean_policy == "clean":
            cleaned_artifacts = clean_previous_compile_artifacts(paths, previous_artifacts)
            manifest.pop("compile", None)
            manifest.pop("build", None)
            if not args.json:
                print("Cleaned previous compile artifacts:")
                for item in cleaned_artifacts:
                    print(f"  {item}")
                if not cleaned_artifacts:
                    print("  none")
        elif clean_policy == "no-clean" and previous_artifacts and not args.json:
            print("Continuing without cleaning previous compile artifacts.")
        stage, logs, output, staged = stage_compile_inputs(paths)
        staged_source = copy_compile_source_to_stage(source_ref, stage)
        staged.append({"source": source_ref["host_path"], "destination": str(staged_source), "reason": "registered_source_tree_copy"})
        entrypoints = detect_compile_entrypoints(staged_source)

        compile_context = effective_compile_context(paths, logs, include_paths=source_include_paths_from_manifest(manifest))
        manifest["compile_time"]["active_cpp_symbols"] = compile_context["active_cpp_symbols"]
        manifest["compile_time"]["active_cpp_symbols_source"] = compile_context["active_cpp_symbols_source"]
        manifest["compile_time"]["active_symbol_resolution"] = compile_context["active_symbol_resolution"]
        manifest["compile_time"]["input_cppdefs_hash"] = compile_context["input_cppdefs_hash"]
        manifest["compile_time"]["input_param_hash"] = compile_context["input_param_hash"]
        manifest["compile_time"]["effective_preprocessor_provenance"] = compile_context["effective_preprocessor_provenance"]
        manifest["compile_time"]["effective_preprocessor_provenance_source"] = compile_context["effective_preprocessor_provenance_source"]
        manifest["compile_time"]["dimensions"] = compile_context["dimensions"]
        manifest["compile_time"]["effective_param_source"] = compile_context["effective_param_source"]
        manifest["compile_time"]["effective_param_resolution"] = compile_context["effective_param_resolution"]
        manifest["runtime_execution_plan"] = runtime_execution_plan(paths, compile_context)

        script = write_compile_script(paths, stage, output, source_ref)
        report_path = paths["metadata"] / "compile_report.md"
        attempt_path = paths["metadata"] / "compile_attempt.json"
        stdout_path = paths["build"] / "compile_stdout.log"
        stderr_path = paths["build"] / "compile_stderr.log"
        legacy_log_path = logs / f"compile_{args.experiment_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
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
        if clean_policy == "clean":
            findings.append("Previous compile artifacts were cleaned before this compile attempt.")
        elif clean_policy == "no-clean":
            findings.append("Compile continued without cleaning previous compile artifacts.")
        warnings = list(manifest.get("reporting", {}).get("warnings", []))
        manifest["compile_time"]["staged_inputs"] = staged
        manifest["docker_backend"]["image"] = docker_image
        manifest["docker_backend"]["working_directory"] = container_path(stage, paths["experiments_root"])
        manifest["docker_backend"]["compile_command_summary"] = " ".join(docker_cmd)
        manifest["docker_backend"]["mounts"] = docker_mounts

        failure_category = "none"
        exit_code = 0
        proc_returncode = None
        if not entrypoints:
            failure_category = "missing_compile_entrypoint"
            exit_code = 9
            warnings.append("No supported compile entrypoint found in registered source tree copy.")
            stdout_path.write_text("", encoding="utf-8")
            stderr_path.write_text("ERROR: no supported compile entrypoint found in registered source tree.\n", encoding="utf-8")
        else:
            docker_path = shutil.which("docker")
            if docker_path is None:
                stdout_path.write_text("", encoding="utf-8")
                stderr_path.write_text("ERROR: docker executable not found on host PATH.\n", encoding="utf-8")
                failure_category = "docker_backend"
                exit_code = 7
            else:
                info_proc = run_docker_command(["docker", "info"])
                if info_proc.returncode != 0:
                    stdout_path.write_text(info_proc.stdout or "", encoding="utf-8")
                    stderr_path.write_text(info_proc.stderr or "ERROR: Docker daemon unavailable.\n", encoding="utf-8")
                    failure_category = "docker_backend"
                    exit_code = 7
                else:
                    proc = subprocess.run(docker_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    proc_returncode = proc.returncode
                    stdout_path.write_text(proc.stdout or "", encoding="utf-8")
                    stderr_path.write_text(proc.stderr or "", encoding="utf-8")
                    if proc.returncode in {125, 126, 127}:
                        failure_category = "docker_backend"
                        exit_code = 7
                    elif proc.returncode != 0:
                        failure_category = "compile_failure"
                        exit_code = 8

        legacy_log_path.write_text(
            (stdout_path.read_text(encoding="utf-8", errors="replace") if stdout_path.exists() else "")
            + (stderr_path.read_text(encoding="utf-8", errors="replace") if stderr_path.exists() else ""),
            encoding="utf-8",
        )
        binary = find_compile_binary(paths) if exit_code == 0 else None
        attempt = {
            "attempted_at": utc_now(),
            "status": "success" if exit_code == 0 else "failed",
            "failure_category": failure_category,
            "source_id": source_ref["source_id"],
            "source_installed_path": source_ref.get("installed_path") or source_ref["host_path"],
            "stage_dir": str(stage),
            "docker_image": docker_image,
            "docker_command": docker_cmd if entrypoints else [],
            "returncode": proc_returncode if proc_returncode is not None else exit_code,
            "warnings": warnings,
            "logs": {"stdout_path": str(stdout_path), "stderr_path": str(stderr_path)},
            "binary": binary,
            "staged_inputs": staged,
            "compile_entrypoints": entrypoints,
            "clean_policy": clean_policy,
            "previous_compile_artifacts": previous_artifact_summary,
            "cleaned_artifacts": cleaned_artifacts,
        }
        write_compile_attempt(attempt_path, attempt)
        if binary:
            manifest.setdefault("build", {})["binary"] = binary
        manifest["compile"] = {"last_attempt": attempt}
        append_command(
            manifest,
            "compile",
            [args.experiment_name],
            inputs_used=[source_ref["host_path"]] + [s["source"] for s in staged],
            staging_decisions=staged + [{"source": str(script), "destination": str(script), "reason": "generated_compile_wrapper"}],
            mappings=docker_mounts,
            logs=[str(stdout_path), str(stderr_path), str(legacy_log_path)],
            reports=[str(report_path), str(attempt_path)],
            warnings=warnings,
            findings=findings,
            failure_category=failure_category,
            exit_code=exit_code,
            docker_image=docker_image,
            source_ref=source_ref,
        )
        manifest["reporting"]["compile_outcome"] = {
            "failure_category": failure_category,
            "exit_code": exit_code,
            "log": str(legacy_log_path),
            "stdout_log": str(stdout_path),
            "stderr_log": str(stderr_path),
            "attempt": str(attempt_path),
        }
        write_compile_report(manifest, report_path, legacy_log_path, failure_category, exit_code, attempt)
        write_manifest(manifest, paths["manifest"])
        summary = manifest_summary(manifest)
        summary.update(
            {
                "compile_report": str(report_path),
                "compile_attempt": str(attempt_path),
                "compile_stdout": str(stdout_path),
                "compile_stderr": str(stderr_path),
                "compile_log": str(legacy_log_path),
                "failure_category": failure_category,
                "docker_image": docker_image,
                "source_id": source_ref["source_id"],
                "clean_policy": clean_policy,
                "cleaned_artifacts": cleaned_artifacts,
                "previous_compile_artifacts": previous_artifact_summary,
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
