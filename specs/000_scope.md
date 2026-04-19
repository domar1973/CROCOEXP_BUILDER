# Scope

## Project goals

- Provide host-side infrastructure for traceable CROCO compile and run workflows.
- Define experiments from real CROCO artifacts rather than hardcoded experiment cases.
- Treat Docker only as the execution backend, not as the user interface or source of truth.
- Keep all user-facing commands and scripts on the host.
- Ensure users never need to enter the container manually for normal import, inspect, compile, dry-run, or run operations.
- Preserve `CROCO_EXPERIMENTS/<experiment_name>/input/` as the canonical user-provided evidence folder.
- Keep runtime data assets such as `.nc` files in `input/` during normal workflow.
- Store generated metadata, build products, reports, logs, snapshots, and run outputs outside `input/`.
- Support repo-level registered compile sources, selected per experiment, for official CROCO source trees, MSOT, custom forks, or patched source trees.
- Store registered compile source trees under `CROCO_EXPERIMENTS/sources/<source_id>/` so Docker-backed compile operations can access them through the mounted `CROCO_EXPERIMENTS` tree.
- Infer builder-relevant staging and mounting needs from artifacts without claiming CROCO-level semantic truth.
- Record what was attempted, which inputs were used, how files were staged or mounted, what Docker did, what warnings were observed, and what failed.
- Preserve reproducibility by snapshotting effective config/code artifacts, asset inventories, host/container path mappings, command context, and logs.

## Non-goals

- Do not replace Docker with another execution backend.
- Do not require users to learn or operate inside the Docker container.
- Do not make hardcoded named cases the main source of experiment behavior.
- Do not assume every CROCO experiment needs the same external NetCDF files.
- Do not rewrite CROCO source behavior.
- Do not make `crocoexp setup` choose a global CROCO version or source tree for all experiments.
- Do not use a global CROCO version variable as the main source of compile input truth.
- Do not assume registered compile sources are only official CROCO versions; MSOT and custom forks are valid registered sources.
- Do not use symlinks to host paths outside `CROCO_EXPERIMENTS` as the normal source installation mechanism.
- Do not prove that compile-time directives are scientifically or technically correct.
- Do not prove that a selected compile-time configuration will compile successfully before attempting compilation.
- Do not prove that runtime configuration is semantically compatible with the compiled model before execution.
- Do not determine whether an experiment is scientifically well-posed.
- Do not make metadata a replacement for the user-provided artifacts in `input/`.

Scientific and semantic responsibility remains with the researcher and the surrounding copilot workflow. The builder is responsible for disciplined artifact management, execution attempts, traceability, and diagnostics.

## Invariants to preserve

- Host-side commands are the only supported user entry points.
- Docker remains the isolated backend for compile and run operations.
- Docker mounts the whole `CROCO_EXPERIMENTS` directory.
- User-provided CROCO artifacts live in `CROCO_EXPERIMENTS/<experiment_name>/input/`.
- Registered compile sources live in `CROCO_EXPERIMENTS/sources/<source_id>/` and are repo-level compile infrastructure, not experiment `input/` evidence.
- Source registry state lives in `.crocoexp/sources.json`.
- Compile source selection is per experiment and must be recorded in experiment metadata under compile-time traceability.
- Generated files must be distinguishable from user-provided files and must live outside `input/`.
- Runtime data assets such as `.nc` files remain in `input/` and are accessed through mount-path mapping or symlinks when needed.
- Compile-time findings are recorded separately from runtime findings.
- Asset classifications are reporting and staging aids for the current builder attempt, not proof that the CROCO experiment is semantically valid.
- Possible inconsistencies and ambiguities are reported with evidence.
- Compile and run may be attempted when warnings, ambiguities, contradictions, or possible semantic inconsistencies exist, unless an infrastructural blocker exists or the user selects an explicit strict policy.
- A dry-run must not require manual container entry and must not perform a full model run.
- Runs must leave inspectable logs, outputs, reports, and snapshots on the host.

## Pain points of current design

- The current design is too rigid because it assumes `GRD_FILE`, `INI_FILE`, and `FRC_FILE` are always required.
- Experiments that use analytical definitions, climatology, restart files, boundary forcing, or other CROCO-supported modes do not fit a single fixed asset checklist.
- Hardcoded cases make the system difficult to extend and easy to break when a real experiment differs from the expected template.
- Required-file errors can be misleading when a file is only a placeholder, parser-level non-selected reference, or optional runtime asset for the current builder attempt.
- Users are forced to reason about container internals instead of host-side experiment artifacts.
- Compile source provenance is weak when source trees are selected by informal notes, container-local defaults, or scattered version variables.
- Symlinked source trees outside `CROCO_EXPERIMENTS` can break inside Docker because only `CROCO_EXPERIMENTS` is mounted.
- Compile-time and runtime concerns are blurred, making it unclear whether a failure came from missing evidence, staging, Docker, compilation, execution, or a CROCO-level issue.
- Current validation language overreaches by implying the builder can prove compile/runtime semantic compatibility.
- Reproducibility is weakened when effective artifacts, inferred findings, mounted assets, logs, and command attempts are not captured together.
