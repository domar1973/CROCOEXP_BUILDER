# Acceptance Tests

## Test policy

This document defines acceptance tests only. It does not specify implementation code.

All tests assume:

- commands are launched from the host
- Docker is only the execution backend
- Docker mounts the whole `CROCO_EXPERIMENTS` directory
- user-provided evidence lives under `CROCO_EXPERIMENTS/<experiment_name>/input/`
- generated metadata, build products, reports, logs, snapshots, and outputs live outside `input/`
- `.nc` and similar runtime data assets remain in `input/`
- the builder reports artifact-level findings but does not prove scientific or semantic correctness
- only infrastructural blockers hard-fail by default
- “required” means required for the builder’s staging/mounting plan, not proof of CROCO scientific necessity
- registered compile sources live under `CROCO_EXPERIMENTS/sources/<source_id>/`
- `.crocoexp/sources.json` records repo-level source registry state
- compile source selection is per experiment, not a setup-level global version

## 1. Import minimal experiment from `input/`

### Initial filesystem setup

```text
CROCO_EXPERIMENTS/minimal/input/croco.in
CROCO_EXPERIMENTS/minimal/input/cppdefs.h
CROCO_EXPERIMENTS/minimal/input/param.h
```

### Command invoked

```text
crocoexp import minimal
```

### Expected classification result

- Primary artifacts are classified as user-provided evidence.
- Runtime assets referenced by `croco.in` are classified for reporting and staging.
- No asset is required solely because it is named `GRD_FILE`, `INI_FILE`, or `FRC_FILE`.

### Expected generated paths

```text
CROCO_EXPERIMENTS/minimal/metadata/manifest.json
CROCO_EXPERIMENTS/minimal/metadata/import_report.md
CROCO_EXPERIMENTS/minimal/build/
CROCO_EXPERIMENTS/minimal/runs/
```

### Expected success/failure

Success with exit code `0`, possibly with warnings.

### Expected diagnostic summary

Diagnostics name the three primary artifacts, report asset classification counts, and state that metadata was generated outside `input/`.

## 2. Import experiment with optional `analytical.F`

### Initial filesystem setup

```text
CROCO_EXPERIMENTS/analytical_optional/input/croco.in
CROCO_EXPERIMENTS/analytical_optional/input/cppdefs.h
CROCO_EXPERIMENTS/analytical_optional/input/param.h
CROCO_EXPERIMENTS/analytical_optional/input/analytical.F
```

### Command invoked

```text
crocoexp import analytical_optional
```

### Expected classification result

- `analytical.F` is recorded as present in `input/`.
- Its status is recorded as appears relevant, staged candidate, not staged, or ambiguous.
- Presence alone does not force analytical behavior or prove semantic correctness.

### Expected generated paths

```text
CROCO_EXPERIMENTS/analytical_optional/metadata/manifest.json
CROCO_EXPERIMENTS/analytical_optional/metadata/import_report.md
```

### Expected success/failure

Success with exit code `0`, unless primary artifact parsing fails.

### Expected diagnostic summary

Diagnostics explain what was observed about `analytical.F` and cite compile-time evidence.

## 3. Compile from host through Docker

### Initial filesystem setup

```text
CROCO_EXPERIMENTS/compile_ok/input/croco.in
CROCO_EXPERIMENTS/compile_ok/input/cppdefs.h
CROCO_EXPERIMENTS/compile_ok/input/param.h
CROCO_EXPERIMENTS/compile_ok/metadata/manifest.json
CROCO_EXPERIMENTS/sources/croco-v2.1.2/
.crocoexp/sources.json
```

The manifest contains `compile_time.source_ref.source_id: croco-v2.1.2`.

### Command invoked

```text
crocoexp compile compile_ok
```

### Expected classification result

- Compile-time artifacts are recorded as inputs to the attempt.
- The compile source is resolved from `compile_time.source_ref`.
- Runtime `.nc` data assets, if any, remain in `input/` and are not copied to `build/`.
- `analytical.F` is staged only when artifact-level evidence or user policy says it should be staged.
- Runtime warnings do not block compile by default.

### Expected generated paths

