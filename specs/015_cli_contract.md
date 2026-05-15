# CLI Contract

## Scope

The CLI is the supported user-facing control surface for normal experiment operations.

All commands are launched from the host. Docker is used only as an execution backend for commands that need CROCO build or runtime behavior. Users must not need to enter the container manually.

The CLI is artifact-based. It operates on experiments that already exist as host folders:

```text
CROCO_EXPERIMENTS/<experiment_name>/input/
```

The `input/` directory is the canonical user-provided evidence folder. It may contain `croco.in`, `cppdefs.h`, `param.h`, optional `analytical.F`, NetCDF-like runtime data files, and other user-provided artifacts. Generated files must live outside `input/`.

The CLI records findings and attempts. It does not prove scientific correctness, compile-time correctness, runtime semantic compatibility, or experiment well-posedness.

## Shared conventions

### Experiment root

For `<experiment_name>`, the experiment root is:

```text
CROCO_EXPERIMENTS/<experiment_name>/
```

Expected layout:

```text
CROCO_EXPERIMENTS/<experiment_name>/
  input/
  metadata/
  build/
  runs/
    <run_id>/
      work/
      logs/
      output/
      snapshots/
      reports/
```

Repo-level registered compile sources are stored separately from experiments:

```text
CROCO_EXPERIMENTS/sources/<source_id>/
```

Source registry state is stored under:

```text
.crocoexp/sources.json
```

Registered sources are compile infrastructure. They are not experiment `input/` evidence and are not selected by `crocoexp setup`.

### Runtime workdir policy

`crocoexp run` must create a run-local workdir:

```text
CROCO_EXPERIMENTS/<experiment_name>/runs/<run_id>/work/
```

CROCO is executed from this workdir.

The workdir contains:

- a copied `croco.in`
- the selected compiled binary as `croco` unless explicitly configured otherwise
- relative symlinks to NetCDF-like runtime data files under `input/`, preserving each file's path relative to `input/`

Example:

```text
input/GRD/mesa_grd.nc
input/INIT/mesa_ini.nc

runs/<run_id>/work/GRD/mesa_grd.nc   -> ../../../../input/GRD/mesa_grd.nc
runs/<run_id>/work/INIT/mesa_ini.nc  -> ../../../../input/INIT/mesa_ini.nc
```

The exact symlink target is computed from the symlink parent path to the canonical file under `input/`.

### Docker mount policy

Docker mounts the whole `CROCO_EXPERIMENTS` directory. This is required so relative symlinks from run workdirs to experiment `input/` resolve both on the host and inside the container.

The CLI must record host path to container path mappings for:

- `CROCO_EXPERIMENTS`
- experiment root
- run workdir
- run output directory
- selected binary
- selected source tree for compile attempts

The CLI must not rely on absolute host-path symlinks inside Docker.

### No `run.env`

`run.env` is not supported.

Rules:

- No command sources `run.env`.
- No command performs environment substitution from `run.env`.
- No command accepts `--env-file` or implicit template rendering in this spec.
- If `input/run.env` exists, commands may inventory it as an ignored ordinary user file and warn that it has no effect.
- `croco.in` must be a real CROCO input file ready for the selected CROCO source version. It is not a template by default.

### Reporting policy

Commands that analyze artifacts should apply this reporting order:

1. Record compile-time findings from compile-related artifacts.
2. Record input evidence inventory.
3. Record runtime materialization plan for workdir construction.
4. Build a runtime execution plan from `cppdefs.h`, `param.h`, binary status, and Docker backend configuration.
5. Record superficial runtime findings from `croco.in` without claiming universal CROCO semantic interpretation.
6. Report warnings and suspicious findings with evidence.
7. Hard-fail only for infrastructural blockers by default.

Infrastructural blockers include:

- missing primary artifacts needed for the command
- unknown or unavailable registered compile source when compiling
- inability to write metadata or reports
- inability to construct the requested workdir or symlink plan
- missing binary when running
- symlink target outside the mounted `CROCO_EXPERIMENTS` tree
- broken input symlink that cannot be resolved safely
- Docker/backend failure
- compile failure
- run failure
- inability to construct a supported runtime execution plan
- unsupported compiled runtime backend such as MPI, MPI+OpenMP, OpenACC, XIOS, or OASIS
- planned OpenMP thread count exceeding parsed `NPP`

