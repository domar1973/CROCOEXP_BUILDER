# Acceptance Tests

## Test policy

This document defines acceptance tests only. It does not specify implementation code.

All tests assume:

- commands are launched from the host
- Docker is only the execution backend
- Docker mounts the whole `CROCO_EXPERIMENTS` directory
- user-provided evidence lives under `CROCO_EXPERIMENTS/<experiment_name>/input/`
- generated metadata, build products, workdirs, reports, logs, snapshots, and outputs live outside `input/`
- `.nc`, `.nc4`, `.cdf`, and similar runtime data assets remain canonical in `input/`
- NetCDF-like runtime data assets are exposed to CROCO by relative symlinks created in `runs/<run_id>/work/`
- `croco.in` is treated as version-specific CROCO syntax and is not parsed as universal semantic truth
- `run.env` is not supported and is ignored if present
- the builder reports artifact-level findings but does not prove scientific or semantic correctness
- only infrastructural blockers hard-fail by default
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
crocoexp import minimal --source croco-local
```

### Expected result

- Primary artifacts are classified as user-provided evidence.
- No runtime data asset is required solely because of a key name in `croco.in`.
- No semantic asset parser is required for success.
- Metadata is generated outside `input/`.

### Expected generated paths

```text
CROCO_EXPERIMENTS/minimal/metadata/manifest.json
CROCO_EXPERIMENTS/minimal/metadata/import_report.md
CROCO_EXPERIMENTS/minimal/build/
CROCO_EXPERIMENTS/minimal/runs/
```

### Expected success/failure

Success with exit code `0`, possibly with warnings.

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
crocoexp import analytical_optional --source croco-v2.1.3
```

### Expected result

- `analytical.F` is recorded as present in `input/`.
- Its status is recorded as appears relevant, staged candidate, not staged, or ambiguous.
- Presence alone does not force analytical behavior or prove semantic correctness.

### Expected success/failure

Success with exit code `0`, unless primary artifact parsing fails.

## 3. Compile from host through Docker

### Initial filesystem setup

```text
CROCO_EXPERIMENTS/compile_ok/input/croco.in
CROCO_EXPERIMENTS/compile_ok/input/cppdefs.h
CROCO_EXPERIMENTS/compile_ok/input/param.h
CROCO_EXPERIMENTS/compile_ok/metadata/manifest.json
CROCO_EXPERIMENTS/sources/croco-v2.1.3/
.crocoexp/sources.json
```

The manifest contains `compile_time.source_ref.source_id: croco-v2.1.3`.

### Command invoked

```text
crocoexp compile compile_ok
```

### Expected result

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

## 4. Dry-run reports version-agnostic runtime input contract

### Initial filesystem setup

```text
CROCO_EXPERIMENTS/dry_run_ok/input/croco.in
CROCO_EXPERIMENTS/dry_run_ok/input/cppdefs.h
CROCO_EXPERIMENTS/dry_run_ok/input/param.h
CROCO_EXPERIMENTS/dry_run_ok/input/GRD/grid.nc
CROCO_EXPERIMENTS/dry_run_ok/input/INIT/init.nc
CROCO_EXPERIMENTS/dry_run_ok/build/output/croco
CROCO_EXPERIMENTS/dry_run_ok/metadata/manifest.json
```

### Command invoked

```text
crocoexp dry-run dry_run_ok
```

### Expected result

- Dry-run reports planned workdir.
- Dry-run reports materialization policy `copy_config_symlink_netcdf`.
- Dry-run lists `GRD/grid.nc` and `INIT/init.nc` as NetCDF-like runtime data assets to symlink.
- Dry-run does not classify the assets as ambiguous merely because `croco.in` syntax is unknown.
- Dry-run does not require a semantic parser for `croco.in`.

### Expected generated paths

```text
CROCO_EXPERIMENTS/dry_run_ok/runs/<run_id>/reports/dry_run_report.md
CROCO_EXPERIMENTS/dry_run_ok/runs/<run_id>/snapshots/
CROCO_EXPERIMENTS/dry_run_ok/metadata/report.md
```

### Expected success/failure

Success with exit code `0` when primary artifacts and binary exist.

## 5. Run creates workdir and NetCDF symlinks