```text
CROCO_EXPERIMENTS/compile_ok/build/stage/
CROCO_EXPERIMENTS/compile_ok/build/logs/
CROCO_EXPERIMENTS/compile_ok/build/output/
CROCO_EXPERIMENTS/compile_ok/metadata/compile_report.md
```

### Expected success/failure

Success with exit code `0` when Docker and CROCO compilation succeed. Failure uses exit code `7` for Docker/backend failure or `8` for compile failure.

### Expected diagnostic summary

Diagnostics show Docker image, compile artifacts used, staging decisions, build log path, generated binary/build product path on success, and no instruction requiring container entry.
Diagnostics also show the registered source id and installed source path.

## 4. Dry-run from host

### Initial filesystem setup

```text
CROCO_EXPERIMENTS/dry_run_ok/input/croco.in
CROCO_EXPERIMENTS/dry_run_ok/input/cppdefs.h
CROCO_EXPERIMENTS/dry_run_ok/input/param.h
CROCO_EXPERIMENTS/dry_run_ok/build/output/<binary>
CROCO_EXPERIMENTS/dry_run_ok/metadata/manifest.json
```

### Command invoked

```text
crocoexp dry-run dry_run_ok
```

### Expected classification result

- Required, optional, ignored, and ambiguous staging/mounting classifications are reported.
- Assets selected for staging/mounting have host path to container path mappings.
- Possible semantic mismatches, contradictions, and ambiguities are reported as findings, not hard failures by default.

### Expected generated paths

```text
CROCO_EXPERIMENTS/dry_run_ok/runs/<run_id>/reports/dry_run_report.md
CROCO_EXPERIMENTS/dry_run_ok/runs/<run_id>/snapshots/
CROCO_EXPERIMENTS/dry_run_ok/metadata/report.md
```

### Expected success/failure

Success with exit code `0` when required artifacts/assets for staging/mounting are present, even if warnings are reported.

### Expected diagnostic summary

Diagnostics include binary status, asset classifications with reasons, warnings/findings, Docker or host-only reporting summary, and report path.

## 5. Run from host through Docker

### Initial filesystem setup

```text
CROCO_EXPERIMENTS/run_ok/input/croco.in
CROCO_EXPERIMENTS/run_ok/input/cppdefs.h
CROCO_EXPERIMENTS/run_ok/input/param.h
CROCO_EXPERIMENTS/run_ok/build/output/<binary>
CROCO_EXPERIMENTS/run_ok/metadata/manifest.json
CROCO_EXPERIMENTS/run_ok/runs/<run_id>/reports/dry_run_report.md
```

### Command invoked

```text
crocoexp run run_ok --run-id <run_id>
```

### Expected classification result

- The run uses recorded metadata or refreshes artifact-level checks before execution.
- Assets selected for mounting are mounted from `input/`.
- Warnings or possible semantic findings may be carried into the run record.
- No run output is classified as user input.

### Expected generated paths

```text
CROCO_EXPERIMENTS/run_ok/runs/<run_id>/logs/
CROCO_EXPERIMENTS/run_ok/runs/<run_id>/output/
CROCO_EXPERIMENTS/run_ok/runs/<run_id>/snapshots/
CROCO_EXPERIMENTS/run_ok/runs/<run_id>/reports/
```

### Expected success/failure

Success with exit code `0` when required files exist, a binary exists, Docker execution succeeds, and CROCO exits successfully.

### Expected diagnostic summary

Diagnostics show run id, Docker image, binary used, selected mappings, warnings/findings, log path, output path, snapshot path, and final exit status.

## 6. Analytical-style experiment without external grid, init, or forcing files

### Initial filesystem setup

```text
CROCO_EXPERIMENTS/analytical_no_external/input/croco.in
CROCO_EXPERIMENTS/analytical_no_external/input/cppdefs.h
CROCO_EXPERIMENTS/analytical_no_external/input/param.h
CROCO_EXPERIMENTS/analytical_no_external/input/analytical.F
```

`croco.in` may contain traditional file keys with placeholder values.

### Command invoked

```text
crocoexp dry-run analytical_no_external
```

### Expected classification result

