import json
import os
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
        return subprocess.run(
            [sys.executable, str(CLI)] + args,
            cwd=cwd or REPO_ROOT,
            env=proc_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

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

    def write_cppdefs_param(self, root, name="EXP_A", cppdefs="", param=""):
        input_dir = root / name / "input"
        (input_dir / "cppdefs.h").write_text(cppdefs or "#define TEST\n", encoding="utf-8")
        (input_dir / "param.h").write_text(param or "#define LLm 10\n", encoding="utf-8")

    def make_source(self, tmp, name="source-origin"):
        source = Path(tmp) / name
        ocean = source / "OCEAN"
        ocean.mkdir(parents=True)
        (ocean / "jobcomp").write_text("#!/usr/bin/env bash\necho fake jobcomp\n", encoding="utf-8")
        (source / "README").write_text("fake source tree\n", encoding="utf-8")
        return source

    def install_source(self, tmp, root, source_id="croco-test", flavor="croco", env=None):
        source = self.make_source(tmp, f"{source_id}-origin")
        result = self.run_cli(
            ["--experiments-root", str(root), "source", "install", str(source), "--id", source_id, "--flavor", flavor, "--version", "test"],
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
            manifest_path = root / "EXP_A" / "metadata" / "manifest.json"
            self.assertTrue(manifest_path.exists())
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertIn("input_evidence", manifest)
            self.assertIn("compile_time", manifest)
            self.assertIn("runtime", manifest)
            self.assertIn("assets", manifest)
            self.assertEqual(manifest["runtime_materialization"]["status"], "not_planned_until_run_id")
            self.assertEqual(manifest["runtime_materialization"]["symlinked_runtime_data"], [])
            self.assertEqual(
                [a["source_relative_path_from_input"] for a in manifest["runtime_materialization"]["runtime_data_assets"]],
                ["forcing.nc"],
            )
            self.assertTrue((root / "EXP_A" / "build").is_dir())
            self.assertTrue((root / "EXP_A" / "runs").is_dir())

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

    def test_compile_staging_does_not_copy_nc_before_docker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            env = {"CROCOEXP_REPO_ROOT": str(Path(tmp) / "repo")}
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
                {"host_path": str(root), "container_path": "/opt/CROCO_EXPERIMENTS", "mode": "ro", "purpose": "readonly_experiments_root_mount"},
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
            self.assertEqual(result.returncode, 4)
            self.assertIn("run 'crocoexp import EXP_A' first", result.stderr)
            self.assertFalse((root / "EXP_A" / "metadata" / "manifest.json").exists())

    def test_source_install_copies_tree_and_writes_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            env = {"CROCOEXP_REPO_ROOT": str(Path(tmp) / "repo")}
            source = self.make_source(tmp)
            result = self.run_cli(
                ["--experiments-root", str(root), "source", "install", str(source), "--id", "croco-v1", "--flavor", "croco", "--version", "v1", "--notes", "test source"],
                env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            installed = root / "sources" / "croco-v1"
            self.assertTrue((installed / "OCEAN" / "jobcomp").exists())
            registry = json.loads((Path(env["CROCOEXP_REPO_ROOT"]) / ".crocoexp" / "sources.json").read_text(encoding="utf-8"))
            record = registry["sources"]["croco-v1"]
            self.assertEqual(record["host_path"], str(installed))
            self.assertEqual(record["flavor"], "croco")
            self.assertEqual(record["declared_version"], "v1")
            self.assertEqual(record["notes"], "test source")

    def test_source_list_and_inspect(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            env = {"CROCOEXP_REPO_ROOT": str(Path(tmp) / "repo")}
            self.install_source(tmp, root, source_id="msot-test", flavor="msot", env=env)
            listed = self.run_cli(["--experiments-root", str(root), "source", "list", "--json"], env=env)
            self.assertEqual(listed.returncode, 0, listed.stderr)
            self.assertIn("msot-test", listed.stdout)
            inspected = self.run_cli(["--experiments-root", str(root), "source", "inspect", "msot-test", "--json"], env=env)
            self.assertEqual(inspected.returncode, 0, inspected.stderr)
            details = json.loads(inspected.stdout)
            self.assertEqual(details["source_id"], "msot-test")
            self.assertEqual(details["flavor"], "msot")
            self.assertIn("detected_layout", details)

    def test_source_install_duplicate_without_force_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            env = {"CROCOEXP_REPO_ROOT": str(Path(tmp) / "repo")}
            self.install_source(tmp, root, source_id="dup-source", env=env)
            source = self.make_source(tmp, "dup-origin-2")
            result = self.run_cli(["--experiments-root", str(root), "source", "install", str(source), "--id", "dup-source"], env=env)
            self.assertEqual(result.returncode, 4)
            self.assertIn("already registered", result.stderr)

    def test_import_with_source_records_source_ref(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            env = {"CROCOEXP_REPO_ROOT": str(Path(tmp) / "repo")}
            self.make_exp(root, data=True)
            self.install_source(tmp, root, source_id="croco-import", env=env)
            result = self.run_cli(["--experiments-root", str(root), "import", "EXP_A", "--source", "croco-import"], env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((root / "EXP_A" / "metadata" / "manifest.json").read_text(encoding="utf-8"))
            source_ref = manifest["compile_time"]["source_ref"]
            self.assertEqual(source_ref["source_id"], "croco-import")
            self.assertEqual(source_ref["host_path"], str(root / "sources" / "croco-import"))
            self.assertFalse((root / "EXP_A" / "input" / "OCEAN").exists())

    def test_import_unknown_source_fails_clearly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            env = {"CROCOEXP_REPO_ROOT": str(Path(tmp) / "repo")}
            self.make_exp(root, data=True)
            result = self.run_cli(["--experiments-root", str(root), "import", "EXP_A", "--source", "missing-source"], env=env)
            self.assertEqual(result.returncode, 4)
            self.assertIn("missing-source", result.stderr)

    def test_compile_requires_source_ref(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=True)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"]).returncode, 0)
            result = self.run_cli(["--experiments-root", str(root), "compile", "EXP_A", "--image", "fake/image"])
            self.assertEqual(result.returncode, 3)
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

    def test_setup_image_missing_without_pull_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = self.fake_docker_env(tmp, present=False)
            result = self.run_cli(["setup", "--no-pull"], env=env)
            self.assertEqual(result.returncode, 7)
            repo = Path(env["CROCOEXP_REPO_ROOT"])
            config = json.loads((repo / ".crocoexp" / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(config["failure_category"], "image_missing")
            self.assertEqual(config["setup_status"], "blocked_image_missing")

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

    def test_dry_run_after_import_no_binary_is_success_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=True)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"]).returncode, 0)
            result = self.run_cli(["--experiments-root", str(root), "dry-run", "EXP_A", "--no-docker", "--run-id", "DRY1"])
            self.assertEqual(result.returncode, 0, result.stderr)
            report = root / "EXP_A" / "runs" / "DRY1" / "reports" / "dry_run_report.md"
            self.assertTrue(report.exists())
            self.assertIn("Binary present: False", report.read_text(encoding="utf-8"))

    def test_dry_run_records_report_and_snapshots_without_nc_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, analytical=True, data=True)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"]).returncode, 0)
            result = self.run_cli(["--experiments-root", str(root), "dry-run", "EXP_A", "--no-docker", "--run-id", "DRY2"])
            self.assertEqual(result.returncode, 0, result.stderr)
            snapshots = root / "EXP_A" / "runs" / "DRY2" / "snapshots"
            self.assertTrue((snapshots / "croco.in").exists())
            self.assertTrue((snapshots / "cppdefs.h").exists())
            self.assertTrue((snapshots / "param.h").exists())
            self.assertTrue((snapshots / "analytical.F").exists())
            self.assertTrue((snapshots / "asset_inventory.json").exists())
            self.assertFalse((snapshots / "forcing.nc").exists())
            self.assertTrue((root / "EXP_A" / "metadata" / "report.md").exists())

    def test_dry_run_placeholder_names_not_required_by_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            text = "TITLE == analytical\nGRDNAME == GRD/@GRD_FILE@\nININAME == INIT/@INI_FILE@\nFRCNAME == FORC/@FRC_FILE@\n"
            self.make_exp(root, analytical=True, croco_text=text)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"]).returncode, 0)
            result = self.run_cli(["--experiments-root", str(root), "dry-run", "EXP_A", "--no-docker", "--run-id", "DRY3"])
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((root / "EXP_A" / "metadata" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["assets"]["classification_counts"].get("required", 0), 0)

    def test_dry_run_reports_runtime_data_symlink_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=False, croco_text="TITLE == test\nDATA == any syntax\n")
            self.add_nested_data(root)
            self.add_binary(root)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"]).returncode, 0)
            result = self.run_cli(["--experiments-root", str(root), "dry-run", "EXP_A", "--no-docker", "--run-id", "DRY4"])
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((root / "EXP_A" / "metadata" / "manifest.json").read_text(encoding="utf-8"))
            symlinks = manifest["runtime_materialization"]["symlinked_runtime_data"]
            self.assertEqual({s["source_relative_path_from_input"] for s in symlinks}, {"GRD/grid.nc", "INIT/init.nc"})
            self.assertFalse(manifest["reporting"]["ambiguities"])
            self.assertEqual(manifest["assets"]["classification_counts"].get("ambiguous", 0), 0)
            report = (root / "EXP_A" / "runs" / "DRY4" / "reports" / "dry_run_report.md").read_text(encoding="utf-8")
            self.assertIn("Symlink Plan", report)
            self.assertNotIn("Required Assets Selected For Staging/Mounting", report)

    def test_dry_run_missing_referenced_asset_does_not_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=False)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"]).returncode, 0)
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
            result = self.run_cli(["--experiments-root", str(root), "dry-run", "EXP_A", "--no-docker", "--run-id", "DRY6"])
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((root / "EXP_A" / "metadata" / "manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["reporting"]["possible_mismatches"])

    def test_dry_run_unrecognized_croco_syntax_is_opaque(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=True, croco_text="TITLE == test\nDATA == forcing.nc\n")
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"]).returncode, 0)
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
                self.add_binary(root, name=name)
                self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", name]).returncode, 0)
                result = self.run_cli(["--experiments-root", str(root), "dry-run", name, "--no-docker", "--run-id", "DRY"])
                self.assertEqual(result.returncode, 0, result.stderr)
                manifest = json.loads((root / name / "metadata" / "manifest.json").read_text(encoding="utf-8"))
                self.assertFalse(manifest["reporting"]["ambiguities"])
                self.assertEqual(len(manifest["runtime_materialization"]["symlinked_runtime_data"]), 2)

    def test_dry_run_docker_backed_readiness_uses_fake_docker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=True)
            env = self.fake_docker_env(tmp, present=True)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"], env=env).returncode, 0)
            result = self.run_cli(["--experiments-root", str(root), "dry-run", "EXP_A", "--run-id", "DRY8"], env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((root / "EXP_A" / "metadata" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["reporting"]["backend_outcome"]["mode"], "docker-backed-readiness")

    def test_run_fails_clearly_when_binary_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=True)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"]).returncode, 0)
            result = self.run_cli(["--experiments-root", str(root), "run", "EXP_A", "--run-id", "RUN1", "--image", "fake/image"])
            self.assertEqual(result.returncode, 3)
            self.assertIn("compile", result.stderr)

    def test_run_without_prior_dry_run_creates_outputs_reports_snapshots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, analytical=True, data=True)
            self.add_nested_data(root)
            env = self.fake_docker_env(tmp, present=True)
            env["FAKE_DOCKER_RUN_CODE"] = "0"
            env["FAKE_DOCKER_WORK_OUTPUT"] = "HIS/history.nc"
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"], env=env).returncode, 0)
            binary = self.add_binary(root)
            result = self.run_cli(["--experiments-root", str(root), "run", "EXP_A", "--run-id", "RUN2", "--image", "fake/image"], env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            run_dir = root / "EXP_A" / "runs" / "RUN2"
            self.assertTrue((run_dir / "logs").is_dir())
            self.assertTrue((run_dir / "output").is_dir())
            self.assertTrue((run_dir / "snapshots").is_dir())
            self.assertTrue((run_dir / "reports" / "run_report.md").exists())
            self.assertTrue((run_dir / "logs" / "run.log").exists())
            self.assertFalse((run_dir / "snapshots" / "forcing.nc").exists())
            self.assertTrue((run_dir / "work" / "croco.in").is_file())
            self.assertTrue((run_dir / "work" / "croco").is_file())
            self.assertTrue(os.access(run_dir / "work" / "croco", os.X_OK))
            self.assertTrue((run_dir / "work" / "run_inside_docker.sh").is_file())
            self.assertTrue((run_dir / "work" / "forcing.nc").is_symlink())
            self.assertTrue((run_dir / "work" / "GRD" / "grid.nc").is_symlink())
            self.assertTrue((run_dir / "work" / "INIT" / "init.nc").is_symlink())
            self.assertFalse(os.readlink(run_dir / "work" / "GRD" / "grid.nc").startswith("/"))
            self.assertEqual((run_dir / "work" / "GRD" / "grid.nc").resolve(), root / "EXP_A" / "input" / "GRD" / "grid.nc")
            self.assertEqual((run_dir / "work" / "INIT" / "init.nc").resolve(), root / "EXP_A" / "input" / "INIT" / "init.nc")
            script = (run_dir / "work" / "run_inside_docker.sh").read_text(encoding="utf-8")
            self.assertIn("./croco croco.in", script)
            self.assertTrue((run_dir / "output" / "HIS" / "history.nc").is_file())
            self.assertTrue((run_dir / "work" / "HIS" / "history.nc").is_file())
            self.assertEqual((root / "EXP_A" / "input" / "forcing.nc").read_bytes(), b"not a real netcdf")
            manifest = json.loads((root / "EXP_A" / "metadata" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["commands"][-1]["command"], "run")
            self.assertEqual(manifest["reporting"]["run_outcome"]["failure_category"], "none")
            self.assertEqual(manifest["snapshots"]["latest_run_snapshot"]["kind"], "run")
            self.assertEqual(manifest["runtime_materialization"]["workdir_host_path"], str(run_dir / "work"))
            command_parts = manifest["docker_backend"]["run_command_summary"].split()
            volume_specs = [command_parts[i + 1] for i, part in enumerate(command_parts[:-1]) if part == "-v"]
            self.assertTrue(volume_specs)
            for spec in volume_specs:
                self.assertIn(":", spec)
                self.assertTrue(spec.split(":", 1)[0].startswith("/"))
                self.assertTrue(spec.startswith(str(root)))
            self.assertIn("-w", command_parts)
            self.assertEqual(command_parts[command_parts.index("-w") + 1], "/opt/CROCO_EXPERIMENTS/EXP_A/runs/RUN2/work")
            self.assertEqual(
                manifest["reporting"]["run_outcome"]["collected_outputs"][0]["destination_host_path"],
                str(run_dir / "output" / "HIS" / "history.nc"),
            )
            self.assertEqual(manifest["reporting"]["run_outcome"]["collected_outputs"][0]["action"], "copied_from_workdir")
            self.assertEqual(Path(manifest["commands"][-1]["inputs_used"][-1]), binary)

    def test_openmp_runtime_plan_forces_npp_threads(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=True)
            self.write_cppdefs_param(
                root,
                cppdefs="#define OPENMP\n",
                param="parameter (NPP=8)\nparameter (NSUB_X=2, NSUB_E=4)\n",
            )
            env = self.fake_docker_env(tmp, present=True)
            env["FAKE_DOCKER_RUN_CODE"] = "0"
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"], env=env).returncode, 0)
            self.add_binary(root)
            result = self.run_cli(["--experiments-root", str(root), "run", "EXP_A", "--run-id", "OMP8", "--image", "fake/image"], env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((root / "EXP_A" / "metadata" / "manifest.json").read_text(encoding="utf-8"))
            plan = manifest["runtime_execution_plan"]
            self.assertEqual(plan["parallel_backend"], "openmp")
            self.assertEqual(plan["openmp"]["planned_omp_num_threads"], 8)
            self.assertIn("-e OMP_NUM_THREADS=8", manifest["docker_backend"]["run_command_summary"])
            script = root / "EXP_A" / "runs" / "OMP8" / "work" / "run_inside_docker.sh"
            self.assertIn("export OMP_NUM_THREADS=8", script.read_text(encoding="utf-8"))

    def test_exact_backend_symbols_ignore_mpi_compatibility_macros(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=True)
            self.write_cppdefs_param(
                root,
                cppdefs="# define OPENMP\n# undef MPI\n#define MPI_COMM_WORLD 0\n#define MPI_master_only\n",
                param="parameter (NPP=8)\n",
            )
            env = self.fake_docker_env(tmp, present=True)
            env["FAKE_DOCKER_RUN_CODE"] = "0"
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"], env=env).returncode, 0)
            self.add_binary(root)
            result = self.run_cli(["--experiments-root", str(root), "run", "EXP_A", "--run-id", "COMPAT", "--image", "fake/image"], env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((root / "EXP_A" / "metadata" / "manifest.json").read_text(encoding="utf-8"))
            plan = manifest["runtime_execution_plan"]
            self.assertEqual(plan["parallel_backend"], "openmp")
            self.assertTrue(plan["backend_symbols"]["OPENMP"])
            self.assertFalse(plan["backend_symbols"]["MPI"])
            self.assertIn("MPI_COMM_WORLD", manifest["compile_time"]["parsed_symbols"])
            self.assertIn("MPI_MASTER_ONLY", manifest["compile_time"]["parsed_symbols"])

    def test_distribution_style_branches_resolve_effective_openmp(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=True)
            self.write_cppdefs_param(
                root,
                cppdefs=(
                    "#define MESA_ROTANTE\n"
                    "#ifdef MESA_ROTANTE\n"
                    "# define OPENMP\n"
                    "# undef  MPI\n"
                    "#endif\n"
                    "#ifdef BASIN\n"
                    "# undef  OPENMP\n"
                    "# define MPI\n"
                    "#endif\n"
                    "#ifdef BENGUELA\n"
                    "# define MPI\n"
                    "# undef OPENMP\n"
                    "#endif\n"
                    "#define MPI_COMM_WORLD 0\n"
                    "#define MPI_master_only\n"
                ),
                param=(
                    "#ifdef MPI\n"
                    "      parameter (NPP=1)\n"
                    "      parameter (NNODES=4)\n"
                    "#elif defined OPENMP\n"
                    "      parameter (NPP=8)\n"
                    "      parameter (NSUB_X=2, NSUB_E=4)\n"
                    "#else\n"
                    "      parameter (NPP=1)\n"
                    "#endif\n"
                ),
            )
            env = self.fake_docker_env(tmp, present=True)
            env["FAKE_DOCKER_RUN_CODE"] = "0"
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"], env=env).returncode, 0)
            self.add_binary(root)
            result = self.run_cli(["--experiments-root", str(root), "run", "EXP_A", "--run-id", "MESA", "--image", "fake/image"], env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((root / "EXP_A" / "metadata" / "manifest.json").read_text(encoding="utf-8"))
            plan = manifest["runtime_execution_plan"]
            self.assertEqual(plan["parallel_backend"], "openmp")
            self.assertTrue(plan["backend_symbols"]["OPENMP"])
            self.assertFalse(plan["backend_symbols"]["MPI"])
            self.assertEqual(plan["openmp"]["npp"], 8)
            self.assertEqual(plan["openmp"]["nsub_x"], 2)
            self.assertEqual(plan["openmp"]["nsub_e"], 4)
            self.assertEqual(plan["openmp"]["planned_omp_num_threads"], 8)
            self.assertIn("-e OMP_NUM_THREADS=8", manifest["docker_backend"]["run_command_summary"])
            script = root / "EXP_A" / "runs" / "MESA" / "work" / "run_inside_docker.sh"
            script_text = script.read_text(encoding="utf-8")
            self.assertIn("export OMP_NUM_THREADS=8", script_text)
            self.assertIn('echo "CROCOEXP: OMP_NUM_THREADS=${OMP_NUM_THREADS}"', script_text)

    def test_stale_compile_symbols_are_recomputed_from_current_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=True)
            self.write_cppdefs_param(root, cppdefs="#define TEST\n", param="parameter (NPP=1)\n")
            env = self.fake_docker_env(tmp, present=True)
            env["FAKE_DOCKER_RUN_CODE"] = "0"
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"], env=env).returncode, 0)
            manifest_path = root / "EXP_A" / "metadata" / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["reporting"]["compile_outcome"] = {"failure_category": "none", "exit_code": 0}
            manifest["compile_time"]["active_cpp_symbols"] = ["TEST"]
            manifest["compile_time"]["dimensions"] = {"npp": 1, "nsub_x": 1, "nsub_e": 1, "np_xi": None, "np_eta": None, "nnodes": None}
            manifest["compile_time"]["input_cppdefs_hash"] = "stale"
            manifest["compile_time"]["input_param_hash"] = "stale"
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            self.write_cppdefs_param(
                root,
                cppdefs="#define MESA_ROTANTE\n#if defined MESA_ROTANTE\n# define OPENMP\n# undef MPI\n#endif\n",
                param="#ifdef OPENMP\nparameter (NPP=8)\nparameter (NSUB_X=2, NSUB_E=4)\n#else\nparameter (NPP=1)\n#endif\n",
            )
            self.add_binary(root)
            result = self.run_cli(["--experiments-root", str(root), "run", "EXP_A", "--run-id", "STALE", "--image", "fake/image"], env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            plan = manifest["runtime_execution_plan"]
            self.assertEqual(plan["parallel_backend"], "openmp")
            self.assertTrue(plan["active_symbol_resolution"]["contains_OPENMP"])
            self.assertEqual(plan["active_symbol_resolution"]["source"], "freshly_preprocessed")
            self.assertEqual(plan["effective_param_resolution"]["parsed_NPP"], 8)
            self.assertEqual(plan["openmp"]["planned_omp_num_threads"], 8)

    def test_wrong_compile_evidence_without_provenance_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=True)
            self.write_cppdefs_param(
                root,
                cppdefs="#define MESA_ROTANTE\n#if defined MESA_ROTANTE\n# define OPENMP\n# undef MPI\n#endif\n#define ANA_GRID\n#define ANA_INITIAL\n",
                param="#ifdef MPI\nparameter (NPP=1)\nparameter (NSUB_X=1, NSUB_E=1)\n#elif defined OPENMP\nparameter (NPP=8)\nparameter (NSUB_X=2, NSUB_E=4)\n#else\nparameter (NPP=1)\n#endif\n",
            )
            env = self.fake_docker_env(tmp, present=True)
            env["FAKE_DOCKER_RUN_CODE"] = "0"
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"], env=env).returncode, 0)
            manifest_path = root / "EXP_A" / "metadata" / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            logs = root / "EXP_A" / "build" / "logs"
            logs.mkdir(parents=True, exist_ok=True)
            wrong_symbols = logs / "active_cpp_symbols.txt"
            wrong_symbols.write_text("#define ANA_GRID 1\n#define ANA_INITIAL 1\n", encoding="utf-8")
            wrong_param = logs / "effective_param.h"
            wrong_param.write_text("parameter (NPP=1)\nparameter (NSUB_X=1, NSUB_E=1)\n", encoding="utf-8")
            manifest["reporting"]["compile_outcome"] = {"failure_category": "none", "exit_code": 0}
            manifest["compile_time"]["active_cpp_symbols"] = ["ANA_GRID", "ANA_INITIAL"]
            manifest["compile_time"]["active_cpp_symbols_source"] = str(wrong_symbols)
            manifest["compile_time"]["effective_param_source"] = str(wrong_param)
            manifest["compile_time"]["dimensions"] = {"npp": 1, "nsub_x": 1, "nsub_e": 1, "np_xi": None, "np_eta": None, "nnodes": None}
            manifest["compile_time"]["input_cppdefs_hash"] = manifest["runtime_execution_plan"]["active_symbol_resolution"]["input_cppdefs_hash"]
            manifest["compile_time"]["input_param_hash"] = manifest["runtime_execution_plan"]["effective_param_resolution"]["input_param_hash"]
            manifest["compile_time"].pop("effective_preprocessor_provenance", None)
            manifest["compile_time"].pop("effective_preprocessor_provenance_source", None)
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            self.add_binary(root)
            result = self.run_cli(["--experiments-root", str(root), "run", "EXP_A", "--run-id", "WRONGEVID", "--image", "fake/image"], env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            plan = manifest["runtime_execution_plan"]
            self.assertEqual(plan["parallel_backend"], "openmp")
            self.assertEqual(plan["openmp"]["planned_omp_num_threads"], 8)
            self.assertFalse(plan["active_symbol_resolution"]["compile_time_active_symbols_trusted"])
            self.assertIn(
                plan["active_symbol_resolution"]["trust_rejection_reason"],
                {"missing effective preprocessor provenance", "active_cpp_symbols artifact is missing"},
            )
            self.assertTrue(plan["active_symbol_resolution"]["fresh_preprocessing_attempted"])

    def test_experiment_cppdefs_precedes_source_tree_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            env = self.fake_docker_env(tmp, present=True)
            env["FAKE_DOCKER_RUN_CODE"] = "0"
            self.make_exp(root, data=True)
            self.write_cppdefs_param(
                root,
                cppdefs="#define MESA_ROTANTE\n#if defined MESA_ROTANTE\n# define OPENMP\n#endif\n",
                param="#ifdef OPENMP\nparameter (NPP=8)\nparameter (NSUB_X=2, NSUB_E=4)\n#else\nparameter (NPP=1)\n#endif\n",
            )
            source = self.make_source(tmp, "source-default")
            (source / "OCEAN" / "cppdefs.h").write_text("#define OTHER_CASE\n#undef OPENMP\n", encoding="utf-8")
            install = self.run_cli(["--experiments-root", str(root), "source", "install", str(source), "--id", "default-source"], env=env)
            self.assertEqual(install.returncode, 0, install.stderr)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A", "--source", "default-source"], env=env).returncode, 0)
            self.add_binary(root)
            result = self.run_cli(["--experiments-root", str(root), "run", "EXP_A", "--run-id", "PRECEDENCE", "--image", "fake/image"], env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((root / "EXP_A" / "metadata" / "manifest.json").read_text(encoding="utf-8"))
            plan = manifest["runtime_execution_plan"]
            self.assertEqual(plan["parallel_backend"], "openmp")
            self.assertTrue(plan["backend_symbols"]["OPENMP"])
            self.assertIn(str(root / "EXP_A" / "input"), plan["active_symbol_resolution"]["include_paths"][0])
            self.assertIn(str(root / "EXP_A" / "input" / "cppdefs.h"), plan["active_symbol_resolution"]["probe_content"])

    def test_mpi_compatibility_macro_alone_does_not_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=True)
            self.write_cppdefs_param(root, cppdefs="#define MPI_COMM_WORLD 0\n", param="#define LLm 10\n")
            env = self.fake_docker_env(tmp, present=True)
            env["FAKE_DOCKER_RUN_CODE"] = "0"
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"], env=env).returncode, 0)
            self.add_binary(root)
            result = self.run_cli(["--experiments-root", str(root), "run", "EXP_A", "--run-id", "MPIDUMMY", "--image", "fake/image"], env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((root / "EXP_A" / "metadata" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["runtime_execution_plan"]["parallel_backend"], "serial")
            self.assertFalse(manifest["runtime_execution_plan"]["backend_symbols"]["MPI"])

    def test_openmp_unparsed_npp_defaults_to_one_with_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=True)
            self.write_cppdefs_param(root, cppdefs="#define OPENMP\n", param="parameter (NPP=NP_THREADS)\n")
            env = self.fake_docker_env(tmp, present=True)
            env["FAKE_DOCKER_RUN_CODE"] = "0"
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"], env=env).returncode, 0)
            self.add_binary(root)
            result = self.run_cli(["--experiments-root", str(root), "run", "EXP_A", "--run-id", "OMP1", "--image", "fake/image"], env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((root / "EXP_A" / "metadata" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["runtime_execution_plan"]["openmp"]["planned_omp_num_threads"], 1)
            self.assertIn("OMP_NUM_THREADS=1", manifest["docker_backend"]["run_command_summary"])
            self.assertTrue(any("NPP could not be parsed" in warning for warning in manifest["reporting"]["warnings"]))

    def test_mpi_runtime_plan_blocks_before_docker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=True)
            self.write_cppdefs_param(root, cppdefs="#define MPI\n", param="parameter (NNODES=4)\n")
            env = self.fake_docker_env(tmp, present=True)
            env["FAKE_DOCKER_RUN_CODE"] = "0"
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"], env=env).returncode, 0)
            self.add_binary(root)
            result = self.run_cli(["--experiments-root", str(root), "run", "EXP_A", "--run-id", "MPIBLOCK", "--image", "fake/image"], env=env)
            self.assertEqual(result.returncode, 4, result.stderr)
            run_dir = root / "EXP_A" / "runs" / "MPIBLOCK"
            self.assertFalse((run_dir / "work" / "run_inside_docker.sh").exists())
            self.assertNotIn("fake docker run", (run_dir / "logs" / "run.log").read_text(encoding="utf-8"))
            manifest = json.loads((root / "EXP_A" / "metadata" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["reporting"]["run_outcome"]["failure_category"], "unsupported_runtime_backend")
            self.assertEqual(manifest["runtime_execution_plan"]["parallel_backend"], "mpi")
            self.assertTrue(manifest["runtime_execution_plan"]["blockers"])

    def test_xios_runtime_plan_blocks_before_docker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=True)
            self.write_cppdefs_param(root, cppdefs="#define XIOS\n", param="#define LLm 10\n")
            env = self.fake_docker_env(tmp, present=True)
            env["FAKE_DOCKER_RUN_CODE"] = "0"
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"], env=env).returncode, 0)
            self.add_binary(root)
            result = self.run_cli(["--experiments-root", str(root), "run", "EXP_A", "--run-id", "XIOSBLOCK", "--image", "fake/image"], env=env)
            self.assertEqual(result.returncode, 4, result.stderr)
            run_dir = root / "EXP_A" / "runs" / "XIOSBLOCK"
            self.assertFalse((run_dir / "work" / "run_inside_docker.sh").exists())
            self.assertNotIn("fake docker run", (run_dir / "logs" / "run.log").read_text(encoding="utf-8"))
            manifest = json.loads((root / "EXP_A" / "metadata" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["runtime_execution_plan"]["parallel_backend"], "unsupported_complex")
            self.assertTrue(any("XIOS" in b["description"] for b in manifest["runtime_execution_plan"]["blockers"]))

    def test_run_require_dry_run_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=True)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"]).returncode, 0)
            self.add_binary(root)
            result = self.run_cli(["--experiments-root", str(root), "run", "EXP_A", "--run-id", "RUN3", "--image", "fake/image", "--require-dry-run"])
            self.assertEqual(result.returncode, 4)
            self.assertIn("dry-run report", result.stderr)

    def test_run_require_dry_run_after_matching_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=True)
            env = self.fake_docker_env(tmp, present=True)
            env["FAKE_DOCKER_RUN_CODE"] = "0"
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"], env=env).returncode, 0)
            self.add_binary(root)
            dry = self.run_cli(["--experiments-root", str(root), "dry-run", "EXP_A", "--no-docker", "--run-id", "RUN4"], env=env)
            self.assertEqual(dry.returncode, 0, dry.stderr)
            result = self.run_cli(["--experiments-root", str(root), "run", "EXP_A", "--run-id", "RUN4", "--image", "fake/image", "--require-dry-run"], env=env)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_run_missing_referenced_asset_reaches_croco_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=False)
            env = self.fake_docker_env(tmp, present=True)
            env["FAKE_DOCKER_RUN_CODE"] = "0"
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"]).returncode, 0)
            self.add_binary(root)
            result = self.run_cli(["--experiments-root", str(root), "run", "EXP_A", "--run-id", "RUN5", "--image", "fake/image"], env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = root / "EXP_A" / "runs" / "RUN5" / "reports" / "run_report.md"
            self.assertTrue(report.exists())
            manifest = json.loads((root / "EXP_A" / "metadata" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["runtime_materialization"]["symlinked_runtime_data"], [])
            self.assertEqual(manifest["reporting"]["run_outcome"]["failure_category"], "none")

    def test_run_blocked_materialization_does_not_generate_wrapper_or_start_docker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            exp = self.make_exp(root, data=False)
            outside = Path(tmp) / "outside.nc"
            outside.write_bytes(b"outside")
            (exp / "input" / "unsafe.nc").symlink_to(outside)
            env = self.fake_docker_env(tmp, present=True)
            env["FAKE_DOCKER_RUN_CODE"] = "0"
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"], env=env).returncode, 0)
            self.add_binary(root)
            result = self.run_cli(["--experiments-root", str(root), "run", "EXP_A", "--run-id", "RUNBLOCK", "--image", "fake/image"], env=env)
            self.assertEqual(result.returncode, 4, result.stderr)
            run_dir = root / "EXP_A" / "runs" / "RUNBLOCK"
            self.assertFalse((run_dir / "work" / "run_inside_docker.sh").exists())
            log = (run_dir / "logs" / "run.log").read_text(encoding="utf-8")
            self.assertNotIn("fake docker run", log)
            manifest = json.loads((root / "EXP_A" / "metadata" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["reporting"]["run_outcome"]["failure_category"], "metadata_or_staging")
            self.assertEqual(manifest["docker_backend"]["run_command_summary"], "not attempted; runtime planning or workdir materialization blocked")

    def test_run_env_ignored_and_unresolved_tokens_warn_without_substitution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            exp = self.make_exp(root, croco_text="TITLE == ${CASE_NAME}\n")
            (exp / "input" / "run.env").write_text("CASE_NAME=replaced\n", encoding="utf-8")
            env = self.fake_docker_env(tmp, present=True)
            env["FAKE_DOCKER_RUN_CODE"] = "0"
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"], env=env).returncode, 0)
            self.add_binary(root)
            result = self.run_cli(["--experiments-root", str(root), "run", "EXP_A", "--run-id", "RUNENV", "--image", "fake/image"], env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            work_croco = root / "EXP_A" / "runs" / "RUNENV" / "work" / "croco.in"
            self.assertIn("${CASE_NAME}", work_croco.read_text(encoding="utf-8"))
            self.assertNotIn("replaced", work_croco.read_text(encoding="utf-8"))
            manifest = json.loads((root / "EXP_A" / "metadata" / "manifest.json").read_text(encoding="utf-8"))
            warnings = "\n".join(manifest["reporting"]["warnings"])
            self.assertIn("run.env is ignored", warnings)
            self.assertIn("${CASE_NAME}", warnings)

    def test_run_reports_findings_without_blocking_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, analytical=True, data=True)
            env = self.fake_docker_env(tmp, present=True)
            env["FAKE_DOCKER_RUN_CODE"] = "0"
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"], env=env).returncode, 0)
            self.add_binary(root)
            result = self.run_cli(["--experiments-root", str(root), "run", "EXP_A", "--run-id", "RUN6", "--image", "fake/image"], env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((root / "EXP_A" / "metadata" / "manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["reporting"]["possible_mismatches"])

    def test_run_records_docker_command_and_failure_category(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=True)
            env = self.fake_docker_env(tmp, present=True)
            env["FAKE_DOCKER_RUN_CODE"] = "9"
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"], env=env).returncode, 0)
            self.add_binary(root)
            result = self.run_cli(["--experiments-root", str(root), "run", "EXP_A", "--run-id", "RUN7", "--image", "fake/image"], env=env)
            self.assertEqual(result.returncode, 9)
            manifest = json.loads((root / "EXP_A" / "metadata" / "manifest.json").read_text(encoding="utf-8"))
            self.assertIn("docker run", manifest["docker_backend"]["run_command_summary"])
            self.assertEqual(manifest["reporting"]["run_outcome"]["failure_category"], "run_failure")


if __name__ == "__main__":
    unittest.main()
