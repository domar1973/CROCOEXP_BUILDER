# Metadata Manifest

## Principle

The canonical evidence for an experiment is the user-provided `input/` directory:

```text
CROCO_EXPERIMENTS/<experiment_name>/input/
```

Metadata is derived from that evidence. It records findings, mappings, symlink plans, staging decisions, command attempts, logs, reports, failures, and reproducibility details. It is not the source of truth for the experiment itself.

Generated metadata, reports, build products, work directories, logs, snapshots, and run outputs must live outside `input/`.

The manifest supports traceability. It must not imply that the builder has proven scientific correctness, compile-time correctness, runtime semantic compatibility, or experiment well-posedness.

Registered compile source metadata is repo-level infrastructure state, not experiment evidence. The source registry lives at:

```text
.crocoexp/sources.json
```

Registered source trees are copied under:

```text
CROCO_EXPERIMENTS/sources/<source_id>/
```

An experiment manifest may record a selected source in `compile_time.source_ref`, but the source tree itself is not copied into the experiment `input/` directory.

`run.env` is not supported and must not appear as a configuration source in the manifest. If present under `input/`, it is recorded only as an ignored ordinary user file.

## Canonical manifest path

The canonical manifest file is:

```text
CROCO_EXPERIMENTS/<experiment_name>/metadata/manifest.json
```

The canonical human-readable report is:

```text
CROCO_EXPERIMENTS/<experiment_name>/metadata/report.md
```

Command-specific reports may be written under:

```text
CROCO_EXPERIMENTS/<experiment_name>/metadata/
CROCO_EXPERIMENTS/<experiment_name>/runs/<run_id>/reports/
```

There should be one canonical manifest. Reports may be regenerated from the manifest, current artifacts, and command history when possible.

## Source registry path

The repo-level source registry is:

```text
.crocoexp/sources.json
```

It records compile sources installed under:

```text
CROCO_EXPERIMENTS/sources/<source_id>/
```

The registry should contain one record per source id. Required fields for each record:

- `source_id`
- `host_path`
- `container_path`
- `declared_version`
- `installed_at`
- `origin_path`
- `notes`

Recommended fields when practical:

- `git_commit`
- `git_branch`
- `content_hash`
- `detected_layout`
- `installed_by_command`
- `warnings`

This registry is repo-level infrastructure state. It is not a global source/version selector, and `crocoexp setup` must not write experiment-level source metadata.

New v1.0.1 registry records and manifests must not include a `flavor` field. Legacy `flavor: "croco"` metadata may be read and normalized away on rewrite. Legacy non-CROCO flavor values are rejected with an explicit migration error because CROCOEXP v1.0.1 only supports CROCO sources.

Repo-internal operational paths must be persisted as repo-root-relative POSIX paths. Absolute external paths are allowed only for explicitly informational provenance fields such as `origin_path`.

## Required manifest fields

The manifest must contain these top-level fields:

```text
schema_version
experiment
paths
input_evidence
compile_time
runtime
runtime_materialization
capabilities
assets
reporting
docker_backend
commands
snapshots
history
runtime_execution_plan
```

The legacy `overrides` field is not required in this spec. Runtime behavior is governed by the input tree convention, not override-driven asset classification.

### `schema_version`

Required fields:

- `version`
- `created_by`

### `experiment`

Required fields:

- `name`
- `root_host_path`
- `created_at`
- `updated_at`

### `paths`

Records canonical host-side paths and container mappings.

Required host fields:

- `experiments_root_host_path`
- `experiment_root_host_path`
- `input_host_path`
- `metadata_host_path`
- `build_host_path`
- `runs_host_path`

Required container fields:

- `experiments_root_container_path`
- `experiment_root_container_path`
- `input_container_path`
- `metadata_container_path`
- `build_container_path`
- `runs_container_path`

The manifest must record that Docker mounts the whole `CROCO_EXPERIMENTS` directory.

### `input_evidence`

