"""Real pytest retry/resource behavior and pinned grader resource identities."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest

from procontract_evaluator_runtime import PLUGIN, PLUGIN_NAME, load_assets, preserve_container_service


class GraderAssetsTest(unittest.TestCase):
    def test_archive_drift_is_detected_before_reuse(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "resources.tar.gz"
            path.write_bytes(b"pinned resources")
            descriptor = dict(archive=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                environment={"GRADER_LITERAL": "$(must-not-execute)"}, path_prepend=["tools/bin"])
            assets = load_assets(descriptor)
            self.assertEqual(assets.environment["GRADER_LITERAL"], "$(must-not-execute)")
            path.write_bytes(b"changed resources")
            with self.assertRaisesRegex(ValueError, "changed"):
                assets.verify()


@unittest.skipUnless(os.environ.get("PC_CONTAINER_TEST_DOCKER") and os.environ.get("PC_CONTAINER_TEST_IMAGE"),
                     "requires an explicitly selected private-container control")
class ContainerTimeoutTest(unittest.TestCase):
    def test_timeout_stops_test_processes_preserves_keeper_and_retained_observations(self):
        from programbench.container import ContainerEnvironment
        env = ContainerEnvironment(image=os.environ["PC_CONTAINER_TEST_IMAGE"],
            executable=os.environ["PC_CONTAINER_TEST_DOCKER"], cwd="/workspace", cpus=1,
            run_args=["--network", "none"])
        self.addCleanup(env.cleanup)
        preserve_container_service(env)
        self.assertIs(preserve_container_service(env), env)
        original_timeout = env.default_timeout
        result = env.execute("printf saved > /tmp/pc-retained-control; printf prefix; sleep 30 & sleep 30 & wait", timeout=.4)
        self.assertEqual(result["returncode"], -1)
        self.assertIn("Command timed out after 0.4s", result["exception_info"])
        self.assertEqual(result["output"], "prefix")
        self.assertTrue(result["timeout_cleanup"]["confirmed"], result)
        running = subprocess.check_output([env.executable, "inspect", "--format", "{{.State.Running}}", env.container_id], text=True).strip()
        self.assertEqual(running, "true")
        self.assertEqual(env.execute("cat /tmp/pc-retained-control", timeout=5),
                         {"output": "saved", "returncode": 0, "exception_info": ""})
        processes = env.execute("ps -eo args", timeout=5)["output"]
        self.assertNotIn("sleep 30", processes)
        self.assertIn("sleep 2h", processes)
        self.assertEqual(env.default_timeout, original_timeout)


@unittest.skipUnless(importlib.util.find_spec("pytest") and importlib.util.find_spec("pytest_rerunfailures"),
                     "requires pytest and pytest-rerunfailures")
class PytestAttemptTest(unittest.TestCase):
    def test_retry_reclaims_only_unreachable_resources_and_retains_real_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / (PLUGIN_NAME + ".py")).write_text(PLUGIN)
            with socket.socket() as port:
                port.bind(("127.0.0.1", 0))
                number = port.getsockname()[1]
            (root / "test_retry.py").write_text(f'''import gc, socket
gc.disable()
class Resource:
    def __init__(self, port):
        self.cycle = self
        self.socket = socket.socket()
        self.socket.bind(('127.0.0.1', port))
live = Resource(0)
live_address = live.socket.getsockname()
def test_failure():
    resource = Resource({number})
    assert False, 'REAL_BEHAVIOR_FAILURE'
def test_pass():
    assert live.socket.fileno() >= 0
    assert live.socket.getsockname() == live_address
''')
            env = {**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                "PYTHONPATH": str(root) + os.pathsep + os.environ.get("PYTHONPATH", "")}
            env.pop("PYTEST_ADDOPTS", None)
            command = [sys.executable, "-m", "pytest", "-q", "-p", "pytest_rerunfailures",
                "--reruns=2", "--reruns-delay=0", "test_retry.py"]
            baseline = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(baseline.returncode, 1, baseline.stdout + baseline.stderr)
            self.assertIn("Address already in use", baseline.stdout)
            repaired = subprocess.run(command + ["-p", PLUGIN_NAME], cwd=root, env=env,
                capture_output=True, text=True, timeout=30)
            self.assertEqual(repaired.returncode, 1, repaired.stdout + repaired.stderr)
            self.assertNotIn("Address already in use", repaired.stdout)
            observations = [json.loads(line) for line in (root / "attempts-main.jsonl").read_text().splitlines()]
            calls = [row for row in observations if row["phase"] == "call"]
            failed = [row for row in calls if row["outcome"] == "failed"]
            self.assertEqual([row["attempt"] for row in failed], [1, 2, 3])
            self.assertTrue(all(row["exception_type"] == "AssertionError" for row in failed), failed)
            self.assertEqual(sum(row["outcome"] == "passed" for row in calls), 1)


if __name__ == "__main__":
    unittest.main()
