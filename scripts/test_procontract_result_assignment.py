"""A valid result for another assignment cannot replace this assignment's cache."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import procontract_store as store
import test_procontract_rsi as fixtures


class ResultAssignmentTest(unittest.TestCase):
    def test_complete_valid_cache_from_another_task_cannot_be_substituted(self):
        with tempfile.TemporaryDirectory() as tmp:
            tasks = fixtures.FakeTasks()
            host = fixtures.host(fixtures.campaign(tmp), tasks)
            version = host.incumbent()
            original = host.measure(version, fixtures.DEV[0], "dev")
            unrelated = host.measure(version, fixtures.DEV[1], "dev")
            path = Path(original["run_dir"]).parent / "result.json"
            path.write_text(json.dumps(unrelated))
            before = (list(tasks.runs), store.events(host.store))
            with self.assertRaisesRegex(RuntimeError, "task assignment"):
                fixtures.host(host.camp, tasks).measure(version, fixtures.DEV[0], "dev")
            self.assertEqual((tasks.runs, store.events(host.store)), before)

    def test_cached_coordinate_or_attempt_path_drift_never_relabels_or_executes(self):
        with tempfile.TemporaryDirectory() as tmp:
            tasks = fixtures.FakeTasks()
            host = fixtures.host(fixtures.campaign(tmp), tasks)
            version, task = host.incumbent(), fixtures.DEV[0]
            result = host.measure(version, task, "dev")
            path = Path(result["run_dir"]).parent / "result.json"
            before = (list(tasks.runs), store.events(host.store))
            for key, value in (
                ("version", "a" * 64),
                ("task", fixtures.DEV[1]),
                ("purpose", "confirm"),
                ("run_dir", str(host.camp / "elsewhere" / "attempt-1")),
                ("run_dir", str(path.parent / "attempt-3")),
            ):
                with self.subTest(key=key, value=value):
                    path.write_text(json.dumps({**result, key: value}))
                    with self.assertRaisesRegex(RuntimeError, "task assignment"):
                        fixtures.host(host.camp, tasks).measure(version, task, "dev")
                    self.assertEqual((tasks.runs, store.events(host.store)), before)
            path.write_text(json.dumps(result))
            self.assertEqual(host.measure(version, task, "dev"), result)

    def test_host_assignment_cannot_be_overridden_by_adapter_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            tasks = fixtures.FakeTasks()
            host = fixtures.host(fixtures.campaign(tmp), tasks)
            version, task = host.incumbent(), fixtures.DEV[0]
            run = tasks.run_and_label

            def labelled(*args):
                return {
                    **run(*args),
                    "version": "elsewhere",
                    "task": "another",
                    "purpose": "confirm",
                    "run_dir": "/not-this-run",
                }

            with mock.patch.object(tasks, "run_and_label", side_effect=labelled):
                result = host.measure(version, task, "dev")
            self.assertEqual(
                {key: result[key] for key in ("version", "task", "purpose", "run_dir")},
                {
                    "version": version,
                    "task": task,
                    "purpose": "dev",
                    "run_dir": str(
                        host.camp / "runs" / f"dev-{version[:12]}-{task}" / "attempt-1"
                    ),
                },
            )
            self.assertEqual(host.measure(version, task, "dev"), result)


if __name__ == "__main__":
    unittest.main()
