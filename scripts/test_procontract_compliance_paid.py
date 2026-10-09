"""Real allowance DB: fixed auditors are separate jobs, never learned analysts."""

from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import procontract_ph_audit as audits
import procontract_ph_protocol as protocol
import procontract_study_budget as budget


class PaidAuditTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.camp = Path(temporary.name)
        self.limits = {
            "task_launches": 12,
            "learning_launches": 21,
            "allocated_seconds": 291600,
        }
        self.host = SimpleNamespace(
            camp=self.camp, terms={"study": {"manifest_sha256": "a" * 64}}
        )
        self.seal = {"limits": self.limits}
        self.database = self.camp / "study-budget.sqlite"
        budget.initialize(self.database, "a" * 64, self.limits)

    def reserve(self, key, kind, identity):
        return budget.reserve(
            self.database,
            "a" * 64,
            key,
            kind,
            18000 if kind == "task" else 3600,
            self.limits,
            identity,
        )

    def audit(self, name):
        return audits.Audit(
            self.host, self.seal, episode_profile=protocol.profile(name)
        )

    def test_only_h_profile_has_the_four_job_extension_and_global_cap_is_unchanged(
        self,
    ):
        for number in range(11):
            self.reserve(f"task-{number}", "task", {})
        for number in range(15):
            self.reserve(f"learning-{number}", "learning", {})
        self.assertEqual(
            self.audit(protocol.H_PROTOCOL).paid(completed_runs=set())["reserved"],
            {"task_launches": 11, "learning_launches": 15, "allocated_seconds": 252000},
        )
        with self.assertRaisesRegex(RuntimeError, "launch envelope"):
            self.audit(protocol.PROTOCOL).paid(completed_runs=set())
        for number in range(15, 18):
            self.reserve(f"learning-{number}", "learning", {})
        self.audit(protocol.H_PROTOCOL).paid(completed_runs=set())
        self.reserve("extra-task", "task", {})
        with self.assertRaisesRegex(RuntimeError, "launch envelope"):
            self.audit(protocol.H_PROTOCOL).paid(completed_runs=set())
        for number in range(18, 21):
            self.reserve(f"learning-{number}", "learning", {})
        with self.assertRaises(budget.BudgetExceeded):
            self.reserve("22nd-learning", "learning", {})
        self.assertEqual(
            budget.status(self.database, "a" * 64, self.limits)["limits"], self.limits
        )

    def test_fixed_auditor_has_dedicated_paid_claim_audit_not_analyst_configuration(
        self,
    ):
        identity = {"role": "fixed_auditor", "phase": "probe"}
        key = "fixed-auditor/probe"
        receipt = self.reserve(key, "learning", identity)
        peer = SimpleNamespace(audit_reservation=mock.Mock())
        with mock.patch.dict(sys.modules, {"procontract_fixed_auditor": peer}):
            audit = self.audit(protocol.H_PROTOCOL)
            self.assertEqual(audit.paid()["reserved"]["learning_launches"], 1)
            peer.audit_reservation.assert_called_once_with(
                self.host, self.seal, key, identity, receipt
            )
            self.assertEqual(audit.paid_runs, {str(self.camp / key): receipt})
            with self.assertRaisesRegex(RuntimeError, "H-only"):
                self.audit(protocol.PROTOCOL).paid()

    def test_fixed_path_cannot_masquerade_as_a_learned_analyst(self):
        self.reserve("fixed-auditor/probe", "learning", {"role": "analyst.md"})
        with self.assertRaisesRegex(RuntimeError, "H-only"):
            self.audit(protocol.H_PROTOCOL).paid()

    def test_fixed_role_cannot_bypass_the_lane_terminal_configuration_audit(self):
        self.reserve("fixed-auditor/probe", "learning", {"role": "fixed_auditor"})
        peer = SimpleNamespace(
            audit_reservation=mock.Mock(side_effect=ValueError("changed fixed config"))
        )
        with mock.patch.dict(sys.modules, {"procontract_fixed_auditor": peer}):
            with self.assertRaisesRegex(ValueError, "changed fixed config"):
                self.audit(protocol.H_PROTOCOL).paid()


if __name__ == "__main__":
    unittest.main()
