# CLI Contract

## Scope

The CLI is the supported user-facing control surface for normal experiment operations.

All commands are launched from the host. Docker is used only as an execution backend for commands that need CROCO build or runtime behavior. Users must not need to enter the container manually.

The CLI is artifact-based. It operates on experiments that already exist as host folders:

```text
CROCO_EXPERIMENTS/<experiment_name>/input/
```

The `input/` directory is the canonical user-provided evidence folder. It may contain `croco.in`, `cppdefs.h`, `param.h`, optional `analytical.F`, data files such as `.nc`, and other user-provided artifacts. Generated files must live outside `input/`.

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
      logs/
      output/
      snapshots/
      reports/
```

### Docker mount policy

Docker mounts the whole `CROCO_EXPERIMENTS` directory.

The CLI must record host path to container path mappings for assets selected for staging or mounting in generated metadata. Data assets such as `.nc` files remain in `input/` and are accessed by symlink or mount-path mapping when needed. They must not be copied or moved during normal import, compile, dry-run, or run workflows.

### Reporting policy

Commands that analyze artifacts should apply this reporting order:

1. Record compile-time findings from compile-related artifacts.
2. Record runtime findings from runtime artifacts.
3. Classify assets for staging and reporting.
4. Apply user overrides where they clarify paths, staging, or ambiguity.
5. Report warnings, ambiguities, contradictions, and possible semantic mismatches with evidence.
6. Hard-fail only for infrastructural blockers by default.

Infrastructural blockers include:

- missing primary artifacts needed for the command
- inability to write metadata or reports
- inability to construct the requested staging/mounting plan
- missing runtime assets classified as required for staging or mounting
- missing binary when running
- Docker/backend failure
- compile failure
- run failure

Possible semantic mismatches, contradictions, suspicious combinations, and ambiguities are findings by default. They may become hard failures only when an explicit strict policy is requested.

### Exit code model

Recommended exit codes:

- `0`: command completed successfully
- `1`: general failure
- `2`: invalid CLI usage or missing argument
- `3`: missing primary required artifact or runtime asset required for staging/mounting
- `4`: artifact parsing or metadata/reporting failure
- `5`: optional strict-policy failure for warnings, ambiguity, contradiction, or possible semantic mismatch
- `7`: Docker/backend failure
- `8`: compile failure
- `9`: run failure

Exit code `5` is reserved for explicit strict behavior. It is not a default failure code for ambiguity, contradiction, suspicious combinations, or possible semantic mismatch.

## Optional strict flags

Future optional strict flags may include:

- `--strict`: fail on ambiguity, contradiction, or possible semantic mismatch.
- `--fail-on-ambiguity`: fail when any asset classification remains ambiguous.
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

### Minimal arguments

- `<experiment_name>`: name of an existing directory under `CROCO_EXPERIMENTS/`.

### Optional arguments

- `--experiments-root <path>`: defaults to `CROCO_EXPERIMENTS`.
- `--force`: recompute generated metadata even if a manifest already exists.
- `--override <path>`: host-side override file for resolving ambiguity.
- `--json`: emit machine-readable summary.
- `--no-docker-check`: skip Docker availability check. Import itself should not require Docker execution.
- `--strict`: optional future mode that fails on ambiguity, contradiction, or possible semantic mismatch.

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
- `4`: artifact parsing, metadata writing, or report generation failed enough that the builder cannot record the import attempt.
- `5`: optional strict policy failed because warnings, ambiguity, contradiction, or possible semantic mismatch were found.

### Minimal user-visible diagnostics

The command must print:

- experiment name and resolved experiment root
- detected primary artifacts
- whether `input/analytical.F` exists and whether it appears relevant
- count of required, optional, ignored, and ambiguous assets
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

## `crocoexp inspect <experiment_name>`

### Purpose

Show current metadata, evidence, findings, warnings, asset inventory, and path mappings. Optionally recompute metadata from `input/`.

### Minimal arguments

- `<experiment_name>`

### Optional arguments

- `--experiments-root <path>`
- `--recompute`: re-read `input/` artifacts and update manifest.
- `--json`: emit manifest summary as JSON.
- `--assets`: include full asset inventory.
- `--capabilities`: include detected compile-time findings and inferred capabilities.
- `--mounts`: include host path to container path mappings.
- `--strict`: optional future mode that fails on ambiguity, contradiction, or possible semantic mismatch during recompute.

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
- runtime findings summary
- asset classification counts
- reporting status
- warning, ambiguity, and possible mismatch summaries
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

### Minimal arguments

- `<experiment_name>`

### Optional arguments

- `--experiments-root <path>`
- `--clean`: clear generated build artifacts for this experiment before compiling.
- `--override <path>`: host-side override file for staging or backend settings.
- `--image <name-or-id>`: Docker image to use.
- `--jobs <n>`: build parallelism.
- `--json`: emit machine-readable build summary.
- `--strict`: optional future mode that fails before compile on warnings, ambiguity, contradiction, or possible semantic mismatch.

### Expected generated files/directories

May create or update:

- `metadata/manifest.json`
- `metadata/compile_report.md`
- `build/`
- `build/stage/`
- `build/logs/`
- `build/output/`

`build/stage/` may contain staged copies of code and configuration files needed for compilation. Runtime data assets such as `.nc` files must remain in `input/` and must not be duplicated into `build/`.

### Exit code behavior

- `0`: compile completed and binary/build output is host-visible.
- `3`: required compile-time artifact is missing.
- `4`: metadata writing failure, report generation failure, or inability to construct the requested compile staging plan before Docker execution.
- `5`: optional strict policy failed before compile.
- `7`: Docker backend failure.
- `8`: CROCO compilation failed.

### Minimal user-visible diagnostics

The command must print:

- Docker image used
- experiment root and build directory
- compile-time artifacts used
- whether `analytical.F` was staged and why
- warnings, ambiguities, contradictions, or possible semantic findings carried into the attempt
- build log path
- binary or build product path, if successful
- failure category: missing artifact, staging, Docker, or compile failure

### Docker usage

Docker is used. The user must not enter the container manually. Docker must mount the whole `CROCO_EXPERIMENTS` directory.

### Existing binary requirement

No existing binary is required. This command creates or updates the binary/build product.

### Write permissions

May modify:

- `metadata/`
- `build/`

Must not modify:

- `input/`, except reading user-provided artifacts
- `runs/`, except possibly recording no run state

## `crocoexp dry-run <experiment_name>`

### Purpose

Produce a traceable pre-execution report without performing a full model run.

Dry-run is mainly infrastructural and artifact-based. It reports asset availability, staging/mounting mappings, binary status, Docker readiness, warnings, ambiguities, contradictions, and possible semantic mismatches. It does not prove the CROCO experiment is semantically valid.

### Minimal arguments

- `<experiment_name>`

### Optional arguments

- `--experiments-root <path>`
- `--run-id <run_id>`: choose the run directory where reports are written.
- `--override <path>`: host-side override file for resolving path or classification ambiguity.
- `--image <name-or-id>`: Docker image to validate against.
- `--no-docker`: perform host-only static reporting when possible.
- `--json`: emit machine-readable dry-run summary.
- `--strict`: optional future mode that fails on warnings, ambiguity, contradiction, or possible semantic mismatch.

### Expected generated files/directories

May create or update:

- `metadata/manifest.json`
- `metadata/report.md`
- `runs/<run_id>/reports/dry_run_report.md`
- `runs/<run_id>/snapshots/`

Snapshots may contain effective config/code artifacts for reproducibility. Runtime data assets such as `.nc` files remain canonical in `input/` and must be represented in snapshots by references, hashes, sizes, and mappings rather than copied.

### Exit code behavior

- `0`: dry-run report completed, possibly with warnings or possible semantic findings.
- `3`: primary required artifact or runtime asset classified as required for staging/mounting is missing.
- `4`: metadata/report generation failed or the requested staging/mounting plan cannot be constructed.
- `5`: optional strict policy failed.
- `7`: Docker backend failure when Docker-backed readiness checks are requested.

### Minimal user-visible diagnostics

The command must print:

- compile-time findings summary
- runtime findings summary
- required, optional, ignored, and ambiguous asset lists with reasons
- warning and possible mismatch summaries
- host path to container path mappings for assets selected for staging/mounting
- binary status
- Docker command summary or backend-readiness summary
- dry-run report path

Dry-run must explicitly avoid assuming `GRD_FILE`, `INI_FILE`, and `FRC_FILE` are required unless artifact-level evidence indicates they must be staged or mounted for the attempted run.

### Docker usage

Docker may be used for backend-aware checks. With `--no-docker`, dry-run may perform host-only static reporting and must say so in diagnostics.

### Existing binary requirement

Dry-run should report whether a binary exists. It should not require a binary unless policy says the dry-run must include binary-specific checks.

### Write permissions

May modify:

- `metadata/`
- `runs/<run_id>/reports/`
- `runs/<run_id>/snapshots/`

Must not modify:

- `input/`
- `build/`, except reading binary status

## `crocoexp run <experiment_name>`

### Purpose

Attempt CROCO execution through Docker and record the result.

Run uses the artifact-based experiment definition, staged build product, asset mappings, and generated metadata. It may proceed with warnings, ambiguities, contradictions, or possible semantic findings unless blocked by missing assets required for staging/mounting, missing binary, inability to construct the staging/mounting plan, Docker/backend failure, explicit strict policy, or CROCO execution failure.

### Minimal arguments

- `<experiment_name>`

### Optional arguments

- `--experiments-root <path>`
- `--run-id <run_id>`
- `--override <path>`
- `--image <name-or-id>`
- `--require-dry-run`: require an existing dry-run report for the same effective manifest.
- `--require-clean-dry-run`: optional strict policy requiring a dry-run with no warnings, ambiguities, contradictions, or possible semantic findings.
- `--resume-from <restart_asset>`
- `--json`: emit machine-readable run summary.
- `--strict`: optional future mode that fails before run on warnings, ambiguity, contradiction, or possible semantic mismatch.

### Expected generated files/directories

Creates or updates:

- `runs/<run_id>/logs/`
- `runs/<run_id>/output/`
- `runs/<run_id>/snapshots/`
- `runs/<run_id>/reports/`
- `metadata/manifest.json`
- `metadata/run_index.json`, if a run index is used

Run outputs must never be written back into `input/`.

### Exit code behavior

- `0`: run completed successfully.
- `3`: primary required artifact, runtime asset required for staging/mounting, or required binary is missing.
- `4`: metadata, staging/mounting plan construction, or pre-run reporting failed.
- `5`: optional strict policy failed.
- `7`: Docker backend failure.
- `9`: CROCO run failed.

### Minimal user-visible diagnostics

The command must print:

- run id
- Docker image used
- binary/build product used
- selected asset mappings
- warning and possible semantic finding summary
- log path
- output path
- snapshot path
- final exit status

Failure diagnostics must state whether the failure came from missing artifacts, missing binary, metadata/staging, strict policy, Docker, or CROCO execution.

### Docker usage

Docker is used. The user must not enter the container manually. Docker mounts the whole `CROCO_EXPERIMENTS` directory.

### Existing binary requirement

A binary/build product is required. If missing, the command fails with a diagnostic instructing that compile is needed.

### Write permissions

May modify:

- `metadata/`
- `runs/<run_id>/logs/`
- `runs/<run_id>/output/`
- `runs/<run_id>/snapshots/`
- `runs/<run_id>/reports/`

Must not modify:

- `input/`
- `build/`, except reading the selected binary/build product
