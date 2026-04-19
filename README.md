# CROCOEXP_BUILDER

CROCOEXP_BUILDER is a host-side tool for managing traceable CROCO experiment workflows. It prepares Docker-backed execution, registers compile source trees, imports real experiment artifacts, and records what was attempted during compile, dry-run, and run operations.

The builder is infrastructure-oriented and traceability-oriented. It does not prove that a CROCO configuration is scientifically valid or that compile-time and runtime choices are semantically compatible. It records evidence, staging decisions, mappings, warnings, logs, reports, snapshots, and failures so the researcher can inspect and reproduce each attempt.

## Core Architecture

- Docker is the execution backend only.
- Users launch all commands from the host with `crocoexp`.
- Experiment evidence lives under `CROCO_EXPERIMENTS/<experiment_name>/input/`.
- Runtime data files such as `.nc` remain canonical in `input/`.
- Registered compile source trees live under `CROCO_EXPERIMENTS/sources/<source_id>/`.
- The source registry lives at `.crocoexp/sources.json`.
- Experiment manifests live at `CROCO_EXPERIMENTS/<experiment_name>/metadata/manifest.json`.
- Compile source selection is per experiment through `compile_time.source_ref`.
- Setup records Docker/backend readiness only. It is not a global CROCO source selector.

## Repository Commands

Check and record Docker backend readiness:

```bash
./crocoexp setup --no-pull
```

Use `--pull` when you want setup to pull the selected image if it is missing:

```bash
./crocoexp setup --pull
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
    *.nc                # optional runtime data
```

Import the experiment and select its compile source:

```bash
./crocoexp import my_experiment --source croco-v2.1.2
```

Inspect current metadata:

```bash
./crocoexp inspect my_experiment
```

Compile through Docker from the host:

```bash
./crocoexp compile my_experiment
```

Generate a pre-execution report without running CROCO:

```bash
./crocoexp dry-run my_experiment
```

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
        logs/
        output/
        snapshots/
        reports/
```

## Data Handling Policy

`input/` is the canonical location for user-provided experiment artifacts. The builder must not modify files there during normal workflow.

Runtime data assets such as `.nc` files stay in `input/`. They are mounted or mapped for execution and recorded in metadata, but they are not copied into `build/` or run snapshots as part of normal workflow.

Generated metadata, reports, build products, logs, snapshots, and run outputs live outside `input/`. Compile source trees are copied into `CROCO_EXPERIMENTS/sources/<source_id>/` so Docker can access them through the managed experiments mount without depending on external host symlinks.

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

## Design Boundaries

CROCOEXP_BUILDER reports warnings, ambiguities, suspicious combinations, and possible mismatches as findings by default. These findings are not the same as hard blockers.

Default hard failures are mainly infrastructural: missing required primary artifacts, missing registered source metadata, missing binary for run, inability to construct staging or mappings, inability to write metadata or reports, Docker/backend failure, compile failure, and run failure.

Researchers and their copilot workflow remain responsible for scientific setup, CROCO semantics, and interpretation of model behavior.
