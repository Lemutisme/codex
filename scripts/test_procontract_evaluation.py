import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import procontract_evaluation as evaluation

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