### Initial filesystem setup

```text
CROCO_EXPERIMENTS/run_ok/input/croco.in
CROCO_EXPERIMENTS/run_ok/input/cppdefs.h
CROCO_EXPERIMENTS/run_ok/input/param.h
CROCO_EXPERIMENTS/run_ok/input/GRD/grid.nc
CROCO_EXPERIMENTS/run_ok/input/INIT/init.nc
CROCO_EXPERIMENTS/run_ok/build/output/croco
CROCO_EXPERIMENTS/run_ok/metadata/manifest.json
```

### Command invoked

```text
crocoexp run run_ok --run-id test_run
```

### Expected result

- `runs/test_run/work/` is created.
- `input/croco.in` is copied to `runs/test_run/work/croco.in`.
- The binary is available as `runs/test_run/work/croco`.
- `runs/test_run/work/GRD/grid.nc` is a relative symlink to `input/GRD/grid.nc`.
- `runs/test_run/work/INIT/init.nc` is a relative symlink to `input/INIT/init.nc`.
- Symlink targets resolve on the host.
- Because Docker mounts the whole `CROCO_EXPERIMENTS` tree, the same relative symlinks resolve inside the container.
- CROCO is executed with working directory set to the container path for `runs/test_run/work/`.

### Expected generated paths

```text
CROCO_EXPERIMENTS/run_ok/runs/test_run/work/
CROCO_EXPERIMENTS/run_ok/runs/test_run/logs/
CROCO_EXPERIMENTS/run_ok/runs/test_run/output/
CROCO_EXPERIMENTS/run_ok/runs/test_run/snapshots/
CROCO_EXPERIMENTS/run_ok/runs/test_run/reports/
```

### Expected success/failure

Success with exit code `0` when Docker execution and CROCO execution succeed. Failure uses exit code `9` when CROCO exits non-zero.

## 6. Analytical-style experiment without external NetCDF files

### Initial filesystem setup

```text
CROCO_EXPERIMENTS/analytical_no_external/input/croco.in
CROCO_EXPERIMENTS/analytical_no_external/input/cppdefs.h
CROCO_EXPERIMENTS/analytical_no_external/input/param.h
CROCO_EXPERIMENTS/analytical_no_external/input/analytical.F
CROCO_EXPERIMENTS/analytical_no_external/build/output/croco
```

### Command invoked

```text
crocoexp dry-run analytical_no_external
```

### Expected result

- Analytical-looking compile-time findings may be recorded.
- No external grid, initial condition, or forcing file is required by CROCOEXP.
- NetCDF symlink count is zero.
- The report does not claim scientific or semantic correctness.

### Expected success/failure

Success with exit code `0` if no infrastructural blocker exists.

## 7. External-data experiment with CROCO v2.1-style `croco.in`

### Initial filesystem setup

```text
CROCO_EXPERIMENTS/external_new/input/croco.in
CROCO_EXPERIMENTS/external_new/input/cppdefs.h
CROCO_EXPERIMENTS/external_new/input/param.h
CROCO_EXPERIMENTS/external_new/input/GRD/mesa_grd.nc
CROCO_EXPERIMENTS/external_new/input/INIT/mesa_ini.nc
CROCO_EXPERIMENTS/external_new/build/output/croco
```

`croco.in` uses syntax such as:

```text
grid: filename
GRD/mesa_grd.nc

initial: NRREC filename
0
INIT/mesa_ini.nc
```

### Command invoked

```text
crocoexp dry-run external_new
```

### Expected result

- Dry-run succeeds without needing to understand `grid:` or `initial:`.
- Both `.nc` files are planned for symlink materialization because they exist under `input/`.
- No asset is reported as ambiguous due to unrecognized CROCO keywords.

### Expected success/failure

Success with exit code `0`.

## 8. External-data experiment with older `GRDNAME`-style `croco.in`

### Initial filesystem setup

```text
CROCO_EXPERIMENTS/external_old/input/croco.in
CROCO_EXPERIMENTS/external_old/input/cppdefs.h
CROCO_EXPERIMENTS/external_old/input/param.h
CROCO_EXPERIMENTS/external_old/input/GRD/grid.nc
CROCO_EXPERIMENTS/external_old/input/INIT/init.nc
CROCO_EXPERIMENTS/external_old/build/output/croco
```

