import json
from pathlib import Path
import subprocess
import sys
import tomllib
import unittest

import procontract_benchmark_runner as runner
from procontract_execution_health import ExecutionHealth


class ExecutionHealthTest(unittest.TestCase):
    def test_unrelated_and_unattributed_events_do_not_describe_executor_health(self):
        health = ExecutionHealth()
        for thread_id, event in [
            (None, {"method": "thread/environment/disconnected", "params": {}}),
            (
                "executor",
                {"method": "turn/completed", "params": {"threadId": "executor"}},
            ),
            (
                "executor",
                {
                    "method": "thread/environment/disconnected",
                    "params": {"threadId": "worker"},
                },
            ),
        ]:
            health.observe(event, thread_id)
        self.assertEqual(
            health.summary(),
            {
                "disconnect_observed": False,
                "disconnect_count": 0,
                "disconnections": [],
                "events_omitted": 0,
            },
        )

    def test_repeated_or_large_events_have_bounded_receipts(self):
        health = ExecutionHealth()
        event = {
            "method": "thread/environment/disconnected",
            "params": {"threadId": "executor", "environmentId": "x" * 10000},
            "emittedAtMs": 1234,
        }
        for _ in range(20):
            health.observe(event, "executor")
        self.assertEqual(
            health.summary(),
            {
                "disconnect_observed": True,
                "disconnect_count": 20,
                "disconnections": [{"environment_id": "x" * 256, "emitted_at_ms": 1234}]
                * 16,
                "events_omitted": 4,
            },
        )

    @unittest.skipUnless(
        sys.platform == "linux", "validate Linux container shell limits"
    )
    def test_generated_environment_command_limits_child_without_killing_parent(self):
        config = tomllib.loads(
            runner.environments_toml(Path("/w"), Path("/codex"), "image:test")
        )
        args = config["environments"][0]["args"]
        wrapper = args[args.index("image:test") + 1 : args.index("/opt/codex")]
        child = """
import json, resource, subprocess, sys
limit = resource.getrlimit(resource.RLIMIT_AS)
probe = subprocess.run([sys.executable, '-c', 'a=bytearray(9*1024**3)'], capture_output=True)
print(json.dumps({'limit': limit, 'child_failed': probe.returncode != 0,
                  'memory_error': b'MemoryError' in probe.stderr, 'parent_alive': True}))
"""
        result = subprocess.run(
            wrapper + [sys.executable, "-c", child],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertEqual(
            json.loads(result.stdout),
            {
                "limit": [8589934592, 8589934592],
                "child_failed": True,
                "memory_error": True,
                "parent_alive": True,
            },
        )


if __name__ == "__main__":
    unittest.main()