- Analytical-looking compile-time findings are recorded.
- Placeholder or parser-level non-selected `GRD_FILE`, `INI_FILE`, and `FRC_FILE` references are classified as ignored, optional, or ambiguous, not required by name alone.
- The report does not claim scientific or semantic correctness.

### Expected generated paths

```text
CROCO_EXPERIMENTS/analytical_no_external/metadata/manifest.json
CROCO_EXPERIMENTS/analytical_no_external/runs/<run_id>/reports/dry_run_report.md
```

### Expected success/failure

Success with exit code `0` if no infrastructural blocker exists.

### Expected diagnostic summary

Diagnostics explain why external grid, initial condition, and forcing files were not classified as required for staging/mounting by artifact-level classification.

## 7. External-data experiment with grid, init, and forcing files

### Initial filesystem setup

```text
CROCO_EXPERIMENTS/external_data/input/croco.in
CROCO_EXPERIMENTS/external_data/input/cppdefs.h
CROCO_EXPERIMENTS/external_data/input/param.h
CROCO_EXPERIMENTS/external_data/input/grid.nc
CROCO_EXPERIMENTS/external_data/input/init.nc
CROCO_EXPERIMENTS/external_data/input/forcing.nc
```

`croco.in` references the three `.nc` assets in a way the builder classifies as required for staging/mounting in the run attempt.

### Command invoked

```text
crocoexp dry-run external_data
```

### Expected classification result

- `grid.nc` is classified as required for staging/mounting.
- `init.nc` is classified as required for staging/mounting.
- `forcing.nc` is classified as required for staging/mounting.
- All data assets classified as required have host path to container path mappings.
- All data assets classified as required use copy policy `remain_in_input`.

### Expected generated paths

```text
CROCO_EXPERIMENTS/external_data/metadata/manifest.json
CROCO_EXPERIMENTS/external_data/runs/<run_id>/reports/dry_run_report.md
```

### Expected success/failure

Success with exit code `0`.

### Expected diagnostic summary

Diagnostics identify each external asset classified as required for staging/mounting and cite the runtime references and artifact-level evidence.

## 8. Referenced assets remain in `input/`

### Initial filesystem setup

```text
CROCO_EXPERIMENTS/assets_in_input/input/croco.in
CROCO_EXPERIMENTS/assets_in_input/input/cppdefs.h
CROCO_EXPERIMENTS/assets_in_input/input/param.h
CROCO_EXPERIMENTS/assets_in_input/input/grid.nc
```

`croco.in` references `grid.nc`.

### Command invoked

```text
crocoexp dry-run assets_in_input
```

### Expected classification result

- `grid.nc` is classified as required, optional, ignored, or ambiguous according to artifact-level evidence.
- If selected for staging/mounting, its canonical host path remains under `input/`.
- The manifest records host path to container path mapping.

### Expected generated paths

```text
CROCO_EXPERIMENTS/assets_in_input/metadata/manifest.json
CROCO_EXPERIMENTS/assets_in_input/runs/<run_id>/reports/dry_run_report.md
```

No copy of `grid.nc` is expected under `build/`, `metadata/`, or `runs/`.

### Expected success/failure

Success if the asset exists when classified as required for staging/mounting and no other infrastructural blocker exists.

### Expected diagnostic summary

Diagnostics state that the data asset remains in `input/` and is accessed through Docker mount mapping.

## 9. Build stages config/code files but leaves `.nc` data in `input/`

### Initial filesystem setup

```text
CROCO_EXPERIMENTS/stage_policy/input/croco.in
CROCO_EXPERIMENTS/stage_policy/input/cppdefs.h
CROCO_EXPERIMENTS/stage_policy/input/param.h
CROCO_EXPERIMENTS/stage_policy/input/analytical.F
CROCO_EXPERIMENTS/stage_policy/input/grid.nc
```

### Command invoked

```text
crocoexp compile stage_policy
```

### Expected classification result

- Compile-relevant config/code files may be staged into `build/stage/`.
- `grid.nc` remains only in `input/`.
- Manifest records `grid.nc` with copy policy `remain_in_input`.

### Expected generated paths

```text
CROCO_EXPERIMENTS/stage_policy/build/stage/
CROCO_EXPERIMENTS/stage_policy/build/logs/
CROCO_EXPERIMENTS/stage_policy/build/output/
```