`croco.in` uses syntax such as:

```text
GRDNAME == GRD/grid.nc
ININAME == INIT/init.nc
```

### Command invoked

```text
crocoexp dry-run external_old
```

### Expected result

- Dry-run succeeds without needing to understand `GRDNAME` or `ININAME`.
- Both `.nc` files are planned for symlink materialization.
- Runtime syntax differences do not affect staging.

### Expected success/failure

Success with exit code `0`.

## 9. Referenced assets remain canonical in `input/`

### Initial filesystem setup

```text
CROCO_EXPERIMENTS/assets_in_input/input/croco.in
CROCO_EXPERIMENTS/assets_in_input/input/cppdefs.h
CROCO_EXPERIMENTS/assets_in_input/input/param.h
CROCO_EXPERIMENTS/assets_in_input/input/grid.nc
CROCO_EXPERIMENTS/assets_in_input/build/output/croco
```

### Command invoked

```text
crocoexp run assets_in_input --run-id test_run
```

### Expected result

- `input/grid.nc` remains in `input/`.
- `runs/test_run/work/grid.nc` is a symlink, not a copy.
- No copy of `grid.nc` is created under `build/`, `metadata/`, `runs/test_run/snapshots/`, or `runs/test_run/output/`.
- Manifest records the symlink relationship.

### Expected success/failure

Success when CROCO exits successfully; otherwise run failure with logs preserved.

## 10. Build stages config/code files but leaves `.nc` data in `input/`

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

### Expected result

- Compile-relevant config/code files may be staged into `build/stage/`.
- `grid.nc` remains only in `input/`.
- Manifest records `grid.nc` with materialization policy `symlink_into_workdir`.

### Expected success/failure

Success with exit code `0` if Docker and compilation succeed.

## 11. `run.env` is ignored

### Initial filesystem setup

```text
CROCO_EXPERIMENTS/run_env_ignored/input/croco.in
CROCO_EXPERIMENTS/run_env_ignored/input/cppdefs.h
CROCO_EXPERIMENTS/run_env_ignored/input/param.h
CROCO_EXPERIMENTS/run_env_ignored/input/run.env
CROCO_EXPERIMENTS/run_env_ignored/input/grid.nc
CROCO_EXPERIMENTS/run_env_ignored/build/output/croco
```

`run.env` contains values that would change paths if sourced.

### Command invoked

```text
crocoexp dry-run run_env_ignored
```

### Expected result

- `run.env` is recorded as ignored.
- No value from `run.env` appears in the materialization plan unless it also appears in real evidence independently.
- Diagnostic warning states that `run.env` is unsupported and has no effect.
- No command attempts to source or parse `run.env`.

### Expected success/failure

Success with exit code `0`, possibly with warning.

## 12. Unresolved template tokens are warnings only

### Initial filesystem setup

```text
CROCO_EXPERIMENTS/template_tokens/input/croco.in
CROCO_EXPERIMENTS/template_tokens/input/cppdefs.h
CROCO_EXPERIMENTS/template_tokens/input/param.h
CROCO_EXPERIMENTS/template_tokens/input/grid.nc
CROCO_EXPERIMENTS/template_tokens/build/output/croco
```

`croco.in` contains `${GRD_FILE}`.

### Command invoked

```text
crocoexp dry-run template_tokens
```

### Expected result

- Dry-run reports unresolved template token `${GRD_FILE}` as a warning.
- No substitution is performed.
- NetCDF files under `input/` are still included in the symlink plan.
- Dry-run does not fail by default.

### Expected success/failure

Success with exit code `0`.

## 13. Unsafe symlink target outside `CROCO_EXPERIMENTS` blocks run

### Initial filesystem setup

```text
CROCO_EXPERIMENTS/unsafe_link/input/croco.in
CROCO_EXPERIMENTS/unsafe_link/input/cppdefs.h
CROCO_EXPERIMENTS/unsafe_link/input/param.h
CROCO_EXPERIMENTS/unsafe_link/input/external.nc -> /tmp/external.nc
CROCO_EXPERIMENTS/unsafe_link/build/output/croco
```

