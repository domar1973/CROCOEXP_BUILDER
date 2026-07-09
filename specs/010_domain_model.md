# Domain Model

## Entities

### Experiment

An experiment is the host-side unit of evidence, generated metadata, execution attempts, prepared work directories, and outputs.

It is rooted at:

```text
CROCO_EXPERIMENTS/<experiment_name>/
```

It contains:

- `input/`: canonical user-provided CROCO artifacts and runtime data assets.
- `metadata/`: generated manifest, findings, reports, and command records.
- `build/`: staged compile area and build outputs.
- `runs/<run_id>/`: logs, outputs, snapshots, reports, and run-local work directory.

Expected run layout:

```text
CROCO_EXPERIMENTS/<experiment_name>/runs/<run_id>/
  work/
  output/
  logs/
  snapshots/
  reports/
```

An experiment is not a hardcoded case. It is an artifact-backed workspace assembled from real files and recorded findings.

### Registered compile source

A registered compile source is a repo-level source tree that can be selected as a compile input for one or more experiments.

Registered sources are stored under:

```text
CROCO_EXPERIMENTS/sources/<source_id>/
```

They may represent:

- CROCO source trees
- patched local CROCO source trees

The key concept is `source_id`, not a global CROCO version. A source is selected per experiment and recorded in that experiment's compile-time metadata as `compile_time.source_ref`.

The v1.0.1 model has no source `flavor` field for new source records or manifests. Legacy metadata with `flavor: "croco"` may be read for compatibility and normalized away on rewrite. Legacy `flavor` values for non-CROCO sources are rejected because pipelines and non-CROCO source families are outside CROCOEXP scope.

Registered source metadata is recorded in:

```text
.crocoexp/sources.json
```

The source registry is repo-level infrastructure state. It is not experiment `input/` evidence, and it is not selected by `crocoexp setup`.

Normal workflow copies a source tree into `CROCO_EXPERIMENTS/sources/<source_id>/`. Symlinks to host paths outside `CROCO_EXPERIMENTS` are not the default mechanism because they may be broken inside the Docker mount.

### Input evidence

`input/` is the canonical evidence folder. It may contain:

- `croco.in`
- `cppdefs.h`
- `param.h`
- optional `analytical.F`
- NetCDF-like runtime data assets such as `.nc`, `.nc4`, `.cdf`
- other user-provided files relevant to the experiment

The builder may read, hash, snapshot, symlink, or reference evidence, but generated files must not be written into `input/`.

Runtime data assets remain in `input/` during normal workflow. In run work directories they are represented by relative symbolic links, not copies.

`run.env` is not a recognized evidence type. If a file named `run.env` exists under `input/`, it is recorded only as an ignored ordinary user file and must not be sourced, parsed, rendered, or applied.

### Runtime data asset

A runtime data asset is a user-provided file under `input/` that may be read by CROCO during execution. NetCDF-like runtime data assets are recognized by file extension, not by parsing `croco.in`.

Default NetCDF-like extensions:

- `.nc`
- `.nc4`
- `.cdf`

Future implementations may allow extension configuration, but default behavior must not require a CROCO-version-specific parser.

Runtime data asset records should include:

- canonical host path under `input/`
- relative path from `input/`
- planned workdir symlink path
- relative symlink target
- exists
- size and hash when practical
- source: `input_tree_scan`
- copy policy: `symlink_into_work`

### Run work directory

A run work directory is the per-run filesystem view from which CROCO is executed.

It is located at:

```text
CROCO_EXPERIMENTS/<experiment_name>/runs/<run_id>/work/
```

The run work directory is generated. It must not be treated as user-provided evidence.

It contains:

- copied `croco.in`
- selected binary as `croco` or an explicitly recorded binary name
- symlinks to NetCDF-like runtime data assets preserving input-relative paths
- optional copied runtime helper files when explicitly required by implementation policy

