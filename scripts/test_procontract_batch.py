import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import procontract_batch as batch
import procontract_evaluation as evaluation
import procontract_store as store

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

    def test_a_label_failure_halts_the_batch_and_leaves_the_run_ran(self):
        with tempfile.TemporaryDirectory() as tmp:
            batch_dir = Path(tmp)
            runs = [
                {
                    "run_id": f"r{i}",
                    "instance": f"x__y.000000{i}",
                    "arm": "on",
                    "repeat": 1,
                    "order": i,
                }
                for i in range(3)
            ]
            fake = [
                sys.executable,
                str(Path(__file__).parent / "testing" / "fake_runner.py"),
            ]

            def label(run, run_dir):
                raise evaluation.PinDrift("drift")

            with self.assertRaises(evaluation.PinDrift):
                batch.run_batch(
                    batch_dir, runs, PROTOCOL, fake, label=label, parallel=1
                )

            phases = [
                json.loads(
                    Path(batch_dir, "runs", r["run_id"], "state.json").read_text()
                )["phase"]
                if Path(batch_dir, "runs", r["run_id"], "state.json").exists()
                else "planned"
                for r in runs
            ]
        self.assertEqual(phases, ["ran", "planned", "planned"])


class KnownBranchErrorsTest(unittest.TestCase):
    def test_missing_known_lists_planned_instances_without_a_baseline(self):
        runs = [
            {"instance": "a"},
            {"instance": "b"},
            {"instance": "b"},
            {"instance": "c"},
        ]
        self.assertEqual(batch.missing_known(runs, {"a": [], "c": ["e"]}), ["b"])


class RelabelTest(unittest.TestCase):
    def test_execution_event_is_appended_once_per_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            batch_store = Path(tmp, "store")
            run_dir = Path(tmp, "runs", "r1", "attempt-2")
            run_dir.mkdir(parents=True)
            Path(run_dir, "run.json").write_text(json.dumps({"turns_completed": 1}))
            run = {"run_id": "r1", "instance": "x__y.0000000", "arm": "on", "repeat": 1}

            batch.append_execution(batch_store, store.identities(), run, run_dir)
            batch.append_execution(batch_store, store.identities(), run, run_dir)

            bodies = [e["event"]["body"] for e in store.events(batch_store)]
        self.assertEqual(
            bodies,
            [{**run, "attempt": 2, "turns_completed": 1}],
        )

    def test_archive_is_built_atomically_and_falls_back_to_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp, "src")
            source.mkdir()
            Path(source, "f").write_text("data")
            archive = Path(tmp, "arch", "r1")
            archive.with_name(f"r1.tmp-{os.getpid()}").mkdir(parents=True)

            with mock.patch("os.link", side_effect=OSError("EXDEV")):
                batch.archive_run(source, archive)

            self.assertEqual(Path(archive, "f").read_text(), "data")
            self.assertEqual([p.name for p in archive.parent.iterdir()], ["r1"])


if __name__ == "__main__":
    unittest.main()