### Command invoked

```text
crocoexp dry-run unsafe_link
```

### Expected result

- The input symlink is detected.
- Its resolved target is outside `CROCO_EXPERIMENTS`.
- The materialization plan is blocked because the target would not be guaranteed visible inside Docker.

### Expected success/failure

Failure with exit code `3` or `4`, with precise diagnostic.

## 14. Successful run writes outputs outside `input/`

### Initial filesystem setup

```text
CROCO_EXPERIMENTS/output_policy/input/croco.in
CROCO_EXPERIMENTS/output_policy/input/cppdefs.h
CROCO_EXPERIMENTS/output_policy/input/param.h
CROCO_EXPERIMENTS/output_policy/input/grid.nc
CROCO_EXPERIMENTS/output_policy/build/output/croco
```

### Command invoked

```text
crocoexp run output_policy --run-id test_run
```

### Expected result

- Input data assets remain canonical under `input/`.
- Generated run outputs are classified as generated output, not user evidence.
- Outputs are written under `runs/test_run/output/` or collected there after execution.
- No generated output is written to `input/`.

### Expected generated paths

```text
CROCO_EXPERIMENTS/output_policy/runs/test_run/logs/
CROCO_EXPERIMENTS/output_policy/runs/test_run/output/
CROCO_EXPERIMENTS/output_policy/runs/test_run/snapshots/
CROCO_EXPERIMENTS/output_policy/runs/test_run/reports/
```

## 15. Reproducibility snapshot includes effective config and symlink inventory

### Initial filesystem setup

```text
CROCO_EXPERIMENTS/snapshot_ok/input/croco.in
CROCO_EXPERIMENTS/snapshot_ok/input/cppdefs.h
CROCO_EXPERIMENTS/snapshot_ok/input/param.h
CROCO_EXPERIMENTS/snapshot_ok/input/GRD/grid.nc
CROCO_EXPERIMENTS/snapshot_ok/build/output/croco
```

### Command invoked

```text
crocoexp run snapshot_ok --run-id test_run
```

### Expected result

- Snapshot includes copied `croco.in`, `cppdefs.h`, and `param.h`.
- Snapshot includes selected source reference and binary reference.
- Snapshot includes symlink inventory for `GRD/grid.nc`.
- Snapshot records size and hash of `grid.nc` when practical.
- Snapshot does not copy `grid.nc`.

### Expected success/failure

Success when CROCO exits successfully; otherwise run failure with snapshot preserved if practical.

## 16. Possible compile/runtime mismatch is reported, not blocked by default

### Initial filesystem setup

```text
CROCO_EXPERIMENTS/possible_mismatch/input/croco.in
CROCO_EXPERIMENTS/possible_mismatch/input/cppdefs.h
CROCO_EXPERIMENTS/possible_mismatch/input/param.h
CROCO_EXPERIMENTS/possible_mismatch/input/forcing.nc
CROCO_EXPERIMENTS/possible_mismatch/build/output/croco
```

`croco.in` appears to request an external forcing file. Compile-time findings appear analytical or do not clearly show the corresponding capability.

### Command invoked

```text
crocoexp dry-run possible_mismatch
```

### Expected result

- Metadata may record a possible mismatch with compile-time and runtime evidence.
- The finding is reported as a warning by default.
- `forcing.nc` is included in the symlink plan because it is a NetCDF-like file under `input/`.
- The finding does not block dry-run by default.

### Expected success/failure

Success with exit code `0`.

## 17. Source install for official CROCO tree

### Initial filesystem setup

```text
/tmp/croco-v2.1.3/
```

The source tree exists and is readable.

### Command invoked

```text
crocoexp source install /tmp/croco-v2.1.3 --id croco-v2.1.3 --version v2.1.3
```

### Expected result

- Source tree is copied under `CROCO_EXPERIMENTS/sources/croco-v2.1.3/`.
- `.crocoexp/sources.json` records the source id and metadata.
- No experiment `input/` directory is modified.

### Expected success/failure

Success with exit code `0`.

## 18. Source install rejects non-CROCO legacy registry entries

Legacy registry records that declare non-CROCO source metadata must fail with a clear migration error.

## 19. Source list returns registered IDs

