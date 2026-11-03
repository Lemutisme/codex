import json
from pathlib import Path
import tempfile
import threading
import unittest

from procontract_research_control import ControlServer,invoke


class BoundRuntime:
    def __init__(self):self.receipts={};self.starts=0
    def control(self,operation,identity,request,thread):
        body=(operation,request,thread)
        if identity in self.receipts:
            if self.receipts[identity][0]!=body:raise ValueError('request identity conflicts')
            return self.receipts[identity][1]
        if operation=='start':self.starts+=1
        response={'message':'Research '+operation,'state':'active' if self.starts else 'idle'}
        self.receipts[identity]=(body,response);return response


class ResearchControlTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='pc-control-test-');self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'s';self.runtime=BoundRuntime()
        self.server=ControlServer(self.path,self.runtime,'configured-profile')
        thread=threading.Thread(target=self.server.serve_forever,daemon=True);thread.start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)

    def test_status_does_not_start_and_repeated_explicit_request_keeps_its_identity(self):
        invoke(self.path,'status');self.assertEqual(self.runtime.starts,0)
        goal='inspect; $(not-shell)\nand retain evidence'
        first=invoke(self.path,'start',goal,request_id='one',thread_id='thread')
        self.assertEqual(invoke(self.path,'start',goal,request_id='one',thread_id='thread'),first)
        self.assertEqual(self.runtime.starts,1)
        self.assertEqual(self.runtime.receipts['one'][0],('start',goal,'thread'))
        self.assertEqual(first['profile_sha256'],'configured-profile')
        with self.assertRaisesRegex(RuntimeError,'conflicts'):invoke(self.path,'start','different',request_id='one',thread_id='thread')

    def test_owner_endpoint_rejects_unoffered_authority_or_execution_fields(self):
        for extra in [{'argv':['arbitrary']},{'scope':'new authority'},{'root':'/another'}]:
            with self.assertRaisesRegex(ValueError,'unknown control field'):
                self.server.control({'schema':1,'request_id':'x','operation':'start','request':'study',**extra})
        with self.assertRaisesRegex(RuntimeError,'does not accept'):invoke(self.path,'cancel','new goal')
        with self.assertRaisesRegex(RuntimeError,'empty'):invoke(self.path,'start',' ')
        self.assertEqual(self.runtime.starts,0)


if __name__=='__main__':unittest.main()