The command must execute CROCO with current working directory set to the work directory. This makes `croco.in` relative paths resolve against the generated work tree.

### Compile-time findings

Compile-time findings describe what the builder can observe from compile-related artifacts.

Primary inputs:

- `input/cppdefs.h`
- `input/param.h`
- selected registered compile source under `CROCO_EXPERIMENTS/sources/<source_id>/`
- source files or includes staged for compilation
- optional `input/analytical.F`

Findings may include:

- detected CPP symbols or flags
- dimensions or constants parsed from `param.h`
- whether `analytical.F` exists and appears relevant
- selected compile source reference and registry metadata
- files staged for compilation
- warnings or suspicious combinations

Compile-time findings are descriptive metadata. They do not prove that the configuration is correct or that compilation will succeed. The compilation attempt and its logs are the authoritative record of whether the selected configuration compiled.

### Runtime findings

Runtime findings describe what the builder can observe from runtime artifacts.

Primary input:

- `input/croco.in`

Runtime findings may include:

- raw text properties of `croco.in`
- unresolved template-looking tokens such as `${...}`
- referenced-looking strings when cheaply detectable
- warnings about likely portability issues

Runtime findings must not drive universal required-asset selection. `croco.in` is version-specific CROCO syntax, not universal CROCOEXP semantic truth.

The run attempt and CROCO logs are the authoritative record of what happened during execution.

### Runtime materialization plan

The runtime materialization plan records how `input/` is exposed under `runs/<run_id>/work/`.

Required fields:

- input root
- workdir root
- binary source
- binary destination
- copied runtime config files
- symlinked NetCDF-like runtime assets
- skipped files
- warnings
- Docker working directory
- Docker mounts

The plan is infrastructural. It does not prove that CROCO will successfully read any file.

### Runtime execution plan

The runtime execution plan records how CROCOEXP intends to launch the compiled CROCO binary from the run work directory.

It is derived from compile-time evidence, especially `input/cppdefs.h` and `input/param.h`, not from `input/croco.in`.

It records:

- detected launch-relevant symbols such as `OPENMP`, `MPI`, `OPENACC`, `XIOS`, `OASIS`, and `AGRIF`
- parsed execution dimensions such as `NPP`, `NSUB_X`, `NSUB_E`, `NP_XI`, `NP_ETA`, and `NNODES`
- selected launch profile: `serial`, `openmp`, `mpi`, `hybrid`, `openacc`, or `unsupported_complex`
- environment variables controlled by CROCOEXP, especially `OMP_NUM_THREADS`
- Docker `-e` variables needed for launch
- wrapper command used to start CROCO
- warnings and blockers for unsupported launch profiles

The runtime execution plan is infrastructural. It does not prove that the CROCO configuration is scientifically correct or that the model will run successfully after launch.

### Assets

Assets are host-side files discovered under `input/` or generated by CROCOEXP.

Asset records should include:

- host path
- relative path from input or generated root
- role
- provenance
- exists
- size/hash when practical
- runtime materialization policy
- generated vs user-provided status

Asset roles include:

- `primary_config`: `croco.in`, `cppdefs.h`, `param.h`
- `optional_code`: `analytical.F`
- `runtime_data`: NetCDF-like files under `input/`
- `other_user_file`
- `generated_work_file`
- `generated_output`
- `generated_report`
- `generated_log`

The old required/optional/ignored/ambiguous runtime asset classifier is not part of the default staging contract. It may be reintroduced only as an optional diagnostic profile, not as the default behavior.

### Docker backend

The Docker backend is the execution adapter for compiling and running CROCO.

Responsibilities:

- Use the selected Docker image.
- Mount the whole `CROCO_EXPERIMENTS` directory.
- Make registered compile sources under `CROCO_EXPERIMENTS/sources/` available to compile commands.
- Make the run work directory available to runtime commands.
- Execute CROCO from the run work directory.
- Return logs, exit codes, and generated outputs to host-side locations.