### Expected success/failure

Success with exit code `0` if Docker and compilation succeed.

### Expected diagnostic summary

Diagnostics list staged compile files and explicitly state that runtime data files were not duplicated.

## 10. Possible compile/runtime mismatch is reported, not blocked by default

### Initial filesystem setup

```text
CROCO_EXPERIMENTS/possible_mismatch/input/croco.in
CROCO_EXPERIMENTS/possible_mismatch/input/cppdefs.h
CROCO_EXPERIMENTS/possible_mismatch/input/param.h
CROCO_EXPERIMENTS/possible_mismatch/input/forcing.nc
```

`croco.in` requests an external forcing file. Compile-time findings appear analytical or do not clearly show the corresponding capability.

### Command invoked

```text
crocoexp dry-run possible_mismatch
```

### Expected classification result

- The forcing reference is recorded.
- Metadata records a possible mismatch with compile-time and runtime evidence.
- The finding is reported as a warning by default.

### Expected generated paths

```text
CROCO_EXPERIMENTS/possible_mismatch/metadata/manifest.json
CROCO_EXPERIMENTS/possible_mismatch/metadata/report.md
CROCO_EXPERIMENTS/possible_mismatch/runs/<run_id>/reports/dry_run_report.md
```

### Expected success/failure

Success with exit code `0` if assets classified as required for staging/mounting exist and no infrastructural blocker exists. With explicit `--strict`, failure with exit code `5` is acceptable.

### Expected diagnostic summary

Diagnostics cite the runtime request, the compile-time finding, and state that this is a reported possible mismatch, not a default hard blocker.

## 11. Ambiguous asset classification is reported

### Initial filesystem setup

```text
CROCO_EXPERIMENTS/ambiguous/input/croco.in
CROCO_EXPERIMENTS/ambiguous/input/cppdefs.h
CROCO_EXPERIMENTS/ambiguous/input/param.h
CROCO_EXPERIMENTS/ambiguous/input/data.nc
```

The artifacts reference `data.nc` in a way that could map to more than one builder-level role, or parser evidence cannot determine whether the reference should be selected for staging/mounting.

### Command invoked

```text
crocoexp dry-run ambiguous
```

### Expected classification result

- `data.nc` is classified as ambiguous.
- Manifest records candidate interpretations and recommended resolution.
- No silent guess is made.

### Expected generated paths

```text
CROCO_EXPERIMENTS/ambiguous/metadata/manifest.json
CROCO_EXPERIMENTS/ambiguous/runs/<run_id>/reports/dry_run_report.md
```

### Expected success/failure

Success with exit code `0` if the ambiguity does not prevent construction of the requested staging/mounting plan. With explicit `--strict`, failure with exit code `5` is acceptable.

### Expected diagnostic summary

Diagnostics explain the ambiguity, show evidence, and indicate that a host-side override or artifact correction can clarify it.

## 12. Missing required asset with precise diagnostic

### Initial filesystem setup

```text
CROCO_EXPERIMENTS/missing_asset/input/croco.in
CROCO_EXPERIMENTS/missing_asset/input/cppdefs.h
CROCO_EXPERIMENTS/missing_asset/input/param.h
```

`croco.in` references `forcing.nc` in a way the builder classifies as required for staging/mounting in the attempted run, but `input/forcing.nc` does not exist.

### Command invoked

```text
crocoexp dry-run missing_asset
```

### Expected classification result

- `forcing.nc` is classified as required for staging/mounting.
- Manifest records `exists: false`.
- Reporting status records `blocked_missing_artifact`.

### Expected generated paths

```text
CROCO_EXPERIMENTS/missing_asset/metadata/manifest.json
CROCO_EXPERIMENTS/missing_asset/metadata/report.md
CROCO_EXPERIMENTS/missing_asset/runs/<run_id>/reports/dry_run_report.md
```

### Expected success/failure

Failure with exit code `3`.

### Expected diagnostic summary

Diagnostics name `forcing.nc`, show the expected host path under `input/`, cite the `croco.in` key that led to the staging/mounting classification, and identify the failure as a missing required artifact.

## 13. Successful run writes outputs outside `input/`