Possible semantic mismatches, contradictions, suspicious combinations, and ambiguities are findings by default. They may become hard failures only when an explicit strict policy is requested.

### Exit code model

Recommended exit codes:

- `0`: command completed successfully
- `1`: general failure
- `2`: invalid CLI usage or missing argument
- `3`: missing primary required artifact or unsafe/missing file needed for workdir materialization
- `4`: artifact parsing, metadata/reporting, or workdir preparation failure
- `5`: optional strict-policy failure for warnings, ambiguity, contradiction, or possible semantic mismatch
- `7`: Docker/backend failure
- `8`: compile failure
- `9`: run failure

Exit code `5` is reserved for explicit strict behavior. It is not a default failure code for ambiguity, contradiction, suspicious combinations, or possible semantic mismatch.

## `crocoexp source install <path> --id <source_id>`

### Purpose

Register a compile source tree by copying it into:

```text
CROCO_EXPERIMENTS/sources/<source_id>/
```

This command supports official CROCO source trees, MSOT, custom forks, and patched source trees. Source registration is about reproducible compile input provenance, not semantic validation of the source.

### Minimal arguments

- `<path>`: existing host path to the source tree to install.
- `--id <source_id>`: stable identifier used by experiments.

### Optional arguments

- `--experiments-root <path>`
- `--flavor <croco|msot|custom>`: declared source flavor.
- `--declared-version <value>`: human-declared version or tag.
- `--notes <text>`: human-readable notes.
- `--force`: replace an existing registered source with the same `source_id`.
- `--json`: emit machine-readable summary.

### Expected generated files/directories

May create or update:

- `CROCO_EXPERIMENTS/sources/`
- `CROCO_EXPERIMENTS/sources/<source_id>/`
- `.crocoexp/sources.json`

Must not modify experiment `input/` directories or experiment manifests.

### Exit code behavior

- `0`: source installed and registry written.
- `2`: invalid CLI usage, missing `--id`, or invalid `source_id`.
- `3`: origin source path is missing.
- `4`: duplicate `source_id` without `--force`, source copy failure, or registry write failure.

### Minimal user-visible diagnostics

The command must print source id, origin path, installed host path, flavor, declared version, detected git branch/commit when practical, registry path, and any replacement warning from `--force`.

### Docker usage

Docker is not required. The command is host-side file management only.

### Existing binary requirement

No existing binary is required.

### Write permissions

May modify `CROCO_EXPERIMENTS/sources/` and `.crocoexp/sources.json`.

Must not modify experiment `input/`, `metadata/`, `build/`, or `runs/`.

## `crocoexp source list`

### Purpose

List registered compile source IDs and basic metadata.

### Minimal arguments

None.

### Optional arguments

- `--experiments-root <path>`
- `--json`

### Expected generated files/directories

None. This command is read-only.

### Exit code behavior

- `0`: list completed. Empty registry is a successful result.
- `4`: source registry is unreadable or malformed.

### Minimal user-visible diagnostics

The command must print source id, installed host path, flavor, declared version, and install timestamp.

### Docker usage

Docker is not used.

### Existing binary requirement

No existing binary is required.

### Write permissions

Read-only.

## `crocoexp source inspect <source_id>`

### Purpose

Show detailed registry metadata for one registered compile source.

### Minimal arguments

- `<source_id>`

### Optional arguments

- `--experiments-root <path>`
- `--json`

### Expected generated files/directories

None. This command is read-only.

### Exit code behavior

- `0`: source metadata was found and displayed.
- `3`: `source_id` is not registered.
- `4`: source registry is unreadable or malformed.

### Minimal user-visible diagnostics

The command must print source id, flavor, declared version, installed host path, origin path copied from, install timestamp, detected layout, git branch and commit when available, and content identity when practical.

