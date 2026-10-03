import json
import subprocess
import os
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

import procontract_evaluation as evaluation
import procontract_store as store

FAKE = [sys.executable, str(Path(__file__).parent / "testing" / "fake_programbench.py")]
INSTANCE = "owner__tool.abc1234"


def write_plan(tmp: str, steps: list[dict]) -> None:
    plan = Path(tmp, "plan.json")
    plan.write_text(json.dumps({INSTANCE: steps}))
    os.environ["FAKE_PROGRAMBENCH_PLAN"] = str(plan)


def package(tmp: str) -> Path:
    workspace = Path(tmp, "pkg-src")
    workspace.mkdir(exist_ok=True)
    Path(workspace, "compile.sh").write_text("#!/bin/sh\n")
    dest = Path(tmp, "submission.tar.gz")
    evaluation.package(workspace, dest)
    return dest


class PinTest(unittest.TestCase):
    def test_epoch_is_stable_and_drift_is_refused(self):
        pins = {
            "programbench_head": "a",
            "uv_lock_sha256": "b",
            "hf_revision": "c",
            "images": {"task": "d"},
        }
        self.assertEqual(
            evaluation.epoch(pins), evaluation.epoch(dict(reversed(list(pins.items()))))
        )
        self.assertEqual(len(evaluation.epoch(pins)), 64)
        with self.assertRaises(evaluation.PinDrift):
            evaluation.check_pins(pins, {**pins, "hf_revision": "changed"})


