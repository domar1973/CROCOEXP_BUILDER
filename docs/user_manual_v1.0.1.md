# CROCOEXP User Manual v1.0.1

## Purpose

CROCOEXP v1.0.1 is a reproducible host-side orchestrator for CROCO experiment workflows. It records how an experiment was set up, which source tree was selected, what was imported, what was compiled, what was planned, what was run, and what failed.

CROCOEXP guarantees reproducible orchestration.
CROCO guarantees the numerical model.
The user guarantees the scientific configuration.

CROCOEXP does not prove scientific correctness, compile correctness in a scientific sense, runtime semantic compatibility, numerical stability, or experiment well-posedness.

## Supported Scope

Supported v1.0.1 commands:

- `setup`
- `source install`
- `source list`
- `source inspect`
- `source uninstall`
- `experiment list`
- `experiment unimport`
- `import`
- `inspect`
- `compile`
- `dry-run`
- `run`

Supported execution scope:

- Host-side CLI workflow
- Docker-backed compile and run execution
- Serial CROCO execution
- OpenMP execution only when planned and tested by the implementation

Out-of-scope execution for v1.0.1:

- MPI
- OPENACC
- XIOS
- OASIS
- AGRIF
- GPU execution
- coupled execution
- nested execution unless explicitly implemented and tested

Unsupported profiles are blocked conservatively before run execution.

## Core Concepts

- **Host-side CLI**: users run `./crocoexp ...` from the host.
- **Repo-root path model**: commands may run from any subdirectory in the repo; CROCOEXP resolves paths through the detected repo root without changing the process cwd globally.
- **Docker backend**: Docker is used by CROCOEXP as a compile/run backend, not as the user interface.
- **Experiment root**: `CROCO_EXPERIMENTS/<experiment_name>/`.
- **Immutable `input/`**: user-provided CROCO artifacts and runtime data live under `input/`; CROCOEXP commands do not modify those files.
- **Generated metadata**: manifests, reports, attempts, logs, plans, and snapshots are generated outside `input/`.
- **Source registry**: compile source trees are registered at repo level under `CROCO_EXPERIMENTS/sources/<source_id>/`, with metadata in `.crocoexp/sources.json`.
- **Per-experiment source binding**: `import --source <source_id>` records the selected source in the experiment manifest as `compile_time.source_ref`.
- **Compile attempt**: `compile` stages inputs, invokes Docker, records logs, and writes compile metadata.
- **Dry-run plan**: `dry-run` plans runtime materialization and execution without launching CROCO.
- **Run attempt**: `run` consumes the dry-run plan, materializes a workdir, invokes Docker for supported profiles, and records the attempt.
- **Runtime workdir**: CROCO runs from `CROCO_EXPERIMENTS/<experiment_name>/runs/<run_id>/work/`.
- **Relative symlink materialization**: runtime data stay in `input/`; `run` exposes them through relative symlinks inside the run-local workdir.
- **Traceability vs validation**: CROCOEXP records orchestration evidence and failures. It does not validate the science.

## Directory Layout

Expected repo/workspace layout:

```text
.crocoexp/
  config.json
  setup_report.md
  sources.json

CROCO_EXPERIMENTS/
  sources/<source_id>/
  <experiment_name>/
    input/
    metadata/
    build/
    runs/<run_id>/
      work/
      output/
      logs/
      snapshots/
      reports/
```

Directory meanings:

- `.crocoexp/config.json`: repo-level Docker/backend setup state.
- `.crocoexp/setup_report.md`: human-readable setup report.
- `.crocoexp/sources.json`: repo-level source registry.
- `CROCO_EXPERIMENTS/sources/<source_id>/`: managed copy of a CROCO source tree.
- `CROCO_EXPERIMENTS/<experiment_name>/input/`: canonical user-provided evidence. Put `croco.in`, `cppdefs.h`, `param.h`, optional `analytical.F`, and runtime data here.
- `metadata/`: generated manifests, reports, compile attempts, and dry-run plans.
- `build/`: generated compile staging, logs, and build products.
- `runs/<run_id>/work/`: run-local workdir used for CROCO execution.
- `runs/<run_id>/output/`: observed/generated outputs inventory area.
- `runs/<run_id>/logs/`: run stdout/stderr logs.
- `runs/<run_id>/snapshots/`: small provenance snapshots and runtime data inventories.
- `runs/<run_id>/reports/`: run attempt metadata and human-readable run reports.

