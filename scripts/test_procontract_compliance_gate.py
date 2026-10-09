"""Real Host/store routing with synthetic task/auditor peers; not compliance/RSI proof."""

import hashlib
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

import procontract_compliance_gate as gate
import procontract_guarded_stream as guarded
import procontract_store as store
import test_procontract_guarded_stream as guarded_fixtures


class GateTest(unittest.TestCase):
    make_host = guarded_fixtures.GuardedStreamTest.make_host

    def setUp(self):
        self.host = self.make_host()
        self.host.terms["pools"]["confirm"] = self.host.terms["pools"]["confirm"][:4]
        self.host.terms["gates"].update(confirm_tasks=4, confirm_min_wins=3)
        self.calls, self.verified, self.receipts = [], [], {}
        self.outcomes, self.corrupt = {}, None
        self.adapter = SimpleNamespace(build_run_pack=self.capture)
        self.auditor = SimpleNamespace(execute=self.execute, verify=self.verify)
        self.enterContext(
            mock.patch.dict(
                sys.modules,
                {
                    "procontract_compliance_adapter": self.adapter,
                    "procontract_fixed_auditor": self.auditor,
                },
            )
        )
        self.enterContext(mock.patch.object(gate, "enabled", return_value=True))

    def capture(self, host, run):
        artifacts = {
            name: hashlib.sha256((run / name).read_bytes()).hexdigest()
            for name in ("manifest.json", "run.json", "../result.json")
        }
        if self.corrupt:
            artifacts["synthetic_corruption"] = self.corrupt
        return {"synthetic_pack": True}, {"artifacts": artifacts}

    def execute(self, host, phase, packs, receipts):
        self.calls.append((phase, len(packs), len(host.insights())))
        self.assertNotIn(phase, self.receipts)
        receipt = {
            "phase": phase,
            "outcome": self.outcomes.get(phase, "accepted"),
            "identity": store.digest("synthetic_capture", receipts),
        }
        self.receipts[phase] = receipt
        return receipt

    def verify(self, host, phase, packs, receipts):
        self.verified.append(phase)
        receipt = self.receipts[phase]
        if receipt["identity"] != store.digest("synthetic_capture", receipts):
            raise RuntimeError("bound source changed")
        return receipt

    def test_four_fixed_jobs_precede_each_learning_and_first_adoption(self):
        root = self.host.incumbent()
        for _ in range(3):
            self.host.stream_step()
        self.assertEqual(
            [(phase, size) for phase, size, _ in self.calls],
            [
                ("initial_serve", 1),
                ("probe", 1),
                ("confirmation", 8),
                ("successor_serve", 1),
            ],
        )
        self.assertEqual([count for _, _, count in self.calls], [0, 1, 2, 2])
        self.assertNotEqual(self.host.incumbent(), root)
        records = store.events(self.host.store)
        accepted = [
            e
            for e in records
            if e["event"]["kind"] == "selection"
            and e["event"]["body"].get("role") == "fixed_auditor_gate"
        ]
        adoption = [
            e
            for e in records
            if e["event"]["kind"] == "selection"
            and e["event"]["body"].get("role") == "incumbent"
        ][-1]
        self.assertLess(accepted[2]["seq"], adoption["seq"])
        self.assertIn("confirmation", self.verified)

    def test_rejected_initial_job_prevents_learning_and_cannot_be_upgraded(self):
        self.outcomes["initial_serve"] = "rejected"
        with self.assertRaises(gate.Inconclusive):
            self.host.stream_step()
        self.assertEqual(self.host.insights(), [])
        self.receipts["initial_serve"]["outcome"] = "accepted"
        with self.assertRaisesRegex(RuntimeError, "evidence changed"):
            self.host.stream_step()
        self.assertEqual(len(self.calls), 1)
        self.assertFalse(guarded.learned(self.host, 1))

    def test_missing_evidence_freezes_unknown_without_buying_or_retrying_job(self):
        with mock.patch.object(
            self.adapter, "build_run_pack", side_effect=ValueError("missing")
        ):
            with self.assertRaises(gate.Inconclusive):
                self.host.stream_step()
        with self.assertRaisesRegex(gate.Inconclusive, "frozen evidence unknown"):
            self.host.stream_step()
        self.assertEqual((self.calls, self.host.insights()), ([], []))
        events = [
            e["body"]
            for e in self.host.events("selection")
            if e["body"].get("role") == "fixed_auditor_gate"
        ]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["outcome"], "unknown")

    def test_public_analysis_and_research_cannot_bypass_a_stopped_audit(self):
        self.outcomes["initial_serve"] = "rejected"
        with self.assertRaises(gate.Inconclusive):
            self.host.stream_step()
        parent = self.host.incumbent()
        before = self.host.events("exposure")
        with self.assertRaises(gate.Inconclusive):
            self.host.analyze(parent)
        with self.assertRaises(gate.Inconclusive):
            self.host.research(parent, 1)
        self.assertEqual(self.host.events("exposure"), before)
        self.assertFalse(any(self.host.camp.glob("insight/*/*/launch-claim.json")))
        self.assertFalse(any(self.host.camp.glob("research/*/launch-claim.json")))

    def test_direct_research_role_cannot_run_during_the_probe_phase(self):
        self.host.terms["adoption"] = "explicit"
        self.host.stream_step()
        self.host.stream_step()
        with self.assertRaisesRegex(RuntimeError, "forbids this learning role"):
            gate.authorize_learning(self.host, self.host.incumbent(), "research.md")
        self.assertEqual(len(self.calls), 3)

    def test_probe_failure_prevents_analysis_and_all_confirmation_tasks(self):
        self.host.stream_step()
        self.outcomes["probe"] = "unknown"
        with self.assertRaises(gate.Inconclusive):
            self.host.stream_step()
        self.assertEqual(len(self.host.insights()), 1)
        self.assertFalse(
            any("confirmation" in e["body"] for e in self.host.events("assignment"))
        )
        with self.assertRaises(gate.Inconclusive):
            self.host.stream_step()
        self.assertEqual(
            [phase for phase, _, _ in self.calls], ["initial_serve", "probe"]
        )

    def test_high_score_confirmation_cannot_override_rejection_or_buy_again(self):
        root = self.host.incumbent()
        self.host.stream_step()
        self.outcomes["confirmation"] = "rejected"
        with self.assertRaises(gate.Inconclusive):
            self.host.stream_step()
        candidate = self.host.batches()[1]["version"]
        self.assertEqual(self.host.incumbent(), root)
        self.assertFalse(self.host.contract(f"adoption.{candidate[:16]}")["support"])
        with self.assertRaises(gate.Inconclusive):
            self.host.stream_step()
        self.assertEqual(
            [phase for phase, _, _ in self.calls],
            ["initial_serve", "probe", "confirmation"],
        )

    def test_direct_first_adoption_revalidates_artifacts_but_settled_replay_does_not(
        self,
    ):
        self.host.terms["adoption"] = "explicit"
        self.host.stream_step()
        self.host.stream_step()
        candidate = self.host.batches()[1]["version"]
        self.corrupt = "changed"
        with self.assertRaisesRegex(RuntimeError, "bound source changed"):
            self.host.adopt(candidate)
        self.corrupt = None
        self.host.adopt(candidate)
        calls = len(self.calls), len(self.verified)
        self.corrupt = "historical cleanup"
        self.assertIn("already adopted", self.host.adopt(candidate))
        self.assertEqual((len(self.calls), len(self.verified)), calls)

    def test_supported_resume_requires_existing_frozen_receipt(self):
        self.host.terms["adoption"] = "explicit"
        self.host.stream_step()
        self.host.stream_step()
        candidate = self.host.batches()[1]["version"]
        original = self.host.events

        def hide_gate(kind):
            return [
                event
                for event in original(kind)
                if event["body"].get("role") != "fixed_auditor_gate"
                or event["body"].get("phase") != "confirmation"
            ]

        with mock.patch.object(self.host, "events", side_effect=hide_gate):
            with self.assertRaisesRegex(RuntimeError, "missing frozen"):
                self.host.confirm(candidate, self.host.incumbent())
            with self.assertRaisesRegex(RuntimeError, "missing frozen"):
                self.host.adopt(candidate)
        self.assertEqual(len(self.calls), 3)

    def test_confirmation_authorization_requires_both_earlier_gate_receipts(self):
        self.host.stream_step()
        self.host.terms["adoption"] = "explicit"
        self.host.stream_step()
        original = self.host.events
        for phase in ("initial_serve", "probe"):

            def hide_gate(kind):
                return [
                    event
                    for event in original(kind)
                    if event["body"].get("role") != "fixed_auditor_gate"
                    or event["body"].get("phase") != phase
                ]

            with mock.patch.object(self.host, "events", side_effect=hide_gate):
                with self.assertRaisesRegex(RuntimeError, "missing frozen"):
                    gate.authorize_confirmation(self.host)
        self.assertEqual(len(self.calls), 3)

    def test_old_root_cannot_learn_after_adoption_before_successor_assignment(self):
        parent = self.host.incumbent()
        self.host.stream_step()
        self.host.stream_step()
        with self.assertRaisesRegex(RuntimeError, "learning authority differs"):
            gate.authorize_learning(self.host, parent, "analyst.md")
        with self.assertRaisesRegex(RuntimeError, "learning authority differs"):
            gate.authorize_learning(self.host, self.host.incumbent(), "analyst.md")
        self.assertEqual(len(self.calls), 3)

    def test_unreconciled_confirmation_claim_blocks_direct_learning(self):
        self.host.terms["adoption"] = "explicit"
        self.host.stream_step()
        with mock.patch.object(
            self.auditor, "execute", side_effect=self.claim_then_crash
        ):
            with self.assertRaisesRegex(RuntimeError, "crashed after claim"):
                self.host.stream_step()
        with self.assertRaisesRegex(RuntimeError, "unreconciled fixed auditor"):
            gate.authorize_learning(self.host, self.host.incumbent(), "analyst.md")

    def claim_then_crash(self, host, phase, packs, receipts):
        if phase != "confirmation":
            return self.execute(host, phase, packs, receipts)
        root = host.camp / "fixed-auditor" / phase
        root.mkdir(parents=True)
        (root / "claim.json").write_text("synthetic crash marker")
        raise RuntimeError("crashed after claim")

    def test_successor_failure_stops_before_successor_research(self):
        self.host.stream_step()
        self.host.stream_step()
        self.outcomes["successor_serve"] = "rejected"
        with self.assertRaises(gate.Inconclusive):
            self.host.stream_step()
        self.assertEqual(len(self.host.insights()), 2)
        self.assertFalse((self.host.camp / "research/step-3").exists())


if __name__ == "__main__":
    unittest.main()
