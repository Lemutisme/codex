"""Continuation uses the parent ledger: no refund, duplicate launch, or old terminal rewrite."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

import procontract_control_continuation as controls
import procontract_online_plan as plans
import procontract_study_budget as budget
from procontract_credential_gate import PROFILE


class ContinuationTests(unittest.TestCase):
    def test_remaining_tasks_share_original_claims_and_preserve_stopped_record(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            prompt = root / "prompt"
            prompt.write_text("fixed request")
            parent = {
                "root": str(root),
                "protocol": plans.PROTOCOL,
                "selection_mode": "deployment",
                "selection_profile": plans.selection_profile("deployment"),
                "files": {},
                "tasks": ["a", "b", "c"],
                "arms": ["vanilla"],
                "model": "luna",
                "effort": "max",
                "binary": "/fixed/codex",
                "seed": {},
                "provider": {},
                "prompt": str(prompt),
                "episode_secs": 18000,
                "inference_secs": 14400,
                "grading_secs": 3600,
                "research_secs": 0,
                "limits": {
                    "task_launches": 3,
                    "learning_launches": 0,
                    "allocated_seconds": 54000,
                },
            }
            path = root / "online-plan.json"
            plans.publish(path, parent)
            digest = plans.sha(path)
            database = root / "budget.sqlite"
            budget.initialize(database, digest, parent["limits"])
            budget.reserve(
                database, digest, "0-vanilla", "task", 18000, parent["limits"], {}
            )
            plans.publish(root / "terminal.json", {"status": "stopped"})
            original = (root / "terminal.json").read_bytes()
            run = root / "runs/0-vanilla"
            plans.publish(
                run / "run.json",
                {"native_process_exit": {"status": "exited", "returncode": 0}},
            )
            plans.publish(run / "online-trace-cleanup.json", {})
            restored, descriptor = controls.remaining(path, digest)
            self.assertEqual(restored, parent)
            self.assertEqual(descriptor["indices"], [1, 2])
            clean = (run / "run.json").read_bytes()
            (run / "run.json").write_text(
                json.dumps({"native_process_exit": {"status": "unknown"}})
            )
            with self.assertRaisesRegex(ValueError, "unresolved"):
                controls.remaining(path, digest)
            (run / "run.json").write_bytes(clean)
            child = {
                **parent,
                "root": str(root / "child"),
                "tasks": ["b", "c"],
                "limits": {
                    "task_launches": 2,
                    "learning_launches": 0,
                    "allocated_seconds": 36000,
                },
                "credential_preflight": PROFILE,
                "continuation": descriptor,
            }
            self.assertEqual(
                controls.ledger(child, "b" * 64), (database, digest, parent["limits"])
            )
            for index in descriptor["indices"]:
                budget.reserve(
                    *controls.ledger(child, "b" * 64)[:2],
                    f"{index}-vanilla",
                    "task",
                    18000,
                    parent["limits"],
                    {"consumer_plan": "b" * 64},
                )
            with self.assertRaises(budget.AlreadyClaimed):
                budget.reserve(
                    database,
                    digest,
                    "1-vanilla",
                    "task",
                    18000,
                    parent["limits"],
                    {"consumer_plan": "c" * 64},
                )
            self.assertEqual(
                budget.status(database, digest, parent["limits"])["reserved"],
                parent["limits"],
            )
            self.assertEqual((root / "terminal.json").read_bytes(), original)
            for change in (
                {"tasks": ["a", "b"]},
                {"model": "different"},
                {"arms": ["adaptive"]},
                {"credential_preflight": None},
            ):
                with self.subTest(change=change), self.assertRaises(ValueError):
                    controls.ledger({**child, **change}, "b" * 64)
            wrong = copy.deepcopy(child)
            wrong["continuation"]["indices"] = [1, 1]
            with self.assertRaises(ValueError):
                controls.ledger(wrong, "b" * 64)


if __name__ == "__main__":
    unittest.main()