### Initial filesystem setup

```text
CROCO_EXPERIMENTS/output_policy/input/croco.in
CROCO_EXPERIMENTS/output_policy/input/cppdefs.h
CROCO_EXPERIMENTS/output_policy/input/param.h
CROCO_EXPERIMENTS/output_policy/input/grid.nc
CROCO_EXPERIMENTS/output_policy/input/init.nc
CROCO_EXPERIMENTS/output_policy/input/forcing.nc
CROCO_EXPERIMENTS/output_policy/build/output/<binary>
```

### Command invoked

```text
crocoexp run output_policy
```

### Expected classification result

- Input data assets remain canonical under `input/`.
- Generated run outputs are classified as generated output, not user evidence.

### Expected generated paths

```text
CROCO_EXPERIMENTS/output_policy/runs/<run_id>/logs/
CROCO_EXPERIMENTS/output_policy/runs/<run_id>/output/
CROCO_EXPERIMENTS/output_policy/runs/<run_id>/snapshots/
CROCO_EXPERIMENTS/output_policy/runs/<run_id>/reports/
```

No generated output is expected under:

```text
CROCO_EXPERIMENTS/output_policy/input/
```

### Expected success/failure

Success with exit code `0` if Docker and CROCO execution succeed.

### Expected diagnostic summary

Diagnostics show log and output paths under `runs/<run_id>/` and confirm no output was written to `input/`.

## 14. Reproducibility snapshot includes effective config and asset inventory

### Initial filesystem setup

```text
CROCO_EXPERIMENTS/snapshot_ok/input/croco.in
CROCO_EXPERIMENTS/snapshot_ok/input/cppdefs.h
CROCO_EXPERIMENTS/snapshot_ok/input/param.h
CROCO_EXPERIMENTS/snapshot_ok/input/analytical.F
CROCO_EXPERIMENTS/snapshot_ok/input/grid.nc
CROCO_EXPERIMENTS/snapshot_ok/build/output/<binary>
```

### Command invoked

```text
crocoexp run snapshot_ok
```

### Expected classification result

- Effective config/code artifacts are included in the snapshot.
- Asset inventory selected for staging/mounting is included in the snapshot.
- Runtime data assets are represented by path, mapping, size, and hash when practical, not duplicated.

### Expected generated paths

```text
CROCO_EXPERIMENTS/snapshot_ok/runs/<run_id>/snapshots/croco.in
CROCO_EXPERIMENTS/snapshot_ok/runs/<run_id>/snapshots/cppdefs.h
CROCO_EXPERIMENTS/snapshot_ok/runs/<run_id>/snapshots/param.h
CROCO_EXPERIMENTS/snapshot_ok/runs/<run_id>/snapshots/analytical.F
CROCO_EXPERIMENTS/snapshot_ok/runs/<run_id>/snapshots/manifest.json
CROCO_EXPERIMENTS/snapshot_ok/runs/<run_id>/snapshots/asset_inventory.json
```

`analytical.F` is expected only when staged or used by the effective workflow.

### Expected success/failure

Success with exit code `0` if Docker and CROCO execution succeed.

### Expected diagnostic summary

Diagnostics show snapshot path and confirm the snapshot contains effective configuration, asset inventory, Docker image identifier, command summary, and host path to container path mappings.

## 15. Source install for official CROCO tree

### Initial filesystem setup

```text
/tmp/source_origins/croco-v2.1.2/
CROCO_EXPERIMENTS/
```

The origin path contains a plausible CROCO source tree.

### Command invoked

```text
crocoexp source install /tmp/source_origins/croco-v2.1.2 --id croco-v2.1.2 --flavor croco --declared-version v2.1.2
```

### Expected classification result

- The source is registered as compile infrastructure.
- The source is not treated as experiment `input/` evidence.
- No semantic claim is made about whether this source can compile a given experiment.

### Expected generated paths

```text
CROCO_EXPERIMENTS/sources/croco-v2.1.2/
.crocoexp/sources.json
```

### Expected success/failure

Success with exit code `0` if copy and registry writing succeed.

### Expected diagnostic summary

Diagnostics show source id, flavor, declared version, origin path, installed path, and registry path.

