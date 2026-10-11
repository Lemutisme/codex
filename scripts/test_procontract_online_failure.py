"""Only a specific safely-closed episode failure may cross the continuation gate."""

import copy
import unittest
import sqlite3
import tempfile
from pathlib import Path
from unittest import mock

import procontract_benchmark_runner as runner

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

    def test_status_poll_closes_sqlite_connections_including_query_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.sqlite"
            db = sqlite3.connect(path)
            db.execute("CREATE TABLE records(kind TEXT,key TEXT,json TEXT)")
            db.execute(
                "INSERT INTO records VALUES ('status','t','{\"phase\":\"working\"}')"
            )
            db.commit()
            db.close()
            connect = sqlite3.connect
            for broken in (False, True):
                connection = connect(path)
                if broken:
                    connection.execute("DROP TABLE records")
                    connection.commit()
                with mock.patch.object(
                    runner.sqlite3, "connect", return_value=connection
                ):
                    self.assertEqual(
                        runner.read_status(path, "t"),
                        None if broken else {"phase": "working"},
                    )
                with self.assertRaises(sqlite3.ProgrammingError):
                    connection.execute("SELECT 1")

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
            {"native_notice_trace": {"storage": {"exhausted": True}}},
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
