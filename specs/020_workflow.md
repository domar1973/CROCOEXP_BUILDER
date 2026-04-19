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
- inspect metadata, logs, outputs, reports, and snapshots on the host

The user should not need to:

- enter the Docker container manually
- copy files by hand into the container
- edit container-local files
- know container-internal paths for normal operation
- maintain a global CROCO version setting for all experiments

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
- `.nc` and similar runtime data assets remain in `input/`.
- `metadata/` contains generated manifests, findings, reports, and command records.
- `build/` contains staged compile files and build products.
- `runs/<run_id>/` contains generated logs, outputs, snapshots, and reports.
- `sources/<source_id>/` contains copied registered compile source trees.
- `.crocoexp/sources.json` contains the repo-level source registry.
- Registered sources are compile infrastructure, not experiment `input/` evidence.
- `crocoexp setup` does not select a global compile source.
- Generated files must always be distinguishable from user-provided files.
- Run outputs never go back into `input/`.

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
- referenced runtime data assets
- other user-provided files relevant to the experiment

The import step should:

- register the existing experiment folder
- record selected registered compile source when invoked as `crocoexp import <experiment_name> --source <source_id>`
- parse artifact-level evidence where practical
- record compile-time findings separately from runtime findings
- classify referenced assets for reporting and staging
- record warnings, ambiguities, contradictions, and possible inconsistencies as findings
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

Compile is an attempt. The builder does not prove in advance that the compile-time directives are correct or that the build will succeed. Compile should not fail merely because runtime metadata contains warnings, ambiguities, contradictions, or possible semantic mismatches.

Compile may hard-fail by default for:

- missing primary compile artifacts
- missing or unknown registered compile source
- inability to write metadata or construct the requested compile staging plan
- Docker/backend failure
- actual compile failure reported by the build process
- explicit strict policy selected by the user

## Dry-run

Dry-run is launched from the host and produces a traceable pre-execution report without performing a full model run.

The dry-run step should:

- re-read or verify current `input/croco.in`, `input/cppdefs.h`, and `input/param.h`
- report compile-time findings and runtime findings separately
- report required, optional, ignored, and ambiguous staging/mounting classifications with evidence
- report possible semantic mismatches, contradictions, or suspicious combinations as findings
- show host paths and container mount paths
- show the Docker command summary or execution plan
- report binary presence or absence
- write reports and snapshots outside `input/`

Dry-run must not behave like a CROCO semantic proof engine. It should avoid assuming `GRD_FILE`, `INI_FILE`, and `FRC_FILE` are required for staging/mounting by name alone. Ambiguity, contradictions, and possible compile/runtime mismatches are warnings/findings by default unless strict mode is selected.

Dry-run may hard-fail by default for:

- missing primary artifacts
- inability to write reports or construct the requested staging/mounting plan
- missing runtime assets classified as required for staging/mounting
- Docker/backend failure when Docker-backed readiness checks are requested
- explicit strict policy selected by the user

## Run

Run is launched from the host and executed by Docker.

The run step should:

- require an existing binary or an explicitly selected build product
- perform or reuse artifact-level checks needed to stage and mount files
- mount required host-side inputs and selected optional inputs
- execute CROCO in the container
- stream or capture logs to host-visible files
- write model outputs under `runs/<run_id>/output/`
- snapshot effective config/code artifacts and asset inventory
- record exit status, timing, Docker details, and failure category

Run is an attempt. It may proceed after dry-run when metadata contains warnings, ambiguities, contradictions, or possible semantic inconsistencies, unless there is an infrastructural blocker or explicit strict policy.

Run may hard-fail by default for:

- missing runtime assets classified as required for staging/mounting
- missing binary/build product
- inability to write metadata or construct the requested staging/mounting plan
- Docker/backend failure
- CROCO execution failure
- explicit strict policy selected by the user

## Outputs, logs, and snapshots

Generated state must be host-visible and outside `input/`.

Required locations:

- `CROCO_EXPERIMENTS/<experiment_name>/metadata/`
- `CROCO_EXPERIMENTS/<experiment_name>/build/`
- `CROCO_EXPERIMENTS/<experiment_name>/runs/<run_id>/logs/`
- `CROCO_EXPERIMENTS/<experiment_name>/runs/<run_id>/output/`
- `CROCO_EXPERIMENTS/<experiment_name>/runs/<run_id>/snapshots/`
- `CROCO_EXPERIMENTS/<experiment_name>/runs/<run_id>/reports/`

Snapshots should include:

- effective `croco.in`
- effective `cppdefs.h`
- effective `param.h`
- effective `analytical.F`, when used
- selected registered compile source reference and registry metadata
- asset inventory with builder staging/mounting classification and provenance
- host-to-container mount mapping
- Docker image identifier
- command invocation details
- logs or references to logs
- checksums or equivalent identifiers for important inputs

Runtime data assets such as `.nc` files should not be duplicated into snapshots during normal workflow. Snapshot records should represent them with path, mapping, size, and hash when practical.

## Minimal acceptance criteria

- A user can import an experiment from `input/croco.in`, `input/cppdefs.h`, and `input/param.h` without selecting a hardcoded case.
- A user can install and inspect registered compile sources under `CROCO_EXPERIMENTS/sources/<source_id>/`.
- Import can record a per-experiment registered compile source using `--source <source_id>`.
- Compile uses the experiment's registered source reference rather than a setup-level global version.
- The system records whether `input/analytical.F` exists and whether it appears relevant.
- The system does not always require `GRD_FILE`, `INI_FILE`, and `FRC_FILE`.
- Required, optional, ignored, and ambiguous staging/mounting classifications are reported with reasons.
- Compile can be attempted from the host and executed in Docker.
- Dry-run can be started from the host and produces a traceable artifact-based report.
- Run can be attempted from the host and writes logs, outputs, and snapshots to host-visible paths.
- No normal workflow step requires manual container entry.
- Generated metadata is separated from user-provided artifacts.
- Failures distinguish missing artifacts, missing binary, Docker/backend failure, compile failure, run failure, warnings, and possible semantic findings.