### Docker usage

Docker is not used.

### Existing binary requirement

No existing binary is required.

### Write permissions

Read-only.

## Optional strict flags

Optional strict flags may include:

- `--strict`: fail on warning, suspicious finding, contradiction, or possible semantic mismatch.
- `--fail-on-warning`: fail when warnings are produced.
- `--require-clean-dry-run`: require dry-run with no warnings before run.

Default behavior remains permissive and traceable.

## `crocoexp import <experiment_name>`

### Purpose

Register and analyze an existing experiment whose user-provided artifacts already live in:

```text
CROCO_EXPERIMENTS/<experiment_name>/input/
```

Import creates generated metadata and the managed experiment structure outside `input/`. It does not create a named case profile and does not prove that the experiment will compile or run.

When `--source <source_id>` is provided, import records the selected registered compile source under `compile_time.source_ref`. This is per-experiment traceability, not a global source/version setting.

### Minimal arguments

- `<experiment_name>`: name of an existing directory under `CROCO_EXPERIMENTS/`.

### Optional arguments

- `--experiments-root <path>`: defaults to `CROCO_EXPERIMENTS`.
- `--source <source_id>`: select a registered compile source for this experiment.
- `--force`: recompute generated metadata even if a manifest already exists.
- `--json`: emit machine-readable summary.
- `--no-docker-check`: skip Docker availability check. Import itself should not require Docker execution.
- `--strict`: optional mode that fails on warning, contradiction, or possible semantic mismatch.

No `--env-file` or template-rendering option is part of this spec.

### Expected generated files/directories

May create:

- `metadata/`
- `metadata/manifest.json`
- `metadata/import_report.md`
- `metadata/report.md`
- `build/`
- `runs/`

Must not create or modify files inside `input/`.

### Exit code behavior

- `0`: import completed and manifest written, possibly with warnings.
- `3`: `input/croco.in`, `input/cppdefs.h`, or `input/param.h` is missing.
- `4`: artifact parsing, metadata writing, report generation, or `--source <source_id>` registry resolution failed enough that the builder cannot record the import attempt.
- `5`: optional strict policy failed.

### Minimal user-visible diagnostics

The command must print:

- experiment name and resolved experiment root
- detected primary artifacts
- whether `input/analytical.F` exists and whether it appears relevant
- selected registered compile source, if provided
- NetCDF-like runtime data asset count discovered by input tree scan
- ignored `run.env` warning, if present
- warning and finding count
- path to `metadata/manifest.json`
- missing artifact summary, if any

### Docker usage

Docker is not required for artifact parsing. The command may check Docker availability unless disabled, but it must not require container entry or container-local edits.

### Existing binary requirement

No existing binary is required.

### Write permissions

May modify:

- `metadata/`
- `build/` directory creation only
- `runs/` directory creation only

Must not modify:

- `input/`
- existing scripts or source code outside the experiment managed directories

Import must not modify `CROCO_EXPERIMENTS/sources/<source_id>/`; it only reads the source registry to resolve `--source`.

## `crocoexp inspect <experiment_name>`

### Purpose

Show current metadata, evidence, findings, runtime materialization policy, warnings, and source selection. Optionally recompute metadata from `input/`.

### Minimal arguments

- `<experiment_name>`

### Optional arguments

- `--experiments-root <path>`
- `--recompute`: re-read `input/` artifacts and update manifest.
- `--json`: emit manifest summary as JSON.
- `--assets`: include full input evidence inventory.
- `--capabilities`: include detected compile-time findings and inferred capabilities.
- `--mounts`: include host path to container path mappings.
- `--strict`: optional mode that fails on warning or suspicious finding during recompute.

### Expected generated files/directories

Without `--recompute`, inspect should not write files.

With `--recompute`, may update:

- `metadata/manifest.json`
- `metadata/report.md`

Must not modify `input/`.

### Exit code behavior

- `0`: inspection completed, possibly with warnings.
- `3`: required primary artifacts are missing when recomputing.
- `4`: manifest is missing or invalid and recompute was not requested.
- `5`: optional strict policy failed during recompute.

