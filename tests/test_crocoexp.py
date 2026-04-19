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

    def test_dry_run_external_data_required_when_obviously_referenced(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=True)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"]).returncode, 0)
            result = self.run_cli(["--experiments-root", str(root), "dry-run", "EXP_A", "--no-docker", "--run-id", "DRY4"])
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((root / "EXP_A" / "metadata" / "manifest.json").read_text(encoding="utf-8"))
            required = [a for a in manifest["assets"]["inventory"] if a["classification"] == "required"]
            self.assertTrue(any(Path(a["host_path"]).name == "forcing.nc" for a in required))
            self.assertTrue(manifest["assets"]["selected_mounts"])

    def test_dry_run_missing_required_referenced_asset_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=False)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"]).returncode, 0)
            result = self.run_cli(["--experiments-root", str(root), "dry-run", "EXP_A", "--no-docker", "--run-id", "DRY5"])
            self.assertEqual(result.returncode, 3)
            manifest = json.loads((root / "EXP_A" / "metadata" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["reporting"]["status"], "blocked_missing_artifact")

    def test_dry_run_possible_mismatch_reported_not_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, analytical=True, data=True)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"]).returncode, 0)
            result = self.run_cli(["--experiments-root", str(root), "dry-run", "EXP_A", "--no-docker", "--run-id", "DRY6"])
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((root / "EXP_A" / "metadata" / "manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["reporting"]["possible_mismatches"])

    def test_dry_run_ambiguous_asset_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=True, croco_text="TITLE == test\nDATA == forcing.nc\n")
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"]).returncode, 0)
            result = self.run_cli(["--experiments-root", str(root), "dry-run", "EXP_A", "--no-docker", "--run-id", "DRY7"])
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((root / "EXP_A" / "metadata" / "manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["reporting"]["ambiguities"])
            self.assertEqual(manifest["assets"]["classification_counts"].get("ambiguous"), 1)

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
            env = self.fake_docker_env(tmp, present=True)
            env["FAKE_DOCKER_RUN_CODE"] = "0"
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
            self.assertEqual((root / "EXP_A" / "input" / "forcing.nc").read_bytes(), b"not a real netcdf")
            manifest = json.loads((root / "EXP_A" / "metadata" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["commands"][-1]["command"], "run")
            self.assertEqual(manifest["reporting"]["run_outcome"]["failure_category"], "none")
            self.assertEqual(manifest["snapshots"]["latest_run_snapshot"]["kind"], "run")
            self.assertEqual(Path(manifest["commands"][-1]["inputs_used"][-1]), binary)

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

    def test_run_missing_required_referenced_asset_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CROCO_EXPERIMENTS"
            self.make_exp(root, data=False)
            self.assertEqual(self.run_cli(["--experiments-root", str(root), "import", "EXP_A"]).returncode, 0)
            self.add_binary(root)
            result = self.run_cli(["--experiments-root", str(root), "run", "EXP_A", "--run-id", "RUN5", "--image", "fake/image"])
            self.assertEqual(result.returncode, 3)
            report = root / "EXP_A" / "runs" / "RUN5" / "reports" / "run_report.md"
            self.assertTrue(report.exists())
            manifest = json.loads((root / "EXP_A" / "metadata" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["reporting"]["run_outcome"]["failure_category"], "missing_artifact")

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
