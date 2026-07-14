# Changelog

## [1.0.2] - Unreleased

### Fixed

- Docker-based `run` now initializes the default container environment before launching CROCO, including `LD_LIBRARY_PATH` for NetCDF dynamic libraries.
- Docker-based `compile` and auxiliary container commands now use the same container profile initialization path.
- Experiments imported before image profiles existed now fall back to the default container profile.
- `compile --clean` now handles permission issues caused by previous Docker-created build artifacts.

### Changed

- Introduced internal container image profiles to centralize Docker image selection and image-specific initialization.

## v1.0.0

Initial stable release of CROCOEXP Builder as a host-side, traceability-oriented CROCO experiment orchestrator.

### Supported Commands

- `crocoexp setup`
- `crocoexp source install /path/to/source --id <source_id>`
- `crocoexp source list`
- `crocoexp source inspect <source_id>`
- `crocoexp import <experiment_name>`
- `crocoexp import <experiment_name> --source <source_id>`
- `crocoexp inspect <experiment_name>`
- `crocoexp inspect <experiment_name> --json`
- `crocoexp compile <experiment_name>`
- `crocoexp dry-run <experiment_name>`
- `crocoexp dry-run <experiment_name> --json`
- `crocoexp run <experiment_name>`
- `crocoexp run <experiment_name> --run-id <run_id>`
- `crocoexp run <experiment_name> --json`

### Stable Scope

- Normal workflow is launched from the host.
- Docker is used only as the compile/run backend.
- `setup` records Docker backend readiness and does not select a CROCO source.
- Registered source trees are copied under `CROCO_EXPERIMENTS/sources/<source_id>/`.
- Source registry metadata is stored in `.crocoexp/sources.json`.
- Source selection is per experiment through `compile_time.source_ref`.
- `import` records existing `input/` evidence and writes generated metadata outside `input/`.
- `inspect` is read-only.
- `compile` records Docker-backed build attempts, logs, and metadata.
- `dry-run` plans runtime materialization and execution without launching CROCO.
- `run` consumes the dry-run plan, materializes a run-local workdir, creates relative symlinks to runtime data in `input/`, launches supported profiles through Docker, and records the attempt.

### Execution Scope

v1.0.0 supports serial execution and tested OpenMP execution. MPI, OPENACC, XIOS, OASIS, AGRIF, GPU, coupled, nested, and other specialized execution profiles are out of scope unless explicitly implemented and tested in a later release.

### Guarantees And Limitations

- `input/` is canonical user-provided evidence and is not modified by CROCOEXP commands.
- Runtime data assets remain canonical in `input/`.
- `croco.in` is recorded as CROCO input syntax but is not treated as universal semantic truth.
- `run.env` is unsupported and ignored if present.
- CROCOEXP records reproducible orchestration evidence, attempts, logs, reports, snapshots, warnings, and failures.
- CROCOEXP does not prove scientific correctness, compile correctness, runtime semantic compatibility, or experiment well-posedness.
- Added `docs/user_manual_v1.0.0.md` as the stable v1.0.0 user manual.
- Added citation guidance to `README.md` and `docs/user_manual_v1.0.0.md`, using `CITATION.cff` as the metadata source of truth.

### v1.0.0 Release Checklist

- [x] Tests pass with `python -m unittest tests/test_crocoexp.py`.
- [x] Setup command documented.
- [x] Source registry documented.
- [x] Import, inspect, compile, dry-run, and run documented.
- [x] Acceptance workflow covered by tests.
- [x] Unsupported profiles documented.
- [x] `input/` immutability documented.
- [x] Docker backend behavior documented.
