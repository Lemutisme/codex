"""Both real H gates, kernel, budget, claims and citation replay; synthetic task/model transport.

The fixture's study readiness/mount boundaries stay stubbed as in the native Host
fixture. No production gate, auditor decision parser, reservation or replay is mocked.
"""

import hashlib
import os
import unittest
from unittest import mock

import procontract_compliance_adapter as adapter
import procontract_compliance_gate as compliance
import procontract_fixed_auditor as lane
import procontract_fixed_auditor_role as role
import procontract_ph_audit as audits
import procontract_ph_protocol as protocol
import procontract_store as store
import procontract_study_budget as budget
import test_procontract_fixed_auditor_role as auditor_fixtures
import test_procontract_h_admission as fixtures


class ComposedGateTest(unittest.TestCase):
    args = fixtures.AdmissionTest.args
    make_host = fixtures.AdmissionTest.make_host
    cached = fixtures.AdmissionTest.cached
    complete = fixtures.AdmissionTest.complete
    measured = fixtures.AdmissionTest.measured
    trace_outcome = fixtures.AdmissionTest.trace_outcome
    root_program_document = None
    program_document = fixtures.AdmissionTest.program_document

    def setUp(self):
        # Restore the actual compliance gates after the focused fixture stubs them.
        real_gates = {
            name: getattr(compliance, name)
            for name in (
                "authorize_confirmation",
                "authorize_learning",
                "confirmation",
            )
        }
        original_write = fixtures.write

        def write_plan(path, value):
            if path.name == "campaign.json" and path.parent.name == "h-campaign":
                plan = path.parent.parent / "h-only-plan.json"
                original_write(
                    plan,
                    {
                        "schema": 1,
                        "protocol": protocol.H_PROTOCOL,
                        "campaign": str(path.parent),
                        "source_sha256": protocol.digest(protocol.SUPERVISOR),
                        "max_phases": 3,
                        "required_admission": protocol.H_ADMISSION,
                    },
                )
                value["ph_supervisor"] = {
                    "plan_path": str(plan),
                    "plan_sha256": protocol.digest(plan),
                }
            original_write(path, value)

        with mock.patch.object(fixtures, "write", side_effect=write_plan):
            fixtures.AdmissionTest.setUp(self)
        # Audit imports the same readiness selector by value; retain the fixture stub.
        self.enterContext(
            mock.patch.object(
                audits,
                "campaign_profile",
                return_value=protocol.profile(protocol.H_PROTOCOL),
            )
        )
        for name, function in real_gates.items():
            self.enterContext(mock.patch.object(compliance, name, function))
        self.native_calls, self.verdict = [], "supported_within_evidence"
        self.enterContext(
            mock.patch.object(adapter, "build_run_pack", side_effect=self.capture)
        )
        self.enterContext(
            mock.patch.object(lane.native, "run", side_effect=self.native)
        )
        key = self.host.terms["fixed_auditor"]["routing"]["env_key"]
        self.enterContext(
            mock.patch.dict(os.environ, {key: "SYNTHETIC_TEST_CREDENTIAL"})
        )
        for batch in self.host.batches():
            compliance.stream(self.host, batch)

    def capture(self, host, run):
        # Synthetic normal-build task evidence, but bind it to the real run artifacts.
        value = auditor_fixtures.pack(str(run.relative_to(host.camp)))
        receipt = auditor_fixtures.receipt(value)
        receipt["artifacts"] = {
            name: protocol.digest(run / name)
            for name in (
                "manifest.json",
                "run.json",
                "submission.tar.gz",
                "../result.json",
            )
        }
        return value, receipt

    def native(self, binary, root, service, provider, credential):
        phase = root.name
        self.assertNotIn(phase, self.native_calls)
        self.assertTrue((root / "claim.json").is_file())
        reservation = protocol.document(root / "study-launch.json")
        self.assertEqual(
            (reservation["kind"], reservation["deadline_secs"]), ("learning", 3600)
        )
        if phase == "confirmation":
            notices = [
                e["body"]
                for e in self.host.events("selection")
                if e["body"].get("role") == "h_confirmation_delivery"
            ]
            self.assertEqual(
                (len(notices), notices[0]["evidence"]["candidate_observed"]), (1, 4)
            )
        self.native_calls.append(phase)
        (root / "codex-home").mkdir()
        (root / "codex-home/config.toml").write_text(role.config(provider))
        (root / "codex-home/environments.toml").write_text("include_local = false\n")
        for name in ("rpc.jsonl", "stdout.log", "stderr.log"):
            (root / name).write_bytes(b"")
        rows = auditor_fixtures.serve(service)
        (root / "evidence-served.jsonl").write_bytes(
            b"".join(role.encoded(row) + b"\n" for row in rows)
        )
        raw = role.encoded(
            {
                "schema": 1,
                "audits": [
                    auditor_fixtures.answer(
                        value,
                        self.verdict
                        if phase == "confirmation"
                        else "supported_within_evidence",
                    )
                    for value in service.packs
                ],
            }
        )
        return raw, {
            "schema": 1,
            "status": "completed",
            "native_exit": 0,
            "final_sha256": hashlib.sha256(raw).hexdigest(),
            "final_usage": {"totalTokens": 17},
        }

    def test_both_gates_precede_actual_adoption_and_finite_audit_replays_without_cost(
        self,
    ):
        with mock.patch.object(self.host, "measure_all", side_effect=self.measured):
            self.assertIn("adopted", self.host.confirm(self.candidate_id, self.parent))
        self.assertEqual(self.host.incumbent(), self.candidate_id)
        self.assertEqual(self.native_calls, ["initial_serve", "probe", "confirmation"])
        records = store.events(self.host.store)
        selections = [row for row in records if row["event"]["kind"] == "selection"]
        notice = next(
            row
            for row in selections
            if row["event"]["body"].get("role") == "h_confirmation_delivery"
        )
        audit = next(
            row
            for row in selections
            if row["event"]["body"].get("phase") == "confirmation"
            and row["event"]["body"].get("role") == "fixed_auditor_gate"
        )
        adopted = [
            row for row in selections if row["event"]["body"].get("role") == "incumbent"
        ][-1]
        self.assertLess(notice["seq"], audit["seq"])
        self.assertLess(audit["seq"], adopted["seq"])
        before = budget.status(self.database, "a" * 64, self.limits)
        packs, receipts = [], []
        for arm in notice["event"]["body"]["evidence"]["arms"]:
            pack, receipt = self.capture(self.host, self.host.camp / arm["run"])
            packs.append(pack)
            receipts.append(receipt)
        self.assertEqual(
            lane.verify(self.host, "confirmation", packs, receipts)["outcome"],
            "accepted",
        )
        self.assertEqual(
            lane.execute(self.host, "confirmation", packs, receipts)["outcome"],
            "accepted",
        )
        self.assertEqual(
            (self.native_calls, budget.status(self.database, "a" * 64, self.limits)),
            (["initial_serve", "probe", "confirmation"], before),
        )

    def test_unsupported_audit_prevents_adoption_despite_actual_notice_and_score_wins(
        self,
    ):
        self.verdict = "unknown"
        with mock.patch.object(self.host, "measure_all", side_effect=self.measured):
            with self.assertRaises(compliance.Inconclusive):
                self.host.confirm(self.candidate_id, self.parent)
        self.assertEqual(self.host.incumbent(), self.parent)
        self.assertIsNone(
            self.host.contract(f"adoption.{self.candidate_id[:16]}")["support"]
        )
        before = budget.status(self.database, "a" * 64, self.limits)
        with mock.patch.object(
            self.host.adapter, "run_and_label", side_effect=AssertionError("new task")
        ):
            with self.assertRaises(compliance.Inconclusive):
                self.host.confirm(self.candidate_id, self.parent)
        with self.assertRaisesRegex(RuntimeError, "no supported adoption"):
            self.host.adopt(self.candidate_id)
        self.assertEqual(
            (self.native_calls, budget.status(self.database, "a" * 64, self.limits)),
            (["initial_serve", "probe", "confirmation"], before),
        )


if __name__ == "__main__":
    unittest.main()
