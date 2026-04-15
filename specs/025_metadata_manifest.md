# Metadata Manifest

## Principle

The canonical evidence for an experiment is the user-provided `input/` directory:

```text
CROCO_EXPERIMENTS/<experiment_name>/input/
```

Metadata is derived from that evidence. It records findings, mappings, overrides, staging decisions, command attempts, logs, reports, failures, and reproducibility details. It is not the source of truth for the experiment itself.

Generated metadata, reports, build products, logs, snapshots, and run outputs must live outside `input/`.

The manifest supports traceability. It must not imply that the builder has proven scientific correctness, compile-time correctness, runtime semantic compatibility, or experiment well-posedness.

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

## Required manifest fields

The manifest must contain these top-level fields:

```text
schema_version
experiment
paths
input_evidence
compile_time
runtime
capabilities
assets
overrides
reporting
docker_backend
commands
snapshots
history
```

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
- `runtime_asset`
- `other_user_file`

The presence of `input/analytical.F` must be recorded separately from whether it appears relevant for the current builder attempt, staged, not staged, or ambiguous.

### `compile_time`

Records findings derived from compile-related artifacts.

Required fields:

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

### `runtime`

Records findings derived from runtime artifacts.

Required fields:

- `source_artifacts`
- `parsed_keys`
- `referenced_assets`
- `runtime_requests`
- `warnings`
- `findings`

Runtime findings must record `croco.in` references even when later classified as optional, ignored, or ambiguous. They are descriptive metadata, not proof that execution will succeed.

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
- `classification_counts`
- `selected_mounts`

Required fields for each asset:

- `id`
- `role`
- `source`
- `host_path`
- `container_path`
- `relative_path_from_input`, when applicable
- `referenced_by`
- `compile_time_relevance`
- `runtime_relevance`
- `classification`
- `classification_reason`
- `provenance`
- `exists`
- `content_hash`, when available and practical
- `large_data`
- `copy_policy`

Allowed classifications:

- `required`
- `optional`
- `ignored`
- `ambiguous`

Required `copy_policy` values:

- `remain_in_input`
- `stage_copy_allowed`
- `snapshot_copy_allowed`
- `metadata_only`

Data assets such as `.nc` files must use `remain_in_input` for normal workflow. They must not use `snapshot_copy_allowed` or `stage_copy_allowed` in normal workflow. The manifest must explicitly record that these files were not duplicated or moved.

### `overrides`

Records user-provided overrides.

Required fields for each override:

- `id`
- `source_file`
- `scope`
- `target`
- `value`
- `reason`
- `applied`
- `diagnostics`

Override scopes may include:

- `asset_classification`
- `path_mapping`
- `capability_disambiguation`
- `docker_backend`
- `run_option`
- `strict_policy`

Overrides clarify builder behavior. They do not prove scientific or semantic correctness.

### `reporting`

Replaces a proof-oriented validation model with a reporting-oriented status model.

Required fields:

- `status`
- `last_reported_at`
- `manifest_hash`
- `checks`
- `warnings`
- `ambiguities`
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
- `asset_resolution`
- `staging`
- `mounting`
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

### `commands`

Records attempted commands.

Required fields for each command record:

- `id`
- `timestamp`
- `command`
- `arguments`
- `inputs_used`
- `staging_decisions`
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
- `asset_inventory_ref`
- `manifest_hash`

Snapshots may copy effective config/code artifacts such as `croco.in`, `cppdefs.h`, `param.h`, and staged `analytical.F`. Runtime data assets such as `.nc` files must remain canonical in `input/` and must be represented by paths, hashes, sizes, and mappings rather than duplicated.

### `history`

Records high-level activity. It may summarize `commands`.

Each entry must include:

- `timestamp`
- `command`
- `result`
- `exit_code`
- `manifest_hash_after`, when available

## Recomputed vs persisted fields

### Recomputed from `input/`

These fields should be recomputed whenever import, inspect with recompute, compile, dry-run, or run refreshes metadata:

- `input_evidence`
- `compile_time.parsed_symbols`
- `compile_time.detected_flags`
- `compile_time.dimensions`
- `runtime.parsed_keys`
- `runtime.referenced_assets`
- `capabilities`
- `assets.inventory`
- `assets.classification_counts`
- `assets.selected_mounts`
- `reporting.checks`
- `reporting.warnings`
- `reporting.ambiguities`
- `reporting.possible_mismatches`
- `reporting.infrastructural_blockers`

### Persisted as command state

These fields are persisted because they record decisions or history:

- `experiment.created_at`
- `overrides`
- `docker_backend.image`, if explicitly selected
- `commands`
- `snapshots.snapshot_records`
- `history`
- run ids and report paths

### Recomputed but compared for staleness

These fields should be compared against prior values:

- content hashes for primary artifacts
- content hashes for assets selected for staging/mounting when practical
- manifest hash used for dry-run reports
- build input hash used for binary provenance

