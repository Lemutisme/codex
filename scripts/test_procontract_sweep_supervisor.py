"""Exercise the entire 200-slot supervisor with real durable budgets and no models."""

import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

import procontract_sweep as sweep


class SupervisorTests(unittest.TestCase):
    def exercise(self, first_failure=False):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            digest = "a" * 64
            tasks = [f"fixture-{i}" for i in range(200)]
            limits = {
                "task_launches": 200,
                "learning_launches": 0,
                "allocated_seconds": 3600000,
            }
            plan = {
                "root": str(root),
                "provider": {},
                "episode_secs": 18000,
                "limits": limits,
                "seed": sweep.online.seed(),
                "tasks": tasks,
                "parallel": 4,
                "disk_admission_gib": 50,
                "entrypoint": "fixture-only",
            }
            authorization = root / "authorization.json"
            authorization.write_text(
                json.dumps(
                    {
                        "plan_sha256": digest,
                        "limits": limits,
                        "authorized": True,
                        "user_message": "unit fixture; no model calls",
                    }
                )
            )
            launched = []

            class FakeJob:
                def __init__(self, command, log, seconds):
                    self.index = int(command[command.index("--index") + 1])
                    self.pid = 10000 + self.index
                    self.started = time.monotonic()
                    self.deadline = self.started + seconds
                    launched.append(self.index)
                    key = f"{self.index}-successor"
                    sweep.budgets.reserve(
                        root / "budget.sqlite",
                        digest,
                        key,
                        "task",
                        seconds,
                        limits,
                        {"task": tasks[self.index]},
                    )
                    directory = root / "runs" / key
                    directory.mkdir(parents=True)
                    result = {
                        "episode": key,
                        "task": tasks[self.index],
                        "arm": "successor",
                        "status": "infrastructure_failed"
                        if first_failure and self.index == 0
                        else "scored",
                    }
                    (directory / "result.json").write_text(json.dumps(result))

                def status(self):
                    return 2 if first_failure and self.index == 0 else 0

                def signal(self, _signal):
                    pass

                def close(self):
                    pass

            with (
                mock.patch.object(sweep.jobs, "Job", FakeJob),
                mock.patch.object(
                    sweep.jobs,
                    "cleanup_containers",
                    return_value={"remaining_owned_containers": []},
                ),
                mock.patch.object(sweep.credentials, "inspect", return_value={}),
                mock.patch.object(
                    sweep.runner, "current_key", return_value="LOCAL_FIXTURE_ONLY"
                ),
                mock.patch.object(
                    sweep.shutil,
                    "disk_usage",
                    return_value=type("Disk", (), {"free": 1 << 40})(),
                ),
                mock.patch.object(sweep.time, "sleep"),
                mock.patch.object(sweep.report, "write"),
                mock.patch("builtins.print"),
            ):
                result = sweep.run(plan, digest, authorization)
                before = (root / "budget.sqlite").read_bytes()
                with self.assertRaises(FileExistsError):
                    sweep.run(plan, digest, authorization)
                self.assertEqual((root / "budget.sqlite").read_bytes(), before)
            self.assertEqual(len(launched), len(set(launched)))
            self.assertEqual(
                result["budget"]["reserved"]["task_launches"], len(launched)
            )
            self.assertEqual(result["budget"]["reserved"]["learning_launches"], 0)
            return launched, result

    def test_all_200_slots_are_run_once_not_the_old_three_task_prefix(self):
        launched, result = self.exercise()
        self.assertEqual(launched, list(range(200)))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["budget"]["reserved"]["allocated_seconds"], 3600000)

    def test_infrastructure_failure_drains_admitted_jobs_without_replacement(self):
        launched, result = self.exercise(first_failure=True)
        self.assertEqual(launched, list(range(4)))
        self.assertEqual(result["status"], "stopped")


if __name__ == "__main__":
    unittest.main()
