"""Prepared learning launch must pass independent compliance before any reservation."""

import unittest
from unittest import mock

import procontract_benchmark_runner as runner
import procontract_compliance_gate as gate
import test_procontract_study_launch as fixtures


class LearningLaunchTest(unittest.TestCase):
    args = fixtures.StudyLaunchTest.args
    make_host = fixtures.StudyLaunchTest.make_host
    cached = fixtures.StudyLaunchTest.cached
    initialize_study = fixtures.StudyLaunchTest.initialize_study
    balance = fixtures.StudyLaunchTest.balance
    preparation = fixtures.StudyLaunchTest.preparation
    transport = fixtures.StudyLaunchTest.transport
    setUp = fixtures.StudyLaunchTest.setUp

    def test_missing_phase_audit_denies_all_learned_roles_before_app_server_or_budget(
        self,
    ):
        with self.transport() as opened:
            for role in ("analyst.md", "challenger.md", "research.md"):
                args = self.preparation(role, role[:-3])
                runner.prepare(args)
                with mock.patch.object(gate, "enabled", return_value=True):
                    with self.assertRaisesRegex(RuntimeError, "no fixed H phase"):
                        runner.run(args)
        self.assertEqual(opened, [])
        self.assertEqual(
            self.balance()["reserved"],
            {"task_launches": 0, "learning_launches": 0, "allocated_seconds": 0},
        )


if __name__ == "__main__":
    unittest.main()
