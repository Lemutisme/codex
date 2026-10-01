import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import procontract_m0_report as report
import procontract_store as store


def row(
    task,
    arm,
    role,
    verdict=None,
    solved=False,
    validity="valid",
    score=80.0,
    validated=None,
):
    return {
        "task": task,
        "arm": arm,
        "run_id": f"{task}-{arm}",
        "role": role,
        "verdict": verdict,
        "validity": validity,
        "solved": solved,
        "score": score,
        "validated": validated,
        "cost_total": 10,
    }


class EstimandTest(unittest.TestCase):
    def test_estimands_use_the_specified_denominators(self):
        rows = [
            row("a", "on", "judged", "support", solved=True),
            row("b", "on", "judged", "support", solved=False),
            row("c", "on", "judged", "defeat", solved=True, validated=True),
            row("d", "on", "judged", "support", validity="invalid", solved=None),
            row("a", "on", "final_workspace", solved=True, score=100.0),
            row("a", "off", "final_workspace", solved=False, score=90.0),
        ]
        result = report.estimands(rows, {"a": 67.0}, seed=1)

        self.assertEqual(result["p_solved_given_supported"]["point"], 0.5)
        self.assertEqual(result["p_solved_given_supported"]["n"], 2)
        self.assertEqual(result["missed_defect_rate"]["point"], 0.5)
        self.assertEqual(result["disagreement"]["point"], 1.0)
        self.assertEqual(result["validated_defeats"]["point"], 1.0)
        self.assertEqual(result["excluded"]["invalid"], 1)
        self.assertEqual(
            result["solved_by_arm"],
            {
                "on": {"solved": 1, "valid": 1, "invalid": 0, "missing": 0},
                "off": {"solved": 0, "valid": 1, "invalid": 0, "missing": 0},
            },
        )
        self.assertEqual(result["score_above_null"]["on"], 33.0)

    def test_clustered_ci_is_deterministic_and_brackets_the_point(self):
        values = {"a": [1.0, 1.0], "b": [0.0], "c": [1.0]}
        point, low, high = report.clustered_ci(values, seed=3)
        self.assertEqual((point, low, high), report.clustered_ci(values, seed=3))
        self.assertTrue(low <= point <= high)

    def test_repeat_two_rows_do_not_inflate_arm_counts_or_costs(self):
        first = row("a", "on", "final_workspace", solved=True, score=100.0)
        second = dict(first, run_id="a-on-2", repeat=2, solved=False, cost_total=999)
        rows = [first, second]
        result = report.estimands(rows, {"a": 50.0})
        self.assertEqual(result["solved_by_arm"]["on"]["valid"], 1)
        self.assertEqual(result["score_above_null"]["on"], 50.0)
        self.assertEqual(report.costs(rows), {"on": {"median": 10, "p90": 10}})

    def test_missing_counts_assigned_runs_without_a_final_label(self):
        rows = [row("a", "on", "final_workspace", solved=True)]
        assigned = [
            {"run_id": "a-on", "arm": "on", "repeat": 1},
            {"run_id": "b-on", "arm": "on", "repeat": 1},
            {"run_id": "b-on-2", "arm": "on", "repeat": 2},
        ]
        result = report.estimands(rows, {}, assigned=assigned)
        self.assertEqual(result["solved_by_arm"]["on"]["missing"], 1)

    def test_validated_defeats_ignore_label_validity(self):
        rows = [
            row(
                "a",
                "on",
                "judged",
                "defeat",
                solved=None,
                validity="invalid",
                validated=True,
            ),
            row("b", "on", "judged", "defeat", solved=True, validated=False),
            row("c", "on", "judged", "defeat", solved=True, validated=None),
        ]
        result = report.estimands(rows, {})
        self.assertEqual(result["validated_defeats"]["point"], 0.5)
        self.assertEqual(result["validated_defeats"]["n"], 2)
        self.assertEqual(result["disagreement"]["n"], 2)