class EvaluateTest(unittest.TestCase):
    def evaluate(self, tmp, steps, known=frozenset()):
        write_plan(tmp, steps)
        return evaluation.evaluate_package(
            package(tmp),
            INSTANCE,
            Path(tmp, "work"),
            FAKE,
            Path(tmp),
            "rev",
            set(known),
        )

    def test_a_clean_evaluation_is_valid_on_the_first_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.evaluate(
                tmp, [{"score": "99", "solved": False, "branch_errors": []}]
            )
        self.assertEqual(
            (result["validity"], result["attempts"], result["outcome"]["score"]),
            ("valid", 1, "99"),
        )

    def test_a_new_branch_error_is_retried_then_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.evaluate(
                tmp, [{"score": "99", "solved": False, "branch_errors": ["b1"]}]
            )
        self.assertEqual((result["validity"], result["attempts"]), ("invalid", 3))

    def test_a_transient_branch_error_recovers_on_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.evaluate(
                tmp,
                [
                    {"score": "99", "solved": False, "branch_errors": ["b1"]},
                    {"score": "99", "solved": False, "branch_errors": []},
                ],
            )
        self.assertEqual((result["validity"], result["attempts"]), ("valid", 2))

    def test_known_branch_error_from_null_sentinel_is_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.evaluate(
                tmp,
                [{"score": "100", "solved": False, "branch_errors": ["efa8c407dbe3"]}],
                {"efa8c407dbe3"},
            )
        self.assertEqual((result["validity"], result["attempts"]), ("valid", 1))

    def test_the_outcome_carries_the_per_test_pass_rate(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.evaluate(
                tmp, [{"score": "90", "solved": False, "branch_errors": []}]
            )
        self.assertEqual(
            (result["outcome"]["pass_rate"], result["outcome"]["counted"]), (0.9, 10)
        )

    def test_an_evaluator_crash_counts_as_an_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.evaluate(
                tmp,
                [{"crash": True}, {"score": "✅", "solved": True, "branch_errors": []}],
            )
        self.assertEqual(
            (result["validity"], result["attempts"], result["outcome"]["solved"]),
            ("valid", 2, True),
        )


class PassRateTest(unittest.TestCase):
    def test_a_test_that_fails_every_rerun_counts_once_as_failed(self):
        # ProgramBench runs pytest with --reruns=2 and records every attempt; a test that
        # fails all three reads (passed, passed, failure).
        results = [
            {"name": "t1", "branch": "b", "status": "passed"},
            {"name": "t1", "branch": "b", "status": "passed"},
            {"name": "t1", "branch": "b", "status": "failure"},
            {"name": "t2", "branch": "b", "status": "passed"},
        ]
        self.assertEqual(
            evaluation.pass_rate(results, set(), set()),
            {"pass_rate": 0.5, "passed": 1, "counted": 2},
        )

    def test_ignored_tests_and_branches_drop_out_and_skips_leave_the_denominator(self):
        results = [
            {"name": "t1", "branch": "b", "status": "passed"},
            {"name": "t2", "branch": "b", "status": "failure"},
            {"name": "t3", "branch": "x", "status": "failure"},
            {"name": "t4", "branch": "b", "status": "skipped"},
            {"name": "t5", "branch": "b", "status": "not_run"},
        ]
        self.assertEqual(
            evaluation.pass_rate(results, {"x"}, {"b/t2"}),
            {"pass_rate": 0.5, "passed": 1, "counted": 2},
        )

    def test_nothing_countable_has_no_pass_rate(self):
        self.assertIsNone(evaluation.pass_rate([], set(), set())["pass_rate"])

    def test_ignored_tests_come_from_the_instance_tests_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = Path(tmp, "src", "programbench", "data", "tasks", INSTANCE)
            task.mkdir(parents=True)
            Path(task, "tests.json").write_text(
                json.dumps(
                    {
                        "branches": {
                            "b": {"ignored_tests": [{"name": "t2"}]},
                            "x": {"ignored": True},
                        }
                    }
                )
            )
            self.assertEqual(
                evaluation.ignored_tests(Path(tmp), INSTANCE), ({"x"}, {"b/t2"})
            )

    def test_a_task_without_tests_json_ignores_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(
                evaluation.ignored_tests(Path(tmp), INSTANCE), (set(), set())
            )


class LabelKeyTest(unittest.TestCase):
    def test_label_keys_separate_roles_with_identical_bytes(self):
        judged = {
            "kind": "judged",
            "contract_id": "c",
            "generation": 1,
            "verdict": "support",
        }
        final = {"kind": "final_workspace"}
        self.assertNotEqual(
            evaluation.label_key("r", "s", judged, "e"),
            evaluation.label_key("r", "s", final, "e"),
        )


if __name__ == "__main__":
    os.chdir(Path(__file__).parent)
    unittest.main()


class LabelRunTest(unittest.TestCase):
    def run_dir_with_judgment(self, tmp: str) -> tuple[Path, str]:
        run_dir = Path(tmp, "run")
        workspace = run_dir / "workspace"
        workspace.mkdir(parents=True)
        Path(workspace, "answer.txt").write_text("judged")
        run_store = run_dir / "codex-home" / "pro_contract"
        captured = store.capture(run_store, workspace, ["executable", "target", ".git"])
        store.append(
            run_store,
            "verification",
            {**store.identities(model="m"), "policies": {"reviewer": "00" * 32}},
            {
                "contract_id": "c1",
                "generation": 1,
                "subject_hash": captured["subject_hash"],
                "verdict": "support",
            },
        )
        Path(workspace, "answer.txt").write_text("edited after freezing")
        return run_dir, captured["subject_hash"]

    def label(self, tmp, run_dir, steps, known=frozenset()):
        write_plan(tmp, steps)
        return evaluation.label_run(
            run_dir,
            Path(tmp, "batch-store"),
            "r1",
            INSTANCE,
            "ee" * 32,
            FAKE,
            Path(tmp),
            "rev",
            set(known),
            store.identities(),
        )

    def test_the_judged_subject_is_labelled_from_its_frozen_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir, judged = self.run_dir_with_judgment(tmp)
            labels = self.label(
                tmp, run_dir, [{"score": "99", "solved": False, "branch_errors": []}]
            )
            seen_file = (
                run_dir
                / "labels"
                / judged
                / "eval"
                / "attempt-1"
                / INSTANCE
                / "fake-seen.json"
            )
            seen = json.loads(seen_file.read_text())
        roles = sorted(label["role"]["kind"] for label in labels)
        self.assertEqual(roles, ["final_workspace", "judged"])
        self.assertEqual(seen["./answer.txt"], "judged")

    def test_label_run_labels_final_workspace_without_judgments(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp, "run")
            Path(run_dir, "workspace").mkdir(parents=True)
            Path(run_dir, "workspace", "main.rs").write_text("x")
            labels = self.label(
                tmp, run_dir, [{"score": "70", "solved": False, "branch_errors": []}]
            )
        self.assertEqual(
            [label["role"]["kind"] for label in labels], ["final_workspace"]
        )

    def test_labelling_twice_does_not_duplicate_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir, _ = self.run_dir_with_judgment(tmp)
            step = [{"score": "99", "solved": False, "branch_errors": []}]
            self.label(tmp, run_dir, step)
            again = self.label(tmp, run_dir, step)
            labels = [
                e
                for e in store.events(Path(tmp, "batch-store"))
                if e["event"]["kind"] == "label"
            ]
        self.assertEqual((again, len(labels)), ([], 2))

    def test_a_missing_subject_gives_an_invalid_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp, "run")
            Path(run_dir, "workspace").mkdir(parents=True)
            run_store = run_dir / "codex-home" / "pro_contract"
            store.append(
                run_store,
                "verification",
                {**store.identities(model="m"), "policies": {"reviewer": "00" * 32}},
                {
                    "contract_id": "c1",
                    "generation": 1,
                    "subject_hash": "ab" * 32,
                    "verdict": "defeat",
                },
            )
            labels = self.label(
                tmp, run_dir, [{"score": "70", "solved": False, "branch_errors": []}]
            )
        judged = [label for label in labels if label["role"]["kind"] == "judged"]
        self.assertEqual(
            (judged[0]["validity"], "not bound" in judged[0]["reason"]),
            ("invalid", True),
        )

    def test_unreadable_workspace_gives_an_invalid_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp, "run")
            secret = Path(run_dir, "workspace", "secret")
            secret.parent.mkdir(parents=True)
            secret.write_text("x")
            secret.chmod(0)
            try:
                labels = self.label(
                    tmp,
                    run_dir,
                    [{"score": "70", "solved": False, "branch_errors": []}],
                )
            finally:
                secret.chmod(0o600)
        self.assertEqual(
            (labels[0]["validity"], labels[0]["outcome"]), ("invalid", None)
        )

    def test_a_package_failure_is_an_invalid_label_and_later_subjects_still_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir, _ = self.run_dir_with_judgment(tmp)
            real = evaluation.package
            calls = []

            def flaky(source, archive):
                calls.append(archive)
                if len(calls) == 1:
                    raise subprocess.CalledProcessError(2, "tar")
                real(source, archive)

            with mock.patch.object(evaluation, "package", flaky):
                labels = self.label(
                    tmp,
                    run_dir,
                    [{"score": "99", "solved": False, "branch_errors": []}],
                )
        by_role = {label["role"]["kind"]: label for label in labels}
        self.assertEqual(by_role["judged"]["validity"], "invalid")
        self.assertEqual(by_role["final_workspace"]["validity"], "valid")

    def test_malformed_eval_json_is_a_crashed_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_plan(
                tmp,
                [
                    {"score": "70", "malformed": True},
                    {"score": "70", "solved": False, "branch_errors": []},
                ],
            )
            result = evaluation.evaluate_package(
                package(tmp), INSTANCE, Path(tmp, "work"), FAKE, Path(tmp), "rev", set()
            )
        self.assertEqual((result["validity"], result["attempts"]), ("valid", 2))
