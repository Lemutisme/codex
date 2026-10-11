"""The actual study loop finishes its finite matrix or stops on integrity failure."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import procontract_online as online
import procontract_online_pilot as pilot
import procontract_online_plan as plans


class SupervisorTests(unittest.TestCase):
    def drive(self, outcome):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = {
                "root": str(root),
                "tasks": ["a", "b", "c"],
                "arms": ["frozen", "adaptive"],
                "seed": online.seed(),
                "episode_secs": 18000,
                "limits": {
                    "task_launches": 6,
                    "learning_launches": 3,
                    "allocated_seconds": 108000,
                },
            }
            calls = []

            def child(command, **_kwargs):
                index = int(command[command.index("--index") + 1])
                arm = command[command.index("--arm") + 1]
                key = f"{index}-{arm}"
                calls.append(key)
                if outcome == "crash" and index == 1:
                    return 1
                if outcome == "missing" and index == 1:
                    return 0
                value = {
                    "task": plan["tasks"][index],
                    "episode": key,
                    "arm": arm,
                    "status": "failed" if key == "0-adaptive" else "scored",
                }
                plans.publish(root / "runs" / key / "result.json", value)
                return 0

            with (
                mock.patch.object(plans, "authorize", return_value={"fixture": True}),
                mock.patch.object(plans, "verify"),
                mock.patch.object(pilot.owned_process, "run", side_effect=child),
                mock.patch("builtins.print"),
            ):
                result = pilot.run(plan, "a" * 64, root / "authorization")
            self.assertEqual(json.loads((root / "terminal.json").read_text()), result)
            return result, calls

    def test_failed_task_does_not_cancel_other_predeclared_slots_or_hide_in_mean(self):
        result, calls = self.drive("contained")
        self.assertEqual(
            calls,
            [
                "0-frozen",
                "0-adaptive",
                "1-adaptive",
                "1-frozen",
                "2-frozen",
                "2-adaptive",
            ],
        )
        self.assertEqual(
            (result["status"], len(result["episodes"])), ("completed_with_failures", 6)
        )
        self.assertEqual(
            [e for e in result["episodes"] if e["status"] == "failed"],
            [{"task": "a", "episode": "0-adaptive", "status": "failed"}],
        )

    def test_crash_or_missing_receipt_stops_without_replacement(self):
        for failure in ("crash", "missing"):
            with self.subTest(failure=failure):
                result, calls = self.drive(failure)
                self.assertEqual(
                    (result["status"], calls),
                    ("stopped", ["0-frozen", "0-adaptive", "1-adaptive"]),
                )
                self.assertEqual(result["restarts"], 0)


if __name__ == "__main__":
    unittest.main()
