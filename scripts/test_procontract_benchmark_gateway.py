import concurrent.futures
import http.client
import http.server
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from procontract_benchmark_gateway import Budget, Gateway, prepare_payload, truncate_output


def payload(output=None):
    return json.dumps(dict(model='gpt-5.6-luna', reasoning={'effort': 'max'}, stream=True,
        tools=[{'type': 'namespace', 'tools': [{'type': 'function', 'name': 'exec'}]}],
        input=[] if output is None else [{'type': 'function_call_output', 'call_id': 'c', 'output': output}])).encode()


class GatewayTests(unittest.TestCase):
    def test_nontext_tool_result_is_explicit_recoverable_feedback(self):
        output = [{"type":"input_text","text":"Local documentation loaded."},
                  {"type":"input_image","image_url":"data:image/png;base64,LOCAL_IMAGE_BYTES"}]
        forwarded, audit = prepare_payload(payload(output), 'gpt-5.6-luna', 'max')
        value = json.loads(forwarded)
        text = value['input'][0]['output'][0]['text']
        self.assertIn('Tool observation incomplete', text)
        self.assertIn('Local documentation loaded.', text)
        self.assertNotIn('LOCAL_IMAGE_BYTES', forwarded.decode())
        self.assertNotIn('image_url', forwarded.decode())
        self.assertEqual(value['input'][0]['call_id'], 'c')
        self.assertEqual(audit[0]['kind'], 'unavailable_observation')
        self.assertEqual(audit[0]['content_types'], ['input_image'])
        # Re-sending retained history does not erase the explicit failure or add it twice.
        replay, adjustments = prepare_payload(forwarded, 'gpt-5.6-luna', 'max')
        self.assertEqual(json.loads(replay), value)
        self.assertEqual(adjustments, [])

    def test_owner_close_waits_for_a_sqlite_writer_and_fences_late_callbacks(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'budget.sqlite'
            budget=Budget(path,seconds=None,requests=None);grant=budget.arm()
            request,_=budget.reserve(b'x',b'x',[])
            entered=threading.Event();release=threading.Event();closed=threading.Event();errors=[]
            def hold():
                entered.set();release.wait(5);return 1
            budget.db.create_function('hold_checkpoint',0,hold)
            budget.db.execute('CREATE TRIGGER checkpoint_writer AFTER UPDATE OF http_status ON requests BEGIN SELECT hold_checkpoint(); END')
            def write():
                try:budget.checkpoint(request,status=200)
                except Exception as error:errors.append(error)
            def close():
                budget.close();closed.set()
            writer=threading.Thread(target=write);writer.start()
            self.assertTrue(entered.wait(2))
            closer=threading.Thread(target=close);closer.start()
            try:self.assertFalse(closed.wait(.05))
            finally:release.set();writer.join(2);closer.join(2)
            self.assertTrue(closed.is_set());self.assertFalse(errors)
            budget.checkpoint(request,terminal='response.completed',finished=True)
            budget.observe_identity(request,{'model':'late'})
            budget.reject('late');budget.close()
            with self.assertRaisesRegex(ValueError,'budget_closed'):
                budget.reserve(b'x',b'x',[])
            reopened=Budget(path,seconds=None,requests=None)
            self.assertEqual(reopened.arm()['started'],grant['started'])
            self.assertEqual(reopened.status()['used'],1)
            self.assertEqual(reopened.db.execute('SELECT http_status,terminal FROM requests').fetchone(),(200,None))
            self.assertEqual(reopened.db.execute('SELECT count(*) FROM response_identity').fetchone()[0],0)
            reopened.close()

    def test_owner_close_during_connection_cannot_dispatch_afterward(self):
        connecting=threading.Event();release=threading.Event();received=[]
        class Upstream(http.server.BaseHTTPRequestHandler):
            def log_message(self,*_):pass
            def do_POST(self):received.append(True);self.send_error(500)
        upstream=http.server.ThreadingHTTPServer(('127.0.0.1',0),Upstream)
        threading.Thread(target=upstream.serve_forever,daemon=True).start()
        original=http.client.HTTPConnection.connect
        def connect(connection):
            if connection.port==upstream.server_port:
                connecting.set();release.wait(5)
            return original(connection)
        with tempfile.TemporaryDirectory() as root:
            budget=Budget(Path(root)/'budget.sqlite',seconds=None,requests=None)
            gateway=Gateway(budget,f'http://127.0.0.1:{upstream.server_port}/v1')
            thread=threading.Thread(target=gateway.serve_forever,daemon=True);thread.start();budget.arm()
            def post():
                conn=http.client.HTTPConnection('127.0.0.1',gateway.server_port,timeout=3)
                try:
                    conn.request('POST','/v1/responses',body=payload());conn.getresponse().read()
                except (OSError,http.client.HTTPException):pass
                finally:conn.close()
            try:
                with patch.object(http.client.HTTPConnection,'connect',connect), concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    response=pool.submit(post);self.assertTrue(connecting.wait(2))
                    gateway.shutdown();gateway.server_close();thread.join();release.set()
                    response.result(timeout=2)
                    for _ in range(100):
                        with budget.lock:
                            finished=budget.db.execute('select finished from requests').fetchone()[0]
                        if finished is not None:break
                        time.sleep(.01)
                    self.assertIsNotNone(finished)
                self.assertEqual(received,[])
                self.assertEqual(budget.status()['used'],1)
            finally:
                release.set();gateway.server_close();budget.close()
        upstream.shutdown();upstream.server_close()

    def test_untimed_allocation_requires_admission_and_survives_restart_without_renewal(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'budget.sqlite'
            budget=Budget(path,seconds=None,requests=None)
            with self.assertRaisesRegex(ValueError,'unarmed'):
                budget.reserve(b'x',b'x',[])
            original=budget.arm()
            self.assertIsNone(original['deadline'])
            with patch('procontract_benchmark_gateway.time.time',return_value=original['started']+10**9):
                self.assertIsNone(budget.reserve(b'x',b'x',[])[1])
            budget.close()
            reopened=Budget(path,seconds=None,requests=None)
            self.assertEqual(reopened.arm()['started'],original['started'])
            self.assertEqual(reopened.status()['used'],1)
            reopened.close()
            with self.assertRaisesRegex(ValueError,'profile changed'):
                Budget(path,seconds=60,requests=None)

    def test_absent_persisted_deadline_cannot_widen_an_admitted_finite_grant(self):
        with tempfile.TemporaryDirectory() as root:
            budget=Budget(Path(root)/'budget.sqlite',seconds=60)
            budget.arm()
            with budget.db:budget.db.execute('UPDATE budget SET deadline=NULL')
            with self.assertRaisesRegex(ValueError,'unarmed'):
                budget.reserve(b'x',b'x',[])
            budget.close()

    def test_untimed_http_stream_can_be_closed_by_its_owner(self):
        entered=threading.Event();release=threading.Event()
        class Upstream(http.server.BaseHTTPRequestHandler):
            def log_message(self,*_):pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
                self.wfile.write(b'data: {"type":"response.created","response":{"id":"open"}}\n\n');self.wfile.flush()
                entered.set();release.wait(5)
        upstream=http.server.ThreadingHTTPServer(('127.0.0.1',0),Upstream)
        threading.Thread(target=upstream.serve_forever,daemon=True).start()
        with tempfile.TemporaryDirectory() as root:
            budget=Budget(Path(root)/'budget.sqlite',seconds=None,requests=None)
            gateway=Gateway(budget,f'http://127.0.0.1:{upstream.server_port}/v1')
            thread=threading.Thread(target=gateway.serve_forever,daemon=True);thread.start();budget.arm()
            def post():
                conn=http.client.HTTPConnection('127.0.0.1',gateway.server_port,timeout=3)
                try:
                    conn.request('POST','/v1/responses',body=payload())
                    r=conn.getresponse();return r.status,r.read()
                finally:conn.close()
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    response=pool.submit(post)
                    self.assertTrue(entered.wait(2))
                    gateway.shutdown();gateway.server_close();thread.join()
                    self.assertEqual(response.result(timeout=2)[0],200)
                self.assertEqual(budget.status()['used'],1)
                self.assertIsNone(budget.status()['deadline'])
            finally:
                release.set();gateway.server_close();budget.close()
        upstream.shutdown();upstream.server_close()

    def test_shared_budget_is_atomic_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)/'budget.sqlite'
            budget = Budget(path, requests=7)
            original = budget.arm()
            def reserve(_):
                try:
                    return budget.reserve(b'original', b'forwarded', [])[0]
                except ValueError:
                    return None
            with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
                ids = [i for i in pool.map(reserve, range(40)) if i is not None]
            self.assertEqual(sorted(ids), list(range(1, 8)))
            budget.close()
            reopened = Budget(path, requests=7)
            self.assertEqual(reopened.arm()['deadline'], original['deadline'])
            with self.assertRaisesRegex(ValueError, 'request_budget'):
                reopened.reserve(b'x', b'x', [])
            reopened.close()
            with self.assertRaisesRegex(ValueError, 'profile changed'):
                Budget(path, requests=8)
            with self.assertRaisesRegex(ValueError, 'profile changed'):
                Budget(path, requests=None)

    def test_time_only_allocation_counts_concurrent_attempts_past_1000(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)/'budget.sqlite'
            budgets = [Budget(path, seconds=60, requests=None) for _ in range(4)]
            with patch('procontract_benchmark_gateway.time.time', return_value=100):
                original = budgets[0].arm()
                with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
                    ids = list(pool.map(
                        lambda i: budgets[i % len(budgets)].reserve(b'x', b'x', [])[0],
                        range(1024)))
            self.assertEqual(sorted(ids), list(range(1, 1025)))
            # Incomplete and failed streams are charged, not refunded.
            budgets[0].checkpoint(1, failure='disconnected', finished=True)
            for budget in budgets:
                budget.close()
            reopened = Budget(path, seconds=60, requests=None)
            with patch('procontract_benchmark_gateway.time.time', return_value=159):
                status = reopened.arm()
                self.assertEqual(status['deadline'], original['deadline'])
                self.assertIsNone(status['requests'])
                self.assertEqual(status['used'], 1024)
                self.assertEqual(reopened.reserve(b'x', b'x', [])[0], 1025)
            with patch('procontract_benchmark_gateway.time.time', return_value=160):
                with self.assertRaisesRegex(ValueError, 'wall_time_exhausted'):
                    reopened.reserve(b'x', b'x', [])
            self.assertEqual(reopened.status()['used'], 1025)
            reopened.close()
            with self.assertRaisesRegex(ValueError, 'profile changed'):
                Budget(path, seconds=60, requests=1000)
            with self.assertRaisesRegex(ValueError, 'profile changed'):
                Budget(path, seconds=120, requests=None)

    def test_default_request_ceiling_remains_1000(self):
        with tempfile.TemporaryDirectory() as root:
            budget = Budget(Path(root)/'budget.sqlite')
            self.assertEqual(budget.arm()['requests'], 1000)
            for _ in range(1000):
                budget.reserve(b'x', b'x', [])
            with self.assertRaisesRegex(ValueError, 'model_request_budget_exhausted'):
                budget.reserve(b'x', b'x', [])
            budget.close()

    def test_unarmed_or_expired_never_dispatches(self):
        with tempfile.TemporaryDirectory() as root:
            b = Budget(Path(root)/'b.sqlite', seconds=.02)
            with self.assertRaises(ValueError):
                b.reserve(b'a', b'a', [])
            b.arm()
            time.sleep(.03)
            with self.assertRaises(ValueError):
                b.reserve(b'a', b'a', [])
            self.assertEqual(b.status()['used'], 0)
            b.close()

    def test_unicode_head_tail_and_source_binding(self):
        original = '头'*5000+'秘密'*20+'尾'*5000
        forwarded, audit = prepare_payload(payload(original), 'gpt-5.6-luna', 'max')
        text = json.loads(forwarded)['input'][0]['output']
        self.assertTrue(text.startswith('头'*5000) and text.endswith('尾'*5000))
        self.assertNotIn('秘密', text)
        self.assertIn('40 characters elided', text)
        self.assertEqual(audit[0]['original_characters'], 10040)
        self.assertEqual(truncate_output('x'*9999), 'x'*9999)

    def test_role_and_network_bypasses_rejected(self):
        for change in [dict(model='other'), dict(reasoning={'effort':'low'}),
                       dict(tools=[{'type':'web_search'}]), dict(previous_response_id='r'),
                       dict(input=[{'type':'additional_tools','tools':[{'type':'web_search'}]}]),
                       dict(input=[{'type':'message','content':[{'image_url':'http://external/'}]}])]:
            value = json.loads(payload()); value.update(change)
            with self.assertRaises(ValueError):
                prepare_payload(json.dumps(value), 'gpt-5.6-luna', 'max')

    def test_real_http_stream_and_inflight_deadline(self):
        for request_limit in (2, None):
            with self.subTest(request_limit=request_limit):
                self.check_real_http_stream_and_inflight_deadline(request_limit)

    def check_real_http_stream_and_inflight_deadline(self, request_limit):
        received = []
        class Upstream(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def do_POST(self):
                received.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
                if len(received) == 1:
                    self.wfile.write(b'data: {"type":"response.completed","response":{"usage":{"input_tokens":1,"output_tokens":1}}}\n\n')
                    self.wfile.flush()
                else:
                    time.sleep(1)
        upstream = http.server.ThreadingHTTPServer(('127.0.0.1',0), Upstream)
        threading.Thread(target=upstream.serve_forever, daemon=True).start()
        with tempfile.TemporaryDirectory() as root:
            budget = Budget(Path(root)/'b.sqlite', seconds=.6, requests=request_limit)
            gateway = Gateway(budget, f'http://127.0.0.1:{upstream.server_port}/v1')
            thread = threading.Thread(target=gateway.serve_forever,daemon=True);thread.start()
            budget.arm()
            def post():
                conn = http.client.HTTPConnection('127.0.0.1',gateway.server_port,timeout=2)
                conn.request('POST','/v1/responses',body=payload('a'*11000))
                response=conn.getresponse();data=response.read();conn.close()
                return response.status,data
            self.assertIn(b'response.completed',post()[1])
            started=time.monotonic();self.assertEqual(post()[0],200)
            self.assertLess(time.monotonic()-started,.9)
            self.assertEqual(post()[0],409)
            self.assertEqual(len(received),2)
            self.assertIn('elided_chars',received[0]['input'][0]['output'])
            gateway.shutdown();gateway.server_close();thread.join()
            rows=budget.db.execute('SELECT terminal,usage,failure FROM requests ORDER BY id').fetchall()
            self.assertEqual(rows[0][0],'response.completed')
            self.assertEqual(json.loads(rows[0][1])['output_tokens'],1)
            self.assertEqual(rows[1][2],'task_deadline')
            budget.close()
        upstream.shutdown();upstream.server_close()


if __name__ == '__main__':
    unittest.main()
