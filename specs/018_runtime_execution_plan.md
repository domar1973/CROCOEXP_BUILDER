# Runtime Execution Plan

## Purpose

The runtime execution plan defines how CROCOEXP launches a compiled CROCO binary.

It is derived from compile-time evidence such as `cppdefs.h` and `param.h`, not from `croco.in`.

CROCOEXP treats `croco.in` as opaque for runtime asset semantics, but it must still launch the compiled binary with a compatible backend profile.

## Inputs

Primary inputs:

- `input/cppdefs.h`
- `input/param.h`
- selected compiled binary
- Docker backend configuration

`croco.in` is not used to infer the runtime execution backend.

## Detected compile-time capabilities

CROCOEXP should detect, when practical:

- `OPENMP`
- `MPI`
- `OPENACC`
- `XIOS`
- `OASIS`
- `AGRIF`

These symbols are detected from `cppdefs.h` and related compile-time evidence.

## Parsed dimensional parameters

CROCOEXP should parse, when practical:

- `NPP`
- `NSUB_X`
- `NSUB_E`
- `NP_XI`
- `NP_ETA`
- `NNODES`

These are parsed from `param.h`.

If a value cannot be parsed, it is recorded as `unknown`.

## Supported launch profiles

### Serial

If neither `OPENMP` nor `MPI` nor specialized backends are active, CROCOEXP may launch:

```bash
./croco croco.in

## Relationship to runtime materialization

Runtime materialization and runtime execution planning are separate.

`runtime_materialization` answers: what files are visible under `runs/<run_id>/work/`?

`runtime_execution_plan` answers: how does CROCOEXP launch the compiled binary from that work directory?

The runtime execution plan may depend on the workdir path and selected binary, but it does not decide which NetCDF files are symlinked.

## OpenMP rule

If `OPENMP` is detected and `MPI` is not detected:

- If `NPP` is parsed from `param.h`, set `OMP_NUM_THREADS=NPP`.
- If `NPP` cannot be parsed, set `OMP_NUM_THREADS=1` and record a warning.
- Pass `-e OMP_NUM_THREADS=<value>` to Docker.
- Write a hard assignment in `run_inside_docker.sh`:

```bash
export OMP_NUM_THREADS=<value>
./croco croco.in
```

Do not use `${OMP_NUM_THREADS:-<value>}`, because a host or container environment may already contain an invalid value.
```

Add unsupported profiles:

```markdown
## Unsupported launch profiles in v1

The following profiles are detected but unsupported by the v1 launcher:

- MPI
- MPI + OpenMP hybrid
- OpenACC
- XIOS
- OASIS

If detected, `run` must fail before Docker execution with a clear infrastructural blocker.
