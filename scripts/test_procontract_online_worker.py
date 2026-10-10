"""Native worker transport contract; a real local subprocess and no model calls."""

from pathlib import Path
import sys
import tempfile
import threading
import unittest

import procontract_online as online
import procontract_online_worker as worker
from test_procontract_online import candidate


class WorkerTests(unittest.TestCase):
    def test_researcher_consumes_current_method_without_execution_or_dynamic_tools(
        self,
    ):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run = root / "run"
            run.mkdir()
            program, raw = candidate(online.seed(), "fixture")
            packet = {"program": online.seed(), "observations": {}, "past_rewards": []}
            script = root / "fixture"
            script.write_text(f"""#!{sys.executable}
import json, sys
for line in sys.stdin:
    v=json.loads(line)
    m=v.get('method')
    if m=='initialize': print(json.dumps({{'id':v['id'],'result':{{}}}}),flush=True)
    if m=='thread/start':
        p=v['params']
        assert p['environments']==p['dynamicTools']==p['selectedCapabilityRoots']==[]
        assert p['sandbox']=='read-only'
        print(json.dumps({{'id':v['id'],'result':{{'thread':{{'id':'t'}}}}}}),flush=True)
    if m=='turn/start':
        assert {packet["program"]["research"]!r} in v['params']['input'][0]['text']
        print(json.dumps({{'id':v['id'],'result':{{'turn':{{'id':'u'}}}}}}),flush=True)
        print(json.dumps({{'method':'item/completed','params':{{'threadId':'t','turnId':'u','item':{{'type':'agentMessage','text':{raw.decode()!r}}}}}}}),flush=True)
        print(json.dumps({{'method':'turn/completed','params':{{'threadId':'t','turn':{{'id':'u','status':'completed'}}}}}}),flush=True)
""")
            script.chmod(0o700)
            result, receipt = worker.run(
                script,
                run,
                packet,
                {"base_url": "http://127.0.0.1", "env_key": "KEY"},
                "not-real",
                deadline_secs=3,
                cancellation=threading.Event(),
            )
            self.assertEqual(online.proposal(result)[0], program)
            self.assertEqual(
                (receipt["status"], receipt["evidence_calls"]), ("completed", 0)
            )
            config = (run / "codex-home/config.toml").read_text()
            self.assertNotIn("not-real", config)
            self.assertIn('"env_key" = "ONLINE_RESEARCH_API_KEY"', config)


if __name__ == "__main__":
    unittest.main()
