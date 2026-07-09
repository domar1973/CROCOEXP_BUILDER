# Scope

## Project goals

- Provide host-side infrastructure for traceable CROCO compile and run workflows.
- Define experiments from real CROCO artifacts rather than hardcoded experiment cases.
- Treat Docker only as the execution backend, not as the user interface or source of truth.
- Keep all user-facing commands and scripts on the host.
- Ensure users never need to enter the container manually for normal import, inspect, compile, dry-run, or run operations.
- Preserve `CROCO_EXPERIMENTS/<experiment_name>/input/` as the canonical user-provided evidence folder.
- Keep runtime data assets such as `.nc` files in `input/` during normal workflow.
- Expose NetCDF runtime data to model execution through relative symbolic links created in the run-local work directory.
- Store generated metadata, build products, reports, logs, snapshots, work directories, symlink forests, and run outputs outside `input/`.
- Support repo-level registered CROCO source trees, selected per experiment.
- Store registered compile source trees under `CROCO_EXPERIMENTS/sources/<source_id>/` so Docker-backed compile operations can access them through the mounted `CROCO_EXPERIMENTS` tree.
- Treat `croco.in` as version-specific CROCO input, not as universal semantic truth for CROCOEXP.
- Derive a runtime execution plan from compile-time evidence such as `cppdefs.h` and `param.h` so the compiled binary is launched with a compatible backend profile.
- Record what was attempted, which inputs were used, how files were staged or symlinked, what Docker did, what warnings were observed, and what failed.
- Preserve reproducibility by snapshotting effective config/code artifacts, runtime input inventories, symlink plans, command context, and logs.

## Non-goals

- Do not replace Docker with another execution backend.
- Do not require users to learn or operate inside the Docker container.
- Do not make hardcoded named cases the main source of experiment behavior.
- Do not assume every CROCO experiment needs the same external NetCDF files.
- Do not rewrite CROCO source behavior.
- Do not manage external pipelines or non-CROCO source families.
- Do not introduce a new source `flavor`, `kind`, `type`, `pipeline`, or backend selector for CROCO sources.
- Do not make `crocoexp setup` choose a global CROCO version or source tree for all experiments.
- Do not use a global CROCO version variable as the main source of compile input truth.
- Do not assume registered compile sources are only unmodified releases; patched source trees can be registered when they remain compilable CROCO sources.
- Do not use symlinks to host paths outside `CROCO_EXPERIMENTS` as the normal source installation mechanism.
- Do not parse `croco.in` as a universal asset contract, because its syntax depends on the CROCO source version.
- Do not perform universal CROCO semantic validation in `dry-run`.
- Do not infer required runtime assets by recognizing version-specific keys such as `GRDNAME`, `grid:`, `initial:`, `FRCNAME`, or similar.
- Do not source, render, substitute, or otherwise support `run.env`.
- Do not provide backward compatibility for the previous parser-based runtime asset inference design.
- Do not prove that compile-time directives are scientifically or technically correct.
- Do not prove that a selected compile-time configuration will compile successfully before attempting compilation.
- Do not prove that runtime configuration is semantically compatible with the compiled model before execution.
- Do not determine whether an experiment is scientifically well-posed.
- Do not make metadata a replacement for the user-provided artifacts in `input/`.
- Do not treat `croco.in` as the source of runtime backend launch requirements such as OpenMP threads, MPI ranks, XIOS servers, OpenACC devices, or OASIS coupling launch profiles.
- Do not silently launch binaries compiled with unsupported runtime backends such as MPI, MPI+OpenMP hybrid, OpenACC, XIOS, or OASIS.

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
- Runtime data assets such as `.nc`, `.nc4`, and NetCDF-like files remain canonical in `input/`.
- During `run`, NetCDF-like runtime data assets are materialized into `runs/<run_id>/work/` by relative symlinks that preserve their path relative to `input/`.
- Symlink targets must be relative paths within the mounted `CROCO_EXPERIMENTS` tree, never absolute host paths.
- Primary runtime config/code files needed by CROCO execution, especially `croco.in`, are copied into the run-local work directory as regular files.
- Compile-time findings are recorded separately from runtime findings.
- Runtime finding extraction is descriptive only; it must not determine the symlink forest required for execution.
- Possible inconsistencies and ambiguities are reported with evidence.
- Compile and run may be attempted when warnings, ambiguities, contradictions, or possible semantic inconsistencies exist, unless an infrastructural blocker exists.
- A dry-run must not require manual container entry and must not perform a full model run.
- Runs must leave inspectable logs, outputs, reports, snapshots, and the prepared work directory on the host.
- `run.env` is not a recognized artifact. If present, it is ignored as an ordinary user file and must not affect command behavior.
- Runtime materialization and runtime execution planning are separate records.
- Runtime materialization controls filesystem visibility under `runs/<run_id>/work/`.
- Runtime execution planning controls how the binary is launched from that work directory.
- If `OPENMP` is detected, CROCOEXP must set `OMP_NUM_THREADS` explicitly.
- If `MPI`, `OPENACC`, `XIOS`, or `OASIS` are detected and no launch profile is implemented, run must fail before Docker execution with a clear infrastructural blocker.

## Runtime input contract

CROCOEXP guarantees filesystem visibility, not CROCO semantic interpretation.

At run time, CROCOEXP creates:

```text
CROCO_EXPERIMENTS/<experiment_name>/runs/<run_id>/work/
```

The run-local `work/` directory is the execution working directory for CROCO. It contains:

- a copied `croco.in`
- the selected compiled binary, normally as `croco`
- copied small config/code artifacts only when needed for traceability or runtime behavior
- relative symlinks to NetCDF-like runtime data assets under `input/`, preserving each asset's path relative to `input/`

Example:

```text
input/GRD/mesa_grd.nc
input/INIT/mesa_ini.nc

runs/<run_id>/work/GRD/mesa_grd.nc   -> ../../../../input/GRD/mesa_grd.nc
runs/<run_id>/work/INIT/mesa_ini.nc  -> ../../../../input/INIT/mesa_ini.nc
```

The exact relative target must be computed from the symlink parent directory to the canonical file under `input/`.

CROCOEXP does not need to know whether `croco.in` uses `grid:`, `GRDNAME ==`, or any other version-specific syntax. The researcher/copilot is responsible for writing `croco.in` so that its relative paths resolve from the run-local `work/` directory.

## Pain points addressed by this design

- Parser-based asset inference from `croco.in` is fragile across CROCO versions.
- The previous design classified real files as ambiguous when the runtime key syntax was not recognized.
- Required-file errors were misleading when the builder did not understand a particular CROCO input syntax.
- Users were forced to reason about container internals instead of host-side experiment artifacts.
- Runtime data staging depended on a universal semantic parser that cannot be correct for all CROCO variants.
- Compile-time and runtime concerns were blurred, making it unclear whether a failure came from missing evidence, staging, Docker, compilation, execution, or a CROCO-level issue.
- `run.env` created an implicit templating layer whose behavior was not guaranteed by CROCOEXP.
- Reproducibility was weakened when effective artifacts, symlink plans, logs, and command attempts were not represented as a single runtime contract.
