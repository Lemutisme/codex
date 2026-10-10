"""Strict native request witness reused without inheriting a legacy study's authority."""

import shutil
import subprocess
import unittest
from unittest import mock

from procontract_online_trace import OnlineTrace
import procontract_online_trace as tracing
import test_procontract_native_notice_receipt as fixture


class TraceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture.NativeNoticeReceiptTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.run = self.fixture.root.parent.parent
        self.storage = {
            "mount_id": "owned",
            "device": "device",
            "max_bytes": 1 << 30,
            "max_inodes": 65536,
            "exhausted": False,
        }

    def observer(self):
        with (
            mock.patch.object(tracing.subprocess, "run"),
            mock.patch.object(tracing.trace, "storage", return_value=self.storage),
        ):
            observer = OnlineTrace(self.run, "a" * 64)
        shutil.copytree(self.fixture.root, observer.root / self.fixture.root.name)
        observer.thread_id = fixture.THREAD
        observer.before_send(
            {
                "params": {
                    "threadId": fixture.THREAD,
                    "expectedTurnId": fixture.TURN,
                    "input": [{"text": fixture.NOTICE}],
                }
            }
        )
        return observer

    def test_ack_without_a_completed_model_request_is_not_consumption(self):
        observer = self.observer()
        with mock.patch.object(tracing.trace, "storage", return_value=self.storage):
            result = observer.after_run(
                {"attempt": {"outcome": "accepted", "turn_id": fixture.TURN}},
                {"status": "exited"},
            )
        self.assertEqual(
            result["evidence"],
            {"status": "unknown", "reason": "no_completed_notice_request"},
        )

    def test_completed_native_request_witness_preserves_original_history(self):
        observer = self.observer()
        self.fixture.write_events(self.fixture.events)
        shutil.copyfile(
            self.fixture.root / "trace.jsonl",
            observer.root / self.fixture.root.name / "trace.jsonl",
        )
        with mock.patch.object(tracing.trace, "storage", return_value=self.storage):
            result = observer.after_run(
                {"attempt": {"outcome": "accepted", "turn_id": fixture.TURN}},
                {"status": "exited"},
            )
        self.assertEqual(
            (result["evidence"]["status"], result["evidence"]["scope"]),
            ("observed", "request_contains_notice_and_response_completed"),
        )

    def test_archive_failure_never_destroys_the_only_evidence(self):
        observer = self.observer()
        with (
            mock.patch.object(tracing.trace, "storage", return_value=self.storage),
            mock.patch.object(
                tracing.subprocess,
                "run",
                side_effect=subprocess.TimeoutExpired("tar", 60),
            ) as command,
        ):
            with self.assertRaises(subprocess.TimeoutExpired):
                observer.close()
        self.assertEqual(command.call_count, 1)
        self.assertEqual(command.call_args.args[0][0], "tar")
        self.assertFalse(observer._closed)


if __name__ == "__main__":
    unittest.main()