Records user-provided files discovered under `input/`.

Required fields for each evidence item:

- `id`
- `role`
- `host_path`
- `container_path`
- `relative_path_from_input`
- `exists`
- `kind`
- `size_bytes`, when available
- `content_hash`, when available and practical
- `last_modified`, when available
- `provenance`

Primary evidence roles:

- `croco_in`
- `cppdefs_h`
- `param_h`
- `analytical_f`
- `runtime_data`
- `ignored_user_file`
- `other_user_file`

The presence of `input/analytical.F` must be recorded separately from whether it appears relevant for the current builder attempt, staged, not staged, or ambiguous.

`run.env`, when present, must use role `ignored_user_file` with a note that CROCOEXP does not support environment-file substitution.

### `compile_time`

Records findings derived from compile-related artifacts.

Required fields:

- `source_ref`, for compilable experiments when a source has been selected
- `source_artifacts`
- `parsed_symbols`
- `detected_flags`
- `dimensions`
- `analytical_finding`
- `staged_inputs`
- `warnings`
- `findings`

`analytical_finding` should distinguish:

- `not_present`
- `present_in_input`
- `appears_relevant`
- `staged_for_compile`
- `not_staged`
- `ambiguous`

Compile-time findings must remain separate from runtime findings. They are descriptive metadata, not proof that compilation will succeed.

Minimum `source_ref` shape:

```json
{
  "source_id": "croco-v2.1.3",
  "declared_version": "v2.1.3",
  "host_path": "CROCO_EXPERIMENTS/sources/croco-v2.1.3",
  "container_path": "/opt/CROCO_EXPERIMENTS/sources/croco-v2.1.3",
  "registry_path": ".crocoexp/sources.json",
  "origin_path": "/path/copied/from",
  "git_commit": "optional",
  "git_branch": "optional",
  "detected_layout": "optional",
  "selected_at": "timestamp",
  "selection_source": "import --source"
}
```

`source_ref` is part of compile input traceability. It is not a semantic assertion that the source can compile, matches the experiment, or is scientifically correct.

### `runtime`

Records lightweight findings derived from runtime artifacts.

Required fields:

- `source_artifacts`
- `croco_in_present`
- `unresolved_template_tokens`
- `suspicious_absolute_paths`
- `referenced_like_strings`
- `warnings`
- `findings`

Runtime findings must not determine required runtime assets. `croco.in` is version-specific and must be treated as opaque by default.

### `runtime_materialization`

Records the run input contract and symlink plan.

Required top-level fields:

- `policy`
- `input_root_host_path`
- `workdir_host_path`, when a run id is known
- `workdir_container_path`, when a run id is known
- `binary_source_host_path`
- `binary_workdir_relative_path`
- `copied_files`
- `symlinked_runtime_data`
- `skipped_files`
- `warnings`
- `blockers`

Allowed `policy` values:

- `copy_config_symlink_netcdf`

Each `copied_files` record must include:

- `source_host_path`
- `destination_host_path`
- `destination_relative_path_from_workdir`
- `reason`

Each `symlinked_runtime_data` record must include:

- `source_host_path`
- `source_relative_path_from_input`
- `link_host_path`
- `link_relative_path_from_workdir`
- `relative_symlink_target`
- `container_link_path`
- `container_target_path`
- `exists`
- `safe_target`
- `content_hash`, when practical
- `size_bytes`, when available

`safe_target` is true only when the symlink target resolves inside the mounted `CROCO_EXPERIMENTS` tree.

### `capabilities`

Records inferred capabilities or behavior categories as reporting aids.

Required fields for each capability:

- `id`
- `name`
- `status`
- `evidence`
- `source`
- `confidence`
- `notes`

Allowed capability statuses:

- `observed`
- `not_observed`
- `unknown`
- `ambiguous`
- `suspicious`

Capability records are internal reasoning categories, not public named experiment cases and not hard gatekeepers by default.

### `assets`

