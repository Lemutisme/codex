"""Operator pin and fresh-authorization boundaries, without inference or Docker."""

import json
from pathlib import Path
import tempfile
import unittest

import procontract_online_plan as plans


class PlanTests(unittest.TestCase):
    def test_task_order_is_independent_of_input_order_and_scores(self):
        tasks = {"c": {"score": 100}, "a": {"score": 0}, "d": {}, "b": {}}
        selected = plans.select_tasks(tasks)
        self.assertEqual(
            plans.select_tasks(dict(reversed(list(tasks.items())))), selected
        )
        self.assertEqual(
            plans.select_tasks({key: {"score": -9} for key in tasks}), selected
        )
        self.assertEqual(len(set(selected)), 3)
        with self.assertRaises(ValueError):
            plans.select_tasks(["a", "b"])

    def test_plan_drift_and_input_drift_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.write_text("original")
            plan = {
                "root": str(root),
                "protocol": "online-program-learning-pilot-v1",
                "files": {str(source): plans.sha(source)},
            }
            path = root / "online-plan.json"
            plans.publish(path, plan)
            digest = plans.sha(path)
            self.assertEqual(plans.verify(path, digest), plan)
            source.write_text("changed")
            with self.assertRaisesRegex(ValueError, "input drift"):
                plans.verify(path, digest)
            path.write_text("{}")
            with self.assertRaisesRegex(ValueError, "operator pin"):
                plans.verify(path, digest)

    def test_authorization_cannot_reuse_another_plan_or_change_budget(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "authorization.json"
            limits = {
                "task_launches": 6,
                "learning_launches": 3,
                "allocated_seconds": 108000,
            }
            body = {
                "plan_sha256": "a" * 64,
                "authorized": True,
                "user_message": "fixture only",
                "limits": limits,
            }
            path.write_text(json.dumps(body))
            self.assertEqual(
                plans.authorize({"limits": limits}, "a" * 64, path),
                {"path": str(path), "sha256": plans.sha(path)},
            )
            for wrong in (
                {**body, "authorized": False},
                {**body, "plan_sha256": "b" * 64},
                {**body, "user_message": ""},
                {**body, "limits": {**limits, "task_launches": 7}},
            ):
                path.write_text(json.dumps(wrong))
                with self.assertRaises(ValueError):
                    plans.authorize({"limits": limits}, "a" * 64, path)

    def test_receipt_publication_is_non_overwriting(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "receipt.json"
            plans.publish(path, {"state": "unknown"})
            with self.assertRaises(FileExistsError):
                plans.publish(path, {"state": "success"})
            self.assertEqual(json.loads(path.read_text()), {"state": "unknown"})


if __name__ == "__main__":
    unittest.main()