class RevalidationPiecesTest(unittest.TestCase):
    def test_failing_steps_treats_non_pass_as_failure_and_skips_malformed(self):
        out = "noise\n@@PC a pass\n@@PC b fail\n@@PC c timeout\n@@PC d\n@@PC\n"
        self.assertEqual(report._failing_steps(out), {"b", "c"})

    def test_latest_attempt_is_numeric(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertIsNone(report._latest_attempt(root))
            for name in ["attempt-2", "attempt-10", "attempt-x"]:
                (root / name).mkdir()
            self.assertEqual(report._latest_attempt(root), root / "attempt-10")

    def test_defeat_without_run_dir_is_not_checkable(self):
        with tempfile.TemporaryDirectory() as tmp:
            body = {
                "run_id": "r",
                "instance": "i",
                "role": {"contract_id": "c", "generation": 1},
            }
            self.assertIsNone(report._revalidate_one(Path(tmp), body))


def _append(batch_store, kind, body):
    return store.append(
        batch_store, kind, store.identities(evaluator_epoch="1" * 64), body
    )


def label(run_id, instance, role, validity="valid", solved=True, score="✅"):
    return {
        "label_key": "2" * 64,
        "run_id": run_id,
        "instance": instance,
        "subject_hash": "0" * 64,
        "role": role,
        "outcome": None if solved is None else {"solved": solved, "score": score},
        "validity": validity,
        "reason": None,
        "attempts": 1,
    }


class BatchTest(unittest.TestCase):
    def build(self, tmp):
        batch = Path(tmp)
        bs = batch / "store"
        bs.mkdir()
        for run_id, arm, repeat in [("r1", "on", 1), ("r2", "on", 2), ("r3", "off", 1)]:
            _append(
                bs,
                "assignment",
                {"run_id": run_id, "instance": "t__a", "arm": arm, "repeat": repeat},
            )
        cost = {"executor": {"total_tokens": 5}, "workers": {"total_tokens": 7}}
        _append(
            bs,
            "execution",
            {
                "run_id": "r1",
                "instance": "t__a",
                "arm": "on",
                "repeat": 1,
                "attempt": 1,
                "cost": cost,
            },
        )
        judged = {
            "kind": "judged",
            "contract_id": "c",
            "generation": 1,
            "verdict": "support",
        }
        _append(bs, "label", label("r1", "t__a", judged, solved=False, score="50"))
        _append(
            bs,
            "label",
            label("r1", "t__a", {"kind": "final_workspace"}, solved=False, score="50"),
        )
        _append(
            bs, "label", label("r2", "t__a", {"kind": "final_workspace"}, solved=True)
        )
        _append(
            bs, "label", label("r1", "t__a", {"kind": "final_workspace"}, solved=True)
        )
        _append(
            bs,
            "label",
            label(None, "t__a", {"kind": "null_sentinel"}, solved=True, score="40"),
        )
        return batch

    def test_load_rows_dedupes_relabels_and_reads_nulls_and_costs(self):
        with tempfile.TemporaryDirectory() as tmp:
            batch = self.build(tmp)
            rows, nulls, assigned = report.load_rows(batch)
        self.assertEqual(nulls, {"t__a": 40.0})
        self.assertEqual(len(assigned), 3)
        finals = {r["run_id"]: r for r in rows if r["role"] == "final_workspace"}
        self.assertEqual(sorted(finals), ["r1", "r2"])
        self.assertTrue(finals["r1"]["solved"])
        self.assertEqual(finals["r1"]["score"], 100.0)
        self.assertEqual(finals["r1"]["cost_total"], 12)
        self.assertEqual(finals["r1"]["arm"], "on")
        self.assertEqual(finals["r2"]["repeat"], 2)
        self.assertEqual(len([r for r in rows if r["role"] == "judged"]), 1)

    def test_report_cli_writes_json_and_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            batch = self.build(tmp)
            out = batch / "REPORT-M0.md"
            argv = ["m0", "report", "--batch-dir", str(batch), "--out", str(out)]
            with mock.patch.object(sys, "argv", argv):
                report.main()
            data = json.loads(out.with_suffix(".json").read_text())
            self.assertEqual(
                data["solved_by_arm"]["on"],
                {"solved": 1, "valid": 1, "invalid": 0, "missing": 0},
            )
            self.assertEqual(data["solved_by_arm"]["off"]["missing"], 1)
            self.assertEqual(
                data["noise"],
                {"pairs": 1, "solved_agreement": 1.0, "mean_abs_score_diff": 0.0},
            )
            self.assertEqual(data["costs"], {"on": {"median": 12, "p90": 12}})
            self.assertTrue(out.read_text().startswith("# M0 report"))


class HelperTest(unittest.TestCase):
    def test_score_parsing(self):
        self.assertEqual(report._score("✅"), 100.0)
        self.assertEqual(report._score("67"), 67.0)
        self.assertIsNone(report._score(None))
        self.assertIsNone(report._score("n/a"))

    def test_noise_on_a_pair(self):
        a = row("t", "on", "final_workspace", solved=True, score=100.0)
        b = dict(a, repeat=2, solved=False, score=90.0)
        self.assertEqual(
            report.noise([dict(a, repeat=1), b]),
            {"pairs": 1, "solved_agreement": 0.0, "mean_abs_score_diff": 10.0},
        )
        self.assertEqual(report.noise([dict(a, repeat=1)]), {"pairs": 0})


if __name__ == "__main__":
    unittest.main()