Records the complete asset inventory.

Required top-level fields:

- `inventory`
- `counts`
- `runtime_data_symlink_policy`

Required fields for each asset:

- `id`
- `role`
- `source`
- `host_path`
- `container_path`
- `relative_path_from_input`, when applicable
- `provenance`
- `exists`
- `content_hash`, when available and practical
- `large_data`
- `materialization_policy`
- `generated`

Allowed `materialization_policy` values:

- `copy_to_workdir`
- `symlink_into_workdir`
- `metadata_only`
- `not_materialized`
- `generated_output`

Data assets such as `.nc` files must use `symlink_into_workdir` for run materialization. They must not use copy policies in normal workflow.

### `reporting`

Replaces a proof-oriented validation model with a reporting-oriented status model.

Required fields:

- `status`
- `last_reported_at`
- `manifest_hash`
- `checks`
- `warnings`
- `suspicious_findings`
- `possible_mismatches`
- `contradictions`
- `infrastructural_blockers`
- `backend_outcome`
- `compile_outcome`
- `run_outcome`
- `strict_policy_result`

Allowed reporting statuses:

- `not_reported`
- `reported_clean`
- `reported_with_warnings`
- `blocked_missing_artifact`
- `blocked_missing_binary`
- `blocked_backend`
- `blocked_compile_failure`
- `blocked_run_failure`
- `blocked_workdir_materialization`
- `blocked_strict_policy`
- `stale`

Each check must include:

- `id`
- `scope`
- `status`
- `evidence`
- `message`

Allowed check scopes:

- `input_evidence`
- `compile_time`
- `runtime`
- `runtime_materialization`
- `docker_backend`
- `snapshot`

### `docker_backend`

Records backend details.

Required fields:

- `mounts`
- `image`
- `working_directory`
- `compile_command_summary`, when applicable
- `run_command_summary`, when applicable
- `backend_findings`

Each mount record must include:

- `host_path`
- `container_path`
- `mode`
- `purpose`

The whole `CROCO_EXPERIMENTS` directory mount must be represented.

For run commands, `working_directory` must be the container path corresponding to `runs/<run_id>/work/`.

### `commands`

Records attempted commands.

Required fields for each command record:

- `id`
- `timestamp`
- `command`
- `arguments`
- `inputs_used`
- `source_ref`, when a registered compile source is used or selected by the command
- `staging_decisions`
- `runtime_materialization_ref`, when applicable
- `host_container_mappings`
- `docker_image`, when applicable
- `logs_produced`
- `reports_produced`
- `snapshots_produced`
- `warnings`
- `findings`
- `failure_category`
- `exit_code`

Allowed failure categories:

- `none`
- `missing_artifact`
- `missing_binary`
- `metadata_or_staging`
- `workdir_materialization`
- `strict_policy`
- `docker_backend`
- `compile_failure`
- `run_failure`

### `snapshots`

Records reproducibility snapshots.

Required fields:

- `policy`
- `latest_compile_snapshot`
- `latest_dry_run_snapshot`
- `latest_run_snapshot`
- `snapshot_records`

Each snapshot record must include:

- `id`
- `run_id`, when applicable
- `kind`
- `host_path`
- `created_at`
- `included_artifacts`
- `runtime_materialization_ref`, when applicable
- `manifest_hash`

Snapshots may copy effective config/code artifacts such as `croco.in`, `cppdefs.h`, `param.h`, and staged `analytical.F`. Runtime data assets such as `.nc` files must remain canonical in `input/` and must be represented by paths, hashes, sizes, and symlink records rather than duplicated.

Snapshots for compile, dry-run, and run should include the selected `compile_time.source_ref` or a reference to it. Snapshots should not duplicate entire registered source trees during normal workflow; they should record source id, installed path, registry metadata, git commit or content identity when practical, and the staged source/config files actually used.

### `history`

Records high-level activity. It may summarize `commands`.

Each entry must include:

