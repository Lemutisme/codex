import concurrent.futures
import http.client
import http.server
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from procontract_benchmark_gateway import Budget, Gateway, prepare_payload, truncate_output


def payload(output=None):
    return json.dumps(dict(model='gpt-5.6-luna', reasoning={'effort': 'max'}, stream=True,
        tools=[{'type': 'namespace', 'tools': [{'type': 'function', 'name': 'exec'}]}],
        input=[] if output is None else [{'type': 'function_call_output', 'call_id': 'c', 'output': output}])).encode()


class GatewayTests(unittest.TestCase):
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
            budget = Budget(Path(root)/'b.sqlite', seconds=.6, requests=2)
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