Docker is not the experiment source of truth. Users must not need to enter the container manually.

## Sources of truth

### User-provided evidence

The primary source of truth is the real CROCO experiment artifact set under `input/`:

- `input/croco.in`
- `input/cppdefs.h`
- `input/param.h`
- optional `input/analytical.F`
- runtime data assets under `input/`

These files define what the user is asking the builder to manage and attempt. The builder records metadata derived from them, but metadata is not a replacement for the evidence.

### Generated metadata

Generated metadata records:

- selected registered compile source for the experiment, when known
- compile-time findings
- runtime findings
- input evidence inventory
- runtime materialization plan
- symlink records
- Docker backend details
- command attempts
- logs and reports produced
- warnings, possible inconsistencies, and failures

Generated metadata supports traceability and diagnostics. It should be regenerable from `input/` and command history whenever possible.

Operational paths persisted in generated metadata should be repo-root-relative POSIX paths when they point inside the repo. Runtime code may resolve them to absolute paths internally. Absolute external paths are allowed only for informational provenance fields such as source `origin_path`; operational external paths must fail explicitly.

### Source registry

The source registry records repo-level compile source assets installed under `CROCO_EXPERIMENTS/sources/`.

It records:

- `source_id`
- installed host path under `CROCO_EXPERIMENTS/sources/<source_id>/`
- declared version, when known
- origin path copied from
- installation timestamp
- optional git branch and commit
- detected layout and content identity when practical

The registry is a source of truth for registered compile infrastructure, not for experiment science. It does not prove that a source tree is correct, complete, compatible with an experiment, or able to compile.

## Compile-time truth vs runtime truth

The builder preserves a distinction between compile-time evidence and runtime execution evidence.

Compile-time findings answer: what did the compile-related artifacts appear to request or define?

Runtime materialization answers: which files were made visible to CROCO in the run work directory?

Runtime execution planning answers: how the compiled binary must be launched based on compile-time backend evidence.

Runtime findings answer: what superficial/runtime-artifact observations were recorded from `croco.in`.

Rules:

- Compile-time findings and runtime materialization records must be separate.
- The registered compile source selected for compilation must be recorded as compile-time traceability.
- Runtime data visibility is guaranteed by symlink materialization of input NetCDF-like files, not by semantic parsing of `croco.in`.
- The builder may compare compile-time and runtime information and report suspicious combinations as findings.
- The comparison is descriptive and diagnostic, not a theorem proving step.
- Runtime materialization and runtime execution planning must be recorded separately.
- Compile and run commands may proceed with reported warnings or suspicious combinations unless blocked by an infrastructural blocker.

## File materialization rules

### Copied into run workdir

- `input/croco.in`
- selected compiled binary
- small explicit runtime helper files if implementation policy requires them

Copied files are generated run-local files. They do not replace canonical evidence.

### Symlinked into run workdir

- NetCDF-like runtime data assets under `input/`

Symlink requirements:

- Preserve the path relative to `input/`.
- Use relative symlink targets.
- Targets must remain inside the mounted `CROCO_EXPERIMENTS` tree.
- Do not create absolute host-path symlinks.
- Do not copy large runtime data files during normal workflow.
- Existing symlinks in `input/` that point outside `CROCO_EXPERIMENTS` are blockers unless explicitly allowed by future policy.

### Ignored for behavior

- `run.env`
- unknown files that are not primary config, optional code, or recognized runtime data

Ignored files may still be inventoried as user-provided files.

## Possible inconsistency reporting

The builder may report:

- unresolved `${...}` tokens in `croco.in`
- presence of `run.env`, with note that it is ignored
- NetCDF files present but no obvious references found
- references that look like absolute host paths
- config files that mention output paths under `input/`
- compile/run suspicious combinations

These are findings by default. They are not hard failures unless they prevent construction of the run work directory.
