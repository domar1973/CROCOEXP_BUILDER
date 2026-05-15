# Workflow

## Desired host-only workflow

All normal user actions happen from the host.

The user should be able to:

- place real CROCO artifacts in `CROCO_EXPERIMENTS/<experiment_name>/input/`
- register one or more compile source trees under `CROCO_EXPERIMENTS/sources/<source_id>/`
- import or inspect the experiment from host-side commands
- compile through Docker from a host-side command
- produce a dry-run report from a host-side command
- run CROCO through Docker from a host-side command
- inspect metadata, prepared workdirs, logs, outputs, reports, and snapshots on the host

The user should not need to:

- enter the Docker container manually
- copy files by hand into the container
- edit container-local files
- know container-internal paths for normal operation
- maintain a global CROCO version setting for all experiments
- maintain `run.env`
- rely on CROCOEXP parsing `croco.in` as universal semantic truth

An expected repo-level flow may be:

```text
crocoexp setup
crocoexp source install /path/to/source --id <source_id>
crocoexp source list
crocoexp source inspect <source_id>
crocoexp import <experiment_name> --source <source_id>
crocoexp compile <experiment_name>
crocoexp dry-run <experiment_name>
crocoexp run <experiment_name>
```

`crocoexp setup` prepares Docker backend readiness. Source registration prepares compile input provenance. Experiment import binds a registered source to a specific experiment.

## Storage policy

Each experiment uses this layout:

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

Repo-level source infrastructure uses:

```text
CROCO_EXPERIMENTS/sources/<source_id>/
.crocoexp/sources.json
```

Rules:

- `input/` is canonical for user-provided evidence.
- `input/` contains `croco.in`, `cppdefs.h`, `param.h`, optional `analytical.F`, runtime data assets, and other user-provided files.
- `.nc`, `.nc4`, `.cdf`, and similar runtime data assets remain in `input/`.
- `metadata/` contains generated manifests, findings, reports, and command records.
- `build/` contains staged compile files and build products.
- `runs/<run_id>/work/` contains the run-local execution view.
- `runs/<run_id>/logs/` contains host-visible logs.
- `runs/<run_id>/output/` contains generated run outputs or post-run collected outputs.
- `runs/<run_id>/snapshots/` contains reproducibility snapshots and inventories.
- `runs/<run_id>/reports/` contains command-specific reports.
- `sources/<source_id>/` contains copied registered compile source trees.
- `.crocoexp/sources.json` contains the repo-level source registry.
- Registered sources are compile infrastructure, not experiment `input/` evidence.
- `crocoexp setup` does not select a global compile source.
- Generated files must always be distinguishable from user-provided files.
- Run outputs never go back into `input/`.
- `run.env` is not part of the workflow.

## Runtime input contract

The runtime contract is based on filesystem convention, not `croco.in` semantic parsing.

Before executing CROCO, `crocoexp run` creates:

```text
runs/<run_id>/work/
```

The workdir is materialized as follows:

1. Copy `input/croco.in` to `work/croco.in`.
2. Copy or link the selected compiled binary to `work/croco`.
3. Scan `input/` recursively for NetCDF-like runtime data assets.
4. For each NetCDF-like asset, create a relative symlink in `work/` preserving the path relative to `input/`.
5. Execute CROCO from `work/`.

Example:

```text
input/GRD/mesa_grd.nc
input/INIT/mesa_ini.nc

runs/<run_id>/work/GRD/mesa_grd.nc
runs/<run_id>/work/INIT/mesa_ini.nc
```

The symlink paths make both old and new CROCO input syntaxes work as long as the researcher writes paths relative to the execution workdir.

CROCOEXP does not need to know whether the selected CROCO version expects `GRDNAME ==`, `grid:`, or another syntax.

## Register compile sources

Before compiling, the repo may register compile source trees:

```text
crocoexp source install /path/to/source --id <source_id>
crocoexp source list
crocoexp source inspect <source_id>
```

The install step should:

- verify the origin source path exists
- copy the source tree into `CROCO_EXPERIMENTS/sources/<source_id>/`
- register the source in `.crocoexp/sources.json`
- record flavor, declared version, origin path, install time, and optional git metadata when practical

Registered sources may be official CROCO trees, MSOT trees, custom forks, or patched local trees. Source registration controls compile input provenance. It does not prove that the source tree is scientifically correct, technically correct, or compatible with a given experiment.

Normal workflow must not rely on symlinks to host paths outside `CROCO_EXPERIMENTS` because those paths may not exist inside the Docker mount.

## Import experiment

Version 1 is primarily import-and-manage. It assumes the researcher or copilot workflow creates or gathers the CROCO artifacts, then places them under:

```text
CROCO_EXPERIMENTS/<experiment_name>/input/
```

Minimum expected artifacts:

- `input/croco.in`
- `input/cppdefs.h`
- `input/param.h`

Optional artifacts:

- `input/analytical.F`
- NetCDF-like runtime data assets
- other user-provided files relevant to the experiment

The import step should:

- register the existing experiment folder
- record selected registered compile source when invoked as `crocoexp import <experiment_name> --source <source_id>`
- parse artifact-level compile evidence where practical
- record compile-time findings separately from runtime findings
- inventory NetCDF-like runtime data assets under `input/`
- record warnings, contradictions, and possible inconsistencies as findings
- warn if `run.env` is present and state that it is ignored
- create generated metadata outside `input/`
- avoid hardcoded named experiment cases as the main behavior engine

Import should not claim the experiment is scientifically valid or guaranteed to compile/run.

## Compile

Compile is launched from the host and executed by Docker.

The compile step should:

- resolve the compile source from an explicit source option when supported, then from `compile_time.source_ref`, and otherwise fail clearly
- stage code and configuration files needed for compilation under `build/`
- read registered compile source files from `CROCO_EXPERIMENTS/sources/<source_id>/`
- read compile-related evidence from `input/`
- include `analytical.F` only when artifact-level evidence or user policy says it should be staged
- write build logs to the host
- write the compiled binary or build product to a host-visible location
- record inputs used, staging decisions, Docker command details, exit code, and failure category
- record the selected source id and source metadata in compile reports and snapshots
- leave `.nc` and similar runtime data assets in `input/`

Compile is an attempt. The builder does not prove in advance that the compile-time directives are correct or that the build will succeed. Compile should not fail merely because runtime metadata contains warnings, contradictions, or possible semantic mismatches.

## Dry-run

Dry-run is launched from the host and produces a traceable pre-execution infrastructure report without performing a full model run.

The dry-run step should:

- re-read or verify current `input/croco.in`, `input/cppdefs.h`, and `input/param.h`
- report compile-time findings and runtime findings separately
- report the planned run workdir
- report the runtime input materialization policy
- list NetCDF-like runtime data assets that will be symlinked into the workdir
- show planned symlink paths and relative targets
- show host paths and container mount paths
- show the Docker command summary or execution plan
- report binary presence or absence
- report unresolved `${...}` tokens in `croco.in` as warnings, not substitutions
- warn that `run.env` is ignored if present
- write reports and snapshots outside `input/`
- report the runtime execution plan
- report planned `OMP_NUM_THREADS` for OpenMP binaries
- report unsupported runtime launch profiles before run

Dry-run must not behave like a CROCO semantic proof engine. It must not assume `GRD_FILE`, `INI_FILE`, `FRC_FILE`, `grid:`, `initial:`, or any version-specific syntax is required for staging/mounting. It must not classify real NetCDF assets as "ambiguous" merely because `croco.in` syntax is unrecognized.

Dry-run may hard-fail by default for:

- missing primary artifacts
- missing binary when checking run readiness
- inability to write reports
- inability to construct a safe workdir or symlink plan
- Docker/backend failure when Docker-backed readiness checks are requested
- explicit strict policy selected by the user

## Run

Run is launched from the host and executed by Docker.

The run step should:

- require an existing binary or an explicitly selected build product
- create or clean `runs/<run_id>/work/`
- copy `input/croco.in` into `work/croco.in`
- place the selected binary in `work/croco`
- create relative symlinks for NetCDF-like runtime data assets under `input/`
- construct the runtime execution plan from `cppdefs.h`, `param.h`, selected binary, and Docker backend
- apply the runtime execution plan to the Docker command and wrapper script
- fail before Docker execution when a detected compiled backend requires an unsupported launch profile
- execute CROCO in the container with working directory set to the container path for `work/`
- stream or capture logs to host-visible files
- write or collect model outputs under `runs/<run_id>/output/`
- snapshot effective config/code artifacts and runtime materialization inventory
- record exit status, timing, Docker details, and failure category

Run is an attempt. It may proceed after dry-run when metadata contains warnings or possible semantic inconsistencies, unless there is an infrastructural blocker or explicit strict policy.

Run may hard-fail by default for:

- missing primary artifacts
- missing binary/build product
- inability to write metadata
- inability to construct the workdir
- unsafe or broken symlink targets
- Docker/backend failure
- CROCO runtime failure
- explicit strict policy selected by the user

## Outputs, logs, and snapshots

Every run attempt should produce host-visible records:

```text
runs/<run_id>/work/
runs/<run_id>/logs/
runs/<run_id>/output/
runs/<run_id>/snapshots/
runs/<run_id>/reports/
```

Snapshots should include:

- copied `croco.in`
- copied or referenced `cppdefs.h`
- copied or referenced `param.h`
- selected source reference
- binary reference
- symlink inventory for NetCDF-like runtime data
- Docker image and command summary
- exit code and failure category

Snapshots should not duplicate NetCDF runtime data assets. They should record path, size, hash when practical, and symlink target.

## Minimal acceptance criteria

The workflow is acceptable when:

- Users can place all runtime data under `input/` and write CROCO-relative paths against the future workdir layout.
- `dry-run` reports the planned workdir and symlink forest without parsing `croco.in` semantically.
- `run` creates the workdir and symlinks NetCDF-like assets from `input/`.
- CROCO executes from the workdir.
- Docker users do not need to enter the container.
- `input/` is not modified.
- `run.env` is neither required nor used.
- Logs and outputs are inspectable on the host.
