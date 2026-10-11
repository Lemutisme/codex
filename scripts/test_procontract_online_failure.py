"""Only a specific safely-closed episode failure may cross the continuation gate."""

import copy
import unittest

from procontract_online_failure import contained_contract_failure, ContractUnavailable


class FailureBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.summary = {
            "status": {
                "phase": "abstained",
                "resting": True,
                "contract_id": None,
                "detail": "./ fixture rejected",
            },
            "native_process_exit": {"status": "exited", "returncode": 0},
            "execution_environment": {"disconnect_observed": False},
            "runner_error": "ContractUnavailable",
            "server_exited_early": True,
            "online_learning": {"research": None, "candidate": None, "dispatch": None},
        }

    def test_guard_preserves_bounded_failure_data_not_an_invented_quality(self):
        error = ContractUnavailable({**self.summary["status"], "detail": "安全" * 500})
        self.assertLessEqual(len(error.contract_status["detail"].encode()), 300)
        self.assertEqual(
            contained_contract_failure(self.summary),
            {
                "kind": "contract_unavailable",
                "quality": None,
                "reason": "./ fixture rejected",
            },
        )
        normal = {
            **self.summary,
            "runner_error": None,
            "server_exited_early": False,
            "turn_statuses": ["completed"],
        }
        self.assertEqual(
            contained_contract_failure(normal), contained_contract_failure(self.summary)
        )

    def test_unclassified_faults_and_unknown_lifetimes_are_never_contained(self):
        changes = [
            {"native_process_exit": {"status": "unknown", "returncode": 0}},
            {"native_process_exit": {"status": "exited", "returncode": False}},
            {"native_process_exit": {"status": "exited", "returncode": 1}},
            {"execution_environment": {"disconnect_observed": True}},
            {"execution_environment": {}},
            {"runner_error": "ValueError"},
            {"runner_error": None},
            {"status": {**self.summary["status"], "contract_id": "already-issued"}},
        ]
        changes += [
            {
                "online_learning": {
                    **self.summary["online_learning"],
                    k: {"status": "unknown"},
                }
            }
            for k in ("research", "candidate", "dispatch")
        ]
        for changed in changes:
            with self.subTest(changed=changed):
                self.assertIsNone(
                    contained_contract_failure(
                        {**copy.deepcopy(self.summary), **changed}
                    )
                )


if __name__ == "__main__":
    unittest.main()