### Minimal user-visible diagnostics

The command must print:

- manifest status and timestamp
- compile-time findings summary
- selected registered compile source, if present
- runtime input contract summary
- NetCDF-like runtime data asset count
- warning and suspicious finding summaries
- stale metadata warning if input artifacts changed since the manifest was generated

### Docker usage

Docker is not used unless a future explicit option checks backend availability. Normal inspect is host-only.

### Existing binary requirement

No existing binary is required.

### Write permissions

May modify `metadata/` only when `--recompute` is used.

## `crocoexp compile <experiment_name>`

### Purpose

Attempt CROCO compilation through Docker using staged compile-related artifacts derived from `input/cppdefs.h`, `input/param.h`, and relevant source/config artifacts.

Compile records what was attempted and what failed or succeeded. It must not fail merely because runtime metadata suggests a possible semantic mismatch.

Compile uses a registered compile source selected for the experiment. Source resolution order is:

1. explicit `--source <source_id>`, if supported by the implementation
2. `compile_time.source_ref` recorded in `metadata/manifest.json`
3. hard failure if no source is known

There is no setup-level or global CROCO version/source selection.

### Minimal arguments

- `<experiment_name>`

### Optional arguments

- `--experiments-root <path>`
- `--clean`: clear generated build artifacts for this experiment before compiling.
- `--image <name-or-id>`: Docker image to use.
- `--source <source_id>`: optional override for the compile source used in this attempt.
- `--jobs <n>`: build parallelism.
- `--json`: emit machine-readable build summary.
- `--strict`: optional mode that fails before compile on warnings or suspicious findings.

### Expected generated files/directories

May create or update:

- `metadata/manifest.json`
- `metadata/compile_report.md`
- `build/`
- `build/stage/`
- `build/logs/`
- `build/output/`

Must not create or modify files inside `input/`.

Must not copy NetCDF-like runtime data assets into `build/`.

### Exit code behavior

- `0`: compile completed and binary/build product was produced.
- `3`: primary compile artifacts or selected source are missing.
- `4`: metadata, staging, or report generation failed.
- `5`: optional strict policy failed before compile.
- `7`: Docker/backend failure.
- `8`: compile process failed.

### Minimal user-visible diagnostics

The command must print experiment name, selected source id, Docker image, staged compile files, compile log path, binary path on success, and failure category on failure.

### Docker usage

Docker is used as backend. The whole `CROCO_EXPERIMENTS` tree is mounted. Registered source trees must be reachable inside the container through that mount.

### Existing binary requirement

No existing binary is required before compile.

### Write permissions

May modify `metadata/` and `build/`.

Must not modify `input/` or registered source trees.

## `crocoexp dry-run <experiment_name>`

### Purpose

Produce a traceable pre-execution infrastructure report without performing a full model run.

Dry-run is not a universal CROCO semantic validator. It does not parse `croco.in` to decide which data files are required. It reports whether CROCOEXP can construct the run workdir according to the runtime input contract.

### Minimal arguments

- `<experiment_name>`

### Optional arguments

- `--experiments-root <path>`
- `--run-id <run_id>`: use a specified dry-run id or planned run id.
- `--image <name-or-id>`: Docker image to check/use in the plan.
- `--json`: emit machine-readable report.
- `--strict`: optional mode that fails on warnings or suspicious findings.

### Expected generated files/directories

May create:

- `runs/<run_id>/reports/dry_run_report.md`
- `runs/<run_id>/snapshots/`
- `metadata/report.md`
- `metadata/manifest.json`

Dry-run may construct a temporary or planned symlink plan for reporting, but it must not perform a full model run.

### Exit code behavior

- `0`: dry-run completed and no infrastructural blocker was found, possibly with warnings.
- `3`: missing primary artifacts, missing binary, or unsafe/missing file needed for materialization.
- `4`: metadata, report, snapshot, or materialization-plan generation failed.
- `5`: optional strict policy failed.
- `7`: Docker/backend readiness check failed when Docker-backed readiness is requested.

### Minimal user-visible diagnostics

