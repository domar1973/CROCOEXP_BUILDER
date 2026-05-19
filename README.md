# CROCOEXP_BUILDER

CROCOEXP_BUILDER is a host-side tool for managing traceable CROCO experiment workflows. It prepares Docker-backed execution, registers compile source trees, imports real experiment artifacts, and records what was attempted during compile, dry-run, and run operations.

The builder is infrastructure-oriented and traceability-oriented. It does not prove that a CROCO configuration is scientifically valid or that compile-time and runtime choices are semantically compatible. It records evidence, staging decisions, mappings, warnings, logs, reports, snapshots, and failures so the researcher can inspect and reproduce each attempt.

## Core Architecture

- Docker is the execution backend only.
- Users launch all commands from the host with `crocoexp`.
- Experiment evidence lives under `CROCO_EXPERIMENTS/<experiment_name>/input/`.
- Runtime data files such as `.nc` remain canonical in `input/`.
- CROCO runs from `CROCO_EXPERIMENTS/<experiment_name>/runs/<run_id>/work/`.
- Runtime data is exposed in `work/` with relative symlinks that preserve paths from `input/`.
- Registered compile source trees live under `CROCO_EXPERIMENTS/sources/<source_id>/`.
- The source registry lives at `.crocoexp/sources.json`.
- Experiment manifests live at `CROCO_EXPERIMENTS/<experiment_name>/metadata/manifest.json`.
- Compile source selection is per experiment through `compile_time.source_ref`.
- Setup records Docker/backend readiness only. It is not a global CROCO source selector.

## Repository Commands

Development note: this repository is implementing v1.0.0 in small slices. The current implemented slices lock the CLI surface, implement repo-level `setup` for Docker backend readiness, implement the repo-level source registry commands, and import existing experiment input trees into generated metadata.

Check and record Docker backend readiness:

```bash
./crocoexp setup --no-pull
```

Use `--pull` when you want setup to pull the selected image if it is missing:

```bash
./crocoexp setup --image domarcroco/images-for-croco:base_croco_msot-1.0.0 --pull
```

Register a compile source tree by copying it into the managed sources area:

```bash
./crocoexp source install /path/to/croco-source --id croco-v2.1.2 --flavor croco --version v2.1.2
```

List and inspect registered sources:

```bash
./crocoexp source list
./crocoexp source inspect croco-v2.1.2
```

Supported source flavors are `croco`, `msot`, and `custom`. Flavor is traceability metadata; it is not semantic validation.

## Experiment Workflow

Create or provide the experiment evidence folder on the host:

```text
CROCO_EXPERIMENTS/my_experiment/
  input/
    croco.in
    cppdefs.h
    param.h
    analytical.F        # optional
    GRD/*.nc            # optional runtime data
    INIT/*.nc           # optional runtime data
    FRC/*.nc            # optional runtime data
```

Import the experiment and select its compile source:

```bash
./crocoexp import minimal
./crocoexp import minimal --source croco-msot-local
./crocoexp import my_experiment --source croco-v2.1.2
```

`input/` is the canonical user-provided evidence folder. Import writes generated metadata under `metadata/`, creates managed `build/` and `runs/` directories if needed, and does not modify `input/`. Import with `--source` records a per-experiment source reference; it does not select a global CROCO version, compile CROCO, or run CROCO.

During import, `croco.in` is recorded as an artifact but is not treated as universal CROCO semantic truth. `run.env`, if present, is ignored and recorded with a warning.

Inspect current metadata:

```bash
./crocoexp inspect minimal
./crocoexp inspect minimal --json
./crocoexp inspect my_experiment
```

`inspect` is read-only. It reads `metadata/manifest.json`, reports recorded artifact-level findings and warnings, and does not modify `input/`, metadata, source registry state, or setup config. It does not compile, dry-run, or run CROCO, and it does not prove scientific correctness, compile correctness, runtime semantic compatibility, or experiment well-posedness.

Compile through Docker from the host:

```bash
./crocoexp compile minimal
./crocoexp compile my_experiment
```

`compile` uses the per-experiment source reference recorded during import. Docker is used only as the backend; build staging, logs, `metadata/compile_attempt.json`, and `metadata/compile_report.md` are written outside `input/`. Compile does not run CROCO, and compile success does not prove scientific correctness or runtime semantic compatibility.

Generate a pre-execution report without running CROCO:

```bash
./crocoexp dry-run minimal
./crocoexp dry-run minimal --json
./crocoexp dry-run my_experiment
```

