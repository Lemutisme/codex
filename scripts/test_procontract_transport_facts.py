import http.client
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import types
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from procontract_benchmark_gateway import Budget, Handler


class Response:
    status=200
    def __init__(self, fail_read=False):self.fail_read=fail_read;self.sent=False
    def getheader(self,k):return 'text/event-stream'
    def read1(self,n):
        if self.fail_read:raise ConnectionResetError('fixture upstream read')
        if self.sent:return b''
        self.sent=True
        return b'data: {"type":"response.completed","response":{"usage":{"input_tokens":1}}}\n\n'

class TransportFactsTests(unittest.TestCase):
    def exercise(self, phase=None, seconds=None, close=False, expired=False):
        with tempfile.TemporaryDirectory() as t:
            b=Budget(Path(t)/'b.sqlite',seconds=seconds,requests=None);grant=b.arm()
            payload=json.dumps({'model':'gpt-5.6-luna','reasoning':{'effort':'max'},'stream':True,'input':[],
                                'client_metadata':{'thread_id':'thread','turn_id':'turn'}}).encode()
            class Socket:
                def settimeout(self,*a):pass
                def shutdown(self,*a):pass
            class Conn:
                sock=Socket()
                def __init__(self,*a,**k):pass
                def connect(self):
                    if phase=='upstream_connect':raise ConnectionRefusedError('fixture connect')
                def request(self,*a,**k):
                    if phase=='upstream_send':raise BrokenPipeError('fixture send')
                def getresponse(self):return Response(phase=='upstream_read')
                def close(self):pass
            class Writer(io.BytesIO):
                def write(self,data):
                    if phase=='downstream_write':raise BrokenPipeError('fixture client disconnected')
                    return super().write(data)
            h=object.__new__(Handler);h.connection=Socket();h.path='/v1/responses'
            h.headers=http.client.HTTPMessage();h.headers['Content-Length']=str(len(payload));h.rfile=io.BytesIO(payload);h.wfile=Writer()
            h.server=types.SimpleNamespace(budget=b,upstream=urlsplit('http://fixture/v1'),connection_lock=threading.Lock(),connections=set(),closing=threading.Event(),api_key=None)
            if close:h.server.closing.set()
            h.send_response=lambda *a:None;h.send_header=lambda *a:None;h.end_headers=lambda:None
            class Timer:
                def __init__(self,delay,callback):self.callback=callback
                def start(self):self.callback()
                def cancel(self):pass
            with patch('procontract_benchmark_gateway.http.client.HTTPConnection',Conn):
                if expired:
                    with patch('procontract_benchmark_gateway.threading.Timer',Timer):h.do_POST()
                else:h.do_POST()
            events=[json.loads(r[0]) for r in b.db.execute('select event_json from request_observations order by seq')]
            row=b.db.execute('select http_status,terminal,usage,failure from requests').fetchone()
            self.assertEqual(b.status()['deadline'],grant['deadline']);self.assertEqual(b.status()['used'],1)
            b.close();return events,row
    def test_precise_io_phases_keep_exception_and_identity(self):
        for phase in ['upstream_connect','upstream_send','upstream_read','downstream_write']:
            with self.subTest(phase=phase):
                events,row=self.exercise(phase);e=next(x for x in events if x['kind']=='transport_error')
                self.assertEqual(e['failure_origin'],phase);self.assertEqual(e['exception_type'],row[3])
                self.assertEqual(events[0]['identity'],{'thread_id':'thread','turn_id':'turn'})
                if phase=='downstream_write':
                    self.assertEqual(row[0],200);self.assertEqual(row[1],'response.completed');self.assertEqual(json.loads(row[2]),{'input_tokens':1})
    def test_no_deadline_and_success_keep_usage(self):
        events,row=self.exercise();self.assertEqual(row[1],'response.completed');self.assertFalse(events[-1]['original_deadline_observed'])
    def test_owner_shutdown_and_original_deadline_are_separate_facts(self):
        e,_=self.exercise(close=True);self.assertTrue(e[-1]['gateway_owner_shutdown_observed']);self.assertFalse(e[-1]['original_deadline_observed'])
        e,row=self.exercise(seconds=60,expired=True);self.assertTrue(e[-1]['original_deadline_observed']);self.assertEqual(row[3],'task_deadline')
    def test_legacy_rows_not_backfilled(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'b.sqlite';b=Budget(p,seconds=None,requests=None);b.arm();r,_=b.reserve(b'{}',b'{}',[]);b.checkpoint(r,failure='BrokenPipeError',finished=True)
            b.db.execute('drop table request_observations');b.db.commit();old=b.db.execute('select * from requests').fetchall();b.close()
            b=Budget(p,seconds=None,requests=None);self.assertEqual(b.db.execute('select * from requests').fetchall(),old);self.assertEqual(b.db.execute('select count(*) from request_observations').fetchone()[0],0);b.close()

if __name__=='__main__':unittest.main()
