# Setup Bootstrap

## Purpose

`crocoexp setup` is a future host-side bootstrap command for preparing the repo-level Docker execution backend.

The setup slice is infrastructure readiness only. It does not import experiments, compile CROCO, run CROCO, perform dry-run semantics, or validate scientific correctness. It records whether the host can use the configured Docker backend and which Docker image should be treated as the repo default.

Setup does not choose a global CROCO source, CROCO version, MSOT tree, or custom source tree. Compile sources are registered separately with the source registry and selected per experiment.

The command should:

- verify Docker CLI availability
- verify Docker daemon availability
- verify whether the canonical Docker image is present locally
- optionally pull the canonical Docker image if missing
- register the default Docker image and setup status for the repo
- write a human-readable setup report
- avoid requiring manual container entry
- avoid touching any experiment `input/` directory

The builder remains host-side, infrastructure-oriented, traceability-oriented, and not a semantic validator of CROCO experiments.

## Non-Goals

`crocoexp setup` does not:

- create experiments
- import experiments
- compile CROCO
- run CROCO
- implement dry-run or run behavior
- validate scientific correctness
- validate compile/runtime semantic compatibility
- prove that a future compile will succeed
- build the Docker image from source in v1
- modify user experiment artifacts
- modify files under `CROCO_EXPERIMENTS/<experiment_name>/input/`
- create or update experiment-level `metadata/manifest.json`
- select a global registered compile source for all experiments
- write `.crocoexp/sources.json`
- copy source trees into `CROCO_EXPERIMENTS/sources/`

## Configuration Policy

Setup writes repo-level backend configuration outside experiment directories.

Recommended layout:

```text
.crocoexp/
  config.json
  setup_report.md
```

This directory is repo-local because setup prepares the builder backend for the repository, not a specific experiment.

`config.json` records the latest configured backend state. It is generated metadata and should be distinguishable from user-provided experiment evidence.

Required `config.json` fields:

- `schema_version`
- `default_docker_image`
- `docker_cli_detected`
- `docker_daemon_ok`
- `image_present_locally`
- `last_setup_at`
- `setup_status`

`config.json` must not contain a global CROCO source id, global CROCO version, MSOT source id, or experiment compile source selection. Source registry state belongs in `.crocoexp/sources.json`.

Recommended additional fields:

- `docker_cli_path`
- `docker_version`
- `image_id`, when available
- `image_checked_at`
- `image_pulled`
- `warnings`
- `failure_category`
- `commands`

Allowed `setup_status` values:

- `not_checked`
- `ready`
- `ready_with_warnings`
- `blocked_docker_cli_missing`
- `blocked_docker_daemon`
- `blocked_image_missing`
- `blocked_image_pull_failed`
- `blocked_config_write`

The human-readable report is:

```text
.crocoexp/setup_report.md
```

It should summarize Docker availability, daemon status, configured image, local image status, pull attempt result, warnings, and next suggested command.

## Canonical Image Policy

There is one canonical default Docker image for the repo.

The initial default should match the current builder convention unless changed by an explicit repo decision:

```text
domarcroco/images-for-croco:base_croco_msot-1.0.0
```

Rules:

- `crocoexp setup` registers the current default image in `.crocoexp/config.json`.
- `crocoexp compile`, future `crocoexp dry-run`, and future `crocoexp run` should use the configured default image unless the command receives an explicit `--image` override.
- The image reference must not be scattered across unrelated scripts, hardcoded wrappers, and informal docs.
- If `--image <name-or-id>` is used, setup records that image as the repo default after successful checks or a successful pull.
- A change from a previous default image is a warning by default, not a hard failure.

The canonical image policy is independent from registered compile source policy. The Docker image describes the execution backend; the registered compile source describes compile input provenance for a specific experiment.

## CLI Contract

### Command

```text
crocoexp setup
```

### Purpose

Prepare and record repo-level Docker backend readiness for CROCOEXP_BUILDER.

### Minimal Arguments

No positional arguments.

### Optional Arguments

- `--image <name-or-id>`: image to register as the repo default instead of the built-in canonical default.
- `--pull`: pull the selected image if it is missing locally.
- `--no-pull`: do not pull an image; fail if the selected image is missing.
- `--check-only`: check Docker and image status without changing existing config unless a report is still required by policy.
- `--force`: overwrite existing `.crocoexp/config.json` even when the image differs from the previous default.
- `--json`: emit a machine-readable summary.

If neither `--pull` nor `--no-pull` is provided, v1 should default to `--no-pull` to avoid unexpected network use. A later UX decision may change this default.

### Expected Generated Files

May create or update:

```text
.crocoexp/
.crocoexp/config.json
.crocoexp/setup_report.md
```

Must not create or modify:

```text
CROCO_EXPERIMENTS/<experiment_name>/input/
CROCO_EXPERIMENTS/<experiment_name>/metadata/manifest.json
CROCO_EXPERIMENTS/<experiment_name>/build/
CROCO_EXPERIMENTS/<experiment_name>/runs/
.crocoexp/sources.json
CROCO_EXPERIMENTS/sources/
```

### Exit Codes

Recommended exit codes:

- `0`: setup completed and backend is ready, possibly with warnings
- `1`: general setup failure
- `2`: invalid CLI usage or incompatible flags
- `4`: unable to write `.crocoexp/config.json` or `.crocoexp/setup_report.md`
- `7`: Docker/backend infrastructure failure