Generated files do not belong in `input/`. NetCDF-like runtime data assets stay canonical in `input/`, and `run` exposes those assets through relative symlinks in `runs/<run_id>/work/`.

Persisted operational paths in manifests and metadata are repo-root-relative POSIX paths when they point inside the repo. External source origins may be recorded as informational provenance, but operational paths outside the repo are rejected.

## Quick Start Workflow

Use this v1.0.1 command sequence:

```bash
./crocoexp setup --image domarcroco/images-for-croco:base_croco-1.0.1 --pull
./crocoexp source install /path/to/croco/source --id croco-local
./crocoexp import minimal --source croco-local
./crocoexp experiment list
./crocoexp inspect minimal
./crocoexp compile minimal
./crocoexp dry-run minimal
./crocoexp run minimal --run-id test-run-001
```

Before `import`, create `CROCO_EXPERIMENTS/minimal/input/` and place the real experiment artifacts there.
Use `./crocoexp experiment unimport minimal` to remove CROCOEXP metadata/build state while preserving `input/`.

## Preparing An Experiment

Create:

```text
CROCO_EXPERIMENTS/<experiment_name>/input/
```

Place real CROCO artifacts there, commonly:

- `croco.in`
- `cppdefs.h`
- `param.h`
- `analytical.F`
- `.nc` files
- `.nc4` files
- `.cdf` files
- `.netcdf` files

`croco.in` is recorded as evidence, but CROCOEXP does not treat it as universal semantic truth. CROCO input syntax varies across CROCO versions and local CROCO variants. CROCOEXP does not infer required runtime data assets solely from text in `croco.in`.

`run.env` is unsupported. If `input/run.env` exists, it is recorded as ignored. It is not sourced, parsed, or used as configuration.

## Command Reference

### `setup`

Purpose: check and record Docker backend readiness.

Syntax:

```bash
./crocoexp setup
./crocoexp setup --image domarcroco/images-for-croco:base_croco-1.0.1 --pull
./crocoexp setup --no-pull
./crocoexp setup --check-only
```

Inputs:

- Docker CLI availability
- Docker daemon availability
- selected Docker image name

Generated outputs:

- `.crocoexp/config.json`
- `.crocoexp/setup_report.md`

What it does not do:

- does not select a CROCO source
- does not select a global CROCO version
- does not touch experiment `input/`
- does not import, compile, dry-run, or run experiments
- does not write `.crocoexp/sources.json`

Common failure cases:

- Docker CLI missing
- Docker daemon unavailable
- image missing and pull disabled
- unable to write setup files

### `source install`

Purpose: copy and register a compile source tree as repo-level infrastructure.

Syntax:

```bash
./crocoexp source install /path/to/croco/source --id croco-local
```

Inputs:

- existing source directory
- safe `source_id`

Generated outputs:

- `CROCO_EXPERIMENTS/sources/<source_id>/`
- `.crocoexp/sources.json`

What it does not do:

- does not bind the source to an experiment
- does not modify experiment `input/`
- does not invoke Docker
- does not compile CROCO

Common failure cases:

- source path missing or not a directory
- invalid source ID
- target source ID already installed
- unable to write registry metadata

### `source list`

Purpose: list repo-level registered source trees.

Syntax:

```bash
./crocoexp source list
./crocoexp source list --json
```

Inputs:

- `.crocoexp/sources.json`, if present

Generated outputs:

- terminal or JSON summary

What it does not do:

- does not modify sources or experiments
- does not invoke Docker

Common failure cases:

- malformed source registry

### `source inspect`

Purpose: inspect one registered source.

Syntax:

```bash
./crocoexp source inspect croco-local
./crocoexp source inspect croco-local --json
```

Inputs:

- source ID
- `.crocoexp/sources.json`

Generated outputs:

- terminal or JSON summary

What it does not do:

- does not modify source trees or experiments
- does not invoke Docker

Common failure cases:

- registry missing
- source ID missing
- malformed registry

### `source uninstall`

Purpose: remove one registered CROCO source without deleting experiments.

Syntax:

```bash
./crocoexp source uninstall croco-local
./crocoexp source uninstall croco-local --force
```

Behavior:

- removes the source registry entry;
- removes the managed installed tree under `CROCO_EXPERIMENTS/sources/<source_id>/` when safe;
- lists dependent experiments before uninstalling;
- asks for confirmation in TTY mode when dependents exist;
- requires `--force` in non-interactive mode when dependents exist;
- never modifies or deletes dependent experiments.

Dependent experiments keep orphaned source references until they are reimported with a valid source.

### `import`

Purpose: inspect an existing experiment `input/` folder and write traceability metadata.

Syntax:

```bash
./crocoexp import minimal --source croco-local
./crocoexp import minimal --source croco-local --json
```

Inputs:

- `CROCO_EXPERIMENTS/<experiment_name>/input/`
- registered source ID via `--source`, or TTY selection when omitted interactively

Generated outputs:

- `metadata/manifest.json`
- `metadata/report.md`
- `build/`
- `runs/`

What it does not do:

- does not modify `input/`
- does not compile CROCO
- does not dry-run or run CROCO
- does not copy registered source trees into the experiment
- does not parse `croco.in` as universal semantic truth
- does not source `run.env`

Common failure cases:

- invalid experiment name
- missing `input/`
- requested source ID missing
- omitted `--source` in non-interactive mode
- no registered sources available
- unable to write metadata

If the imported folder is outside `CROCO_EXPERIMENTS/<experiment_name>/`, CROCOEXP copies it to the canonical location first and imports the copy. The original folder is not modified.

### `experiment list`

Purpose: list imported experiments and source availability.

Syntax:

```bash
./crocoexp experiment list
./crocoexp experiment list --json
```

The list is based on canonical manifests. Experiments with a missing registered source are shown as orphaned.

### `inspect`

Purpose: read and summarize an imported experiment manifest.

Syntax:

```bash
./crocoexp inspect minimal
./crocoexp inspect minimal --json
```

Inputs:

- `metadata/manifest.json`

Generated outputs:

- terminal or JSON summary

What it does not do:

- does not create missing directories
- does not rewrite manifest or reports
- does not modify `input/`
- does not compile, dry-run, or run CROCO
- does not invoke Docker

Common failure cases:

- missing experiment root
- missing `input/`
- missing manifest
- malformed manifest

### `compile`

Purpose: make a traceable Docker-backed build attempt using the experiment source reference.

Syntax:

```bash
./crocoexp compile minimal
./crocoexp compile minimal --clean
./crocoexp compile minimal --no-clean
./crocoexp compile minimal --json
```

Inputs:

- imported manifest
- `compile_time.source_ref`
- `.crocoexp/sources.json`
- registered source tree
- Docker CLI and daemon

If previous compile artifacts are present, non-interactive compile requires `--clean` or `--no-clean`. Interactive compile asks whether to clean, keep, or abort.

Generated outputs:

- `build/stage/`
- `build/compile_stdout.log`
- `build/compile_stderr.log`
- `metadata/compile_attempt.json`
- `metadata/compile_report.md`
- updated `metadata/manifest.json`

What it does not do:

- does not modify `input/`
- does not run CROCO
- does not select a global source
- does not use `run.env`
- does not prove scientific correctness or runtime semantic compatibility

Common failure cases:

- missing manifest
- missing source reference
- missing source registry or source ID
- registered source tree missing
- Docker CLI or daemon unavailable
- no supported compile entrypoint
- compile command returned nonzero

### `dry-run`

Purpose: plan runtime materialization and execution without launching CROCO.

Syntax:

```bash
./crocoexp dry-run minimal
./crocoexp dry-run minimal --json
```

Inputs:

- imported manifest
- successful compile attempt
- recorded binary path
- compile-time evidence such as `cppdefs.h`, `param.h`, and compile metadata

Generated outputs:

- `metadata/dry_run_plan.json`
- `metadata/dry_run_report.md`
- updated `metadata/manifest.json`

What it does not do:

- does not invoke Docker
- does not compile CROCO
- does not launch CROCO
- does not create run workdirs
- does not modify `input/`
- does not infer runtime data requirements from `croco.in`
- does not source `run.env`

Common failure cases:

- missing or malformed manifest
- missing compile attempt
- failed compile attempt
- missing binary metadata
- recorded binary missing
- unsupported runtime execution profile

### `run`

Purpose: consume the dry-run plan, materialize a run-local workdir, execute supported profiles through Docker, and record the attempt.

Syntax:

```bash
./crocoexp run minimal
./crocoexp run minimal --run-id test-run-001
./crocoexp run minimal --json
```

Inputs:

- imported manifest
- `metadata/dry_run_plan.json`
- planned runtime materialization
- planned runtime execution profile
- recorded compiled binary
- Docker CLI and daemon

Generated outputs:

- `runs/<run_id>/work/`
- `runs/<run_id>/output/`
- `runs/<run_id>/logs/run_stdout.log`
- `runs/<run_id>/logs/run_stderr.log`
- `runs/<run_id>/snapshots/`
- `runs/<run_id>/reports/run_attempt.json`
- `runs/<run_id>/reports/run_report.md`
- updated `metadata/manifest.json`

What it does not do:

- does not compile CROCO
- does not modify `input/`
- does not infer runtime data requirements from `croco.in`
- does not support unsupported runtime profiles
- does not prove scientific correctness or runtime semantic compatibility

Common failure cases:

- missing or malformed manifest
- missing or malformed dry-run plan
- dry-run plan blocked
- unsupported execution profile
- binary missing
- runtime data asset missing
- Docker CLI or daemon unavailable
- CROCO execution returned nonzero

## Runtime Data Policy

NetCDF-like runtime assets are:

- `.nc`
- `.nc4`
- `.cdf`
- `.netcdf`

Policy:

- These files stay in `input/`.
- `dry-run` plans relative symlinks from the future workdir to these files.
- `run` materializes those relative symlinks.
- Runtime data are not copied into `work/` as regular files.
- Missing runtime assets cause run materialization failure before CROCO is launched.

Example:

```text
input/GRD/grid.nc
runs/test-run-001/work/GRD/grid.nc -> ../../../../input/GRD/grid.nc
```

## Runtime Execution Profiles

Serial planned command concept:

```bash
./croco croco.in
```

OpenMP planned command concept:

```bash
OMP_NUM_THREADS=<N> ./croco croco.in
```

`N` is derived from compile-time evidence such as `NPP` when available. If OpenMP is planned, CROCOEXP records the chosen environment and command.

Unsupported in v1.0.1 unless explicitly implemented and tested:

- MPI
- OPENACC
- XIOS
- OASIS
- AGRIF

When unsupported symbols are active, `dry-run` records blockers and returns a nonzero status. `run` rejects blocked or unsupported dry-run plans and does not launch CROCO.

## Metadata And Reports

Important generated files:

- `metadata/manifest.json`: canonical experiment traceability manifest.
- `metadata/report.md`: import report with artifact-level evidence.
- `metadata/compile_attempt.json`: machine-readable compile attempt.
- `metadata/compile_report.md`: human-readable compile report.
- `metadata/dry_run_plan.json`: machine-readable runtime materialization and execution plan.
- `metadata/dry_run_report.md`: human-readable dry-run report.
- `runs/<run_id>/reports/run_attempt.json`: machine-readable run attempt.
- `runs/<run_id>/reports/run_report.md`: human-readable run report.
- `runs/<run_id>/logs/run_stdout.log`: run stdout.
- `runs/<run_id>/logs/run_stderr.log`: run stderr.
- `runs/<run_id>/snapshots/`: small reproducibility snapshots and runtime data inventory.

These files are generated outside `input/`.

## Reproducibility Guarantees And Limits

CROCOEXP records:

- attempted commands
- selected source
- staged artifacts
- runtime asset inventory
- symlink plans
- Docker image
- Docker commands
- logs
- warnings
- failures

CROCOEXP does not prove:

- scientific correctness
- compile correctness in the mathematical or scientific sense
- runtime semantic compatibility
- experiment well-posedness
- numerical stability
- quality of forcing, boundary conditions, bathymetry, or parameter choices

## Troubleshooting

- **Docker CLI missing**: install Docker or ensure `docker` is on `PATH`.
- **Docker daemon unavailable**: start Docker and rerun `setup`, `compile`, or `run`.
- **Docker image missing**: run `setup --pull` or configure an available image.
- **Source ID missing**: run `source list`, then install or use an existing source ID.
- **`input/` missing**: create `CROCO_EXPERIMENTS/<experiment_name>/input/` and add real CROCO artifacts.
- **Manifest missing**: run `import <experiment_name>` first.
- **Malformed manifest**: inspect and repair or recreate generated metadata with a clean import.
- **Missing compile source**: rerun import with `--source <source_id>`.
- **Compile entrypoint missing**: verify the registered source tree contains a supported compile entrypoint such as `jobcomp`, `jobcomp_rsf`, or a Makefile.
- **Compile failed**: review `metadata/compile_report.md`, `build/compile_stdout.log`, and `build/compile_stderr.log`.
- **Dry-run blocked because no binary**: rerun `compile` successfully and verify the binary path in `metadata/compile_attempt.json`.
- **Dry-run blocked because unsupported profile**: serial and tested OpenMP are supported; MPI, OPENACC, XIOS, OASIS, and AGRIF are blocked in v1.0.1.
- **Run blocked because runtime asset missing**: restore the missing runtime data asset under `input/` and rerun `dry-run` if needed.
- **Run failed because CROCO returned nonzero**: review `runs/<run_id>/logs/run_stdout.log`, `runs/<run_id>/logs/run_stderr.log`, and `runs/<run_id>/reports/run_report.md`.

## Citing CROCOEXP

Cite CROCOEXP when using it to organize, compile, dry-run, run, or document CROCO experiments. Cite the exact version used. For v1.0.1, the citation metadata source of truth is `CITATION.cff`.

Example citation:

Badagnani, D. (2026). CROCOEXP Builder (v1.0.1) [Software]. https://github.com/domar1973/CROCOEXP_BUILDER

Cite CROCO separately because CROCOEXP does not replace the numerical model. Cite forcing, bathymetry, boundary condition, observational, reanalysis, forecast, or other datasets separately as required by their providers.

Citation of CROCOEXP does not imply that CROCOEXP validates scientific correctness, runtime semantic compatibility, numerical stability, or experiment well-posedness.

BibTeX example:

```bibtex
@software{crocoexp_builder_2026,
  title = {CROCOEXP Builder},
  author = {Badagnani, Daniel},
  year = {2026},
  version = {1.0.1},
  url = {https://github.com/domar1973/CROCOEXP_BUILDER}
}
```

## Release Checklist For Users

Before relying on a v1.0.1 run record:

- Docker works.
- Source is installed.
- Experiment `input/` exists.
- Import completed.
- Inspect output looks reasonable.
- Compile attempt is recorded.
- Dry-run plan has a supported profile.
- Run materialized relative symlinks.
- Logs and reports were reviewed.