## 16. Source install for MSOT tree

### Initial filesystem setup

```text
/tmp/source_origins/msot-main/
CROCO_EXPERIMENTS/
```

### Command invoked

```text
crocoexp source install /tmp/source_origins/msot-main --id msot-main --flavor msot
```

### Expected classification result

- The source is registered with flavor `msot`.
- MSOT is accepted as a registered compile source, not forced into an official CROCO version category.

### Expected generated paths

```text
CROCO_EXPERIMENTS/sources/msot-main/
.crocoexp/sources.json
```

### Expected success/failure

Success with exit code `0` if copy and registry writing succeed.

### Expected diagnostic summary

Diagnostics show that MSOT is registered as compile infrastructure and not as global setup state.

## 17. Source list returns registered IDs

### Initial filesystem setup

```text
.crocoexp/sources.json
CROCO_EXPERIMENTS/sources/croco-v2.1.2/
CROCO_EXPERIMENTS/sources/msot-main/
```

### Command invoked

```text
crocoexp source list
```

### Expected classification result

- Registered sources are listed by `source_id`.
- No experiment metadata is modified.

### Expected generated paths

No generated paths.

### Expected success/failure

Success with exit code `0`.

### Expected diagnostic summary

Diagnostics list `croco-v2.1.2` and `msot-main` with installed paths, flavor, declared version when known, and install timestamp.

## 18. Source inspect returns detailed metadata

### Initial filesystem setup

```text
.crocoexp/sources.json
CROCO_EXPERIMENTS/sources/croco-v2.1.2/
```

### Command invoked

```text
crocoexp source inspect croco-v2.1.2
```

### Expected classification result

- Source registry metadata is displayed.
- The command remains read-only.

### Expected generated paths

No generated paths.

### Expected success/failure

Success with exit code `0`.

### Expected diagnostic summary

Diagnostics show source id, flavor, declared version, installed host path, origin path, git metadata when available, detected layout, and content identity when practical.

## 19. Import with `--source` records `compile_time.source_ref`

### Initial filesystem setup

```text
CROCO_EXPERIMENTS/import_with_source/input/croco.in
CROCO_EXPERIMENTS/import_with_source/input/cppdefs.h
CROCO_EXPERIMENTS/import_with_source/input/param.h
CROCO_EXPERIMENTS/sources/croco-v2.1.2/
.crocoexp/sources.json
```

### Command invoked

```text
crocoexp import import_with_source --source croco-v2.1.2
```

### Expected classification result

- `compile_time.source_ref.source_id` is `croco-v2.1.2`.
- The source is recorded as compile input traceability.
- The source tree is not copied into `input/`.

### Expected generated paths

```text
CROCO_EXPERIMENTS/import_with_source/metadata/manifest.json
CROCO_EXPERIMENTS/import_with_source/metadata/import_report.md
```

### Expected success/failure

Success with exit code `0`.

### Expected diagnostic summary

Diagnostics show the selected source id, flavor, declared version, and installed host path.

## 20. Compile uses `source_ref` from manifest

### Initial filesystem setup

```text
CROCO_EXPERIMENTS/compile_source_ref/input/croco.in
CROCO_EXPERIMENTS/compile_source_ref/input/cppdefs.h
CROCO_EXPERIMENTS/compile_source_ref/input/param.h
CROCO_EXPERIMENTS/compile_source_ref/metadata/manifest.json
CROCO_EXPERIMENTS/sources/croco-v2.1.2/
.crocoexp/sources.json
```

The manifest contains `compile_time.source_ref.source_id: croco-v2.1.2`.

### Command invoked

```text
crocoexp compile compile_source_ref
```

### Expected classification result

- Compile resolves the source from manifest `compile_time.source_ref`.
- Compile reports the registered source as an input.
- The registered source is read as compile infrastructure.

### Expected generated paths

```text
CROCO_EXPERIMENTS/compile_source_ref/build/stage/
CROCO_EXPERIMENTS/compile_source_ref/build/logs/
CROCO_EXPERIMENTS/compile_source_ref/build/output/
CROCO_EXPERIMENTS/compile_source_ref/metadata/compile_report.md
```

### Expected success/failure