Exit code `7` includes:

- Docker CLI missing
- Docker daemon unavailable
- selected image missing and no pull requested
- image pull failure

### Diagnostics

Human-readable diagnostics should include:

- Docker CLI detected: yes/no
- Docker daemon available: yes/no
- selected Docker image
- previous default image, if any
- image present locally: yes/no
- image pull attempted: yes/no
- image pull result, when attempted
- setup config path
- setup report path
- warning count
- failure category, if any

Diagnostics must not suggest entering the container manually.

## Failure Policy

Setup hard-fails only for infrastructural reasons:

- Docker CLI is not installed or not on `PATH`
- Docker daemon is unavailable
- selected image is missing locally and no pull was requested
- image pull fails
- `.crocoexp/config.json` or `.crocoexp/setup_report.md` cannot be written
- invalid or incompatible CLI flags

Warnings may include:

- overriding a previous default image
- selected image differs from the previous repo default
- Docker is ready but no compile has been attempted
- image was pulled and should be treated as newly introduced infrastructure
- setup config is older than the current implementation schema

Warnings are recorded in `.crocoexp/config.json` and `.crocoexp/setup_report.md`. Warnings do not block setup unless an explicit future strict policy says otherwise.

## Acceptance Criteria

### Docker and image already present

Initial setup:

- Docker CLI is on `PATH`.
- Docker daemon responds.
- selected image is already present locally.

Command:

```text
crocoexp setup
```

Expected result:

- exit code `0`
- `.crocoexp/config.json` exists
- `.crocoexp/setup_report.md` exists
- `setup_status` is `ready` or `ready_with_warnings`
- `image_present_locally` is `true`
- no experiment `input/` directories are modified

Expected diagnostic summary:

- Docker CLI detected
- Docker daemon available
- selected image present locally
- backend ready for future compile attempts

### Docker present, image missing, no `--pull`

Initial setup:

- Docker CLI is on `PATH`.
- Docker daemon responds.
- selected image is not present locally.

Command:

```text
crocoexp setup --no-pull
```

Expected result:

- exit code `7`
- setup report is written if possible
- config records `setup_status: blocked_image_missing`
- no experiment `input/` directories are modified

Expected diagnostic summary:

- selected image missing locally
- pull was not requested
- setup is blocked by backend infrastructure readiness

### Docker present, image missing, with `--pull`

Initial setup:

- Docker CLI is on `PATH`.
- Docker daemon responds.
- selected image is not present locally.
- registry access succeeds.

Command:

```text
crocoexp setup --pull
```

Expected result:

- exit code `0`
- image is pulled
- `.crocoexp/config.json` records `image_pulled: true`
- `setup_status` is `ready` or `ready_with_warnings`
- no experiment `input/` directories are modified

Expected diagnostic summary:

- selected image was missing
- pull was attempted
- pull succeeded
- image is now registered as default

### Explicit `--image` override

Initial setup:

- Docker CLI and daemon are available.
- user selects a non-default image.

Command:

```text
crocoexp setup --image <name-or-id> --pull
```

Expected result:

- exit code `0` if image is present or pull succeeds
- `.crocoexp/config.json` records `default_docker_image: <name-or-id>`
- previous default image is recorded or mentioned in warnings when applicable
- no experiment `input/` directories are modified

Expected diagnostic summary:

- selected image differs from the built-in canonical default or previous default
- selected image is now the repo default

### Inability to write setup config or report

Initial setup:

- Docker may or may not be available.
- `.crocoexp/` or repo root is not writable.

Command:

```text
crocoexp setup
```

Expected result:

- exit code `4`
- diagnostic names the path that could not be written
- no experiment `input/` directories are modified

Expected diagnostic summary:

- setup could not persist repo-level backend state
- failure category is `blocked_config_write`

## Relationship To Other Commands

- `crocoexp setup` prepares repo-level Docker backend readiness.
- `crocoexp source install <path> --id <source_id>` registers repo-level compile source trees under `CROCO_EXPERIMENTS/sources/<source_id>/`.
- `crocoexp import <experiment_name>` manages experiment evidence under `CROCO_EXPERIMENTS/<experiment_name>/input/` and writes experiment metadata.
- `crocoexp import <experiment_name> --source <source_id>` records the experiment's selected registered compile source.
- `crocoexp compile <experiment_name>` attempts a Docker-backed build using imported experiment artifacts, the experiment's registered compile source, and the configured default image unless the image is overridden.
- `crocoexp dry-run <experiment_name>` reports execution preparation for an experiment.
- `crocoexp run <experiment_name>` attempts execution through Docker.

Setup is repo-level backend preparation, not experiment-level metadata. It must not modify experiment `input/` directories and must not create or update experiment manifests.

## Open Design Choices

- Whether v1 should default to `--no-pull` or prompt before pulling when an image is missing.
- Whether `--check-only` should write `.crocoexp/setup_report.md` or remain strictly read-only.
- How compile should report image provenance when `.crocoexp/config.json` is absent and the built-in default image is used.
- Whether `.crocoexp/config.json` should be committed to version control or treated as local machine state.
- Whether strict setup policies are needed later for image digest pinning or approved image allowlists.
