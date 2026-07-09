import json
import os
import pty
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CLI = REPO_ROOT / "crocoexp"


class CrocoexpTests(unittest.TestCase):
    def make_exp(self, root, name="EXP_A", analytical=False, data=False, croco_text=None):
        exp = root / name
        input_dir = exp / "input"
        input_dir.mkdir(parents=True)
        (input_dir / "croco.in").write_text(croco_text or "TITLE == test\nFRCNAME == forcing.nc\n", encoding="utf-8")
        (input_dir / "cppdefs.h").write_text("#define TEST\n", encoding="utf-8")
        (input_dir / "param.h").write_text("#define LLm 10\n", encoding="utf-8")
        if analytical:
            (input_dir / "analytical.F").write_text("C analytical\n", encoding="utf-8")
        if data:
            (input_dir / "forcing.nc").write_bytes(b"not a real netcdf")
        return exp

    def add_nested_data(self, root, name="EXP_A"):
        input_dir = root / name / "input"
        (input_dir / "GRD").mkdir(parents=True, exist_ok=True)
        (input_dir / "INIT").mkdir(parents=True, exist_ok=True)
        (input_dir / "GRD" / "grid.nc").write_bytes(b"grid")
        (input_dir / "INIT" / "init.nc").write_bytes(b"init")

    def run_cli(self, args, cwd=None, env=None):
        proc_env = os.environ.copy()
        if env:
            proc_env.update(env)
        args = list(args)
        if "--experiments-root" in args and (env is None or "CROCOEXP_REPO_ROOT" not in env):
            exp_root = Path(args[args.index("--experiments-root") + 1])
            if not exp_root.is_absolute():
                exp_root = (Path(cwd or REPO_ROOT) / exp_root).resolve()
            proc_env["CROCOEXP_REPO_ROOT"] = str(exp_root.parent)
        if "import" in args and "--source" not in args and "--help" not in args and proc_env.get("CROCOEXP_TEST_NO_AUTO_SOURCE") != "1":
            exp_root = None
            if "--experiments-root" in args:
                exp_root = Path(args[args.index("--experiments-root") + 1])
            elif cwd:
                exp_root = Path(cwd) / "CROCO_EXPERIMENTS"
            if exp_root is not None:
                if not exp_root.is_absolute():
                    exp_root = (Path(cwd or REPO_ROOT) / exp_root).resolve()
                source_id = "test-auto-source"
                repo = Path(proc_env.get("CROCOEXP_REPO_ROOT") or exp_root.parent)
                proc_env["CROCOEXP_REPO_ROOT"] = str(repo)
                source = exp_root / "sources" / source_id
                ocean = source / "OCEAN"
                ocean.mkdir(parents=True, exist_ok=True)
                (ocean / "jobcomp").write_text("#!/usr/bin/env bash\necho test auto source\n", encoding="utf-8")
                (ocean / "Makefile").write_text("all:\n\t@echo test\n", encoding="utf-8")
                (source / "cppdefs.h").write_text("#define TEST_SOURCE\n", encoding="utf-8")
                (source / "param.h").write_text("parameter (NPP=1)\n", encoding="utf-8")
                registry_path = repo / ".crocoexp" / "sources.json"
                registry_path.parent.mkdir(parents=True, exist_ok=True)
                registry = {"schema_version": 1, "sources": {}}
                if registry_path.exists():
                    registry = json.loads(registry_path.read_text(encoding="utf-8"))
                registry.setdefault("sources", {})[source_id] = {
                    "source_id": source_id,
                    "host_path": str(source),
                    "installed_path": str(source),
                    "container_path": f"/opt/CROCO_EXPERIMENTS/sources/{source_id}",
                    "declared_version": "test-auto",
                    "installed_at": "2026-01-01T00:00:00+00:00",
                    "origin_path": str(source),
                    "status": "installed",
                    "detected_layout": "croco_ocean_subdir",
                }
                registry_path.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                import_index = args.index("import")
                args[import_index + 2:import_index + 2] = ["--source", source_id]
        return subprocess.run(
            [sys.executable, str(CLI)] + args,
            cwd=cwd or REPO_ROOT,
            env=proc_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def run_cli_pty(self, args, cwd=None, env=None, input_text=""):
        proc_env = os.environ.copy()
        if env:
            proc_env.update(env)
        master, slave = pty.openpty()
        try:
            proc = subprocess.Popen(
                [sys.executable, str(CLI)] + args,
                cwd=cwd or REPO_ROOT,
                env=proc_env,
                stdin=slave,
                stdout=slave,
                stderr=slave,
                text=False,
            )
            os.close(slave)
            slave = None
            if input_text:
                os.write(master, input_text.encode("utf-8"))
            chunks = []
            while True:
                try:
                    chunk = os.read(master, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                chunks.append(chunk)
                if proc.poll() is not None:
                    continue
            returncode = proc.wait()
            output = b"".join(chunks).decode("utf-8", errors="replace")
            return subprocess.CompletedProcess(args, returncode, output, "")
        finally:
            if slave is not None:
                os.close(slave)
            os.close(master)

    def fake_docker_env(self, tmp, present=True, daemon=True, pull_ok=True):
        bin_dir = Path(tmp) / "bin"
        bin_dir.mkdir()
        state = Path(tmp) / "image_present"
        script = bin_dir / "docker"
        script.write_text(
            """#!/usr/bin/env bash
set -euo pipefail
state="${FAKE_DOCKER_STATE}"
case "${1:-}" in
  --version)
    echo "Docker version fake"
    exit 0
    ;;
  info)
    [[ "${FAKE_DOCKER_DAEMON:-1}" == "1" ]] && exit 0 || exit 1
    ;;
  image)
    if [[ "${2:-}" == "inspect" ]]; then
      if [[ "${FAKE_DOCKER_IMAGE_PRESENT:-0}" == "1" || -f "${state}" ]]; then
        echo "sha256:fake"
        exit 0
      fi
      exit 1
    fi
    ;;
  pull)
    if [[ "${FAKE_DOCKER_PULL_OK:-1}" == "1" ]]; then
      touch "${state}"
      echo "pulled ${2:-}"
      exit 0
    fi
    exit 1
    ;;
  run)
    shift
    workdir=""
    mounts_host=()
    mounts_container=()
    while [[ "$#" -gt 0 ]]; do
      case "${1:-}" in
        -v|--volume)
          spec="${2:-}"
          if [[ "${spec}" != *:* ]]; then
            echo "ERROR malformed volume spec: ${spec}" >&2
            exit 64
          fi
          host="${spec%%:*}"
          rest="${spec#*:}"
          container="${rest%%:*}"
          if [[ -z "${host}" || -z "${container}" || "${host}" != /* ]]; then
            echo "ERROR malformed volume spec: ${spec}" >&2
            exit 64
          fi
          mounts_host+=("${host}")
          mounts_container+=("${container}")
          shift 2
          ;;
        -w|--workdir)
          workdir="${2:-}"
          shift 2
          ;;
        *)
          shift
          ;;
      esac
    done
    if [[ -n "${FAKE_DOCKER_WORK_OUTPUT:-}" ]]; then
      host_work=""
      for i in "${!mounts_container[@]}"; do
        container="${mounts_container[$i]}"
        host="${mounts_host[$i]}"
        if [[ "${workdir}" == "${container}" || "${workdir}" == "${container}/"* ]]; then
          host_work="${host}${workdir#"${container}"}"
          break
        fi
      done
      if [[ -z "${host_work}" ]]; then
        echo "ERROR could not translate workdir ${workdir}" >&2
        exit 65
      fi
      mkdir -p "${host_work}/$(dirname "${FAKE_DOCKER_WORK_OUTPUT}")"
      printf 'fake model output\n' > "${host_work}/${FAKE_DOCKER_WORK_OUTPUT}"
    fi
    echo "fake docker run"
    exit "${FAKE_DOCKER_RUN_CODE:-125}"
    ;;
esac
exit 1
""",
            encoding="utf-8",
        )
        script.chmod(0o755)
        return {
            "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            "CROCOEXP_REPO_ROOT": str(Path(tmp) / "repo"),
            "FAKE_DOCKER_STATE": str(state),
            "FAKE_DOCKER_IMAGE_PRESENT": "1" if present else "0",
            "FAKE_DOCKER_DAEMON": "1" if daemon else "0",
            "FAKE_DOCKER_PULL_OK": "1" if pull_ok else "0",
        }

    def add_binary(self, root, name="EXP_A", binary_name="croco"):
        output = root / name / "build" / "output"
        output.mkdir(parents=True, exist_ok=True)
        binary = output / binary_name
        binary.write_text("#!/usr/bin/env bash\necho fake croco\n", encoding="utf-8")
        binary.chmod(0o755)
        return binary

    def seed_compile_attempt(self, root, name="EXP_A", status="success", binary=True):
        exp = root / name
        manifest_path = exp / "metadata" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        source_ref = manifest.get("compile_time", {}).get("source_ref") or {}
        binary_path = self.add_binary(root, name=name) if binary else None
        attempt = {
            "attempted_at": "2026-01-01T00:00:00+00:00",
            "status": status,
            "failure_category": "none" if status == "success" else "compile_failure",
            "source_id": source_ref.get("source_id", "seed-source"),
            "source_installed_path": source_ref.get("host_path"),
            "stage_dir": str(exp / "build" / "stage"),
            "docker_image": "fake/image",
            "docker_command": ["docker", "run", "fake/image"],
            "returncode": 0 if status == "success" else 8,
            "warnings": [],
            "logs": {
                "stdout_path": str(exp / "build" / "compile_stdout.log"),
                "stderr_path": str(exp / "build" / "compile_stderr.log"),
            },
            "binary": {"path": str(binary_path), "sha256": "seed"} if binary_path else None,
        }
        manifest["compile"] = {"last_attempt": attempt}
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (exp / "metadata" / "compile_attempt.json").write_text(json.dumps(attempt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return attempt

    def prepare_dry_run_plan(self, root, name="EXP_A", run_id="DRYRUN", status="success", binary=True, env=None):
        attempt = self.seed_compile_attempt(root, name=name, status=status, binary=binary)
        result = self.run_cli(["--experiments-root", str(root), "dry-run", name, "--run-id", run_id], env=env)
        return result, attempt

    def input_hashes(self, root, name="EXP_A"):
        input_dir = root / name / "input"
        hashes = {}
        for path in sorted(p for p in input_dir.rglob("*") if p.is_file() and not p.is_symlink()):
            hashes[str(path.relative_to(input_dir))] = path.read_bytes()
        for path in sorted(p for p in input_dir.rglob("*") if p.is_symlink()):
            hashes[str(path.relative_to(input_dir))] = f"symlink:{os.readlink(path)}".encode("utf-8")
        return hashes

    def write_cppdefs_param(self, root, name="EXP_A", cppdefs="", param=""):
        input_dir = root / name / "input"
        (input_dir / "cppdefs.h").write_text(cppdefs or "#define TEST\n", encoding="utf-8")
        (input_dir / "param.h").write_text(param or "#define LLm 10\n", encoding="utf-8")

    def make_source(self, tmp, name="source-origin"):
        source = Path(tmp) / name
        ocean = source / "OCEAN"
        ocean.mkdir(parents=True)
        (ocean / "jobcomp").write_text("#!/usr/bin/env bash\necho fake jobcomp\n", encoding="utf-8")
        (ocean / "Makefile").write_text("all:\n\t@echo fake\n", encoding="utf-8")
        (source / "cppdefs.h").write_text("#define TEST_SOURCE\n", encoding="utf-8")
        (source / "param.h").write_text("parameter (NPP=1)\n", encoding="utf-8")
        (source / "README").write_text("fake source tree\n", encoding="utf-8")
        (source / "nested").mkdir()
        (source / "nested" / "data.txt").write_text("preserve me\n", encoding="utf-8")
        return source

    def make_repo(self, tmp):
        repo = Path(tmp) / "repo"
        (repo / ".crocoexp").mkdir(parents=True)
        (repo / "CROCO_EXPERIMENTS").mkdir()
        return repo

    def install_source(self, tmp, root, source_id="croco-test", env=None):
        source = self.make_source(tmp, f"{source_id}-origin")
        result = self.run_cli(
            ["--experiments-root", str(root), "source", "install", str(source), "--id", source_id, "--version", "test"],
            env=env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return source

    def test_import_writes_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=True)
            result = self.run_cli(["--experiments-root", str(root), "import", "EXP_A"])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("experiment_name: EXP_A", result.stdout)
            self.assertIn("manifest_path:", result.stdout)
            self.assertIn("netcdf_runtime_data_asset_count: 1", result.stdout)
            manifest_path = root / "EXP_A" / "metadata" / "manifest.json"
            self.assertTrue(manifest_path.exists())
            self.assertTrue((root / "EXP_A" / "metadata" / "import_report.md").exists())
            self.assertTrue((root / "EXP_A" / "metadata" / "report.md").exists())
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertIn("input_evidence", manifest)
            self.assertIn("compile_time", manifest)
            self.assertIn("runtime", manifest)
            self.assertIn("assets", manifest)
            self.assertEqual(manifest["schema_version"], 1)
            self.assertEqual(manifest["experiment"]["name"], "EXP_A")
            self.assertEqual(manifest["experiment"]["root"], "CROCO_EXPERIMENTS/EXP_A")
            self.assertEqual(manifest["experiment"]["input_dir"], "CROCO_EXPERIMENTS/EXP_A/input")
            self.assertEqual(manifest["import"]["status"], "imported")
            self.assertEqual(manifest["runtime_materialization"]["status"], "not_prepared")
            self.assertEqual(manifest["runtime_execution_plan"]["status"], "not_planned")
            self.assertEqual(manifest["runtime_materialization"]["symlinked_runtime_data"], [])
            self.assertEqual(
                [a["source_relative_path_from_input"] for a in manifest["runtime_materialization"]["runtime_data_assets"]],
                ["forcing.nc"],
            )
            evidence = manifest["evidence"]
            self.assertEqual(evidence["primary_artifacts"]["croco_in"]["path"], "input/croco.in")
            self.assertEqual(evidence["primary_artifacts"]["cppdefs_h"]["path"], "input/cppdefs.h")
            self.assertEqual(evidence["primary_artifacts"]["param_h"]["path"], "input/param.h")
            self.assertEqual(evidence["runtime_data_assets"][0]["path"], "input/forcing.nc")
            self.assertIn(str(root / "EXP_A" / "metadata" / "report.md"), manifest["commands"][-1]["reports_produced"])
            self.assertTrue((root / "EXP_A" / "build").is_dir())
            self.assertTrue((root / "EXP_A" / "runs").is_dir())
            report = (root / "EXP_A" / "metadata" / "report.md").read_text(encoding="utf-8")
            self.assertIn("does not prove scientific correctness", report)

    def test_commands_resolve_paths_from_deep_repo_subdirectory(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            root = repo / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=True)
            source = self.make_source(tmp)

            installed = self.run_cli(["source", "install", str(source), "--id", "deep-source"], cwd=repo)
            self.assertEqual(installed.returncode, 0, installed.stderr)
            root_import = self.run_cli(["import", "EXP_A", "--source", "deep-source", "--json"], cwd=repo)
            deep = root / "EXP_A" / "metadata" / "nested"
            deep.mkdir(parents=True)
            deep_import = self.run_cli(["import", "EXP_A", "--source", "deep-source", "--json"], cwd=deep)
            self.assertEqual(root_import.returncode, 0, root_import.stderr)
            self.assertEqual(deep_import.returncode, 0, deep_import.stderr)
            self.assertEqual(json.loads(root_import.stdout)["asset_classification_counts"], json.loads(deep_import.stdout)["asset_classification_counts"])

            listed = self.run_cli(["source", "list", "--json"], cwd=deep)
            self.assertEqual(listed.returncode, 0, listed.stderr)
            self.assertIn("deep-source", listed.stdout)

    def test_manifest_rewrite_normalizes_internal_absolute_paths_to_repo_relative_posix(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            root = repo / "CROCO_EXPERIMENTS"
            exp = self.make_exp(root, data=True)
            metadata = exp / "metadata"
            metadata.mkdir()
            manifest_path = metadata / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "experiment": {
                            "created_at": "2026-01-01T00:00:00+00:00",
                        },
                        "compile_time": {},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            result = self.run_cli(["import", "EXP_A"], cwd=repo)
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["experiment"]["root_host_path"], "CROCO_EXPERIMENTS/EXP_A")
            self.assertEqual(manifest["paths"]["input_host_path"], "CROCO_EXPERIMENTS/EXP_A/input")
            self.assertEqual(manifest["input_evidence"][0]["host_path"].split("/")[0], "CROCO_EXPERIMENTS")
            self.assertNotIn("\\", manifest["paths"]["input_host_path"])

    def test_external_operational_registry_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            root = repo / "CROCO_EXPERIMENTS"
            self.make_exp(root)
            external = Path(tmp) / "external-source"
            external.mkdir()
            registry = {
                "schema_version": 1,
                "sources": {
                    "external": {
                        "source_id": "external",
                        "host_path": str(external),
                        "installed_path": str(external),
                        "container_path": "/opt/CROCO_EXPERIMENTS/sources/external",
                    }
                },
            }
            (repo / ".crocoexp" / "sources.json").write_text(json.dumps(registry) + "\n", encoding="utf-8")
            result = self.run_cli(["import", "EXP_A", "--source", "external"], cwd=repo)
            self.assertEqual(result.returncode, 4)
            self.assertIn("path externo detectado", result.stderr)
            self.assertIn(".crocoexp/sources.json", result.stderr)

    def test_import_requires_primary_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            exp = self.make_exp(root)
            os.remove(exp / "input" / "param.h")
            result = self.run_cli(["--experiments-root", str(root), "import", "EXP_A"])
            self.assertEqual(result.returncode, 3)
            self.assertIn("param.h", result.stderr)

    def test_import_preserves_nc_in_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=True)
            result = self.run_cli(["--experiments-root", str(root), "import", "EXP_A"])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((root / "EXP_A" / "input" / "forcing.nc").exists())
            self.assertFalse((root / "EXP_A" / "build" / "forcing.nc").exists())

    def test_import_does_not_modify_input_or_use_docker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            exp = self.make_exp(root, data=True)
            input_dir = exp / "input"
            (input_dir / "run.env").write_text("FRCNAME=changed-by-env.nc\n", encoding="utf-8")
            before = {
                p.relative_to(input_dir): p.read_bytes()
                for p in sorted(input_dir.rglob("*"))
                if p.is_file()
            }
            repo = Path(tmp) / "repo"
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            docker = bin_dir / "docker"
            docker.write_text("#!/usr/bin/env bash\necho docker must not run >&2\nexit 99\n", encoding="utf-8")
            docker.chmod(0o755)
            env = {
                "CROCOEXP_REPO_ROOT": str(repo),
                "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            }
            result = self.run_cli(["--experiments-root", str(root), "import", "EXP_A", "--json"], env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            json.loads(result.stdout)
            after = {
                p.relative_to(input_dir): p.read_bytes()
                for p in sorted(input_dir.rglob("*"))
                if p.is_file()
            }
            self.assertEqual(after, before)
            manifest = json.loads((root / "EXP_A" / "metadata" / "manifest.json").read_text(encoding="utf-8"))
            run_env = [item for item in manifest["input_evidence"] if item["relative_path_from_input"] == "run.env"]
            self.assertEqual(run_env[0]["role"], "ignored_user_file")
            self.assertIn("ignored", run_env[0]["note"])
            manifest_text = json.dumps(manifest)
            self.assertNotIn("changed-by-env.nc", manifest_text)
            self.assertTrue(any("run.env is ignored" in warning for warning in manifest["reporting"]["warnings"]))
            self.assertFalse((root / "EXP_A" / "runs" / "work").exists())
            self.assertFalse((repo / ".crocoexp" / "config.json").exists())

    def test_import_does_not_infer_runtime_assets_from_croco_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=False, croco_text="TITLE == test\nFRCNAME == missing_from_disk.nc\n")
            result = self.run_cli(["--experiments-root", str(root), "import", "EXP_A", "--json"])
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((root / "EXP_A" / "metadata" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["evidence"]["runtime_data_assets"], [])
            self.assertEqual(manifest["runtime_materialization"]["runtime_data_assets"], [])

    def test_import_records_all_netcdf_like_runtime_data_extensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            exp = self.make_exp(root, data=False)
            for name in ["grid.nc", "history.nc4", "restart.cdf", "clim.netcdf"]:
                (exp / "input" / name).write_bytes(b"data")
            result = self.run_cli(["--experiments-root", str(root), "import", "EXP_A"])
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((root / "EXP_A" / "metadata" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(
                {entry["path"] for entry in manifest["evidence"]["runtime_data_assets"]},
                {"input/grid.nc", "input/history.nc4", "input/restart.cdf", "input/clim.netcdf"},
            )

    def test_import_rejects_invalid_experiment_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, name="VALID")
            for name in ["", ".", "..", "bad/name", "bad\\name"]:
                result = self.run_cli(["--experiments-root", str(root), "import", name])
                self.assertEqual(result.returncode, 2, name)

    def test_import_fails_when_input_directory_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            (root / "NO_INPUT").mkdir(parents=True)
            result = self.run_cli(["--experiments-root", str(root), "import", "NO_INPUT"])
            self.assertEqual(result.returncode, 6)
            self.assertIn("missing input directory", result.stderr)
            self.assertFalse((root / "NO_INPUT" / "metadata" / "manifest.json").exists())

    def test_compile_staging_does_not_copy_nc_before_docker(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            root = repo / "CROCO_EXPERIMENTS"
            env = {"CROCOEXP_REPO_ROOT": str(repo)}
            self.make_exp(root, analytical=True, data=True)
            self.install_source(tmp, root, env=env)
            import_result = self.run_cli(["--experiments-root", str(root), "import", "EXP_A", "--source", "croco-test"], env=env)
            self.assertEqual(import_result.returncode, 0, import_result.stderr)
            result = self.run_cli(["--experiments-root", str(root), "compile", "EXP_A", "--image", "missing-image-for-test"], env=env)
            self.assertIn(result.returncode, {7, 8})
            stage = root / "EXP_A" / "build" / "stage"
            self.assertTrue((stage / "cppdefs.h").exists())
            self.assertTrue((stage / "param.h").exists())
            self.assertTrue((stage / "analytical.F").exists())
            self.assertFalse((stage / "forcing.nc").exists())
            self.assertTrue((root / "EXP_A" / "metadata" / "compile_report.md").exists())
            manifest = json.loads((root / "EXP_A" / "metadata" / "manifest.json").read_text(encoding="utf-8"))
            mounts = manifest["docker_backend"]["mounts"]
            self.assertIn(
                {"host_path": "CROCO_EXPERIMENTS", "container_path": "/opt/CROCO_EXPERIMENTS", "mode": "ro", "purpose": "readonly_experiments_root_mount"},
                mounts,
            )
            self.assertIn(":ro", manifest["docker_backend"]["compile_command_summary"])
            self.assertIn(":rw", manifest["docker_backend"]["compile_command_summary"])
            self.assertEqual([c["command"] for c in manifest["commands"]], ["import", "compile"])
            self.assertEqual(manifest["compile_time"]["source_ref"]["source_id"], "croco-test")

    def test_compile_requires_prior_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=True)
            result = self.run_cli(["--experiments-root", str(root), "compile", "EXP_A", "--image", "missing-image-for-test"])
            self.assertEqual(result.returncode, 3)
            self.assertIn("run 'crocoexp import EXP_A' first", result.stderr)
            self.assertFalse((root / "EXP_A" / "metadata" / "manifest.json").exists())

    def test_source_install_copies_tree_and_writes_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            root = repo / "CROCO_EXPERIMENTS"
            env = {"CROCOEXP_REPO_ROOT": str(repo)}
            source = self.make_source(tmp)
            result = self.run_cli(
                ["--experiments-root", str(root), "source", "install", str(source), "--id", "croco-v1", "--version", "v1", "--notes", "test source"],
                env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            installed = root / "sources" / "croco-v1"
            self.assertTrue((installed / "OCEAN" / "jobcomp").exists())
            registry = json.loads((Path(env["CROCOEXP_REPO_ROOT"]) / ".crocoexp" / "sources.json").read_text(encoding="utf-8"))
            self.assertEqual(registry["schema_version"], 1)
            record = registry["sources"]["croco-v1"]
            self.assertEqual(record["host_path"], "CROCO_EXPERIMENTS/sources/croco-v1")
            self.assertEqual(record["installed_path"], "CROCO_EXPERIMENTS/sources/croco-v1")
            self.assertEqual(record["installed_from"], str(source))
            self.assertEqual(record["status"], "installed")
            self.assertNotIn("flavor", record)
            self.assertEqual(record["declared_version"], "v1")
            self.assertEqual(record["notes"], "test source")
            self.assertGreaterEqual(record["files_count"], 6)
            self.assertGreater(record["bytes_count"], 0)
            self.assertEqual(
                record["detection"],
                {"has_cppdefs": True, "has_param": True, "has_jobcomp": True, "has_makefile": True},
            )
            self.assertEqual((installed / "nested" / "data.txt").read_text(encoding="utf-8"), "preserve me\n")

    def test_source_list_and_inspect(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            root = repo / "CROCO_EXPERIMENTS"
            env = {"CROCOEXP_REPO_ROOT": str(repo)}
            self.install_source(tmp, root, source_id="croco-list-test", env=env)
            listed = self.run_cli(["--experiments-root", str(root), "source", "list", "--json"], env=env)
            self.assertEqual(listed.returncode, 0, listed.stderr)
            self.assertIn("croco-list-test", listed.stdout)
            inspected = self.run_cli(["--experiments-root", str(root), "source", "inspect", "croco-list-test", "--json"], env=env)
            self.assertEqual(inspected.returncode, 0, inspected.stderr)
            details = json.loads(inspected.stdout)
            self.assertEqual(details["source_id"], "croco-list-test")
            self.assertNotIn("flavor", details)
            self.assertIn("detected_layout", details)
            self.assertIn("detection", details)
            self.assertTrue(details["detection"]["has_jobcomp"])

    def test_source_install_help_does_not_include_flavor_and_option_is_rejected(self):
        help_result = self.run_cli(["source", "install", "--help"])
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertNotIn("--flavor", help_result.stdout)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            source = self.make_source(tmp)
            result = self.run_cli(["--experiments-root", str(root), "source", "install", str(source), "--id", "croco-v1", "--flavor", "croco"])
            self.assertEqual(result.returncode, 2)
            self.assertIn("unrecognized arguments", result.stderr)

    def test_source_uninstall_appears_in_source_help(self):
        result = self.run_cli(["source", "--help"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("uninstall", result.stdout)

    def test_source_install_duplicate_without_force_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            root = repo / "CROCO_EXPERIMENTS"
            env = {"CROCOEXP_REPO_ROOT": str(repo)}
            self.install_source(tmp, root, source_id="dup-source", env=env)
            source = self.make_source(tmp, "dup-origin-2")
            result = self.run_cli(["--experiments-root", str(root), "source", "install", str(source), "--id", "dup-source"], env=env)
            self.assertEqual(result.returncode, 4)
            self.assertIn("already registered", result.stderr)

    def test_source_uninstall_unknown_source_fails_without_modifying_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            root = repo / "CROCO_EXPERIMENTS"
            env = {"CROCOEXP_REPO_ROOT": str(repo)}
            self.install_source(tmp, root, source_id="keep-source", env=env)
            registry_path = Path(env["CROCOEXP_REPO_ROOT"]) / ".crocoexp" / "sources.json"
            before = registry_path.read_text(encoding="utf-8")
            result = self.run_cli(["--experiments-root", str(root), "source", "uninstall", "missing-source"], env=env)
            self.assertEqual(result.returncode, 5)
            self.assertIn("crocoexp source list", result.stderr)
            self.assertEqual(registry_path.read_text(encoding="utf-8"), before)

    def test_source_uninstall_unused_removes_registry_and_managed_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            root = repo / "CROCO_EXPERIMENTS"
            env = {"CROCOEXP_REPO_ROOT": str(repo)}
            self.install_source(tmp, root, source_id="unused-source", env=env)
            installed = root / "sources" / "unused-source"
            result = self.run_cli(["--experiments-root", str(root), "source", "uninstall", "unused-source"], env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Uninstalled source: unused-source", result.stdout)
            self.assertFalse(installed.exists())
            registry = json.loads((Path(env["CROCOEXP_REPO_ROOT"]) / ".crocoexp" / "sources.json").read_text(encoding="utf-8"))
            self.assertNotIn("unused-source", registry["sources"])
            listed = self.run_cli(["--experiments-root", str(root), "source", "list", "--json"], env=env)
            self.assertNotIn("unused-source", listed.stdout)

    def test_source_uninstall_used_without_force_non_tty_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            root = repo / "CROCO_EXPERIMENTS"
            env = {"CROCOEXP_REPO_ROOT": str(repo)}
            self.make_exp(root)
            self.install_source(tmp, root, source_id="used-source", env=env)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A", "--source", "used-source"], env=env).returncode, 0)
            manifest_before = (root / "EXP_A" / "metadata" / "manifest.json").read_text(encoding="utf-8")
            result = self.run_cli(["--experiments-root", str(root), "source", "uninstall", "used-source"], env=env)
            self.assertEqual(result.returncode, 5)
            self.assertIn("Re-run with --force", result.stderr)
            self.assertTrue((root / "sources" / "used-source").exists())
            self.assertEqual((root / "EXP_A" / "metadata" / "manifest.json").read_text(encoding="utf-8"), manifest_before)

    def test_source_uninstall_used_with_force_removes_source_not_experiment(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            root = repo / "CROCO_EXPERIMENTS"
            env = {"CROCOEXP_REPO_ROOT": str(repo)}
            self.make_exp(root)
            self.install_source(tmp, root, source_id="force-source", env=env)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A", "--source", "force-source"], env=env).returncode, 0)
            manifest_path = root / "EXP_A" / "metadata" / "manifest.json"
            manifest_before = manifest_path.read_text(encoding="utf-8")
            result = self.run_cli(["--experiments-root", str(root), "source", "uninstall", "force-source", "--force"], env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Orphaned experiment source references", result.stdout)
            self.assertIn("EXP_A", result.stdout)
            self.assertFalse((root / "sources" / "force-source").exists())
            self.assertTrue((root / "EXP_A").exists())
            self.assertEqual(manifest_path.read_text(encoding="utf-8"), manifest_before)
            registry = json.loads((Path(env["CROCOEXP_REPO_ROOT"]) / ".crocoexp" / "sources.json").read_text(encoding="utf-8"))
            self.assertNotIn("force-source", registry["sources"])

    def test_source_uninstall_used_interactive_negative_keeps_everything(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            root = repo / "CROCO_EXPERIMENTS"
            env = {"CROCOEXP_REPO_ROOT": str(repo)}
            self.make_exp(root)
            self.install_source(tmp, root, source_id="interactive-no", env=env)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A", "--source", "interactive-no"], env=env).returncode, 0)
            manifest_before = (root / "EXP_A" / "metadata" / "manifest.json").read_text(encoding="utf-8")
            result = self.run_cli_pty(["--experiments-root", str(root), "source", "uninstall", "interactive-no"], env=env, input_text="n\n")
            self.assertEqual(result.returncode, 5)
            self.assertIn("Continue? [y/N]", result.stdout)
            self.assertTrue((root / "sources" / "interactive-no").exists())
            self.assertEqual((root / "EXP_A" / "metadata" / "manifest.json").read_text(encoding="utf-8"), manifest_before)

    def test_source_uninstall_used_interactive_yes_uninstalls(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            root = repo / "CROCO_EXPERIMENTS"
            env = {"CROCOEXP_REPO_ROOT": str(repo)}
            self.make_exp(root)
            self.install_source(tmp, root, source_id="interactive-yes", env=env)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A", "--source", "interactive-yes"], env=env).returncode, 0)
            result = self.run_cli_pty(["--experiments-root", str(root), "source", "uninstall", "interactive-yes"], env=env, input_text="yes\n")
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertIn("Uninstalled source: interactive-yes", result.stdout)
            self.assertFalse((root / "sources" / "interactive-yes").exists())

    def test_source_uninstall_does_not_remove_external_or_external_symlink_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            repo = Path(tmp) / "repo"
            env = {"CROCOEXP_REPO_ROOT": str(repo)}
            registry_path = repo / ".crocoexp" / "sources.json"
            registry_path.parent.mkdir(parents=True)
            external = Path(tmp) / "external-source"
            external.mkdir()
            (external / "keep.txt").write_text("keep\n", encoding="utf-8")
            symlink_target = Path(tmp) / "external-target"
            symlink_target.mkdir()
            (symlink_target / "keep.txt").write_text("keep target\n", encoding="utf-8")
            symlink_path = root / "sources" / "symlink-source"
            symlink_path.parent.mkdir(parents=True)
            symlink_path.symlink_to(symlink_target, target_is_directory=True)
            registry = {
                "schema_version": 1,
                "sources": {
                    "external-source": {"source_id": "external-source", "host_path": str(external), "installed_path": str(external)},
                    "symlink-source": {"source_id": "symlink-source", "host_path": str(symlink_path), "installed_path": str(symlink_path)},
                },
            }
            registry_path.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            external_result = self.run_cli(["--experiments-root", str(root), "source", "uninstall", "external-source"], env=env)
            self.assertEqual(external_result.returncode, 0, external_result.stderr)
            self.assertTrue((external / "keep.txt").exists())
            self.assertIn("outside", external_result.stdout)
            symlink_result = self.run_cli(["--experiments-root", str(root), "source", "uninstall", "symlink-source"], env=env)
            self.assertEqual(symlink_result.returncode, 0, symlink_result.stderr)
            self.assertTrue(symlink_path.is_symlink())
            self.assertTrue((symlink_target / "keep.txt").exists())
            self.assertIn("symlink", symlink_result.stdout)

    def test_source_uninstall_aborts_on_corrupt_manifest_without_modifying_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            root = repo / "CROCO_EXPERIMENTS"
            env = {"CROCOEXP_REPO_ROOT": str(repo)}
            self.install_source(tmp, root, source_id="blocked-source", env=env)
            manifest_dir = root / "EXP_A" / "metadata"
            manifest_dir.mkdir(parents=True)
            (manifest_dir / "manifest.json").write_text("{bad json\n", encoding="utf-8")
            registry_path = repo / ".crocoexp" / "sources.json"
            before = registry_path.read_text(encoding="utf-8")
            result = self.run_cli(["--experiments-root", str(root), "source", "uninstall", "blocked-source", "--force"], env=env)
            self.assertEqual(result.returncode, 4)
            self.assertIn("could not be read", result.stderr)
            self.assertEqual(registry_path.read_text(encoding="utf-8"), before)
            self.assertTrue((root / "sources" / "blocked-source").exists())

    def test_source_install_rejects_unsafe_source_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            root = repo / "CROCO_EXPERIMENTS"
            env = {"CROCOEXP_REPO_ROOT": str(repo)}
            source = self.make_source(tmp)
            for source_id in ["", ".", "..", "bad/id", "bad\\id"]:
                result = self.run_cli(["--experiments-root", str(root), "source", "install", str(source), "--id", source_id], env=env)
                self.assertEqual(result.returncode, 2, source_id)

    def test_source_install_does_not_require_setup_or_docker_and_does_not_touch_experiment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            exp = self.make_exp(root, data=True)
            input_dir = exp / "input"
            before = {
                p.relative_to(input_dir): p.read_bytes()
                for p in sorted(input_dir.rglob("*"))
                if p.is_file()
            }
            source = self.make_source(tmp)
            repo = Path(tmp) / "repo"
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            docker = bin_dir / "docker"
            docker.write_text("#!/usr/bin/env bash\necho docker must not run >&2\nexit 99\n", encoding="utf-8")
            docker.chmod(0o755)
            env = {
                "CROCOEXP_REPO_ROOT": str(repo),
                "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            }
            result = self.run_cli(["--experiments-root", str(root), "source", "install", str(source), "--id", "no-setup-needed"], env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            after = {
                p.relative_to(input_dir): p.read_bytes()
                for p in sorted(input_dir.rglob("*"))
                if p.is_file()
            }
            self.assertEqual(after, before)
            self.assertFalse((repo / ".crocoexp" / "config.json").exists())
            self.assertFalse((exp / "metadata").exists())
            self.assertFalse((exp / "metadata" / "manifest.json").exists())
            self.assertTrue((repo / ".crocoexp" / "sources.json").exists())
            self.assertTrue((root / "sources" / "no-setup-needed").is_dir())

    def test_source_list_empty_registry_is_successful_and_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            result = self.run_cli(["--experiments-root", str(root), "source", "list", "--json"], env={"CROCOEXP_REPO_ROOT": str(repo)})
            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads(result.stdout)
            self.assertEqual(summary["sources"], [])
            self.assertFalse((repo / ".crocoexp").exists())

    def test_import_with_source_records_source_ref(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            root = repo / "CROCO_EXPERIMENTS"
            env = {"CROCOEXP_REPO_ROOT": str(repo)}
            self.make_exp(root, data=True)
            self.install_source(tmp, root, source_id="croco-import", env=env)
            source_tree = root / "sources" / "croco-import"
            before = {
                p.relative_to(source_tree): p.read_bytes()
                for p in sorted(source_tree.rglob("*"))
                if p.is_file()
            }
            result = self.run_cli(["--experiments-root", str(root), "import", "EXP_A", "--source", "croco-import"], env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((root / "EXP_A" / "metadata" / "manifest.json").read_text(encoding="utf-8"))
            source_ref = manifest["compile_time"]["source_ref"]
            self.assertEqual(source_ref["source_id"], "croco-import")
            self.assertEqual(source_ref["host_path"], "CROCO_EXPERIMENTS/sources/croco-import")
            self.assertEqual(source_ref["installed_path"], "CROCO_EXPERIMENTS/sources/croco-import")
            self.assertEqual(source_ref["registry_path"], ".crocoexp/sources.json")
            self.assertEqual(source_ref["status"], "registered")
            self.assertFalse((root / "EXP_A" / "input" / "OCEAN").exists())
            after = {
                p.relative_to(source_tree): p.read_bytes()
                for p in sorted(source_tree.rglob("*"))
                if p.is_file()
            }
            self.assertEqual(after, before)
            self.assertEqual(manifest["commands"][-1]["source_ref"]["source_id"], "croco-import")
            self.assertNotIn("flavor", json.dumps(manifest))

    def test_import_external_experiment_copies_to_canonical_location(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            root = repo / "CROCO_EXPERIMENTS"
            env = {"CROCOEXP_REPO_ROOT": str(repo)}
            external_root = Path(tmp) / "external" / "MesaRotante"
            self.make_exp(external_root.parent, name="MesaRotante", data=True)
            (external_root / "input" / "nested").mkdir()
            (external_root / "input" / "nested" / "extra.nc").write_bytes(b"nc")
            self.install_source(tmp, root, source_id="croco-copy", env=env)
            before = self.input_hashes(external_root.parent, name="MesaRotante")
            result = self.run_cli(["--experiments-root", str(root), "import", str(external_root), "--source", "croco-copy"], env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Copied experiment into canonical location", result.stdout)
            canonical = root / "MesaRotante"
            self.assertTrue((canonical / "input" / "forcing.nc").exists())
            self.assertTrue((canonical / "input" / "nested" / "extra.nc").exists())
            self.assertTrue((canonical / "metadata" / "manifest.json").exists())
            self.assertFalse((external_root / "metadata" / "manifest.json").exists())
            self.assertEqual(before, self.input_hashes(external_root.parent, name="MesaRotante"))
            manifest = json.loads((canonical / "metadata" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["experiment"]["root"], "CROCO_EXPERIMENTS/MesaRotante")
            self.assertEqual(manifest["compile_time"]["source_ref"]["source_id"], "croco-copy")
            self.assertEqual(manifest["import"]["canonical_path"], "CROCO_EXPERIMENTS/MesaRotante")
            self.assertNotIn(str(external_root), json.dumps(manifest["compile_time"]))

    def test_import_external_rejects_existing_canonical_name_without_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            root = repo / "CROCO_EXPERIMENTS"
            env = {"CROCOEXP_REPO_ROOT": str(repo)}
            existing = self.make_exp(root, name="EXP_A", data=False)
            sentinel = existing / "input" / "sentinel.txt"
            sentinel.write_text("keep\n", encoding="utf-8")
            external = self.make_exp(Path(tmp) / "external", name="EXP_A", data=True)
            self.install_source(tmp, root, source_id="croco-existing", env=env)
            result = self.run_cli(["--experiments-root", str(root), "import", str(external), "--source", "croco-existing"], env=env)
            self.assertEqual(result.returncode, 4)
            self.assertIn("experiment name already exists", result.stderr)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep\n")
            self.assertFalse((root / "EXP_A" / "metadata" / "manifest.json").exists())

    def test_import_canonical_experiment_operates_in_place(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            root = repo / "CROCO_EXPERIMENTS"
            env = {"CROCOEXP_REPO_ROOT": str(repo)}
            canonical = self.make_exp(root, name="CANONICAL", data=True)
            self.install_source(tmp, root, source_id="croco-in-place", env=env)
            result = self.run_cli(["--experiments-root", str(root), "import", str(canonical), "--source", "croco-in-place"], env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("Copied experiment", result.stdout)
            self.assertTrue((canonical / "metadata" / "manifest.json").exists())
            self.assertFalse((root / "CANONICAL.1").exists())

    def test_import_without_source_non_interactive_fails_without_writing_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            env = {"CROCOEXP_REPO_ROOT": str(Path(tmp) / "repo"), "CROCOEXP_TEST_NO_AUTO_SOURCE": "1"}
            self.make_exp(root)
            self.install_source(tmp, root, source_id="croco-noninteractive", env=env)
            result = self.run_cli(["--experiments-root", str(root), "import", "EXP_A"], env=env)
            self.assertEqual(result.returncode, 5)
            self.assertIn("crocoexp source list", result.stderr)
            self.assertIn("crocoexp import EXP_A --source <source_id>", result.stderr)
            self.assertFalse((root / "EXP_A" / "metadata" / "manifest.json").exists())

    def test_import_without_source_no_registered_sources_fails_with_install_hint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            env = {"CROCOEXP_REPO_ROOT": str(Path(tmp) / "repo"), "CROCOEXP_TEST_NO_AUTO_SOURCE": "1"}
            self.make_exp(root)
            result = self.run_cli(["--experiments-root", str(root), "import", "EXP_A"], env=env)
            self.assertEqual(result.returncode, 5)
            self.assertIn("crocoexp source install /path/to/croco --id croco-v2.1.3", result.stderr)
            self.assertFalse((root / "EXP_A" / "metadata" / "manifest.json").exists())

    def test_import_without_source_interactive_selects_only_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            root = repo / "CROCO_EXPERIMENTS"
            env = {"CROCOEXP_REPO_ROOT": str(repo)}
            self.make_exp(root)
            self.install_source(tmp, root, source_id="croco-one", env=env)
            result = self.run_cli_pty(["--experiments-root", str(root), "import", "EXP_A", "--json"], env=env, input_text="1\n")
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertIn("Available CROCO sources", result.stdout)
            manifest = json.loads((root / "EXP_A" / "metadata" / "manifest.json").read_text(encoding="utf-8"))
            source_ref = manifest["compile_time"]["source_ref"]
            self.assertEqual(source_ref["source_id"], "croco-one")
            self.assertEqual(source_ref["declared_version"], "test")
            self.assertIn("git_commit", source_ref)
            self.assertNotIn("flavor", json.dumps(manifest))

    def test_import_without_source_interactive_selects_among_multiple_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            root = repo / "CROCO_EXPERIMENTS"
            env = {"CROCOEXP_REPO_ROOT": str(repo)}
            self.make_exp(root)
            self.install_source(tmp, root, source_id="croco-first", env=env)
            self.install_source(tmp, root, source_id="croco-second", env=env)
            result = self.run_cli_pty(["--experiments-root", str(root), "import", "EXP_A"], env=env, input_text="2\n")
            self.assertEqual(result.returncode, 0, result.stdout)
            manifest = json.loads((root / "EXP_A" / "metadata" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["compile_time"]["source_ref"]["source_id"], "croco-second")

    def test_legacy_croco_flavor_is_accepted_and_removed_on_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            root = repo / "CROCO_EXPERIMENTS"
            env = {"CROCOEXP_REPO_ROOT": str(repo)}
            self.make_exp(root)
            self.install_source(tmp, root, source_id="legacy-croco", env=env)
            registry_path = Path(env["CROCOEXP_REPO_ROOT"]) / ".crocoexp" / "sources.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry["sources"]["legacy-croco"]["flavor"] = "croco"
            registry_path.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            result = self.run_cli(["--experiments-root", str(root), "import", "EXP_A", "--source", "legacy-croco"], env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((root / "EXP_A" / "metadata" / "manifest.json").read_text(encoding="utf-8"))
            self.assertNotIn("flavor", json.dumps(manifest))
            manifest["compile_time"]["source_ref"]["flavor"] = "croco"
            manifest_path = root / "EXP_A" / "metadata" / "manifest.json"
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            inspect_result = self.run_cli(["--experiments-root", str(root), "inspect", "EXP_A"], env=env)
            self.assertEqual(inspect_result.returncode, 0, inspect_result.stderr)
            rewrite_result = self.run_cli(["--experiments-root", str(root), "import", "EXP_A"], env=env)
            self.assertEqual(rewrite_result.returncode, 0, rewrite_result.stderr)
            rewritten = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertNotIn("flavor", json.dumps(rewritten))

    def test_legacy_non_croco_flavors_are_rejected(self):
        for legacy_flavor in ("msot", "custom"):
            with self.subTest(legacy_flavor=legacy_flavor):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp) / "CROCO_EXPERIMENTS"
                    env = {"CROCOEXP_REPO_ROOT": str(Path(tmp) / "repo")}
                    self.make_exp(root)
                    self.install_source(tmp, root, source_id="legacy-source", env=env)
                    registry_path = Path(env["CROCOEXP_REPO_ROOT"]) / ".crocoexp" / "sources.json"
                    registry = json.loads(registry_path.read_text(encoding="utf-8"))
                    registry["sources"]["legacy-source"]["flavor"] = legacy_flavor
                    registry_path.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                    result = self.run_cli(["--experiments-root", str(root), "import", "EXP_A", "--source", "legacy-source"], env=env)
                    self.assertEqual(result.returncode, 5)
                    self.assertIn("CROCOEXP v1.0.1 only supports CROCO sources", result.stderr)
                    if legacy_flavor == "msot":
                        self.assertIn("pipelines are outside CROCOEXP scope", result.stderr)
                    else:
                        self.assertIn("registered CROCO source installation", result.stderr)

    def test_legacy_non_croco_manifest_flavors_are_rejected(self):
        for legacy_flavor in ("msot", "custom"):
            with self.subTest(legacy_flavor=legacy_flavor):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp) / "CROCO_EXPERIMENTS"
                    self.make_exp(root)
                    self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"]).returncode, 0)
                    manifest_path = root / "EXP_A" / "metadata" / "manifest.json"
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    manifest["compile_time"]["source_ref"] = {"source_id": "legacy-source", "flavor": legacy_flavor}
                    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                    result = self.run_cli(["--experiments-root", str(root), "inspect", "EXP_A"])
                    self.assertEqual(result.returncode, 5)
                    self.assertIn("CROCOEXP v1.0.1 only supports CROCO sources", result.stderr)

    def test_docs_specs_and_help_do_not_advertise_source_flavor_or_pipelines(self):
        help_result = self.run_cli(["source", "install", "--help"])
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertNotIn("--flavor", help_result.stdout)
        text = "\n".join(
            path.read_text(encoding="utf-8")
            for base in (REPO_ROOT / "README.md", REPO_ROOT / "docs", REPO_ROOT / "specs")
            for path in ([base] if base.is_file() else sorted(base.rglob("*.md")))
        )
        for forbidden in ("--flavor", "source flavor", "MSOT", "msot", "`custom`", "custom forks", "custom source"):
            self.assertNotIn(forbidden, text)

    def test_import_unknown_source_fails_clearly(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            root = repo / "CROCO_EXPERIMENTS"
            env = {"CROCOEXP_REPO_ROOT": str(repo)}
            self.make_exp(root, data=True)
            result = self.run_cli(["--experiments-root", str(root), "import", "EXP_A", "--source", "missing-source"], env=env)
            self.assertEqual(result.returncode, 5)
            self.assertIn("missing-source", result.stderr)
            self.assertFalse((root / "EXP_A" / "metadata" / "manifest.json").exists())

    def test_experiment_list_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            root = repo / "CROCO_EXPERIMENTS"
            result = self.run_cli(
                ["--experiments-root", str(root), "experiment", "list"],
                env={"CROCOEXP_REPO_ROOT": str(repo)},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("No experiments registered.", result.stdout)
            self.assertIn("crocoexp import /path/to/experiment --source <source_id>", result.stdout)

    def test_experiment_list_reports_available_and_orphaned_sources_from_subdir(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            root = repo / "CROCO_EXPERIMENTS"
            env = {"CROCOEXP_REPO_ROOT": str(repo)}
            self.make_exp(root, name="EXP_A", data=True)
            self.make_exp(root, name="EXP_B", data=True)
            self.install_source(tmp, root, source_id="croco-list-a", env=env)
            self.install_source(tmp, root, source_id="croco-list-b", env=env)
            imported_a = self.run_cli(["--experiments-root", str(root), "import", "EXP_A", "--source", "croco-list-a"], env=env)
            self.assertEqual(imported_a.returncode, 0, imported_a.stderr)
            imported_b = self.run_cli(["--experiments-root", str(root), "import", "EXP_B", "--source", "croco-list-b"], env=env)
            self.assertEqual(imported_b.returncode, 0, imported_b.stderr)
            uninstalled = self.run_cli(["--experiments-root", str(root), "source", "uninstall", "croco-list-b", "--force"], env=env)
            self.assertEqual(uninstalled.returncode, 0, uninstalled.stderr)

            deep = root / "EXP_A" / "metadata" / "deep"
            deep.mkdir(parents=True)
            listed = self.run_cli(["experiment", "list", "--json"], cwd=deep, env=env)
            self.assertEqual(listed.returncode, 0, listed.stderr)
            summary = json.loads(listed.stdout)
            by_name = {item["experiment_name"]: item for item in summary["experiments"]}
            self.assertEqual(by_name["EXP_A"]["source_id"], "croco-list-a")
            self.assertEqual(by_name["EXP_A"]["source_status"], "available")
            self.assertEqual(by_name["EXP_A"]["path"], "CROCO_EXPERIMENTS/EXP_A")
            self.assertEqual(by_name["EXP_B"]["source_id"], "croco-list-b")
            self.assertEqual(by_name["EXP_B"]["source_status"], "orphaned")

            text = self.run_cli(["experiment", "list"], cwd=deep, env=env)
            self.assertEqual(text.returncode, 0, text.stderr)
            self.assertIn("EXP_A", text.stdout)
            self.assertIn("croco-list-a (available)", text.stdout)
            self.assertIn("croco-list-b (orphaned)", text.stdout)

    def test_experiment_unimport_preserves_input_and_removes_imported_listing(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            root = repo / "CROCO_EXPERIMENTS"
            env = {"CROCOEXP_REPO_ROOT": str(repo)}
            self.make_exp(root, name="EXP_A", data=True)
            self.install_source(tmp, root, source_id="croco-unimport", env=env)
            imported = self.run_cli(["--experiments-root", str(root), "import", "EXP_A", "--source", "croco-unimport"], env=env)
            self.assertEqual(imported.returncode, 0, imported.stderr)
            manifest_path = root / "EXP_A" / "metadata" / "manifest.json"
            self.assertTrue(manifest_path.is_file())
            before_input = self.input_hashes(root, name="EXP_A")
            listed_before = self.run_cli(["--experiments-root", str(root), "experiment", "list", "--json"], env=env)
            self.assertIn("EXP_A", listed_before.stdout)

            result = self.run_cli(["--experiments-root", str(root), "experiment", "unimport", "EXP_A"], env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Unimported experiment: EXP_A", result.stdout)
            self.assertIn("Preserved user input: CROCO_EXPERIMENTS/EXP_A/input", result.stdout)
            self.assertFalse(manifest_path.exists())
            self.assertTrue((root / "EXP_A").is_dir())
            self.assertTrue((root / "EXP_A" / "input" / "forcing.nc").is_file())
            self.assertEqual(before_input, self.input_hashes(root, name="EXP_A"))
            listed_after = self.run_cli(["--experiments-root", str(root), "experiment", "list", "--json"], env=env)
            self.assertEqual(json.loads(listed_after.stdout)["experiments"], [])

    def test_experiment_unimport_unknown_experiment_fails_without_modifying_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            root = repo / "CROCO_EXPERIMENTS"
            env = {"CROCOEXP_REPO_ROOT": str(repo)}
            root.mkdir(parents=True)
            result = self.run_cli(["--experiments-root", str(root), "experiment", "unimport", "Missing"], env=env)
            self.assertEqual(result.returncode, 3)
            self.assertIn("experiment not found: Missing", result.stderr)
            self.assertIn("crocoexp experiment list", result.stderr)
            self.assertEqual(list(root.iterdir()), [])

    def test_experiment_unimport_folder_without_manifest_fails_without_deleting(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            root = repo / "CROCO_EXPERIMENTS"
            env = {"CROCOEXP_REPO_ROOT": str(repo)}
            exp = self.make_exp(root, name="NoManifest", data=True)
            result = self.run_cli(["--experiments-root", str(root), "experiment", "unimport", "NoManifest"], env=env)
            self.assertEqual(result.returncode, 5)
            self.assertIn("exists but is not an imported experiment", result.stderr)
            self.assertTrue(exp.is_dir())
            self.assertTrue((exp / "input" / "forcing.nc").is_file())

    def test_experiment_unimport_from_deep_subdirectory_uses_repo_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            root = repo / "CROCO_EXPERIMENTS"
            env = {"CROCOEXP_REPO_ROOT": str(repo)}
            self.make_exp(root, name="DeepUnimport", data=True)
            self.install_source(tmp, root, source_id="croco-deep-unimport", env=env)
            imported = self.run_cli(["--experiments-root", str(root), "import", "DeepUnimport", "--source", "croco-deep-unimport"], env=env)
            self.assertEqual(imported.returncode, 0, imported.stderr)
            deep = root / "DeepUnimport" / "input" / "nested"
            deep.mkdir(parents=True)
            result = self.run_cli(["experiment", "unimport", "DeepUnimport"], cwd=deep, env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((root / "DeepUnimport" / "metadata" / "manifest.json").exists())
            self.assertTrue((root / "DeepUnimport" / "input").is_dir())

    def test_experiment_unimport_rejects_path_like_names_and_absolute_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            root = repo / "CROCO_EXPERIMENTS"
            env = {"CROCOEXP_REPO_ROOT": str(repo)}
            root.mkdir(parents=True)
            for name in ("../EXP_A", "bad/name", "bad\\name", str(Path(tmp) / "external")):
                with self.subTest(name=name):
                    result = self.run_cli(["--experiments-root", str(root), "experiment", "unimport", name], env=env)
                    self.assertEqual(result.returncode, 2)
                    self.assertIn("invalid experiment name", result.stderr)

    def test_experiment_unimport_does_not_follow_or_remove_external_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            root = repo / "CROCO_EXPERIMENTS"
            env = {"CROCOEXP_REPO_ROOT": str(repo)}
            self.make_exp(root, name="SymlinkSafe", data=True)
            self.install_source(tmp, root, source_id="croco-symlink-unimport", env=env)
            imported = self.run_cli(["--experiments-root", str(root), "import", "SymlinkSafe", "--source", "croco-symlink-unimport"], env=env)
            self.assertEqual(imported.returncode, 0, imported.stderr)
            external = Path(tmp) / "external-build"
            external.mkdir()
            (external / "keep.txt").write_text("keep\n", encoding="utf-8")
            build_link = root / "SymlinkSafe" / "build"
            if build_link.exists():
                shutil.rmtree(build_link)
            build_link.symlink_to(external, target_is_directory=True)

            result = self.run_cli(["--experiments-root", str(root), "experiment", "unimport", "SymlinkSafe"], env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(build_link.is_symlink())
            self.assertTrue((external / "keep.txt").is_file())
            self.assertFalse((root / "SymlinkSafe" / "metadata" / "manifest.json").exists())

    def test_inspect_after_import_reports_manifest_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=True)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"]).returncode, 0)
            result = self.run_cli(["--experiments-root", str(root), "inspect", "EXP_A"])
            self.assertEqual(result.returncode, 0, result.stderr)
            for text in [
                "Experiment name: EXP_A",
                "Input directory:",
                "Manifest path:",
                "Import status: imported",
                "croco.in",
                "cppdefs.h",
                "param.h",
                "analytical.F",
                "Runtime data asset count: 1",
                "Runtime materialization status: not_prepared",
                "Runtime execution plan status: not_planned",
                "does not prove scientific correctness",
            ]:
                self.assertIn(text, result.stdout)

    def test_inspect_json_after_import_is_valid_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=True)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"]).returncode, 0)
            result = self.run_cli(["--experiments-root", str(root), "inspect", "EXP_A", "--json"])
            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads(result.stdout)
            self.assertEqual(summary["experiment_name"], "EXP_A")
            self.assertEqual(summary["import_status"], "imported")
            self.assertTrue(summary["primary_artifacts"]["croco_in"]["present"])
            self.assertEqual(summary["runtime_data_asset_count"], 1)
            self.assertEqual(summary["runtime_materialization_status"], "not_prepared")
            self.assertEqual(summary["runtime_execution_plan_status"], "not_planned")
            self.assertEqual(summary["read_only_checks"]["warnings"], [])

    def test_inspect_is_read_only_and_does_not_use_docker_or_setup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            exp = self.make_exp(root, data=True)
            env = {"CROCOEXP_REPO_ROOT": str(Path(tmp) / "repo")}
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"], env=env).returncode, 0)
            input_dir = exp / "input"
            manifest_path = exp / "metadata" / "manifest.json"
            report_path = exp / "metadata" / "report.md"
            input_before = {
                p.relative_to(input_dir): p.read_bytes()
                for p in sorted(input_dir.rglob("*"))
                if p.is_file()
            }
            manifest_before = manifest_path.read_bytes()
            report_before = report_path.read_bytes()
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            docker = bin_dir / "docker"
            docker.write_text("#!/usr/bin/env bash\necho docker must not run >&2\nexit 99\n", encoding="utf-8")
            docker.chmod(0o755)
            env["PATH"] = f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"
            result = self.run_cli(["--experiments-root", str(root), "inspect", "EXP_A"], env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            input_after = {
                p.relative_to(input_dir): p.read_bytes()
                for p in sorted(input_dir.rglob("*"))
                if p.is_file()
            }
            self.assertEqual(input_after, input_before)
            self.assertEqual(manifest_path.read_bytes(), manifest_before)
            self.assertEqual(report_path.read_bytes(), report_before)
            self.assertFalse((Path(env["CROCOEXP_REPO_ROOT"]) / ".crocoexp" / "config.json").exists())

    def test_inspect_does_not_modify_source_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            root = repo / "CROCO_EXPERIMENTS"
            env = {"CROCOEXP_REPO_ROOT": str(repo)}
            self.make_exp(root, data=True)
            self.install_source(tmp, root, source_id="inspect-source", env=env)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A", "--source", "inspect-source"], env=env).returncode, 0)
            registry_path = Path(env["CROCOEXP_REPO_ROOT"]) / ".crocoexp" / "sources.json"
            before = registry_path.read_bytes()
            result = self.run_cli(["--experiments-root", str(root), "inspect", "EXP_A"], env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Selected source ID: inspect-source", result.stdout)
            self.assertIn("CROCO_EXPERIMENTS/sources/inspect-source", result.stdout)
            self.assertEqual(registry_path.read_bytes(), before)

    def test_inspect_reports_ignored_run_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            exp = self.make_exp(root)
            (exp / "input" / "run.env").write_text("IGNORED=1\n", encoding="utf-8")
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"]).returncode, 0)
            result = self.run_cli(["--experiments-root", str(root), "inspect", "EXP_A"])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("run.env ignored: yes", result.stdout)
            self.assertIn("Ignored user file count: 1", result.stdout)

    def test_inspect_warns_when_recorded_runtime_data_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            exp = self.make_exp(root, data=True)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"]).returncode, 0)
            os.remove(exp / "input" / "forcing.nc")
            result = self.run_cli(["--experiments-root", str(root), "inspect", "EXP_A"])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("recorded runtime data asset missing: input/forcing.nc", result.stdout)

    def test_inspect_fails_without_creating_files_when_manifest_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root)
            result = self.run_cli(["--experiments-root", str(root), "inspect", "EXP_A"])
            self.assertEqual(result.returncode, 3)
            self.assertIn("run 'crocoexp import EXP_A' first", result.stderr)
            self.assertFalse((root / "EXP_A" / "metadata").exists())
            self.assertFalse((root / "EXP_A" / "build").exists())
            self.assertFalse((root / "EXP_A" / "runs").exists())

    def test_inspect_fails_when_experiment_root_or_input_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            missing_root = self.run_cli(["--experiments-root", str(root), "inspect", "MISSING"])
            self.assertEqual(missing_root.returncode, 6)
            self.assertIn("missing experiment directory", missing_root.stderr)
            (root / "NO_INPUT").mkdir(parents=True)
            missing_input = self.run_cli(["--experiments-root", str(root), "inspect", "NO_INPUT"])
            self.assertEqual(missing_input.returncode, 6)
            self.assertIn("missing input directory", missing_input.stderr)

    def test_inspect_fails_on_malformed_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            exp = self.make_exp(root)
            metadata = exp / "metadata"
            metadata.mkdir()
            (metadata / "manifest.json").write_text("{not json\n", encoding="utf-8")
            result = self.run_cli(["--experiments-root", str(root), "inspect", "EXP_A"])
            self.assertEqual(result.returncode, 3)
            self.assertIn("malformed manifest JSON", result.stderr)

    def test_inspect_rejects_invalid_experiment_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, name="VALID")
            for name in ["", ".", "..", "bad/name", "bad\\name"]:
                result = self.run_cli(["--experiments-root", str(root), "inspect", name])
                self.assertEqual(result.returncode, 2, name)

    def test_compile_requires_source_ref(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=True)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"]).returncode, 0)
            manifest_path = root / "EXP_A" / "metadata" / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["compile_time"]["source_ref"] = None
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            result = self.run_cli(["--experiments-root", str(root), "compile", "EXP_A", "--image", "fake/image"])
            self.assertEqual(result.returncode, 5)
            self.assertIn("missing compile source", result.stderr)

    def test_compile_records_source_traceability(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            env = self.fake_docker_env(tmp, present=True)
            self.make_exp(root, data=True)
            self.install_source(tmp, root, source_id="trace-source", env=env)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A", "--source", "trace-source"], env=env).returncode, 0)
            result = self.run_cli(["--experiments-root", str(root), "compile", "EXP_A", "--image", "fake/image"], env=env)
            self.assertIn(result.returncode, {7, 8})
            manifest = json.loads((root / "EXP_A" / "metadata" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["compile_time"]["source_ref"]["source_id"], "trace-source")
            self.assertEqual(manifest["commands"][-1]["source_ref"]["source_id"], "trace-source")
            self.assertIn(str(root / "sources" / "trace-source"), manifest["commands"][-1]["inputs_used"])
            report = (root / "EXP_A" / "metadata" / "compile_report.md").read_text(encoding="utf-8")
            self.assertIn("trace-source", report)

    def test_compile_source_tree_is_readonly_input_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            env = self.fake_docker_env(tmp, present=True)
            self.make_exp(root, data=True)
            self.install_source(tmp, root, source_id="readonly-source", env=env)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A", "--source", "readonly-source"], env=env).returncode, 0)
            result = self.run_cli(["--experiments-root", str(root), "compile", "EXP_A", "--image", "fake/image"], env=env)
            self.assertIn(result.returncode, {7, 8})
            manifest = json.loads((root / "EXP_A" / "metadata" / "manifest.json").read_text(encoding="utf-8"))
            source_mounts = [m for m in manifest["docker_backend"]["mounts"] if m["purpose"] == "registered_compile_source_via_readonly_root_mount"]
            self.assertEqual(source_mounts[0]["mode"], "ro")
            self.assertFalse((root / "sources" / "readonly-source" / "generated").exists())

    def test_compile_writes_attempt_report_logs_and_manifest_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            env = self.fake_docker_env(tmp, present=True)
            env["FAKE_DOCKER_RUN_CODE"] = "0"
            env["FAKE_DOCKER_WORK_OUTPUT"] = "croco"
            self.make_exp(root, data=True)
            self.install_source(tmp, root, source_id="compile-ok", env=env)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A", "--source", "compile-ok"], env=env).returncode, 0)
            input_dir = root / "EXP_A" / "input"
            before = {p.relative_to(input_dir): p.read_bytes() for p in sorted(input_dir.rglob("*")) if p.is_file()}
            result = self.run_cli(["--experiments-root", str(root), "compile", "EXP_A", "--no-clean", "--json"], env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads(result.stdout)
            self.assertEqual(summary["source_id"], "compile-ok")
            self.assertEqual(summary["docker_image"], "domarcroco/images-for-croco:base_croco-1.0.1")
            after = {p.relative_to(input_dir): p.read_bytes() for p in sorted(input_dir.rglob("*")) if p.is_file()}
            self.assertEqual(after, before)
            exp = root / "EXP_A"
            self.assertTrue((exp / "build" / "stage" / "source" / "OCEAN" / "jobcomp").exists())
            self.assertTrue((exp / "build" / "stage" / "experiment_input" / "cppdefs.h").exists())
            self.assertTrue((exp / "metadata" / "compile_attempt.json").exists())
            self.assertTrue((exp / "metadata" / "compile_report.md").exists())
            self.assertTrue((exp / "build" / "compile_stdout.log").exists())
            self.assertTrue((exp / "build" / "compile_stderr.log").exists())
            attempt = json.loads((exp / "metadata" / "compile_attempt.json").read_text(encoding="utf-8"))
            self.assertEqual(attempt["status"], "success")
            self.assertEqual(attempt["source_id"], "compile-ok")
            self.assertEqual(attempt["docker_image"], "domarcroco/images-for-croco:base_croco-1.0.1")
            self.assertTrue(attempt["docker_command"])
            self.assertEqual(attempt["binary"]["path"], str(exp / "build" / "stage" / "croco"))
            manifest = json.loads((exp / "metadata" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["compile"]["last_attempt"]["source_id"], "compile-ok")
            report = (exp / "metadata" / "compile_report.md").read_text(encoding="utf-8")
            self.assertIn("Compile records a build attempt", report)
            self.assertIn("does not prove scientific correctness", report)

    def test_compile_previous_artifacts_without_policy_noninteractive_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            env = self.fake_docker_env(tmp, present=True)
            env["FAKE_DOCKER_RUN_CODE"] = "0"
            self.make_exp(root, data=True)
            self.install_source(tmp, root, source_id="compile-policy", env=env)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A", "--source", "compile-policy"], env=env).returncode, 0)
            sentinel = root / "EXP_A" / "build" / "stage" / "old.o"
            sentinel.parent.mkdir(parents=True, exist_ok=True)
            sentinel.write_text("old\n", encoding="utf-8")

            result = self.run_cli(["--experiments-root", str(root), "compile", "EXP_A"], env=env)
            self.assertEqual(result.returncode, 5)
            self.assertIn("previous compile artifacts detected", result.stderr)
            self.assertIn("crocoexp compile EXP_A --clean", result.stderr)
            self.assertTrue(sentinel.is_file())
            self.assertFalse((root / "EXP_A" / "metadata" / "compile_attempt.json").exists())

    def test_compile_clean_removes_previous_build_artifacts_safely(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            env = self.fake_docker_env(tmp, present=True)
            env["FAKE_DOCKER_RUN_CODE"] = "0"
            env["FAKE_DOCKER_WORK_OUTPUT"] = "croco"
            self.make_exp(root, data=True)
            self.install_source(tmp, root, source_id="compile-clean", env=env)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A", "--source", "compile-clean"], env=env).returncode, 0)
            exp = root / "EXP_A"
            old_object = exp / "build" / "stage" / "old.o"
            old_module = exp / "build" / "old.mod"
            old_object.parent.mkdir(parents=True, exist_ok=True)
            old_object.write_text("old\n", encoding="utf-8")
            old_module.write_text("old\n", encoding="utf-8")
            old_attempt = exp / "metadata" / "compile_attempt.json"
            old_attempt.write_text("{}\n", encoding="utf-8")
            external = Path(tmp) / "external-build-target"
            external.mkdir()
            (external / "keep.txt").write_text("keep\n", encoding="utf-8")
            link = exp / "build" / "external-link"
            link.symlink_to(external, target_is_directory=True)
            source_tree = root / "sources" / "compile-clean"
            input_before = self.input_hashes(root)

            result = self.run_cli(["--experiments-root", str(root), "compile", "EXP_A", "--clean", "--json"], env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads(result.stdout)
            self.assertEqual(summary["clean_policy"], "clean")
            self.assertFalse(old_object.exists())
            self.assertFalse(old_module.exists())
            self.assertFalse(link.exists())
            self.assertTrue((external / "keep.txt").is_file())
            self.assertEqual(input_before, self.input_hashes(root))
            self.assertTrue((exp / "metadata" / "manifest.json").is_file())
            self.assertTrue(source_tree.is_dir())
            attempt = json.loads((exp / "metadata" / "compile_attempt.json").read_text(encoding="utf-8"))
            self.assertEqual(attempt["clean_policy"], "clean")
            self.assertTrue(any("old.mod" in item for item in attempt["cleaned_artifacts"]))

    def test_compile_no_clean_keeps_previous_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            env = self.fake_docker_env(tmp, present=True)
            env["FAKE_DOCKER_RUN_CODE"] = "0"
            self.make_exp(root, data=True)
            self.install_source(tmp, root, source_id="compile-keep", env=env)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A", "--source", "compile-keep"], env=env).returncode, 0)
            sentinel = root / "EXP_A" / "build" / "stage" / "keep.o"
            sentinel.parent.mkdir(parents=True, exist_ok=True)
            sentinel.write_text("keep\n", encoding="utf-8")

            result = self.run_cli(["--experiments-root", str(root), "compile", "EXP_A", "--no-clean", "--json"], env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(sentinel.is_file())
            summary = json.loads(result.stdout)
            self.assertEqual(summary["clean_policy"], "no-clean")
            attempt = json.loads((root / "EXP_A" / "metadata" / "compile_attempt.json").read_text(encoding="utf-8"))
            self.assertEqual(attempt["clean_policy"], "no-clean")

    def test_compile_previous_artifacts_tty_abort_clean_and_keep(self):
        for choice, expected_policy in (("a\n", None), ("c\n", "clean"), ("k\n", "no-clean")):
            with self.subTest(choice=choice.strip() or "enter"):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp) / "CROCO_EXPERIMENTS"
                    env = self.fake_docker_env(tmp, present=True)
                    env["FAKE_DOCKER_RUN_CODE"] = "0"
                    self.make_exp(root, data=True)
                    self.install_source(tmp, root, source_id="compile-tty", env=env)
                    self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A", "--source", "compile-tty"], env=env).returncode, 0)
                    sentinel = root / "EXP_A" / "build" / "stage" / "tty.o"
                    sentinel.parent.mkdir(parents=True, exist_ok=True)
                    sentinel.write_text("tty\n", encoding="utf-8")

                    result = self.run_cli_pty(["--experiments-root", str(root), "compile", "EXP_A"], env=env, input_text=choice)
                    self.assertIn("Previous compile artifacts detected", result.stdout)
                    if expected_policy is None:
                        self.assertEqual(result.returncode, 5)
                        self.assertTrue(sentinel.is_file())
                        self.assertFalse((root / "EXP_A" / "metadata" / "compile_attempt.json").exists())
                    else:
                        self.assertEqual(result.returncode, 0, result.stdout)
                        attempt = json.loads((root / "EXP_A" / "metadata" / "compile_attempt.json").read_text(encoding="utf-8"))
                        self.assertEqual(attempt["clean_policy"], expected_policy)
                        self.assertEqual(sentinel.exists(), expected_policy == "no-clean")

    def test_compile_clean_no_clean_are_mutually_exclusive(self):
        result = self.run_cli(["compile", "EXP_A", "--clean", "--no-clean"])
        self.assertEqual(result.returncode, 2)
        self.assertIn("not allowed with argument", result.stderr)

    def test_compile_orphaned_source_reference_fails_clearly(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            root = repo / "CROCO_EXPERIMENTS"
            env = {"CROCOEXP_REPO_ROOT": str(repo)}
            self.make_exp(root, data=True)
            self.install_source(tmp, root, source_id="compile-orphan", env=env)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A", "--source", "compile-orphan"], env=env).returncode, 0)
            uninstall = self.run_cli(["--experiments-root", str(root), "source", "uninstall", "compile-orphan", "--force"], env=env)
            self.assertEqual(uninstall.returncode, 0, uninstall.stderr)
            result = self.run_cli(["--experiments-root", str(root), "compile", "EXP_A"], env=env)
            self.assertEqual(result.returncode, 5)
            self.assertIn("orphaned compile source reference: compile-orphan", result.stderr)
            self.assertIn("crocoexp source list", result.stderr)

    def test_compile_clean_from_deep_subdirectory_uses_repo_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            root = repo / "CROCO_EXPERIMENTS"
            env = self.fake_docker_env(tmp, present=True)
            env["CROCOEXP_REPO_ROOT"] = str(repo)
            env["FAKE_DOCKER_RUN_CODE"] = "0"
            self.make_exp(root, data=True)
            self.install_source(tmp, root, source_id="compile-deep", env=env)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A", "--source", "compile-deep"], env=env).returncode, 0)
            sentinel = root / "EXP_A" / "build" / "stage" / "deep.o"
            sentinel.parent.mkdir(parents=True, exist_ok=True)
            sentinel.write_text("deep\n", encoding="utf-8")
            deep = root / "EXP_A" / "input" / "nested"
            deep.mkdir(parents=True)

            result = self.run_cli(["compile", "EXP_A", "--clean"], cwd=deep, env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(sentinel.exists())
            self.assertTrue((root / "EXP_A" / "input" / "forcing.nc").is_file())

    def test_compile_uses_configured_image_and_falls_back_without_setup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            env = self.fake_docker_env(tmp, present=True)
            env["FAKE_DOCKER_RUN_CODE"] = "0"
            self.make_exp(root, data=True)
            self.install_source(tmp, root, source_id="image-source", env=env)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A", "--source", "image-source"], env=env).returncode, 0)
            result = self.run_cli(["--experiments-root", str(root), "compile", "EXP_A", "--no-clean", "--json"], env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["docker_image"], "domarcroco/images-for-croco:base_croco-1.0.1")
            repo = Path(env["CROCOEXP_REPO_ROOT"])
            (repo / ".crocoexp" / "config.json").write_text(json.dumps({"default_docker_image": "configured/image:tag"}) + "\n", encoding="utf-8")
            result = self.run_cli(["--experiments-root", str(root), "compile", "EXP_A", "--no-clean", "--json"], env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["docker_image"], "configured/image:tag")

    def test_compile_precondition_failures_are_clear(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=True)
            manifest_path = root / "EXP_A" / "metadata" / "manifest.json"
            manifest_path.parent.mkdir()
            manifest_path.write_text("{not json\n", encoding="utf-8")
            malformed = self.run_cli(["--experiments-root", str(root), "compile", "EXP_A"])
            self.assertEqual(malformed.returncode, 3)
            self.assertIn("malformed manifest JSON", malformed.stderr)

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            root = repo / "CROCO_EXPERIMENTS"
            env = {"CROCOEXP_REPO_ROOT": str(repo)}
            self.make_exp(root, data=True)
            self.install_source(tmp, root, source_id="deleted-registry", env=env)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A", "--source", "deleted-registry"], env=env).returncode, 0)
            os.remove(Path(env["CROCOEXP_REPO_ROOT"]) / ".crocoexp" / "sources.json")
            missing_registry = self.run_cli(["--experiments-root", str(root), "compile", "EXP_A"], env=env)
            self.assertEqual(missing_registry.returncode, 5)
            self.assertIn("deleted-registry", missing_registry.stderr)

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            root = repo / "CROCO_EXPERIMENTS"
            env = {"CROCOEXP_REPO_ROOT": str(repo)}
            self.make_exp(root, data=True)
            self.install_source(tmp, root, source_id="missing-tree", env=env)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A", "--source", "missing-tree"], env=env).returncode, 0)
            shutil.rmtree(root / "sources" / "missing-tree")
            missing_tree = self.run_cli(["--experiments-root", str(root), "compile", "EXP_A"], env=env)
            self.assertEqual(missing_tree.returncode, 5)
            self.assertIn("registered source tree is missing", missing_tree.stderr)

    def test_compile_docker_and_compile_failure_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            env = self.fake_docker_env(tmp, present=True, daemon=False)
            self.make_exp(root, data=True)
            self.install_source(tmp, root, source_id="daemon-source", env=env)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A", "--source", "daemon-source"], env=env).returncode, 0)
            daemon = self.run_cli(["--experiments-root", str(root), "compile", "EXP_A"], env=env)
            self.assertEqual(daemon.returncode, 7)
            self.assertTrue((root / "EXP_A" / "metadata" / "compile_attempt.json").exists())

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            env = self.fake_docker_env(tmp, present=True)
            env["FAKE_DOCKER_RUN_CODE"] = "2"
            self.make_exp(root, data=True)
            self.install_source(tmp, root, source_id="fail-source", env=env)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A", "--source", "fail-source"], env=env).returncode, 0)
            failed = self.run_cli(["--experiments-root", str(root), "compile", "EXP_A"], env=env)
            self.assertEqual(failed.returncode, 8)
            attempt = json.loads((root / "EXP_A" / "metadata" / "compile_attempt.json").read_text(encoding="utf-8"))
            self.assertEqual(attempt["failure_category"], "compile_failure")

    def test_compile_missing_entrypoint_invalid_names_and_missing_docker(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            root = repo / "CROCO_EXPERIMENTS"
            env = {"CROCOEXP_REPO_ROOT": str(repo)}
            self.make_exp(root, data=True)
            source = Path(tmp) / "source-without-entrypoint"
            source.mkdir()
            (source / "README").write_text("no compile entrypoint\n", encoding="utf-8")
            install = self.run_cli(["--experiments-root", str(root), "source", "install", str(source), "--id", "no-entry"], env=env)
            self.assertEqual(install.returncode, 0, install.stderr)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A", "--source", "no-entry"], env=env).returncode, 0)
            result = self.run_cli(["--experiments-root", str(root), "compile", "EXP_A"], env=env)
            self.assertEqual(result.returncode, 9)
            attempt = json.loads((root / "EXP_A" / "metadata" / "compile_attempt.json").read_text(encoding="utf-8"))
            self.assertEqual(attempt["failure_category"], "missing_compile_entrypoint")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, name="VALID")
            for name in ["", ".", "..", "bad/name", "bad\\name"]:
                invalid = self.run_cli(["--experiments-root", str(root), "compile", name])
                self.assertEqual(invalid.returncode, 2, name)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            env = self.fake_docker_env(tmp, present=True)
            self.make_exp(root, data=True)
            self.install_source(tmp, root, source_id="no-docker", env=env)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A", "--source", "no-docker"], env=env).returncode, 0)
            empty_bin = Path(tmp) / "empty-bin"
            empty_bin.mkdir()
            env["PATH"] = str(empty_bin)
            missing = self.run_cli(["--experiments-root", str(root), "compile", "EXP_A"], env=env)
            self.assertEqual(missing.returncode, 7)

    def test_help_output_includes_v1_command_surface(self):
        result = self.run_cli(["--help"])
        self.assertEqual(result.returncode, 0, result.stderr)
        for command in [
            "setup",
            "source install",
            "source list",
            "source inspect",
            "source uninstall",
            "experiment",
            "experiment list",
            "experiment unimport",
            "import",
            "inspect",
            "compile",
            "dry-run",
            "run",
        ]:
            self.assertIn(command, result.stdout)
        for unsupported in [
            "MPI execution is supported",
            "OPENACC execution is supported",
            "XIOS execution is supported",
            "OASIS execution is supported",
            "AGRIF execution is supported",
            "run.env configuration",
            "enter the Docker container",
        ]:
            self.assertNotIn(unsupported, result.stdout)

    def test_command_help_text_reflects_v1_contract(self):
        cases = [
            (["setup", "--help"], ["Docker backend readiness", "does not select a CROCO source"]),
            (["source", "--help"], ["repo-level compile source registry", ".crocoexp/sources.json"]),
            (["source", "install", "--help"], ["repo-level source registry", "does not modify experiments or input/"]),
            (["source", "list", "--help"], ["repo-level registered compile source trees"]),
            (["source", "inspect", "--help"], ["without invoking Docker or modifying experiments"]),
            (["source", "uninstall", "--help"], ["registered CROCO source", "Experiments that reference it are not modified"]),
            (["experiment", "--help"], ["repo-level experiment manifests", "list", "unimport"]),
            (["experiment", "list", "--help"], ["canonical manifest metadata", "source availability"]),
            (["experiment", "unimport", "--help"], ["preserving input/", "CROCOEXP-managed metadata"]),
            (["import", "--help"], ["input/", "metadata outside input/", "requires a registered CROCO source"]),
            (["inspect", "--help"], ["read-only summary", "does not create, rewrite, compile, dry-run, run, or modify input/"]),
            (["compile", "--help"], ["Docker-backed build attempt", "compile_time.source_ref", "outside input/", "--clean", "--no-clean"]),
            (["dry-run", "--help"], ["does not invoke Docker", "does not", "launch CROCO", "source run.env"]),
            (["run", "--help"], ["Consume metadata/dry_run_plan.json", "relative symlinks to input/", "serial/OpenMP"]),
        ]
        for args, expected_fragments in cases:
            with self.subTest(args=args):
                result = self.run_cli(args)
                self.assertEqual(result.returncode, 0, result.stderr)
                for fragment in expected_fragments:
                    self.assertIn(fragment, result.stdout)
                for unsupported in [
                    "MPI execution is supported",
                    "OPENACC execution is supported",
                    "XIOS execution is supported",
                    "OASIS execution is supported",
                    "AGRIF execution is supported",
                    "run.env configuration",
                    "enter the Docker container",
                ]:
                    self.assertNotIn(unsupported, result.stdout)
        dry_help = self.run_cli(["dry-run", "--help"]).stdout
        run_help = self.run_cli(["run", "--help"]).stdout
        self.assertNotIn("--image", dry_help)
        self.assertNotIn("--no-docker", dry_help)
        self.assertNotIn("--image", run_help)
        self.assertNotIn("--require-dry-run", run_help)

    def test_setup_docker_image_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = self.fake_docker_env(tmp, present=True)
            result = self.run_cli(["setup", "--json"], env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            repo = Path(env["CROCOEXP_REPO_ROOT"])
            config = json.loads((repo / ".crocoexp" / "config.json").read_text(encoding="utf-8"))
            self.assertTrue(config["docker_cli_detected"])
            self.assertTrue(config["docker_daemon_ok"])
            self.assertTrue(config["image_present_locally"])
            self.assertIn(config["setup_status"], {"ready", "ready_with_warnings"})
            self.assertTrue((repo / ".crocoexp" / "setup_report.md").exists())

    def test_setup_human_output_includes_required_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = self.fake_docker_env(tmp, present=True)
            result = self.run_cli(["setup"], env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            for text in [
                "Docker CLI detected: yes",
                "Docker daemon available: yes",
                "Selected Docker image:",
                "Previous default image:",
                "Image present locally: yes",
                "Image pull attempted: no",
                "Setup config path:",
                "Setup report path:",
                "Warning count:",
                "Failure category:",
            ]:
                self.assertIn(text, result.stdout)
            self.assertNotIn("enter", result.stdout.lower())
            self.assertNotIn("container manually", result.stdout.lower())

    def test_setup_json_output_is_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = self.fake_docker_env(tmp, present=True)
            result = self.run_cli(["setup", "--json"], env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads(result.stdout)
            self.assertEqual(summary["default_docker_image"], "domarcroco/images-for-croco:base_croco-1.0.1")

    def test_setup_does_not_touch_experiment_input_or_source_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            exp = self.make_exp(root, data=True)
            input_dir = exp / "input"
            before = {
                p.relative_to(input_dir): p.read_bytes()
                for p in sorted(input_dir.rglob("*"))
                if p.is_file()
            }
            env = self.fake_docker_env(tmp, present=True)
            result = self.run_cli(["--experiments-root", str(root), "setup"], env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            after = {
                p.relative_to(input_dir): p.read_bytes()
                for p in sorted(input_dir.rglob("*"))
                if p.is_file()
            }
            self.assertEqual(after, before)
            repo = Path(env["CROCOEXP_REPO_ROOT"])
            self.assertTrue((repo / ".crocoexp" / "config.json").exists())
            self.assertTrue((repo / ".crocoexp" / "setup_report.md").exists())
            self.assertFalse((repo / ".crocoexp" / "sources.json").exists())
            self.assertFalse((root / "sources").exists())
            self.assertFalse((exp / "build").exists())
            self.assertFalse((exp / "runs").exists())

    def test_setup_missing_docker_cli_fails_as_backend_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            empty_bin = Path(tmp) / "empty-bin"
            repo.mkdir()
            empty_bin.mkdir()
            result = self.run_cli(["setup"], env={"CROCOEXP_REPO_ROOT": str(repo), "PATH": str(empty_bin)})
            self.assertEqual(result.returncode, 7)
            config = json.loads((repo / ".crocoexp" / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(config["failure_category"], "docker_cli_missing")

    def test_setup_docker_daemon_unavailable_fails_as_backend_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = self.fake_docker_env(tmp, present=True, daemon=False)
            result = self.run_cli(["setup"], env=env)
            self.assertEqual(result.returncode, 7)
            config = json.loads((Path(env["CROCOEXP_REPO_ROOT"]) / ".crocoexp" / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(config["failure_category"], "docker_daemon_unavailable")

    def test_setup_image_missing_without_pull_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = self.fake_docker_env(tmp, present=False)
            result = self.run_cli(["setup", "--no-pull"], env=env)
            self.assertEqual(result.returncode, 7)
            repo = Path(env["CROCOEXP_REPO_ROOT"])
            config = json.loads((repo / ".crocoexp" / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(config["failure_category"], "image_missing")
            self.assertEqual(config["setup_status"], "blocked_image_missing")

    def test_setup_image_missing_defaults_to_no_pull_and_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = self.fake_docker_env(tmp, present=False)
            result = self.run_cli(["setup"], env=env)
            self.assertEqual(result.returncode, 7)
            config = json.loads((Path(env["CROCOEXP_REPO_ROOT"]) / ".crocoexp" / "config.json").read_text(encoding="utf-8"))
            self.assertFalse(config["pull_attempted"])
            self.assertEqual(config["failure_category"], "image_missing")

    def test_setup_image_missing_with_pull(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = self.fake_docker_env(tmp, present=False, pull_ok=True)
            result = self.run_cli(["setup", "--pull"], env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            repo = Path(env["CROCOEXP_REPO_ROOT"])
            config = json.loads((repo / ".crocoexp" / "config.json").read_text(encoding="utf-8"))
            self.assertTrue(config["image_pulled"])
            self.assertTrue(config["image_present_locally"])

    def test_setup_explicit_image_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = self.fake_docker_env(tmp, present=True)
            result = self.run_cli(["setup", "--image", "example/custom:tag"], env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            repo = Path(env["CROCOEXP_REPO_ROOT"])
            config = json.loads((repo / ".crocoexp" / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(config["default_docker_image"], "example/custom:tag")

    def test_setup_incompatible_pull_flags_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = self.fake_docker_env(tmp, present=True)
            result = self.run_cli(["setup", "--pull", "--no-pull"], env=env)
            self.assertEqual(result.returncode, 2)

    def test_setup_write_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = self.fake_docker_env(tmp, present=True)
            repo = Path(env["CROCOEXP_REPO_ROOT"])
            repo.mkdir()
            (repo / ".crocoexp").write_text("not a directory", encoding="utf-8")
            result = self.run_cli(["setup"], env=env)
            self.assertEqual(result.returncode, 4)
            self.assertIn("unable to write setup config/report", result.stderr)

    def test_compile_uses_setup_default_image_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=True)
            env = self.fake_docker_env(tmp, present=True)
            self.install_source(tmp, root, env=env)
            setup_result = self.run_cli(["setup", "--image", "configured/image:tag"], env=env)
            self.assertEqual(setup_result.returncode, 0, setup_result.stderr)
            import_result = self.run_cli(["--experiments-root", str(root), "import", "EXP_A", "--source", "croco-test"], env=env)
            self.assertEqual(import_result.returncode, 0, import_result.stderr)
            compile_result = self.run_cli(["--experiments-root", str(root), "compile", "EXP_A"], env=env)
            self.assertEqual(compile_result.returncode, 7)
            manifest = json.loads((root / "EXP_A" / "metadata" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["docker_backend"]["image"], "configured/image:tag")

    def test_dry_run_after_import_without_compile_attempt_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=True)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"]).returncode, 0)
            result = self.run_cli(["--experiments-root", str(root), "dry-run", "EXP_A", "--no-docker", "--run-id", "DRY1"])
            self.assertEqual(result.returncode, 10)
            self.assertIn("missing successful compile attempt", result.stderr)

    def test_dry_run_precondition_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root)
            missing = self.run_cli(["--experiments-root", str(root), "dry-run", "EXP_A"])
            self.assertEqual(missing.returncode, 3)
            self.assertIn("run 'crocoexp import EXP_A' first", missing.stderr)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            exp = self.make_exp(root)
            (exp / "metadata").mkdir()
            (exp / "metadata" / "manifest.json").write_text("{not json\n", encoding="utf-8")
            malformed = self.run_cli(["--experiments-root", str(root), "dry-run", "EXP_A"])
            self.assertEqual(malformed.returncode, 3)
            self.assertIn("malformed manifest JSON", malformed.stderr)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"]).returncode, 0)
            self.seed_compile_attempt(root, status="failed")
            failed = self.run_cli(["--experiments-root", str(root), "dry-run", "EXP_A"])
            self.assertEqual(failed.returncode, 10)
            self.assertIn("latest compile attempt did not succeed", failed.stderr)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"]).returncode, 0)
            self.seed_compile_attempt(root, binary=False)
            no_binary = self.run_cli(["--experiments-root", str(root), "dry-run", "EXP_A"])
            self.assertEqual(no_binary.returncode, 10)
            self.assertIn("no recorded binary path", no_binary.stderr)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"]).returncode, 0)
            attempt = self.seed_compile_attempt(root)
            os.remove(attempt["binary"]["path"])
            missing_binary = self.run_cli(["--experiments-root", str(root), "dry-run", "EXP_A"])
            self.assertEqual(missing_binary.returncode, 10)
            self.assertIn("recorded compile binary is missing", missing_binary.stderr)

    def test_dry_run_rejects_invalid_experiment_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, name="VALID")
            for name in ["", ".", "..", "bad/name", "bad\\name"]:
                result = self.run_cli(["--experiments-root", str(root), "dry-run", name])
                self.assertEqual(result.returncode, 2, name)

    def test_dry_run_records_report_and_snapshots_without_nc_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, analytical=True, data=True)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"]).returncode, 0)
            self.seed_compile_attempt(root)
            result = self.run_cli(["--experiments-root", str(root), "dry-run", "EXP_A", "--no-docker", "--run-id", "DRY2"])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((root / "EXP_A" / "metadata" / "dry_run_plan.json").exists())
            self.assertTrue((root / "EXP_A" / "metadata" / "dry_run_report.md").exists())
            self.assertFalse((root / "EXP_A" / "runs" / "DRY2" / "work").exists())
            self.assertTrue((root / "EXP_A" / "metadata" / "report.md").exists())
            report = (root / "EXP_A" / "metadata" / "dry_run_report.md").read_text(encoding="utf-8")
            self.assertIn("Dry-run does not launch CROCO", report)
            self.assertIn("does not prove scientific correctness", report)

    def test_dry_run_placeholder_names_not_required_by_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            text = "TITLE == analytical\nGRDNAME == GRD/@GRD_FILE@\nININAME == INIT/@INI_FILE@\nFRCNAME == FORC/@FRC_FILE@\n"
            self.make_exp(root, analytical=True, croco_text=text)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"]).returncode, 0)
            self.seed_compile_attempt(root)
            result = self.run_cli(["--experiments-root", str(root), "dry-run", "EXP_A", "--no-docker", "--run-id", "DRY3"])
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((root / "EXP_A" / "metadata" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["assets"]["classification_counts"].get("required", 0), 0)

    def test_dry_run_reports_runtime_data_symlink_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=False, croco_text="TITLE == test\nDATA == any syntax\n")
            self.add_nested_data(root)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"]).returncode, 0)
            self.seed_compile_attempt(root)
            result = self.run_cli(["--experiments-root", str(root), "dry-run", "EXP_A", "--no-docker", "--run-id", "DRY4"])
            self.assertEqual(result.returncode, 0, result.stderr)
            json_result = self.run_cli(["--experiments-root", str(root), "dry-run", "EXP_A", "--json", "--run-id", "DRY4JSON"])
            self.assertEqual(json_result.returncode, 0, json_result.stderr)
            self.assertIn("dry_run_plan", json.loads(json_result.stdout))
            manifest = json.loads((root / "EXP_A" / "metadata" / "manifest.json").read_text(encoding="utf-8"))
            symlinks = manifest["runtime_materialization"]["symlinked_runtime_data"]
            self.assertEqual({s["source_relative_path_from_input"] for s in symlinks}, {"GRD/grid.nc", "INIT/init.nc"})
            self.assertFalse(manifest["reporting"]["ambiguities"])
            self.assertEqual(manifest["assets"]["classification_counts"].get("ambiguous", 0), 0)
            report = (root / "EXP_A" / "runs" / "DRY4" / "reports" / "dry_run_report.md").read_text(encoding="utf-8")
            self.assertIn("Symlink Plan", report)
            self.assertNotIn("Required Assets Selected For Staging/Mounting", report)
            plan = json.loads((root / "EXP_A" / "metadata" / "dry_run_plan.json").read_text(encoding="utf-8"))
            self.assertTrue(plan["runtime_materialization"]["symlinks"])
            self.assertFalse(plan["runtime_materialization"]["symlinks"][0]["target_path"].startswith("/"))
            self.assertEqual(plan["status"], "planned")

    def test_dry_run_missing_referenced_asset_does_not_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=False)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"]).returncode, 0)
            self.seed_compile_attempt(root)
            result = self.run_cli(["--experiments-root", str(root), "dry-run", "EXP_A", "--no-docker", "--run-id", "DRY5"])
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((root / "EXP_A" / "metadata" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["runtime_materialization"]["symlinked_runtime_data"], [])
            self.assertEqual(manifest["reporting"]["infrastructural_blockers"], [])

    def test_dry_run_possible_mismatch_reported_not_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, analytical=True, data=True)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"]).returncode, 0)
            self.seed_compile_attempt(root)
            result = self.run_cli(["--experiments-root", str(root), "dry-run", "EXP_A", "--no-docker", "--run-id", "DRY6"])
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((root / "EXP_A" / "metadata" / "manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["reporting"]["possible_mismatches"])

    def test_dry_run_unrecognized_croco_syntax_is_opaque(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=True, croco_text="TITLE == test\nDATA == forcing.nc\n")
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"]).returncode, 0)
            self.seed_compile_attempt(root)
            result = self.run_cli(["--experiments-root", str(root), "dry-run", "EXP_A", "--no-docker", "--run-id", "DRY7"])
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((root / "EXP_A" / "metadata" / "manifest.json").read_text(encoding="utf-8"))
            self.assertFalse(manifest["reporting"]["ambiguities"])
            self.assertEqual(manifest["assets"]["classification_counts"].get("ambiguous", 0), 0)
            self.assertEqual(manifest["runtime_materialization"]["symlinked_runtime_data"][0]["source_relative_path_from_input"], "forcing.nc")

    def test_old_and_new_style_croco_in_pass_dry_run_opaque(self):
        cases = {
            "OLD": "GRDNAME == GRD/grid.nc\nININAME == INIT/init.nc\n",
            "NEW": "grid: filename\nGRD/grid.nc\ninitial: NRREC filename\n0\nINIT/init.nc\n",
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            for name, text in cases.items():
                self.make_exp(root, name=name, croco_text=text)
                self.add_nested_data(root, name=name)
                self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", name]).returncode, 0)
                self.seed_compile_attempt(root, name=name)
                result = self.run_cli(["--experiments-root", str(root), "dry-run", name, "--no-docker", "--run-id", "DRY"])
                self.assertEqual(result.returncode, 0, result.stderr)
                manifest = json.loads((root / name / "metadata" / "manifest.json").read_text(encoding="utf-8"))
                self.assertFalse(manifest["reporting"]["ambiguities"])
                self.assertEqual(len(manifest["runtime_materialization"]["symlinked_runtime_data"]), 2)

    def test_dry_run_does_not_invoke_docker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=True)
            env = self.fake_docker_env(tmp, present=True)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"], env=env).returncode, 0)
            self.seed_compile_attempt(root)
            env["FAKE_DOCKER_DAEMON"] = "0"
            result = self.run_cli(["--experiments-root", str(root), "dry-run", "EXP_A", "--run-id", "DRY8"], env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((root / "EXP_A" / "metadata" / "manifest.json").read_text(encoding="utf-8"))
            self.assertIsNone(manifest["reporting"].get("backend_outcome"))

    def test_dry_run_profiles_and_parameters(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=True)
            self.write_cppdefs_param(
                root,
                cppdefs="#define OPENMP\n",
                param="parameter (NPP=8)\nparameter (NSUB_X=2, NSUB_E=4)\n",
            )
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"]).returncode, 0)
            self.seed_compile_attempt(root)
            result = self.run_cli(["--experiments-root", str(root), "dry-run", "EXP_A", "--json"])
            self.assertEqual(result.returncode, 0, result.stderr)
            plan = json.loads((root / "EXP_A" / "metadata" / "dry_run_plan.json").read_text(encoding="utf-8"))
            execution = plan["runtime_execution_plan"]
            self.assertEqual(execution["profile"], "openmp")
            self.assertEqual(execution["environment"]["OMP_NUM_THREADS"], "8")
            self.assertEqual(execution["parsed_parameters"]["NPP"], 8)
            self.assertEqual(execution["parsed_parameters"]["NSUB_X"], 2)
            self.assertEqual(execution["parsed_parameters"]["NSUB_E"], 4)
            self.assertEqual(execution["parsed_parameters"]["NP_XI"], "unknown")
            self.assertEqual(execution["parsed_parameters"]["NP_ETA"], "unknown")
            self.assertEqual(execution["parsed_parameters"]["NNODES"], "unknown")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=True)
            self.write_cppdefs_param(root, cppdefs="#define MPI\n", param="parameter (NNODES=4)\n")
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"]).returncode, 0)
            self.seed_compile_attempt(root)
            result = self.run_cli(["--experiments-root", str(root), "dry-run", "EXP_A"])
            self.assertEqual(result.returncode, 11)
            plan = json.loads((root / "EXP_A" / "metadata" / "dry_run_plan.json").read_text(encoding="utf-8"))
            self.assertEqual(plan["runtime_execution_plan"]["profile"], "unsupported")
            self.assertTrue(plan["blockers"])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=True)
            self.write_cppdefs_param(root, cppdefs="#define XIOS\n", param="parameter (NPP=1)\n")
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"]).returncode, 0)
            self.seed_compile_attempt(root)
            result = self.run_cli(["--experiments-root", str(root), "dry-run", "EXP_A"])
            self.assertEqual(result.returncode, 11)
            plan = json.loads((root / "EXP_A" / "metadata" / "dry_run_plan.json").read_text(encoding="utf-8"))
            self.assertEqual(plan["runtime_execution_plan"]["profile"], "unsupported")

    def test_run_requires_imported_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=True)
            result = self.run_cli(["--experiments-root", str(root), "run", "EXP_A"])
            self.assertEqual(result.returncode, 3)
            self.assertIn("manifest", result.stderr)

    def test_run_fails_when_root_or_input_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            result = self.run_cli(["--experiments-root", str(root), "run", "MISSING"])
            self.assertEqual(result.returncode, 6)
            self.assertIn("experiment", result.stderr)
            exp = root / "EXP_A"
            (exp / "metadata").mkdir(parents=True)
            (exp / "metadata" / "manifest.json").write_text("{}", encoding="utf-8")
            result = self.run_cli(["--experiments-root", str(root), "run", "EXP_A"])
            self.assertEqual(result.returncode, 6)
            self.assertIn("input", result.stderr)

    def test_run_fails_when_manifest_is_malformed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=True)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"]).returncode, 0)
            (root / "EXP_A" / "metadata" / "manifest.json").write_text("{bad json", encoding="utf-8")
            result = self.run_cli(["--experiments-root", str(root), "run", "EXP_A"])
            self.assertEqual(result.returncode, 3)
            self.assertIn("malformed", result.stderr)

    def test_run_requires_dry_run_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=True)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"]).returncode, 0)
            self.seed_compile_attempt(root)
            result = self.run_cli(["--experiments-root", str(root), "run", "EXP_A", "--run-id", "RUN1"])
            self.assertEqual(result.returncode, 3)
            self.assertIn("dry-run", result.stderr)

    def test_run_fails_when_dry_run_plan_is_malformed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=True)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"]).returncode, 0)
            (root / "EXP_A" / "metadata" / "dry_run_plan.json").write_text("{bad json", encoding="utf-8")
            result = self.run_cli(["--experiments-root", str(root), "run", "EXP_A", "--run-id", "RUN1"])
            self.assertEqual(result.returncode, 3)
            self.assertIn("malformed dry-run", result.stderr)

    def test_run_fails_when_binary_metadata_or_path_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=True)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"]).returncode, 0)
            dry, _ = self.prepare_dry_run_plan(root, run_id="RUNBIN")
            self.assertEqual(dry.returncode, 0, dry.stderr)
            plan_path = root / "EXP_A" / "metadata" / "dry_run_plan.json"
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            binary_path = Path(plan["binary_path"])
            if not binary_path.is_absolute():
                binary_path = Path(tmp) / binary_path
            binary_path.unlink()
            result = self.run_cli(["--experiments-root", str(root), "run", "EXP_A", "--run-id", "RUNBIN"])
            self.assertEqual(result.returncode, 10)
            self.assertIn("binary", result.stderr)
            binary = self.add_binary(root)
            plan["binary_path"] = ""
            plan["runtime_execution_plan"].pop("binary_path", None)
            plan_path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            binary.unlink()
            result = self.run_cli(["--experiments-root", str(root), "run", "EXP_A", "--run-id", "RUNBIN2"])
            self.assertEqual(result.returncode, 10)
            self.assertIn("binary", result.stderr)

    def test_run_rejects_invalid_experiment_names_and_run_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            for name in (".", "..", "bad/name", r"bad\name"):
                result = self.run_cli(["--experiments-root", str(root), "run", name])
                self.assertEqual(result.returncode, 2, name)
            self.make_exp(root, data=True)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"]).returncode, 0)
            for run_id in (".", "..", "bad/id", r"bad\id"):
                result = self.run_cli(["--experiments-root", str(root), "run", "EXP_A", "--run-id", run_id])
                self.assertEqual(result.returncode, 2, run_id)

    def test_run_materializes_workdir_records_attempt_and_preserves_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, analytical=True, data=True)
            self.add_nested_data(root)
            env = self.fake_docker_env(tmp, present=True)
            env["FAKE_DOCKER_RUN_CODE"] = "0"
            env["FAKE_DOCKER_WORK_OUTPUT"] = "HIS/history.nc"
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"], env=env).returncode, 0)
            dry, attempt = self.prepare_dry_run_plan(root, run_id="RUN2", env=env)
            self.assertEqual(dry.returncode, 0, dry.stderr)
            input_before = {p.relative_to(root / "EXP_A" / "input"): p.read_bytes() for p in (root / "EXP_A" / "input").rglob("*") if p.is_file()}
            result = self.run_cli(["--experiments-root", str(root), "run", "EXP_A", "--run-id", "RUN2", "--json"], env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads(result.stdout)
            self.assertEqual(summary["run_id"], "RUN2")
            run_dir = root / "EXP_A" / "runs" / "RUN2"
            for dirname in ("work", "output", "logs", "snapshots", "reports"):
                self.assertTrue((run_dir / dirname).is_dir())
            self.assertTrue((run_dir / "reports" / "run_attempt.json").is_file())
            self.assertTrue((run_dir / "reports" / "run_report.md").is_file())
            self.assertTrue((run_dir / "logs" / "run_stdout.log").is_file())
            self.assertTrue((run_dir / "logs" / "run_stderr.log").is_file())
            self.assertTrue((run_dir / "work" / "croco").is_symlink())
            self.assertTrue((run_dir / "work" / "croco.in").is_symlink())
            self.assertTrue((run_dir / "work" / "forcing.nc").is_symlink())
            self.assertTrue((run_dir / "work" / "GRD" / "grid.nc").is_symlink())
            self.assertFalse(os.readlink(run_dir / "work" / "GRD" / "grid.nc").startswith("/"))
            self.assertEqual((run_dir / "work" / "GRD" / "grid.nc").resolve(), root / "EXP_A" / "input" / "GRD" / "grid.nc")
            self.assertFalse((run_dir / "snapshots" / "forcing.nc").exists())
            self.assertTrue((run_dir / "snapshots" / "manifest.json").is_file())
            self.assertTrue((run_dir / "snapshots" / "dry_run_plan.json").is_file())
            self.assertTrue((run_dir / "snapshots" / "compile_attempt.json").is_file())
            self.assertTrue((run_dir / "snapshots" / "cppdefs.h").is_file())
            self.assertTrue((run_dir / "work" / "HIS" / "history.nc").is_file())
            input_after = {p.relative_to(root / "EXP_A" / "input"): p.read_bytes() for p in (root / "EXP_A" / "input").rglob("*") if p.is_file()}
            self.assertEqual(input_before, input_after)
            manifest = json.loads((root / "EXP_A" / "metadata" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["runs"]["last_run_id"], "RUN2")
            self.assertEqual(manifest["runs"]["last_attempt"]["status"], "success")
            self.assertEqual(manifest["reporting"]["run_outcome"]["failure_category"], "none")
            self.assertEqual(manifest["commands"][-1]["command"], "run")
            attempt_json = json.loads((run_dir / "reports" / "run_attempt.json").read_text(encoding="utf-8"))
            self.assertEqual(attempt_json["docker_image"], attempt["docker_image"])
            self.assertEqual(attempt_json["profile"], "serial")
            self.assertTrue(attempt_json["outputs"])
            self.assertIn("docker", attempt_json["docker_command"][0])
            report = (run_dir / "reports" / "run_report.md").read_text(encoding="utf-8")
            self.assertIn("Run success does not prove scientific correctness", report)

    def test_run_openmp_profile_sets_environment_from_dry_run_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=True)
            self.write_cppdefs_param(root, cppdefs="#define OPENMP\n", param="parameter (NPP=8)\n")
            env = self.fake_docker_env(tmp, present=True)
            env["FAKE_DOCKER_RUN_CODE"] = "0"
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"], env=env).returncode, 0)
            dry, _ = self.prepare_dry_run_plan(root, run_id="OMP8", env=env)
            self.assertEqual(dry.returncode, 0, dry.stderr)
            result = self.run_cli(["--experiments-root", str(root), "run", "EXP_A", "--run-id", "OMP8"], env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            run_dir = root / "EXP_A" / "runs" / "OMP8"
            attempt = json.loads((run_dir / "reports" / "run_attempt.json").read_text(encoding="utf-8"))
            self.assertEqual(attempt["profile"], "openmp")
            self.assertIn("-e", attempt["docker_command"])
            self.assertIn("OMP_NUM_THREADS=8", attempt["docker_command"])
            self.assertIn("export OMP_NUM_THREADS=8", (run_dir / "work" / "run_inside_docker.sh").read_text(encoding="utf-8"))

    def test_run_blocks_unsupported_profile_before_docker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=True)
            self.write_cppdefs_param(root, cppdefs="#define MPI\n", param="parameter (NNODES=4)\n")
            env = self.fake_docker_env(tmp, present=True)
            env["FAKE_DOCKER_RUN_CODE"] = "0"
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"], env=env).returncode, 0)
            dry, _ = self.prepare_dry_run_plan(root, run_id="MPIBLOCK", env=env)
            self.assertEqual(dry.returncode, 11)
            result = self.run_cli(["--experiments-root", str(root), "run", "EXP_A", "--run-id", "MPIBLOCK"], env=env)
            self.assertEqual(result.returncode, 11)
            self.assertIn("blocked", result.stderr)
            self.assertFalse((root / "EXP_A" / "runs" / "MPIBLOCK" / "work" / "run_inside_docker.sh").exists())

    def test_run_missing_runtime_asset_is_materialization_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=True)
            env = self.fake_docker_env(tmp, present=True)
            env["FAKE_DOCKER_RUN_CODE"] = "0"
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"], env=env).returncode, 0)
            dry, _ = self.prepare_dry_run_plan(root, run_id="MISSASSET", env=env)
            self.assertEqual(dry.returncode, 0, dry.stderr)
            (root / "EXP_A" / "input" / "forcing.nc").unlink()
            result = self.run_cli(["--experiments-root", str(root), "run", "EXP_A", "--run-id", "MISSASSET"], env=env)
            self.assertEqual(result.returncode, 12)
            run_dir = root / "EXP_A" / "runs" / "MISSASSET"
            self.assertFalse((run_dir / "work" / "run_inside_docker.sh").exists())
            self.assertNotIn("fake docker run", (run_dir / "logs" / "run_stdout.log").read_text(encoding="utf-8"))
            attempt = json.loads((run_dir / "reports" / "run_attempt.json").read_text(encoding="utf-8"))
            self.assertEqual(attempt["failure_category"], "materialization_failed")
            self.assertTrue(attempt["blockers"])

    def test_run_missing_materialization_plan_maps_to_exit_12(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=True)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"]).returncode, 0)
            dry, _ = self.prepare_dry_run_plan(root, run_id="NOMAT")
            self.assertEqual(dry.returncode, 0, dry.stderr)
            plan_path = root / "EXP_A" / "metadata" / "dry_run_plan.json"
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan.pop("runtime_materialization")
            plan_path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            result = self.run_cli(["--experiments-root", str(root), "run", "EXP_A", "--run-id", "NOMAT"])
            self.assertEqual(result.returncode, 12)
            self.assertIn("materialization", result.stderr)

    def test_run_docker_backend_failures_and_nonzero_execution_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=True)
            env = {"PATH": str(Path(tmp) / "empty-bin"), "CROCOEXP_REPO_ROOT": str(Path(tmp) / "repo")}
            Path(env["PATH"]).mkdir()
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"], env=env).returncode, 0)
            dry, _ = self.prepare_dry_run_plan(root, run_id="NODOCKER", env=env)
            self.assertEqual(dry.returncode, 0, dry.stderr)
            result = self.run_cli(["--experiments-root", str(root), "run", "EXP_A", "--run-id", "NODOCKER"], env=env)
            self.assertEqual(result.returncode, 7)
            attempt = json.loads((root / "EXP_A" / "runs" / "NODOCKER" / "reports" / "run_attempt.json").read_text(encoding="utf-8"))
            self.assertEqual(attempt["failure_category"], "docker_backend")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=True)
            env = self.fake_docker_env(tmp, present=True, daemon=False)
            env["FAKE_DOCKER_RUN_CODE"] = "0"
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"], env=env).returncode, 0)
            dry, _ = self.prepare_dry_run_plan(root, run_id="DAEMON", env=env)
            self.assertEqual(dry.returncode, 0, dry.stderr)
            result = self.run_cli(["--experiments-root", str(root), "run", "EXP_A", "--run-id", "DAEMON"], env=env)
            self.assertEqual(result.returncode, 7)
            attempt = json.loads((root / "EXP_A" / "runs" / "DAEMON" / "reports" / "run_attempt.json").read_text(encoding="utf-8"))
            self.assertEqual(attempt["failure_category"], "docker_backend")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=True)
            env = self.fake_docker_env(tmp, present=True)
            env["FAKE_DOCKER_RUN_CODE"] = "9"
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"], env=env).returncode, 0)
            dry, _ = self.prepare_dry_run_plan(root, run_id="NONZERO", env=env)
            self.assertEqual(dry.returncode, 0, dry.stderr)
            result = self.run_cli(["--experiments-root", str(root), "run", "EXP_A", "--run-id", "NONZERO"], env=env)
            self.assertEqual(result.returncode, 13)
            manifest = json.loads((root / "EXP_A" / "metadata" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["reporting"]["run_outcome"]["failure_category"], "run_failure")

    def test_acceptance_full_mocked_workflow_traceability(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            env = self.fake_docker_env(tmp, present=False)
            env["FAKE_DOCKER_RUN_CODE"] = "0"
            self.make_exp(root, name="minimal", data=True)
            setup = self.run_cli(
                [
                    "--experiments-root",
                    str(root),
                    "setup",
                    "--image",
                    "domarcroco/images-for-croco:base_croco-1.0.1",
                    "--pull",
                ],
                env=env,
            )
            self.assertEqual(setup.returncode, 0, setup.stderr)
            repo = Path(env["CROCOEXP_REPO_ROOT"])
            self.assertTrue((repo / ".crocoexp" / "config.json").is_file())
            self.assertTrue((repo / ".crocoexp" / "setup_report.md").is_file())
            self.assertFalse((repo / ".crocoexp" / "sources.json").exists())

            self.install_source(tmp, root, source_id="croco-local", env=env)
            self.assertTrue((repo / ".crocoexp" / "sources.json").is_file())
            self.assertTrue((root / "sources" / "croco-local").is_dir())

            imported = self.run_cli(["--experiments-root", str(root), "import", "minimal", "--source", "croco-local"], env=env)
            self.assertEqual(imported.returncode, 0, imported.stderr)
            inspected = self.run_cli(["--experiments-root", str(root), "inspect", "minimal"], env=env)
            self.assertEqual(inspected.returncode, 0, inspected.stderr)
            env["FAKE_DOCKER_WORK_OUTPUT"] = "croco"
            compiled = self.run_cli(["--experiments-root", str(root), "compile", "minimal"], env=env)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            env.pop("FAKE_DOCKER_WORK_OUTPUT")
            dry = self.run_cli(["--experiments-root", str(root), "dry-run", "minimal"], env=env)
            self.assertEqual(dry.returncode, 0, dry.stderr)
            env["FAKE_DOCKER_WORK_OUTPUT"] = "HIS/history.nc"
            ran = self.run_cli(["--experiments-root", str(root), "run", "minimal", "--run-id", "test-run-001"], env=env)
            self.assertEqual(ran.returncode, 0, ran.stderr)

            exp = root / "minimal"
            expected = [
                root / "sources" / "croco-local",
                exp / "input",
                exp / "metadata" / "manifest.json",
                exp / "metadata" / "report.md",
                exp / "metadata" / "compile_attempt.json",
                exp / "metadata" / "compile_report.md",
                exp / "metadata" / "dry_run_plan.json",
                exp / "metadata" / "dry_run_report.md",
                exp / "runs" / "test-run-001" / "work",
                exp / "runs" / "test-run-001" / "output",
                exp / "runs" / "test-run-001" / "logs",
                exp / "runs" / "test-run-001" / "snapshots",
                exp / "runs" / "test-run-001" / "reports" / "run_attempt.json",
                exp / "runs" / "test-run-001" / "reports" / "run_report.md",
            ]
            for path in expected:
                self.assertTrue(path.exists(), str(path))
            manifest = json.loads((exp / "metadata" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["compile_time"]["source_ref"]["source_id"], "croco-local")
            self.assertEqual(manifest["compile"]["last_attempt"]["source_id"], "croco-local")
            self.assertEqual(manifest["runs"]["last_run_id"], "test-run-001")
            self.assertFalse((exp / "input" / "croco-local").exists())

    def test_acceptance_input_immutable_across_import_inspect_compile_dry_run_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            env = self.fake_docker_env(tmp, present=True)
            env["FAKE_DOCKER_RUN_CODE"] = "0"
            self.make_exp(root, name="minimal", data=True)
            (root / "minimal" / "input" / "run.env").write_text("SHOULD_NOT_BE_USED=changed.nc\n", encoding="utf-8")
            self.install_source(tmp, root, source_id="immutable-source", env=env)
            before = self.input_hashes(root, "minimal")
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "minimal", "--source", "immutable-source"], env=env).returncode, 0)
            self.assertEqual(self.input_hashes(root, "minimal"), before)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "inspect", "minimal"], env=env).returncode, 0)
            self.assertEqual(self.input_hashes(root, "minimal"), before)
            env["FAKE_DOCKER_WORK_OUTPUT"] = "croco"
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "compile", "minimal"], env=env).returncode, 0)
            self.assertEqual(self.input_hashes(root, "minimal"), before)
            env.pop("FAKE_DOCKER_WORK_OUTPUT")
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "dry-run", "minimal", "--run-id", "IMMUTABLE"], env=env).returncode, 0)
            self.assertEqual(self.input_hashes(root, "minimal"), before)
            env["FAKE_DOCKER_WORK_OUTPUT"] = "ocean_his.nc"
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "run", "minimal", "--run-id", "IMMUTABLE"], env=env).returncode, 0)
            self.assertEqual(self.input_hashes(root, "minimal"), before)
            attempt = json.loads((root / "minimal" / "runs" / "IMMUTABLE" / "reports" / "run_attempt.json").read_text(encoding="utf-8"))
            self.assertNotIn("changed.nc", json.dumps(attempt))

    def test_acceptance_runtime_data_extensions_stay_canonical_and_symlinked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            env = self.fake_docker_env(tmp, present=True)
            env["FAKE_DOCKER_RUN_CODE"] = "0"
            exp = self.make_exp(root, data=False, croco_text="TITLE == test\nFRCNAME == missing_from_croco_in.nc\n")
            for name in ("grid.nc", "history.nc4", "restart.cdf", "clim.netcdf"):
                (exp / "input" / name).write_bytes(name.encode("utf-8"))
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"], env=env).returncode, 0)
            dry, _ = self.prepare_dry_run_plan(root, run_id="DATAEXT", env=env)
            self.assertEqual(dry.returncode, 0, dry.stderr)
            plan = json.loads((root / "EXP_A" / "metadata" / "dry_run_plan.json").read_text(encoding="utf-8"))
            self.assertEqual({s["asset_path"] for s in plan["runtime_materialization"]["symlinks"]}, {f"input/{n}" for n in ("grid.nc", "history.nc4", "restart.cdf", "clim.netcdf")})
            self.assertNotIn("missing_from_croco_in.nc", json.dumps(plan))
            ran = self.run_cli(["--experiments-root", str(root), "run", "EXP_A", "--run-id", "DATAEXT"], env=env)
            self.assertEqual(ran.returncode, 0, ran.stderr)
            work = root / "EXP_A" / "runs" / "DATAEXT" / "work"
            for name in ("grid.nc", "history.nc4", "restart.cdf", "clim.netcdf"):
                link = work / name
                self.assertTrue(link.is_symlink(), name)
                self.assertFalse(os.readlink(link).startswith("/"), name)
                self.assertEqual(link.resolve(), root / "EXP_A" / "input" / name)
            self.assertFalse((root / "EXP_A" / "runs" / "DATAEXT" / "snapshots" / "grid.nc").exists())
            self.assertFalse((root / "EXP_A" / "runs" / "DATAEXT" / "output" / "grid.nc").exists())

    def test_acceptance_run_uses_dry_run_plan_not_fresh_croco_in_parsing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            env = self.fake_docker_env(tmp, present=True)
            env["FAKE_DOCKER_RUN_CODE"] = "0"
            exp = self.make_exp(root, data=False, croco_text="TITLE == test\nGRDNAME == missing_grid_from_text.nc\n")
            (exp / "input" / "actual.nc").write_bytes(b"actual")
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"], env=env).returncode, 0)
            dry, _ = self.prepare_dry_run_plan(root, run_id="PLANONLY", env=env)
            self.assertEqual(dry.returncode, 0, dry.stderr)
            (exp / "input" / "croco.in").write_text("TITLE == changed\nGRDNAME == late.nc\n", encoding="utf-8")
            (exp / "input" / "late.nc").write_bytes(b"late")
            ran = self.run_cli(["--experiments-root", str(root), "run", "EXP_A", "--run-id", "PLANONLY"], env=env)
            self.assertEqual(ran.returncode, 0, ran.stderr)
            work = root / "EXP_A" / "runs" / "PLANONLY" / "work"
            self.assertTrue((work / "actual.nc").is_symlink())
            self.assertFalse((work / "late.nc").exists())
            self.assertNotIn("missing_grid_from_text.nc", json.dumps(json.loads((work.parent / "reports" / "run_attempt.json").read_text(encoding="utf-8"))))

    def test_acceptance_unsupported_profiles_block_dry_run_and_run_without_docker_run(self):
        for symbol in ("MPI", "OPENACC", "XIOS", "OASIS", "AGRIF"):
            with self.subTest(symbol=symbol):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp) / "CROCO_EXPERIMENTS"
                    env = self.fake_docker_env(tmp, present=True)
                    env["FAKE_DOCKER_RUN_CODE"] = "0"
                    self.make_exp(root, data=True)
                    self.write_cppdefs_param(root, cppdefs=f"#define {symbol}\n", param="parameter (NPP=1)\n")
                    self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"], env=env).returncode, 0)
                    dry, _ = self.prepare_dry_run_plan(root, run_id=f"BLOCK_{symbol}", env=env)
                    self.assertEqual(dry.returncode, 11, dry.stderr)
                    ran = self.run_cli(["--experiments-root", str(root), "run", "EXP_A", "--run-id", f"BLOCK_{symbol}"], env=env)
                    self.assertEqual(ran.returncode, 11, ran.stderr)
                    run_dir = root / "EXP_A" / "runs" / f"BLOCK_{symbol}"
                    self.assertFalse((run_dir / "work" / "run_inside_docker.sh").exists())
                    self.assertFalse((run_dir / "logs" / "run_stdout.log").exists())

    def test_acceptance_reports_include_non_validation_disclaimers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            env = self.fake_docker_env(tmp, present=True)
            env["FAKE_DOCKER_RUN_CODE"] = "0"
            self.make_exp(root, data=True)
            self.install_source(tmp, root, source_id="report-source", env=env)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A", "--source", "report-source"], env=env).returncode, 0)
            inspect = self.run_cli(["--experiments-root", str(root), "inspect", "EXP_A"], env=env)
            self.assertEqual(inspect.returncode, 0, inspect.stderr)
            env["FAKE_DOCKER_WORK_OUTPUT"] = "croco"
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "compile", "EXP_A"], env=env).returncode, 0)
            env.pop("FAKE_DOCKER_WORK_OUTPUT")
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "dry-run", "EXP_A", "--run-id", "REPORTS"], env=env).returncode, 0)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "run", "EXP_A", "--run-id", "REPORTS"], env=env).returncode, 0)
            exp = root / "EXP_A"
            texts = [
                (exp / "metadata" / "report.md").read_text(encoding="utf-8"),
                inspect.stdout,
                (exp / "metadata" / "compile_report.md").read_text(encoding="utf-8"),
                (exp / "metadata" / "dry_run_report.md").read_text(encoding="utf-8"),
                (exp / "runs" / "REPORTS" / "reports" / "run_report.md").read_text(encoding="utf-8"),
            ]
            for text in texts:
                self.assertIn("does not prove scientific correctness", text)
                self.assertIn("runtime semantic compatibility", text)
                self.assertIn("experiment well-posedness", text)


if __name__ == "__main__":
    unittest.main()