If primary artifacts or assets selected for staging/mounting change after a report, `reporting.status` should become `stale` until refreshed.

## Asset inventory structure

Asset records must be concrete enough to explain classification.

Example shape:

```json
{
  "id": "asset.grid.main",
  "role": "grid",
  "source": "runtime_reference",
  "host_path": "CROCO_EXPERIMENTS/demo/input/grid.nc",
  "container_path": "/experiments/demo/input/grid.nc",
  "relative_path_from_input": "grid.nc",
  "referenced_by": [
    {
      "artifact": "input/croco.in",
      "key": "GRD_FILE",
      "value": "grid.nc"
    }
  ],
  "compile_time_relevance": "external_grid_observed",
  "runtime_relevance": "referenced",
  "classification": "required",
  "classification_reason": "Artifact-level evidence says the builder selected this file for mounting in the run attempt.",
  "provenance": ["input/croco.in:GRD_FILE", "input/cppdefs.h"],
  "exists": true,
  "large_data": true,
  "copy_policy": "remain_in_input"
}
```

## Host path to container path mapping

Every required or optional asset selected for staging/mounting should have a mapping.

Mapping records must include:

- host path
- container path
- mount root
- relative path from experiment root
- whether the path is a direct mount path, symlink target, or staged copy
- read/write mode

For data assets under `input/`, the preferred mapping is direct access through the mounted `CROCO_EXPERIMENTS` tree. Symlinks are allowed when needed, but the symlink must point back to the canonical file under `input/`.

## Content provenance

Every finding must be traceable to evidence.

Provenance records must include:

- artifact path
- parser or detection rule
- key, symbol, or line reference when available
- classification, warning, or capability affected

Generated files must identify their generated origin. User-provided files under `input/` must never be relabeled as generated.

## Ambiguity reporting

An ambiguity record must include:

- `id`
- `scope`
- `description`
- `evidence`
- `candidate_interpretations`
- `impact`
- `recommended_resolution`
- `override_allowed`
- `strict_policy_effect`

Ambiguity must be surfaced in dry-run. It is a warning/reporting finding by default and a hard blocker only when strict policy requires it or when the ambiguity prevents construction of the requested staging/mounting plan.

## Finding reporting

A finding record for possible mismatches, contradictions, ambiguities, or suspicious combinations must include:

- `id`
- `compile_time_evidence`
- `runtime_evidence`
- `description`
- `impact`
- `recommended_review`
- `strict_policy_effect`

Examples:

- Runtime requests an external forcing file while compile-time evidence appears analytical.
- Runtime references a capability that compile-time findings did not observe.

Possible mismatches, contradictions, ambiguities, and suspicious combinations are reported findings. They do not block compile or run by default because the builder is not a CROCO semantic validator.

## Infrastructural blocker reporting

An infrastructural blocker record must include:

- `id`
- `category`
- `description`
- `evidence`
- `required_resolution`

Blocker categories:

- `missing_artifact`
- `missing_binary`
- `metadata_or_staging`
- `mounting_plan`
- `docker_backend`
- `compile_failure`
- `run_failure`
- `strict_policy`

Only infrastructural blockers hard-fail by default.

## Snapshot policy

Snapshots are generated under:

```text
CROCO_EXPERIMENTS/<experiment_name>/runs/<run_id>/snapshots/
```

Compile-specific snapshots may also be referenced from `build/` metadata, but run reproducibility snapshots belong under the run directory.

Snapshots must include:

- effective `croco.in`
- effective `cppdefs.h`
- effective `param.h`
- effective `analytical.F`, when staged or used
- manifest copy or manifest hash
- asset inventory
- host path to container path mappings
- Docker image identifier
- command summary
- log references

Snapshots must not duplicate runtime data assets such as `.nc` files during normal workflow. They should record path, size, hash when practical, and mapping.

## Separate compile-time and runtime records

Compile-time findings and runtime findings must remain separate in the manifest.

The asset classification layer may refer to both, but it must preserve the chain of reasoning:

```text
compile_time finding -> runtime reference -> asset classification -> report finding
```

The manifest must support explaining why a traditional key such as `GRD_FILE`, `INI_FILE`, or `FRC_FILE` is classified as required, optional, ignored, or ambiguous for this specific builder attempt. Their mere presence in `croco.in` is not sufficient to mark them required for staging/mounting.

## User overrides

Overrides must be explicit, host-side, and recorded in the manifest.

An override may:

- choose between ambiguous asset roles
- supply a missing path mapping
- mark a runtime reference as intentionally not selected for staging/mounting when parser-level evidence cannot resolve it
- select Docker image or backend settings
- enable strict policy

An override may not:

- move or duplicate `.nc` runtime data out of `input/` as normal workflow
- relabel generated files as user evidence
- suppress command logs or failure records
- convert an absent file classified as required for staging/mounting into a successful mounted asset