The command must print:

- experiment root
- run id
- binary presence
- selected Docker image
- input root
- planned workdir
- materialization policy: `copy_config_symlink_netcdf`
- count and list of NetCDF-like files to symlink
- unresolved `${...}` tokens in `croco.in`, if any
- ignored `run.env` warning, if present
- planned Docker working directory
- report path
- infrastructural blockers, if any
- detected runtime backend symbols
- parsed `NPP`, `NSUB_X`, `NSUB_E`, `NP_XI`, `NP_ETA`, and `NNODES` when available
- planned runtime launch profile
- planned `OMP_NUM_THREADS`, when OpenMP is active
- unsupported runtime backend blockers, if any

It must not print "Required Assets Selected For Staging/Mounting" as the primary contract. The primary contract is the input tree and symlink materialization plan.

### Docker usage

Docker is not required for a host-only dry-run. If a Docker-backed readiness check is performed, Docker is used only to verify backend readiness, image availability, binary visibility, and mount assumptions.

### Existing binary requirement

Dry-run should report missing binary as a blocker for run readiness. It may still write a report.

### Write permissions

May modify `metadata/` and create `runs/<run_id>/reports/` and `runs/<run_id>/snapshots/`.

Must not modify `input/`.

## `crocoexp run <experiment_name>`

### Purpose

Execute CROCO through Docker using a run-local workdir constructed from the experiment input tree and selected compiled binary.

Run is an attempt. It may proceed after dry-run when metadata contains warnings or suspicious findings, unless there is an infrastructural blocker or explicit strict policy.

Before launching Docker, `run` must construct and apply the runtime execution plan. For OpenMP binaries, it must pass `OMP_NUM_THREADS` explicitly to Docker and write the same hard assignment in `run_inside_docker.sh`. For unsupported launch profiles, it must fail before Docker execution.


### Minimal arguments

- `<experiment_name>`

### Optional arguments

- `--experiments-root <path>`
- `--run-id <run_id>`: choose a run id instead of generating one.
- `--image <name-or-id>`: Docker image to use.
- `--binary <path>`: explicit compiled binary path, defaulting to the experiment build output.
- `--clean-work`: remove an existing run workdir before materialization.
- `--json`: emit machine-readable run summary.
- `--strict`: optional mode that fails before run on warnings or suspicious findings.

No `--env-file` or template-rendering option is part of this spec.

### Expected generated files/directories

May create or update:

- `runs/<run_id>/work/`
- `runs/<run_id>/logs/`
- `runs/<run_id>/output/`
- `runs/<run_id>/snapshots/`
- `runs/<run_id>/reports/`
- `metadata/manifest.json`

Workdir contents must include:

```text
runs/<run_id>/work/croco
runs/<run_id>/work/croco.in
runs/<run_id>/work/<relative path to each NetCDF-like asset under input> -> relative symlink target
```

Must not create or modify files inside `input/`.

### Exit code behavior

- `0`: CROCO execution completed successfully.
- `3`: missing primary runtime artifact, missing binary, or unsafe materialization input.
- `4`: metadata, workdir, symlink, snapshot, or report generation failed.
- `5`: optional strict policy failed before run.
- `7`: Docker/backend failure.
- `9`: CROCO execution failed.

### Minimal user-visible diagnostics

The command must print:

- experiment name
- run id
- Docker image
- workdir path
- binary used
- copied config files
- NetCDF symlink count
- ignored `run.env` warning, if present
- log path
- output path
- final exit status

### Docker usage

Docker is used as backend. The whole `CROCO_EXPERIMENTS` tree is mounted. The Docker working directory must be the container path corresponding to `runs/<run_id>/work/`.

### Existing binary requirement

An existing binary is required.

### Write permissions

May modify:

- `runs/<run_id>/work/`
- `runs/<run_id>/logs/`
- `runs/<run_id>/output/`
- `runs/<run_id>/snapshots/`
- `runs/<run_id>/reports/`
- `metadata/manifest.json`

Must not modify:

- `input/`
- registered source trees
- other experiments
