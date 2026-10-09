"""Real Host/store and private native reader; only model/mount transport is synthetic."""

import json
from pathlib import Path
import shutil
import unittest
from unittest import mock

import procontract_h_admission as admission
import procontract_h_notice_delivery as delivery_gate
import procontract_native_trace_binding as binding
import procontract_ph_protocol as protocol
import procontract_succession as succession
import test_procontract_h_admission as fixtures

write = fixtures.write


class NoticeDeliveryTest(unittest.TestCase):
    args = fixtures.AdmissionTest.args
    make_host = fixtures.AdmissionTest.make_host
    cached = fixtures.AdmissionTest.cached
    setUp = fixtures.AdmissionTest.setUp
    complete = fixtures.AdmissionTest.complete
    unspent = fixtures.AdmissionTest.unspent
    measured = fixtures.AdmissionTest.measured
    root_program_document = {
        "schema": 2,
        "action": "checkpoint",
        "when": {"always": True},
    }
    program_document = {
        "schema": 2,
        "action": "checkpoint",
        "when": {"all": [{"always": True}]},
    }
    confirmation_outcomes = None

    def trace_outcome(self, version, task, purpose):
        if purpose == "confirm" and self.confirmation_outcomes is not None:
            return self.confirmation_outcomes.get((version, task), "unknown")
        return "observed"

    def table(self):
        return [
            e["body"]
            for e in self.host.events("selection")
            if e["body"].get("role") == "h_confirmation_delivery"
        ]

    def test_ack_only_probe_is_durably_inconclusive_without_confirmation_spend(self):
        trace = self.trace_fixtures[str(self.run)]
        trace.outcome = "unknown"
        summary = protocol.document(self.run / "run.json")
        summary["native_notice_trace"] = trace.finish(
            summary["delivery_budget"], summary["native_process_exit"]
        )
        write(self.run / "run.json", summary)
        with mock.patch.object(self.host, "measure_all") as measure:
            self.assertIn(
                "native notice remains unknown",
                self.host.confirm(self.candidate_id, self.parent),
            )
            measure.assert_not_called()
        self.assertEqual(self.unspent(), ([], [], 2))
        # Later native evidence cannot upgrade the frozen unknown receipt.
        trace.write_events(trace.events)
        with self.assertRaisesRegex(RuntimeError, "changed"):
            self.host.confirm(self.candidate_id, self.parent)
        self.assertEqual(self.unspent(), ([], [], 2))

    def test_incumbent_and_probe_witnesses_do_not_certify_candidate_confirmations(self):
        self.confirmation_outcomes = {
            (self.parent, task): "observed"
            for task in self.host.terms["pools"]["confirm"]
        }
        with mock.patch.object(self.host, "measure_all", side_effect=self.measured):
            self.assertIn(
                "no candidate task observed",
                self.host.confirm(self.candidate_id, self.parent),
            )
        evidence = self.table()[0]["evidence"]
        self.assertEqual(
            (
                evidence["candidate_observed"],
                len(evidence["arms"]),
                self.host.incumbent(),
            ),
            (0, 8, self.parent),
        )
        self.assertEqual(
            sum(a["delivery"]["status"] == "observed" for a in evidence["arms"]), 4
        )
        state = self.host.contract(f"adoption.{self.candidate_id[:16]}")
        self.assertEqual((state["standing"], state["support"]), ("released", None))
        before = self.unspent()
        self.assertIn(
            "sources remain spent", self.host.confirm(self.candidate_id, self.parent)
        )
        self.assertEqual(self.unspent(), before)

    def test_one_candidate_completed_notice_request_is_enough_but_not_obedience(self):
        task = self.host.terms["pools"]["confirm"][0]
        self.confirmation_outcomes = {(self.candidate_id, task): "observed"}
        with mock.patch.object(self.host, "measure_all", side_effect=self.measured):
            self.assertIn("adopted", self.host.confirm(self.candidate_id, self.parent))
        evidence = self.table()[0]["evidence"]
        self.assertEqual(
            (
                evidence["candidate_observed"],
                evidence["binding_failures"],
                len(evidence["arms"]),
            ),
            (1, [], 8),
        )
        self.assertEqual(self.host.incumbent(), self.candidate_id)
        for path in self.host.camp.glob("runs/*/attempt-1/private-native-trace"):
            shutil.rmtree(path)
        self.assertIn("already adopted", self.host.adopt(self.candidate_id))

    def test_another_arm_binding_failure_blocks_even_with_candidate_witnesses(self):
        def corrupt(pairs, purpose):
            results = self.measured(pairs, purpose)
            run = Path(
                results[(self.parent, self.host.terms["pools"]["confirm"][0])][
                    "run_dir"
                ]
            )
            path = run / "native-notice-baseline.json"
            path.write_bytes(path.read_bytes() + b" ")
            return results

        with mock.patch.object(self.host, "measure_all", side_effect=corrupt):
            self.assertIn(
                "invalid native trace bindings",
                self.host.confirm(self.candidate_id, self.parent),
            )
        evidence = self.table()[0]["evidence"]
        self.assertEqual(
            (evidence["candidate_observed"], len(evidence["binding_failures"])), (4, 1)
        )
        self.assertEqual(self.host.incumbent(), self.parent)

    def test_direct_or_supported_adoption_cannot_create_missing_delivery_table(self):
        with (
            mock.patch.object(self.host, "measure_all", side_effect=self.measured),
            mock.patch.object(delivery_gate, "confirmation"),
            mock.patch.object(self.host, "adopt"),
        ):
            self.host.confirm(self.candidate_id, self.parent)
        self.assertEqual(self.table(), [])
        with self.assertRaisesRegex(RuntimeError, "delivery is missing"):
            self.host.adopt(self.candidate_id, presumed=True)
        with mock.patch.object(self.host, "measure_all") as measure:
            with self.assertRaisesRegex(RuntimeError, "delivery is missing"):
                self.host.confirm(self.candidate_id, self.parent)
            measure.assert_not_called()
        self.assertEqual(self.host.incumbent(), self.parent)

    def test_freeze_to_support_interruption_reuses_cached_tasks_without_new_cost(self):
        with (
            mock.patch.object(self.host, "measure_all", side_effect=self.measured),
            mock.patch.object(self.host, "support", side_effect=InterruptedError),
        ):
            with self.assertRaises(InterruptedError):
                self.host.confirm(self.candidate_id, self.parent)
        frozen, before = self.table(), self.unspent()
        self.assertEqual(len(frozen), 1)
        with mock.patch.object(
            self.host.adapter,
            "run_and_label",
            side_effect=AssertionError("new paid attempt"),
        ):
            self.assertIn("adopted", self.host.confirm(self.candidate_id, self.parent))
        self.assertEqual((self.table(), self.unspent()), (frozen, before))

    def test_raw_trace_drift_after_support_blocks_first_adoption(self):
        with (
            mock.patch.object(self.host, "measure_all", side_effect=self.measured),
            mock.patch.object(self.host, "adopt"),
        ):
            self.host.confirm(self.candidate_id, self.parent)
        task = self.host.terms["pools"]["confirm"][0]
        run = (
            self.host.camp
            / "runs"
            / f"confirm-{self.candidate_id[:12]}-{task}"
            / "attempt-1"
        )
        payload = next((run / binding.ROOT).glob("*/payloads/3.json"))
        value = json.loads(payload.read_text())
        value["input"][-1]["content"][0]["text"] = "a different notice"
        write(payload, value)
        with self.assertRaisesRegex(RuntimeError, "delivery is missing, changed"):
            self.host.adopt(self.candidate_id, presumed=True)
        self.assertEqual(self.host.incumbent(), self.parent)

    def test_a_late_receipt_rewrite_cannot_upgrade_frozen_unknown_confirmation(self):
        self.confirmation_outcomes = {}
        with mock.patch.object(self.host, "measure_all", side_effect=self.measured):
            self.host.confirm(self.candidate_id, self.parent)
        task = self.host.terms["pools"]["confirm"][0]
        run = (
            self.host.camp
            / "runs"
            / f"confirm-{self.candidate_id[:12]}-{task}"
            / "attempt-1"
        )
        trace = self.trace_fixtures[str(run)]
        trace.outcome = "observed"
        summary = protocol.document(run / "run.json")
        summary["native_notice_trace"] = trace.finish(
            summary["delivery_budget"], summary["native_process_exit"]
        )
        write(run / "run.json", summary)
        with self.assertRaisesRegex(RuntimeError, "changed"):
            delivery_gate.confirmation(
                self.host,
                self.candidate_id,
                succession.confirmation_plan(self.host, self.candidate_id),
            )
        self.assertEqual(self.host.incumbent(), self.parent)


if __name__ == "__main__":
    unittest.main()
