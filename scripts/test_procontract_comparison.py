import json
import tempfile
import unittest
from unittest import mock

import procontract_comparison as comparison
from test_procontract_rsi import FakeTasks, host, stream_campaign


class ComparisonTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.stream = host(stream_campaign(temporary.name), FakeTasks())
        self.baseline = host(
            stream_campaign(temporary.name, name="baseline"), FakeTasks()
        )

    def test_rejects_changed_identity_and_committed_order(self):
        comparison.validate_comparison(self.stream, self.baseline)
        for key in (
            "codex_sha256",
            "model",
            "effort",
            "task_prompt",
            "research_image",
            "programbench_head",
            "hf_revision",
            "task_deadline_secs",
        ):
            with (
                self.subTest(key=key),
                mock.patch.dict(self.baseline.terms, {key: "other"}),
            ):
                with self.assertRaisesRegex(ValueError, key):
                    comparison.validate_comparison(self.stream, self.baseline)
        with mock.patch.dict(self.baseline.terms["stream"], {"order": []}):
            with self.assertRaisesRegex(ValueError, "order"):
                comparison.validate_comparison(self.stream, self.baseline)

    def test_rejects_a_different_operator_root_not_current_incumbent(self):
        with mock.patch.object(self.baseline, "incumbent", return_value="successor"):
            comparison.validate_comparison(self.stream, self.baseline)
        roots = self.baseline.versions()
        roots["other"] = roots.pop(next(iter(roots)))
        with mock.patch.object(self.baseline, "versions", return_value=roots):
            with self.assertRaisesRegex(ValueError, "roots differ"):
                comparison.validate_comparison(self.stream, self.baseline)

    def test_stream_mode_normalizes_legacy_explore_but_not_guarded(self):
        self.baseline.terms["stream"]["mode"] = "explore"
        comparison.validate_comparison(self.stream, self.baseline)
        self.baseline.terms["stream"]["mode"] = "guarded"
        with self.assertRaisesRegex(ValueError, "mode"):
            comparison.validate_comparison(self.stream, self.baseline)

    def test_method_comparison_normalizes_old_defer_but_not_paired_updaters(self):
        self.baseline.terms["stream"]["method_confirmation"] = "defer"
        comparison.validate_comparison(self.stream, self.baseline)
        self.baseline.terms["stream"]["method_confirmation"] = "paired-descendants"
        with self.assertRaisesRegex(ValueError, "method_confirmation"):
            comparison.validate_comparison(self.stream, self.baseline)

    def test_registry_bound_campaign_cannot_be_compared_with_generic_or_other_pins(
        self,
    ):
        self.stream.terms["canonical"] = {"pins_sha256": "a" * 64}
        with self.assertRaisesRegex(ValueError, "canonical"):
            comparison.validate_comparison(self.stream, self.baseline)
        self.baseline.terms["canonical"] = {"pins_sha256": "b" * 64}
        with self.assertRaisesRegex(ValueError, "canonical"):
            comparison.validate_comparison(self.stream, self.baseline)
        self.baseline.terms["canonical"] = dict(self.stream.terms["canonical"])
        comparison.validate_comparison(self.stream, self.baseline)

    def test_coverage_keeps_invalid_and_unassigned_tasks_in_denominator(self):
        tasks = self.stream.order()
        root = self.stream.incumbent()
        self.stream.record(
            "assignment", {"batch": 1, "version": root, "tasks": tasks[:2]}
        )
        self.stream.measure(root, tasks[0], "stream")
        self.baseline.measure(root, tasks[0], "baseline")
        invalid = self.stream.camp / "runs" / "stream-invalid" / "result.json"
        invalid.parent.mkdir()
        invalid.write_text(
            json.dumps({"version": root, "task": tasks[1], "validity": "invalid"})
        )
        report = comparison.coverage(self.stream, self.baseline)
        self.assertEqual(
            {
                k: report[k]
                for k in ("status", "total_tasks", "assigned_tasks", "valid_pairs")
            },
            {
                "status": "incomplete",
                "total_tasks": 5,
                "assigned_tasks": 2,
                "valid_pairs": 1,
            },
        )
        self.assertEqual(
            report["stream"],
            {"valid": tasks[:1], "invalid": tasks[1:2], "missing": tasks[2:]},
        )
        self.assertEqual(
            report["baseline"],
            {"valid": tasks[:1], "invalid": [], "missing": tasks[1:]},
        )

    def test_rejects_baseline_results_from_a_successor(self):
        path = self.baseline.camp / "runs" / "baseline-wrong" / "result.json"
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps(
                {
                    "task": self.stream.order()[0],
                    "version": "successor",
                    "validity": "valid",
                }
            )
        )
        with self.assertRaisesRegex(ValueError, "unassigned baseline"):
            comparison.coverage(self.stream, self.baseline)