### Initial filesystem setup

```text
CROCO_EXPERIMENTS/sources/croco-v2.1.3/
CROCO_EXPERIMENTS/sources/croco-local/
.crocoexp/sources.json
```

### Command invoked

```text
crocoexp source list
```

### Expected result

- Both source IDs are listed.
- Output includes installed path, declared version, and install timestamp.

### Expected success/failure

Success with exit code `0`.

## 20. Source inspect returns detailed metadata

### Initial filesystem setup

```text
CROCO_EXPERIMENTS/sources/croco-v2.1.3/
.crocoexp/sources.json
```

### Command invoked

```text
crocoexp source inspect croco-v2.1.3
```

### Expected result

- Detailed metadata for `croco-v2.1.3` is printed.
- No experiment directory is modified.

### Expected success/failure

Success with exit code `0`.

## 21. Import with `--source` records `compile_time.source_ref`

### Initial filesystem setup

```text
CROCO_EXPERIMENTS/import_source/input/croco.in
CROCO_EXPERIMENTS/import_source/input/cppdefs.h
CROCO_EXPERIMENTS/import_source/input/param.h
CROCO_EXPERIMENTS/sources/croco-v2.1.3/
.crocoexp/sources.json
```

### Command invoked

```text
crocoexp import import_source --source croco-v2.1.3
```

### Expected result

- Manifest records `compile_time.source_ref.source_id = croco-v2.1.3`.
- Source selection is per experiment.
- No global version variable is written.

### Expected success/failure

Success with exit code `0`.

## 22. Compile uses `source_ref` from manifest

### Initial filesystem setup

```text
CROCO_EXPERIMENTS/compile_source_ref/input/croco.in
CROCO_EXPERIMENTS/compile_source_ref/input/cppdefs.h
CROCO_EXPERIMENTS/compile_source_ref/input/param.h
CROCO_EXPERIMENTS/compile_source_ref/metadata/manifest.json
CROCO_EXPERIMENTS/sources/croco-v2.1.3/
.crocoexp/sources.json
```

Manifest contains `compile_time.source_ref.source_id = croco-v2.1.3`.

### Command invoked

```text
crocoexp compile compile_source_ref
```

### Expected result

- Compile resolves the registered source from manifest.
- Compile report records source id and installed source path.
- No setup-level global source is consulted.

### Expected success/failure

Success with exit code `0` if compilation succeeds; otherwise compile failure with exit code `8`.

## 23. Compile no longer depends on a global version variable

### Initial filesystem setup

```text
CROCO_EXPERIMENTS/no_global_version/input/croco.in
CROCO_EXPERIMENTS/no_global_version/input/cppdefs.h
CROCO_EXPERIMENTS/no_global_version/input/param.h
CROCO_EXPERIMENTS/no_global_version/metadata/manifest.json
CROCO_EXPERIMENTS/sources/croco-source/
.crocoexp/sources.json
```

Manifest selects `croco-source`.

### Command invoked

```text
crocoexp compile no_global_version
```

### Expected result

- Compile uses `croco-source`.
- No global CROCO version is required.
- Diagnostics show selected source id.

### Expected success/failure

Success if compilation succeeds.

## 24. Source tree is copied under `CROCO_EXPERIMENTS/sources/<source_id>/`

### Initial filesystem setup

```text
/tmp/local-croco/
```

### Command invoked

```text
crocoexp source install /tmp/local-croco --id local-croco
```

### Expected result

- Source tree is copied, not symlinked from outside `CROCO_EXPERIMENTS`.
- Installed path is visible under Docker mount.
- Registry records origin path.

### Expected success/failure

Success with exit code `0`.

## 25. Registered source is treated as read-only compile input

### Initial filesystem setup

```text
CROCO_EXPERIMENTS/readonly_source/input/croco.in
CROCO_EXPERIMENTS/readonly_source/input/cppdefs.h
CROCO_EXPERIMENTS/readonly_source/input/param.h
CROCO_EXPERIMENTS/readonly_source/metadata/manifest.json
CROCO_EXPERIMENTS/sources/croco-v2.1.3/
```

### Command invoked

```text
crocoexp compile readonly_source
```

### Expected result

