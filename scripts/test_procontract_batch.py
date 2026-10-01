import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import procontract_batch as batch

PROTOCOL = {
    "retries": {"eval_branch_error": 2, "run_crash": 1},
    "duplicates_per_arm": 4,
}


class PlanTest(unittest.TestCase):
    def test_plan_is_seeded_balanced_and_duplicates_four_instances_per_arm(self):
        dev = [f"o{i}__r{i}.abc{i:04d}" for i in range(40)]
        difficulty = {i: ("easy" if n % 2 else "hard") for n, i in enumerate(dev)}

        runs = batch.plan_runs(dev, difficulty, 30, 4, seed=7)

        self.assertEqual(runs, batch.plan_runs(dev, difficulty, 30, 4, seed=7))
        self.assertEqual(len(runs), 30 * 2 + 4 * 2)
        self.assertEqual(sorted(r["order"] for r in runs), list(range(len(runs))))
        repeats = [r for r in runs if r["repeat"] == 2]
        self.assertEqual(sorted({(r["arm"]) for r in repeats}), ["off", "on"])
        self.assertEqual(len(repeats), 8)


class ReconcileTest(unittest.TestCase):
    def test_actions_follow_the_state_machine_and_crash_budget(self):
        self.assertEqual(
            batch.next_action({"phase": "planned", "attempt": 1}, PROTOCOL), "prepare"
        )
        self.assertEqual(
            batch.next_action({"phase": "prepared", "attempt": 1}, PROTOCOL), "run"
        )
        self.assertEqual(
            batch.next_action({"phase": "ran", "attempt": 1}, PROTOCOL), "label"
        )
        self.assertEqual(
            batch.next_action({"phase": "labelled", "attempt": 1}, PROTOCOL), "done"
        )
        self.assertEqual(
            batch.next_action({"phase": "running", "attempt": 1}, PROTOCOL), "prepare"
        )
        self.assertEqual(
            batch.next_action({"phase": "running", "attempt": 2}, PROTOCOL), "invalid"
        )


class LockTest(unittest.TestCase):
    def test_second_batch_process_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            with batch.BatchLock(Path(tmp)):
                with self.assertRaises(RuntimeError):
                    with batch.BatchLock(Path(tmp)):
                        pass


class RunBatchTest(unittest.TestCase):
    def setUp(self):
        for name in ("FAKE_RUNNER_FAIL_PREPARE", "FAKE_RUNNER_CRASH_ONCE"):
            os.environ.pop(name, None)

    def test_failed_prepare_is_invalid_and_the_batch_continues(self):
        with tempfile.TemporaryDirectory() as tmp:
            batch_dir = Path(tmp)
            runs = [
                {
                    "run_id": "r-bad",
                    "instance": "bad__img.0000000",
                    "arm": "on",
                    "repeat": 1,
                    "order": 0,
                },
                {
                    "run_id": "r-ok",
                    "instance": "ok__img.0000000",
                    "arm": "off",
                    "repeat": 1,
                    "order": 1,
                },
            ]
            fake = [
                sys.executable,
                str(Path(__file__).parent / "testing" / "fake_runner.py"),
            ]
            os.environ["FAKE_RUNNER_FAIL_PREPARE"] = "bad__img.0000000"
            labelled = []

            batch.run_batch(
                batch_dir,
                runs,
                PROTOCOL,
                fake,
                label=lambda run, run_dir: labelled.append(run["run_id"]),
                parallel=1,
            )

            state = {
                r["run_id"]: json.loads(
                    Path(batch_dir, "runs", r["run_id"], "state.json").read_text()
                )
                for r in runs
            }
        self.assertEqual(state["r-bad"]["phase"], "invalid")
        self.assertIn("prepare failed", state["r-bad"]["reason"])
        self.assertEqual((state["r-ok"]["phase"], labelled), ("labelled", ["r-ok"]))

    def test_a_crashed_run_is_rerun_once_in_a_fresh_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            batch_dir = Path(tmp)
            runs = [
                {
                    "run_id": "r1",
                    "instance": "x__y.0000000",
                    "arm": "on",
                    "repeat": 1,
                    "order": 0,
                }
            ]
            fake = [
                sys.executable,
                str(Path(__file__).parent / "testing" / "fake_runner.py"),
            ]
            os.environ["FAKE_RUNNER_CRASH_ONCE"] = str(Path(tmp, "crashed"))

            batch.run_batch(
                batch_dir,
                runs,
                PROTOCOL,
                fake,
                label=lambda run, run_dir: None,
                parallel=1,
            )

            state = json.loads(Path(batch_dir, "runs", "r1", "state.json").read_text())
        self.assertEqual((state["phase"], state["attempt"]), ("labelled", 2))


if __name__ == "__main__":
    unittest.main()
