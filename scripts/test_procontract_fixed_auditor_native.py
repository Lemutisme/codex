"""Real local subprocess protocol fixtures; no sockets, native binary or provider required."""

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

import procontract_fixed_auditor_native as native
import procontract_fixed_auditor_role as role
from test_procontract_fixed_auditor_role import PROVIDER, answer, pack


class NativeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root / "run"
        self.run.mkdir()
        self.service = role.EvidenceService([pack()])

    def fixture(
        self,
        *,
        duplicate_final=False,
        wrong_identity=False,
        hang=False,
        invalid_line=False,
        before_ack=False,
        lingering_child=False,
    ):
        args = []
        for cursor in range(len(self.service.packs[0]._sources)):
            args.append({"op": "index", "pack_id": "p0", "cursor": cursor})
        for file_id in self.service.packs[0]._sources:
            args.append(
                {
                    "op": "read",
                    "pack_id": "p0",
                    "file_id": file_id,
                    "offset": 0,
                    "max_bytes": 2000,
                }
            )
        result = role.encoded(
            {"schema": 1, "audits": [answer(self.service.packs[0])]}
        ).decode()
        script = self.root / "fixture"
        script.write_text(f"""#!{sys.executable}
import json,sys,time,os
ARGS={args!r}
FINAL={result!r}
def send(v):print(json.dumps(v),flush=True)
for line in sys.stdin:
 v=json.loads(line)
 method=v.get('method')
 if method=='initialize':send({{'id':v['id'],'result':{{}}}})
 if method=='thread/start':
  assert v['params']['environments']==[] and v['params']['selectedCapabilityRoots']==[]
  assert len(v['params']['dynamicTools'])==1
  send({{'id':v['id'],'result':{{'thread':{{'id':'t'}}}}}})
 if method=='turn/start':
  if {hang!r}:time.sleep(20)
  if {invalid_line!r}:print('not-json',flush=True);time.sleep(20)
  if not {before_ack!r}:send({{'id':v['id'],'result':{{'turn':{{'id':'u'}}}}}})
  for index,a in enumerate(ARGS):
   send({{'id':'dynamic','method':'item/tool/call','params':{{'threadId':{"other" if wrong_identity else "t"!r},'turnId':'u','tool':'read_evidence','namespace':None,'arguments':a}}}})
   if {before_ack!r} and index==0:send({{'id':v['id'],'result':{{'turn':{{'id':'u'}}}}}})
   reply=json.loads(next(sys.stdin))
   assert reply['id']=='dynamic'
  item={{'method':'item/completed','params':{{'threadId':'t','turnId':'u','item':{{'type':'agentMessage','phase':None,'text':FINAL}}}}}}
  send(item)
  if {duplicate_final!r}:send(item)
  send({{'method':'thread/tokenUsage/updated','params':{{'threadId':'t','turnId':'u','tokenUsage':{{'total':{{'totalTokens':7,'inputTokens':3,'cachedInputTokens':0,'outputTokens':4,'reasoningOutputTokens':0}}}}}}}})
  send({{'method':'turn/completed','params':{{'threadId':'t','turn':{{'id':'u','status':'completed'}}}}}})
  if {lingering_child!r}:
   import signal
   if os.fork()==0:
    signal.signal(signal.SIGTERM,signal.SIG_IGN)
    time.sleep(20)
    os._exit(0)
   break
""")
        script.chmod(0o700)
        return script

    def test_native_protocol_and_usage_capture(self):
        raw, terminal = native.run(
            self.fixture(),
            self.run,
            self.service,
            PROVIDER,
            "NOT_REAL",
            deadline_secs=3,
        )
        self.assertEqual(
            (
                terminal["status"],
                terminal["native_exit"],
                terminal["thread_id"],
                terminal["turn_id"],
                terminal["evidence_calls"],
                terminal["final_usage"]["totalTokens"],
            ),
            ("completed", 0, "t", "u", 10, 7),
        )
        self.assertTrue(self.service.validate(raw)[0]["accepted"])
        self.assertEqual(terminal["final_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertNotIn("NOT_REAL", (self.run / "codex-home/config.toml").read_text())

    def test_tool_notification_before_turn_ack_is_not_refused(self):
        raw, terminal = native.run(
            self.fixture(before_ack=True),
            self.run,
            self.service,
            PROVIDER,
            "NOT_REAL",
            deadline_secs=3,
        )
        self.assertEqual(
            (terminal["status"], terminal["evidence_calls"]), ("completed", 10)
        )
        self.assertTrue(self.service.validate(raw)[0]["accepted"])

    def test_wrong_native_identity_does_not_serve_evidence(self):
        raw, terminal = native.run(
            self.fixture(wrong_identity=True),
            self.run,
            self.service,
            PROVIDER,
            "NOT_REAL",
            deadline_secs=3,
        )
        self.assertEqual(
            (terminal["status"], terminal["evidence_calls"]), ("completed", 0)
        )
        self.assertFalse(self.service.validate(raw)[0]["accepted"])

    def test_duplicate_final_is_failed_not_guess_last(self):
        raw, terminal = native.run(
            self.fixture(duplicate_final=True),
            self.run,
            self.service,
            PROVIDER,
            "NOT_REAL",
            deadline_secs=3,
        )
        self.assertEqual(terminal["status"], "failed")
        self.assertIsNone(raw)

    def test_hung_native_is_terminated_within_bounded_cleanup(self):
        start = time.monotonic()
        raw, terminal = native.run(
            self.fixture(hang=True),
            self.run,
            self.service,
            PROVIDER,
            "NOT_REAL",
            deadline_secs=0.2,
        )
        self.assertEqual(terminal["status"], "timeout")
        self.assertIsNone(raw)
        self.assertLess(time.monotonic() - start, 6)

    def test_pipe_holding_descendant_cannot_hang_cleanup(self):
        start = time.monotonic()
        raw, terminal = native.run(
            self.fixture(lingering_child=True),
            self.run,
            self.service,
            PROVIDER,
            "NOT_REAL",
            deadline_secs=3,
        )
        self.assertEqual(terminal["status"], "completed")
        self.assertIsNotNone(raw)
        self.assertLess(time.monotonic() - start, 2)

    def test_reserved_environment_name_is_not_a_child_override(self):
        provider = {**PROVIDER, "env_key": "CODEX_HOME"}
        raw, terminal = native.run(
            self.fixture(),
            self.run,
            self.service,
            provider,
            "NOT_A_HOME",
            deadline_secs=3,
        )
        self.assertEqual(terminal["status"], "completed")
        self.assertIn(
            'env_key="FIXED_AUDITOR_API_KEY"',
            (self.run / "codex-home/config.toml").read_text(),
        )
        self.assertTrue(self.service.validate(raw)[0]["accepted"])

    def test_ambient_config_presence_fails_before_native(self):
        from unittest.mock import patch

        with patch.object(native.os.path, "lexists", return_value=True):
            with self.assertRaises(RuntimeError):
                native.run(
                    self.fixture(),
                    self.run,
                    self.service,
                    PROVIDER,
                    "NOT_REAL",
                    deadline_secs=3,
                )
        self.assertEqual(list(self.run.iterdir()), [])

    def test_bad_native_json_is_not_ignored(self):
        raw, terminal = native.run(
            self.fixture(invalid_line=True),
            self.run,
            self.service,
            PROVIDER,
            "NOT_REAL",
            deadline_secs=0.2,
        )
        self.assertIn(terminal["status"], ("failed", "timeout"))
        self.assertIsNone(raw)


if __name__ == "__main__":
    unittest.main()