- `timestamp`
- `command`
- `result`
- `exit_code`
- `manifest_hash_after`, when available

### `runtime_execution_plan`

Records how CROCOEXP intends to launch the compiled binary.

Required fields:

- `parallel_backend`
- `detected_symbols`
- `parsed_parameters`
- `openmp`
- `mpi`
- `specialized_backends`
- `environment`
- `launcher`
- `warnings`
- `blockers`

Allowed `parallel_backend` values:

- `serial`
- `openmp`
- `mpi`
- `hybrid`
- `openacc`
- `unsupported_complex`

The `openmp` object must include:

- `enabled`
- `npp`
- `nsub_x`
- `nsub_e`
- `planned_omp_num_threads`
- `source`

The `mpi` object must include:

- `enabled`
- `np_xi`
- `np_eta`
- `nnodes`
- `planned_mpi_ranks`

The `environment` object must record Docker environment variables set by CROCOEXP, including `OMP_NUM_THREADS` when applicable.

The `launcher` object must record the wrapper command and whether Docker execution is allowed.

Unsupported runtime launch profiles must appear in `blockers`.

## Recomputed vs persisted fields

### Recomputed from `input/`

These fields should be recomputed whenever import, inspect with recompute, compile, dry-run, or run refreshes metadata:

- `input_evidence`
- `compile_time.source_ref`, when a selected source is present and registry metadata needs refresh
- `compile_time.parsed_symbols`
- `compile_time.detected_flags`
- `compile_time.dimensions`
- `runtime.unresolved_template_tokens`
- `runtime.suspicious_absolute_paths`
- `capabilities`
- `assets.inventory`
- `runtime_materialization`, for a planned or actual run id
- `reporting.checks`
- `reporting.warnings`
- `reporting.infrastructural_blockers`

### Persisted as command state

These fields are persisted because they record decisions or history:

- `experiment.created_at`
- selected `compile_time.source_ref`, unless changed by explicit import/compile option
- `commands`
- `history`
- completed command outcomes
- run ids
- snapshot records
- logs produced
- reports produced

### Recomputed but compared for staleness

These fields may be recomputed and compared against persisted metadata:

- content hashes of primary artifacts
- runtime data asset inventory
- symlink plans
- source registry metadata
- Docker image defaults
- binary path and modified time

## Host path to container path mapping

The manifest must record that Docker mounts the whole `CROCO_EXPERIMENTS` directory. Container paths for experiment files are derived from that mount.

Symlink records must include both host and container interpretation. Because the symlink targets are relative and remain inside `CROCO_EXPERIMENTS`, they should resolve in both environments.

Absolute host-path symlinks are not allowed for generated run workdirs.

## Snapshot policy

Snapshots must copy or record enough information to reproduce what was attempted:

- `croco.in` used in the run workdir
- `cppdefs.h`
- `param.h`
- optional `analytical.F`
- selected source reference
- binary reference and hash when practical
- runtime materialization plan
- symlink records for NetCDF-like assets
- Docker image
- command summary
- logs and exit code

Snapshots must not copy NetCDF-like runtime data assets during normal workflow.

## Infrastructural blocker reporting

The manifest must distinguish:

- missing primary artifact
- missing registered source
- missing binary
- unsafe symlink target
- broken symlink target
- inability to create workdir
- inability to create relative symlink
- Docker/backend failure
- compile failure
- run failure
- actionable policy failure

## Finding reporting

Findings must include evidence and scope. Findings are not proof of failure unless they are infrastructural blockers.

Examples:

- `run.env_present_ignored`
- `croco_in_contains_template_tokens`
- `croco_in_contains_absolute_path`
- `netcdf_assets_present`
- `no_netcdf_assets_present`
- `input_symlink_points_outside_experiments_root`

## Separate compile-time and runtime records

Compile-time records must not be overwritten by runtime records.

Runtime materialization records must not be used to claim CROCO semantic compatibility. They record filesystem visibility only.
