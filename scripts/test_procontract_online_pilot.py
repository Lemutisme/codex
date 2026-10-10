"""Exercise the paid boundary and post-submission feedback with zero model calls."""

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import procontract_online as online
from procontract_online_lineage import Lineage
import procontract_online_pilot as pilot
import procontract_online_plan as plans
import procontract_study_budget as budgets


class PilotTests(unittest.TestCase):
    def test_each_arm_is_once_and_only_adaptive_gets_its_frozen_reward(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binary = root / "codex"
            binary.write_text("fixture")
            (root / "seed-policy").mkdir()
            (root / "seed-policy/executor.md").write_text(online.seed()["execution"])
            plan = {
                "root": str(root),
                "tasks": ["task-a", "task-b", "task-c"],
                "arms": ["frozen", "adaptive"],
                "model": "gpt-5.6-luna",
                "effort": "max",
                "binary": str(binary),
                "registry": str(root / "registry"),
                "registry_sha256": "b" * 64,
                "pins_sha256": "c" * 64,
                "research_secs": 900,
                "inference_secs": 14400,
                "episode_secs": 18000,
                "grading_secs": 3600,
                "prompt": str(root / "prompt"),
                "provider": {"base_url": "http://127.0.0.1", "env_key": "KEY"},
                "limits": {
                    "task_launches": 6,
                    "learning_launches": 3,
                    "allocated_seconds": 108000,
                },
                "seed": online.seed(),
            }
            digest = "d" * 64
            budgets.initialize(root / "budget.sqlite", digest, plan["limits"])
            plans.publish(root / "launch.json", {"plan_sha256": digest})
            registry = SimpleNamespace(
                tasks={"task-a": {"image": "pinned", "total": 5}}
            )
            prepared = []
            deadlines = []

            def prepare(args):
                prepared.append(args)
                args.run_dir.mkdir(parents=True)
                (args.run_dir / "policy").mkdir()
                (args.run_dir / "manifest.json").write_text("{}")

            def execute(args, *, learning, online_trace):
                deadlines.append(args.deadline_secs)
                summary = {
                    "turn_statuses": ["completed"],
                    "native_process_exit": {"status": "exited"},
                    "server_exited_early": False,
                    "status": {"phase": "supported"},
                    "cost": {},
                }
                if learning is not None:
                    summary["online_learning"] = learning.close()
                (args.run_dir / "run.json").write_text(json.dumps(summary))

            def package(run):
                archive = run / "submission.tar.gz"
                archive.write_bytes(b"frozen fixture")
                return archive

            def grade(command, **_kwargs):
                if command == ["preflight"]:
                    return
                run = Path(command[command.index("--output") + 1]).parent
                archive = run / "submission.tar.gz"
                self.assertTrue(archive.exists())
                output = run / "eval"
                output.mkdir()
                (output / "canonical-result.json").write_text(
                    json.dumps(
                        {
                            "valid": True,
                            "resolved": 2,
                            "total": 5,
                            "submission_sha256": plans.sha(archive),
                        }
                    )
                )

            with (
                mock.patch.object(pilot, "OnlineTrace"),
                mock.patch.object(pilot.canonical, "configure", return_value=registry),
                mock.patch.object(pilot.canonical, "bind_pins"),
                mock.patch.object(
                    pilot.canonical,
                    "preflight",
                    side_effect=AssertionError("must use pinned evaluator subprocess"),
                ),
                mock.patch.object(
                    pilot.canonical, "package_submission", side_effect=package
                ),
                mock.patch.object(
                    pilot.canonical, "worker_command", side_effect=lambda *a: list(a)
                ),
                mock.patch.object(pilot.canonical, "evaluator_env", return_value={}),
                mock.patch.object(pilot.runner, "prepare", side_effect=prepare),
                mock.patch.object(pilot.runner, "run", side_effect=execute),
                mock.patch.object(pilot.runner, "current_key", return_value="NOT_REAL"),
                mock.patch.object(pilot.subprocess, "run", side_effect=grade),
            ):
                frozen = pilot.episode(plan, digest, 0, "frozen")
                self.assertFalse((root / "lineage").exists())
                adaptive = pilot.episode(plan, digest, 0, "adaptive")
                with self.assertRaises(budgets.AlreadyClaimed):
                    pilot.episode(plan, digest, 0, "adaptive")
            self.assertEqual(
                [frozen["outcome"]["resolved"], adaptive["outcome"]["resolved"]], [2, 2]
            )
            self.assertEqual(deadlines, [14400, 13500])
            self.assertEqual(len(prepared), 2)
            plans.publish(root / "terminal.json", {"status": "stopped"})
            with self.assertRaisesRegex(ValueError, "terminal pilot"):
                pilot.episode(plan, digest, 1, "adaptive")
            rewards = [
                e["body"]
                for e in Lineage(root / "lineage").events()
                if e["kind"] == "reward"
            ]
            self.assertEqual(
                [(r["episode"], r["resolved"], r["total"]) for r in rewards],
                [("0-adaptive", 2, 5)],
            )
            used = budgets.status(root / "budget.sqlite", digest, plan["limits"])[
                "reserved"
            ]
            self.assertEqual(
                used,
                {
                    "task_launches": 2,
                    "learning_launches": 1,
                    "allocated_seconds": 36000,
                },
            )


if __name__ == "__main__":
    unittest.main()
