"""Restart actual native Codex and verify another handoff; localhost model fixture only."""

import contextlib
import json
import os
from pathlib import Path
import queue
import sqlite3
import tempfile
import time
import unittest
from unittest import mock

import test_procodex_native as fixture


@unittest.skipUnless(
    os.environ.get("PROCODEX_NATIVE_PACKAGE") and os.environ.get("PROCODEX_TEST_IMAGE"),
    "requires existing native package and Docker image, no paid model",
)
class NativeResumeTests(unittest.TestCase):
    def test_restart_preserves_contract_and_new_turn_does_not_redraft(self):
        owner = self
        base = fixture.AppServer
        records = []
        with tempfile.TemporaryDirectory(prefix="procodex-resume-test-") as temporary:
            output = Path(os.environ.get("PROCODEX_RESUME_REPORT", temporary))
            output.mkdir(parents=True, exist_ok=True)

            class RestartServer(base):
                def __init__(self, *args, **kwargs):
                    self.saved_args, self.saved_kwargs = args, kwargs
                    self.thread_id = self.thread_params = None
                    self.restarted = False
                    super().__init__(*args, **kwargs)

                def request(self, method, params, handle, **kwargs):
                    result = super().request(method, params, handle, **kwargs)
                    if method == "thread/start":
                        self.thread_id = result["thread"]["id"]
                        self.thread_params = params
                    return result

                def snapshot(self):
                    path = (
                        Path(self.saved_args[1]["CODEX_HOME"])
                        / "pro_contract/ledger_1.sqlite"
                    )
                    with contextlib.closing(
                        sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
                    ) as db:
                        status = json.loads(
                            db.execute(
                                "SELECT json FROM records WHERE kind='status' AND key=?",
                                (self.thread_id,),
                            ).fetchone()[0]
                        )
                        contracts = [
                            json.loads(v)
                            for (v,) in db.execute("SELECT state_json FROM contracts")
                        ]
                        commands = [
                            json.loads(v)["command"]["type"]
                            for (v,) in db.execute(
                                "SELECT command_json FROM events ORDER BY seq"
                            )
                        ]
                    return {
                        "status": status,
                        "contracts": contracts,
                        "commands": commands,
                    }

                def close(self):
                    if self.restarted or not self.thread_id:
                        return super().close()
                    self.restarted = True
                    record = {"before": self.snapshot(), "real_provider_calls": 0}
                    records.append(record)
                    stopped = super().close()
                    record["first_exit"] = stopped
                    args = list(self.saved_args)
                    args[2], args[3] = (
                        output / "resume-rpc.jsonl",
                        output / "resume-stderr.log",
                    )
                    resumed = base(*args, **self.saved_kwargs)

                    def handle(value):
                        if "id" in value and "method" in value:
                            resumed.refuse(value)

                    try:
                        resumed.request(
                            "initialize",
                            {
                                "clientInfo": {
                                    "name": "resume-fixture",
                                    "version": "1",
                                },
                                "capabilities": {"experimentalApi": True},
                            },
                            handle,
                        )
                        resumed.notify("initialized")
                        response = resumed.request(
                            "thread/resume",
                            {"threadId": self.thread_id, **self.thread_params},
                            handle,
                        )
                        owner.assertEqual(response["thread"]["id"], self.thread_id)
                        record["restored"] = self.snapshot()
                        owner.assertEqual(record["restored"], record["before"])
                        resumed.request(
                            "turn/start",
                            {
                                "threadId": self.thread_id,
                                "input": [
                                    {
                                        "type": "text",
                                        "text": "Continue under the existing contract and hand off again.",
                                        "text_elements": [],
                                    }
                                ],
                            },
                            handle,
                        )
                        deadline = time.monotonic() + 90
                        while time.monotonic() < deadline:
                            try:
                                handle(resumed.messages.get(timeout=0.1))
                            except queue.Empty:
                                pass
                            record["continued"] = self.snapshot()
                            if (
                                record["continued"]["status"]["phase"] == "supported"
                                and record["continued"]["contracts"][0]["generation"]
                                == 2
                            ):
                                break
                        owner.assertEqual(
                            record["continued"]["commands"],
                            ["issue", "propose", "support", "propose", "support"],
                        )
                        owner.assertEqual(
                            record["continued"]["status"], record["before"]["status"]
                        )
                        owner.assertEqual(
                            record["continued"]["contracts"][0]["standing"],
                            "outstanding",
                        )
                    finally:
                        record["resumed_exit"] = resumed.close()
                        resumed.process.stdout.close()
                        resumed._log.close()
                        (output / "resume-result.json").write_text(
                            json.dumps(record, indent=2) + "\n"
                        )
                    return stopped

            with mock.patch.object(fixture, "AppServer", RestartServer):
                fixture.NativeEvidenceTest(
                    "test_real_executor_and_reviewer_use_frozen_handles"
                ).debug()
            self.assertEqual(len(records), 1)
            self.assertEqual(
                [
                    records[0][key]["returncode"]
                    for key in ("first_exit", "resumed_exit")
                ],
                [0, 0],
            )


if __name__ == "__main__":
    unittest.main()