`dry-run` is host-side planning only. It consumes import and compile metadata, does not compile CROCO, does not launch CROCO, keeps runtime data canonical in `input/`, and plans relative symlinks from a future run-local workdir to NetCDF-like runtime data assets. Runtime execution profile planning is derived from compile-time evidence such as `cppdefs.h` and `param.h`, not from `croco.in`. It writes `metadata/dry_run_plan.json` and `metadata/dry_run_report.md`.

Attempt a CROCO run through Docker:

```bash
./crocoexp run my_experiment
```

Explicit `--image` overrides are available on Docker-backed commands. When no explicit image is provided, commands use the repo setup default image if present, then the built-in default image.

## Directory Layout

```text
.crocoexp/
  config.json           # repo-local Docker/backend setup state
  setup_report.md
  sources.json          # registered compile source registry

CROCO_EXPERIMENTS/
  sources/
    <source_id>/        # managed copy of an official CROCO, MSOT, or custom tree

  <experiment_name>/
    input/              # canonical user-provided experiment evidence
    metadata/           # manifest and generated reports
    build/              # compile staging, logs, and outputs
    runs/
      <run_id>/
        work/
        logs/
        output/
        snapshots/
        reports/
```

## Data Handling Policy

`input/` is the canonical location for user-provided experiment artifacts. The builder must not modify files there during normal workflow.

Runtime data assets such as `.nc`, `.nc4`, `.cdf`, and `.netcdf` files stay in `input/`. They are not copied into `build/`, `metadata/`, run snapshots, or the run workdir as regular files. During `run`, CROCOEXP creates relative symlinks in `runs/<run_id>/work/` that preserve each file's path relative to `input/`.

Example:

```text
input/GRD/mesa_grd.nc
input/INIT/mesa_ini.nc

runs/<run_id>/work/GRD/mesa_grd.nc  -> ../../../../input/GRD/mesa_grd.nc
runs/<run_id>/work/INIT/mesa_ini.nc -> ../../../../input/INIT/mesa_ini.nc
```

Because CROCO executes from `work/`, paths in `croco.in` should be written relative to that workdir, usually mirroring the paths under `input/`, for example `GRD/mesa_grd.nc` and `INIT/mesa_ini.nc`.

Generated metadata, reports, build products, logs, snapshots, and run outputs live outside `input/`. Compile source trees are copied into `CROCO_EXPERIMENTS/sources/<source_id>/` so Docker can access them through the managed experiments mount without depending on external host symlinks.

Docker mounts the whole `CROCO_EXPERIMENTS` tree so workdir symlinks resolve both on the host and in the container. Runtime data should live under `CROCO_EXPERIMENTS/<experiment_name>/input/`; symlinks to arbitrary absolute host paths outside the experiments tree are unsafe.

## `croco.in` And `run.env`

`croco.in` is opaque to CROCOEXP by default. CROCOEXP does not parse it as universal CROCO semantic truth, because CROCO input syntax varies across versions, MSOT, and custom forks. Some versions use keys such as `GRDNAME == ...`; others use blocks such as `grid: filename`.

CROCOEXP guarantees filesystem visibility and execution traceability, not CROCO semantic validation. CROCO itself and its logs remain the authority for runtime model errors.

`run.env` is not supported:

- It is not sourced.
- It is not parsed.
- `croco.in` is not rendered as a template.
- `${...}` tokens in `croco.in` are warnings only.
- If `input/run.env` exists, it is treated as an ignored ordinary user file.

## Runtime Execution Plan

CROCOEXP keeps runtime file materialization separate from runtime process launch:

- Runtime materialization controls filesystem visibility.
- Runtime execution planning controls process launch semantics.

The execution plan is derived from effective compile-time state, not raw `cppdefs.h` line order. CROCO distribution `cppdefs.h` and `param.h` files often contain inactive branches for many named cases. Raw grep can show later `#define MPI` or `#undef OPENMP` lines that do not belong to the active case.

CROCOEXP resolves active CPP symbols with the C preprocessor. Trusted compile evidence such as `active_cpp_symbols.txt` and `effective_param.h` may be reused only when provenance and current `input/cppdefs.h` and `input/param.h` hashes match. Otherwise dry-run/run recompute effective state from the current experiment input files.

Exact active-symbol matching is required. `MPI` means MPI; compatibility symbols such as `MPI_COMM_WORLD` and `MPI_master_only` do not imply MPI.

Supported runtime backends in v1:

- serial
- OpenMP

For OpenMP, CROCOEXP detects effective `OPENMP`, parses effective `NPP`, `NSUB_X`, and `NSUB_E` from preprocessed `param.h`, and sets `OMP_NUM_THREADS=NPP`. Docker receives `-e OMP_NUM_THREADS=<NPP>`, and the run wrapper hard-exports the value:

```bash
export OMP_NUM_THREADS=8
echo "CROCOEXP: OMP_NUM_THREADS=${OMP_NUM_THREADS}"
./croco croco.in
```

This is required because CROCO aborts if the runtime OpenMP thread count exceeds compiled `NPP`.

Detected but unsupported launch profiles in v1:

- MPI
- MPI + OpenMP hybrid
- OpenACC
- XIOS
- OASIS

When one of these exact active symbols requires a specialized runtime profile, CROCOEXP blocks before launching Docker with an infrastructural runtime-backend diagnostic.

## Dry-Run And Run

`dry-run` reports infrastructure, not CROCO semantic proof. It reports primary artifacts, runtime data assets found under `input/`, the symlink plan, Docker mount plan, runtime execution plan, active-symbol diagnostics, effective-parameter diagnostics, unresolved `${...}` warnings, ignored `run.env` warnings, and infrastructural blockers.

`dry-run` does not run CROCO, validate every CROCO input syntax, or decide whether a NetCDF file contains all variables CROCO expects.

`run` creates `runs/<run_id>/work/`, copies `croco.in`, places the compiled binary as `croco`, creates runtime data symlinks, writes `run_inside_docker.sh`, runs Docker from the workdir, captures logs, and copies generated regular outputs into `runs/<run_id>/output/`. The original `input/` tree remains untouched.

## Traceability Model

Each imported experiment has a canonical manifest:

```text
CROCO_EXPERIMENTS/<experiment_name>/metadata/manifest.json
```

The manifest records primary evidence, compile-time findings, runtime findings, selected assets, host-to-container mappings, Docker backend details, command attempts, snapshots, reports, and command history.

The selected compile source is recorded under:

```json
{
  "compile_time": {
    "source_ref": {
      "source_id": "croco-v2.1.2",
      "flavor": "croco",
      "declared_version": "v2.1.2",
      "host_path": "CROCO_EXPERIMENTS/sources/croco-v2.1.2"
    }
  }
}
```

Reports are written for human inspection, including import, compile, dry-run, run, and setup reports. Snapshots copy effective config/code artifacts where appropriate and record references, hashes, sizes, and mappings for runtime data assets.

## Minimal Getting Started

```bash
./crocoexp setup --no-pull
./crocoexp source install /path/to/croco-source --id croco-v2.1.2 --flavor croco --version v2.1.2

mkdir -p CROCO_EXPERIMENTS/my_experiment/input
# Add croco.in, cppdefs.h, param.h, optional analytical.F, and any runtime data to input/

./crocoexp import my_experiment --source croco-v2.1.2
./crocoexp inspect my_experiment
./crocoexp compile my_experiment
./crocoexp dry-run my_experiment
./crocoexp run my_experiment
```

## MesaRotante Pattern

For an experiment such as `MesaRotante`, keep runtime inputs under `input/`:

```text
CROCO_EXPERIMENTS/MesaRotante/input/
  croco.in
  cppdefs.h
  param.h
  GRD/mesa_grd.nc
  INIT/mesa_ini.nc
```

Reference those files from `croco.in` with workdir-relative paths:

```text
GRD/mesa_grd.nc
INIT/mesa_ini.nc
```

A healthy OpenMP dry-run should report the OpenMP launch plan:

```text
Runtime backend: openmp
Planned OMP_NUM_THREADS: 8
Input runtime data assets: 2
```

The run log should include:

```text
CROCOEXP: OMP_NUM_THREADS=8
NUMBER OF THREADS: 8
```

## Design Boundaries

CROCOEXP_BUILDER reports warnings, ambiguities, suspicious combinations, and possible mismatches as findings by default. These findings are not the same as hard blockers.

Default hard failures are mainly infrastructural: missing required primary artifacts, missing registered source metadata, missing binary for run, inability to construct staging or mappings, inability to write metadata or reports, Docker/backend failure, compile failure, and run failure.

Researchers and their copilot workflow remain responsible for scientific setup, CROCO semantics, and interpretation of model behavior. CROCOEXP does not validate whether a grid file contains every variable CROCO expects, validate every `croco.in` syntax variant, validate physical consistency of initial conditions, or decide whether flags such as `CURVGRID`, `SPHERICAL`, or `SOLVE3D` are scientifically correct.

For example, if CROCO reports:

```text
GET_GRID - unable to find grid variable: spherical
```

that is a model/input issue, not a CROCOEXP staging issue, assuming the grid file is visible in `runs/<run_id>/work/`.