Success with exit code `0` when Docker and compilation succeed.

### Expected diagnostic summary

Diagnostics show the source id, installed path, Docker image, staged files, and build log path.

## 21. Compile no longer depends on a global version variable

### Initial filesystem setup

```text
CROCO_EXPERIMENTS/no_global_version/input/croco.in
CROCO_EXPERIMENTS/no_global_version/input/cppdefs.h
CROCO_EXPERIMENTS/no_global_version/input/param.h
CROCO_EXPERIMENTS/no_global_version/metadata/manifest.json
CROCO_EXPERIMENTS/sources/custom-fork/
.crocoexp/sources.json
.crocoexp/config.json
```

The setup config contains only Docker backend image state. The manifest contains `compile_time.source_ref.source_id: custom-fork`.

### Command invoked

```text
crocoexp compile no_global_version
```

### Expected classification result

- Compile uses `custom-fork` from the experiment manifest.
- Compile does not read a setup-level CROCO version/source setting.

### Expected generated paths

```text
CROCO_EXPERIMENTS/no_global_version/metadata/compile_report.md
```

### Expected success/failure

Success with exit code `0` when Docker and compilation succeed.

### Expected diagnostic summary

Diagnostics show the experiment-specific source id and Docker image separately.

## 22. Source tree is copied under `CROCO_EXPERIMENTS/sources/<source_id>/`

### Initial filesystem setup

```text
/tmp/source_origins/custom-fork/
CROCO_EXPERIMENTS/
```

### Command invoked

```text
crocoexp source install /tmp/source_origins/custom-fork --id custom-fork --flavor custom
```

### Expected classification result

- The registered source is a copied managed source tree.
- The normal workflow does not register an external symlink as the main source mechanism.

### Expected generated paths

```text
CROCO_EXPERIMENTS/sources/custom-fork/
.crocoexp/sources.json
```

### Expected success/failure

Success with exit code `0`.

### Expected diagnostic summary

Diagnostics show source copy destination under `CROCO_EXPERIMENTS/sources/custom-fork/`.

## 23. Registered source is treated as read-only compile input

### Initial filesystem setup

```text
CROCO_EXPERIMENTS/source_readonly/input/croco.in
CROCO_EXPERIMENTS/source_readonly/input/cppdefs.h
CROCO_EXPERIMENTS/source_readonly/input/param.h
CROCO_EXPERIMENTS/source_readonly/metadata/manifest.json
CROCO_EXPERIMENTS/sources/croco-v2.1.2/
.crocoexp/sources.json
```

### Command invoked

```text
crocoexp compile source_readonly
```

### Expected classification result

- Source files are read or copied into generated build staging as needed.
- Build products and generated files are written under the experiment `build/`.
- The registered source tree is not modified as part of normal compile.

### Expected generated paths

```text
CROCO_EXPERIMENTS/source_readonly/build/stage/
CROCO_EXPERIMENTS/source_readonly/build/output/
```

No generated file is expected under:

```text
CROCO_EXPERIMENTS/sources/croco-v2.1.2/
```

### Expected success/failure

Success with exit code `0` when Docker and compilation succeed.

### Expected diagnostic summary

Diagnostics distinguish registered source input from generated build outputs.

## 24. Unknown source id in import fails clearly

### Initial filesystem setup

```text
CROCO_EXPERIMENTS/unknown_source/input/croco.in
CROCO_EXPERIMENTS/unknown_source/input/cppdefs.h
CROCO_EXPERIMENTS/unknown_source/input/param.h
.crocoexp/sources.json
```

`missing-source` is not registered.

### Command invoked

```text
crocoexp import unknown_source --source missing-source
```

### Expected classification result

- No `compile_time.source_ref` is recorded as successfully resolved.
- The failure is categorized as source registry or metadata/staging infrastructure, not semantic validation.

### Expected generated paths

No successful manifest is required. If a failure report is written, it must live under `metadata/` and not under `input/`.

### Expected success/failure

Failure with exit code `4` or another implementation-defined registry resolution code documented in the CLI contract.

### Expected diagnostic summary

Diagnostics name `missing-source`, identify `.crocoexp/sources.json`, and explain that the source id is not registered.
