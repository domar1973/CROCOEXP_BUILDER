# Domain Model

## Entities

### Experiment

An experiment is the host-side unit of evidence, generated metadata, execution attempts, and outputs.

It is rooted at:

```text
CROCO_EXPERIMENTS/<experiment_name>/
```

It contains:

- `input/`: canonical user-provided CROCO artifacts and runtime data assets.
- `metadata/`: generated manifest, findings, reports, and command records.
- `build/`: staged compile area and build outputs.
- `runs/<run_id>/`: logs, outputs, snapshots, and reports for execution attempts.

An experiment is not a hardcoded case. It is an artifact-backed workspace assembled from real files and recorded findings.

### Input evidence

`input/` is the canonical evidence folder. It may contain:

- `croco.in`
- `cppdefs.h`
- `param.h`
- optional `analytical.F`
- `.nc` and similar runtime data assets
- other user-provided files relevant to the experiment

The builder may read, hash, stage, mount, or reference evidence in snapshots, but generated files must not be written into `input/`. Snapshots may copy config/code artifacts; runtime data assets remain in `input/` during normal workflow and are represented in snapshots by metadata such as path, mapping, size, and hash when practical.

### Compile-time findings

Compile-time findings describe what the builder can observe from compile-related artifacts.

Primary inputs:

- `input/cppdefs.h`
- `input/param.h`
- source files or includes staged for compilation
- optional `input/analytical.F`

Findings may include:

- detected CPP symbols or flags
- dimensions or constants parsed from `param.h`
- whether `analytical.F` exists and appears relevant
- files staged for compilation
- warnings or suspicious combinations

Compile-time findings are descriptive metadata. They do not prove that the configuration is correct or that compilation will succeed. The compilation attempt and its logs are the authoritative record of whether the selected configuration compiled.

### Runtime findings

Runtime findings describe what the builder can observe from runtime artifacts.

Primary input:

- `input/croco.in`

Findings may include:

- parsed runtime keys and values
- referenced paths
- inferred asset roles
- host/container path mappings
- warnings or ambiguous references

Runtime findings are descriptive metadata. They do not prove that the runtime configuration is semantically compatible with the compiled model or scientifically valid. The run attempt and its logs are the authoritative record of what happened during execution.

### Assets

Assets are host-side files referenced by the experiment or discovered in `input/`.

Examples:

- grid files
- initial condition files
- forcing files
- climatology files
- boundary files
- restart files
- tide files
- bulk flux files
- other files referenced by `croco.in` or supporting configuration

Each asset record should include:

- host path
- container path
- role inferred from artifact-level evidence
- classification: required, optional, ignored, or ambiguous
- provenance explaining the classification
- copy policy

Asset classification is a reporting and staging/mounting aid for the current builder attempt. It should be conservative and evidence-based, but it is not a semantic proof of CROCO behavior.

### Docker backend

The Docker backend is the execution adapter for compiling and running CROCO.

Responsibilities:

- Use or build the required image.
- Mount the whole `CROCO_EXPERIMENTS` directory.
- Run compile, dry-run support, and model execution commands.
- Return logs, exit codes, and generated outputs to host-side locations.

Docker is not the experiment source of truth. Users must not need to enter the container manually.

## Sources of truth

### User-provided evidence

The primary source of truth is the real CROCO experiment artifact set under `input/`:

- `input/croco.in`
- `input/cppdefs.h`
- `input/param.h`
- optional `input/analytical.F`
- runtime data assets referenced by the current builder workflow

These files define what the user is asking the builder to manage and attempt. The builder records metadata derived from them, but metadata is not a replacement for the evidence.

### Generated metadata

Generated metadata records:

- compile-time findings
- runtime findings
- asset inventory and classifications
- host/container mappings
- staging decisions
- Docker backend details
- command attempts
- logs and reports produced
- warnings, ambiguities, possible inconsistencies, and failures

Generated metadata supports traceability and diagnostics. It should be regenerable from `input/` and command history whenever possible.

### User overrides

User overrides may be allowed for path mapping, backend settings, and explicit intent when artifact-level evidence is ambiguous.

Overrides must:

- be host-side
- be recorded in metadata and snapshots
- be visible in dry-run and run reports
- not move `.nc` or similar runtime data out of `input/` during normal workflow

Overrides resolve builder ambiguity; they do not prove scientific or semantic correctness.

## Compile-time truth vs runtime truth

The builder preserves a distinction between compile-time evidence and runtime evidence.

Compile-time findings answer: what did the compile-related artifacts appear to request or define?

Examples:

- Which CPP flags are present.
- Which dimensions and model limits are present in `param.h`.
- Whether `analytical.F` is present and appears relevant.
- Which files were staged for compilation.

Runtime findings answer: what did `croco.in` and related runtime evidence appear to request?

Examples:

- Which paths are referenced.
- Which runtime values are present.
- Which restart, forcing, grid, boundary, or climatology files are named.
- Which output cadence and output files are requested.

Rules:

- Compile-time and runtime findings must be recorded separately.
- The builder may compare them and report possible mismatches, contradictions, ambiguities, or suspicious combinations as findings.
- The comparison is descriptive and diagnostic, not a theorem proving step.
- Compile and run commands may proceed with reported warnings, ambiguities, contradictions, or possible mismatches unless blocked by missing primary artifacts, inability to write metadata, inability to construct the requested staging/mounting plan, missing binary for run, explicit strict policy, Docker/backend failure, compile failure, or run failure.
- Dry-run must show the evidence behind builder-level file classifications, staging/mounting decisions, and warnings.

## File classification rules

### Required

An external file is required when artifact-level evidence indicates the builder must stage or mount it to attempt the requested operation.

Examples:

- `croco.in` contains a parser-recognized reference that the builder selects for staging or mounting in the run attempt.
- A compile command needs `cppdefs.h`, `param.h`, or a staged source/config file.
- A user-selected resume mode names a restart file that must be mounted.

Missing required files are infrastructural blockers because the builder cannot stage or mount what is absent.

### Optional

An external file is optional when it may be relevant but its absence should not block the requested builder operation by default.

Examples:

- A file reference that parser-level evidence does not select for staging or mounting.
- A helper artifact that improves reporting but is not needed for staging.
- A runtime reference whose relevance cannot be proven from artifact-level evidence and is not needed to form the execution attempt.

Optional files should be reported with provenance.

### Ignored

An external file is ignored when artifact-level evidence suggests it is not selected for staging/mounting in the current builder attempt.

Examples:

- A placeholder path in `croco.in`.
- A traditional key such as `GRD_FILE`, `INI_FILE`, or `FRC_FILE` that parser-level evidence does not select for the current attempt.
- A file in `input/` that is not referenced by parsed artifacts.

Ignored files should not be mounted as required inputs. They may still be listed as non-active evidence.

### Ambiguous

An asset is ambiguous when the builder cannot confidently classify it from artifact-level evidence.

Ambiguous cases should:

- be surfaced in dry-run output
- include evidence and candidate interpretations
- allow host-side user overrides when useful
- remain warnings/findings by default unless an explicit strict policy treats them as blockers or the ambiguity prevents construction of the requested staging/mounting plan

## Possible inconsistency reporting

The builder may report possible inconsistencies, contradictions, or suspicious combinations, such as:

- runtime references to a file that appears incompatible with detected compile-time flags
- runtime references to a capability that may not be compiled in
- analytical-looking compile evidence alongside external-data runtime references

These are reported findings. They are not hard failures by default because the builder is not responsible for proving CROCO semantic compatibility. Commands should proceed unless an infrastructural blocker or explicit strict policy stops them.