- Compile may stage files under `build/stage/`.
- Registered source tree is not modified.
- Compile report records source read-only assumption.

### Expected success/failure

Success if compilation succeeds.

## 26. Unknown source id in import fails clearly

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

### Expected result

- Command fails clearly.
- Diagnostic names the unknown source id.
- No files under `input/` are modified.

### Expected success/failure

Failure with exit code `5`.

## 27. Import without `--source` in non-interactive mode fails

### Command invoked

```text
crocoexp import import_source
```

### Expected result

- Command fails without writing an incomplete manifest.
- Diagnostic suggests `crocoexp source list`.
- Diagnostic shows `crocoexp import EXP --source <source_id>`.

### Expected success/failure

Failure with exit code `5`.

## 28. Source uninstall with dependents requires force without TTY

### Initial filesystem setup

```text
CROCO_EXPERIMENTS/import_source/metadata/manifest.json
CROCO_EXPERIMENTS/sources/croco-v2.1.3/
.crocoexp/sources.json
```

Manifest references `compile_time.source_ref.source_id = croco-v2.1.3`.

### Command invoked

```text
crocoexp source uninstall croco-v2.1.3
```

### Expected result

- Command reports dependent experiments.
- Source registry is not modified.
- Experiment manifest is not modified.
- Diagnostic suggests rerunning with `--force`.

### Expected success/failure

Failure with exit code `5`.

## 29. Experiment list marks orphaned source references

### Command invoked

```text
crocoexp experiment list
```

### Expected result

- Imported experiments with manifests are listed.
- Source status is `available` when registered.
- Source status is `orphaned` when a manifest references a missing source id.

### Expected success/failure

Success with exit code `0`.

## 30. Experiment unimport preserves input

### Command invoked

```text
crocoexp experiment unimport import_source
```

### Expected result

- `metadata/manifest.json` is removed.
- `input/` remains.
- NetCDF files under `input/` remain.
- Experiment no longer appears as imported in `crocoexp experiment list`.

### Expected success/failure

Success with exit code `0`.

## 31. Compile with previous artifacts requires explicit clean policy

### Initial filesystem setup

```text
CROCO_EXPERIMENTS/compile_source_ref/build/stage/
CROCO_EXPERIMENTS/compile_source_ref/metadata/manifest.json
```

### Command invoked

```text
crocoexp compile compile_source_ref
```

### Expected result

- In non-interactive mode, command fails before staging.
- Diagnostic requests one of:
  - `crocoexp compile compile_source_ref --clean`
  - `crocoexp compile compile_source_ref --no-clean`

### Expected success/failure

Failure with exit code `5`.

## 32. Compile clean removes only build state

### Command invoked

```text
crocoexp compile compile_source_ref --clean
```

### Expected result

- Previous CROCOEXP-managed build artifacts are removed.
- `input/` is preserved.
- `metadata/manifest.json` is preserved.
- Registered source trees are preserved.
- Compile proceeds from a clean build state.

### Expected success/failure

Success with exit code `0` if compilation succeeds; otherwise documented compile or Docker failure.

## 33. Runtime execution plan: OpenMP

- `input/cppdefs.h` defines `OPENMP`.
- `input/param.h` defines `parameter (NPP=8)`.
- Dry-run reports `parallel_backend: openmp`.
- Dry-run reports planned `OMP_NUM_THREADS=8`.
- Run passes `-e OMP_NUM_THREADS=8` to Docker.
- `run_inside_docker.sh` contains `export OMP_NUM_THREADS=8`.
- `run_inside_docker.sh` runs `./croco croco.in`.

## 34. Runtime execution plan: unparsed NPP

- `OPENMP` is active.
- `NPP` cannot be parsed.
- Dry-run warns and plans `OMP_NUM_THREADS=1`.
- Run uses `OMP_NUM_THREADS=1`.

## 35. Runtime execution plan: unsupported MPI

- `cppdefs.h` defines `MPI`.
- `run` fails before Docker execution with an unsupported runtime backend blocker.
- No Docker run is attempted.

## 36. Runtime execution plan: unsupported XIOS

- `cppdefs.h` defines `XIOS`.
- `run` fails before Docker execution with an unsupported runtime backend blocker.
- No Docker run is attempted.
