"""Focused native diagnosis: actual code-mode tools, timeout, continuation and delivery.

The provider is scripted; no paid inference. Requires a qualified package and Docker image.
"""
import contextlib
import http.server
import json
import os
from pathlib import Path
import queue
import re
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
import tomllib
import unittest

import procodex
from procontract_benchmark_runner import AppServer, TurnTracker, app_server_command, read_status
from test_procodex_native import custom_call, text_values


DECODE = r'''
function decode(x) {
 if(typeof x==="string"){try{return decode(JSON.parse(x));}catch(_){return x;}}
 if(Array.isArray(x))return decode(x[0]);
 if(x && (x.handle!==undefined || x.entry!==undefined || x.source_id!==undefined || x.entries!==undefined))return x;
 for(const k of ["text","content","content_items","output"])if(x && x[k]!==undefined)return decode(x[k]);
 return x;
}
async function readDocument(tool, query) {
 let text="";
 for(let offset=0,i=0;i<200;i++) {
  const page=decode(await tool({...query,offset}));
  if(typeof page.text!=="string")throw new Error(JSON.stringify(page));
  text+=page.text;if(page.eof)return JSON.parse(text);offset=page.next_offset;
 }
 throw new Error("incomplete document");
}
'''


@unittest.skipUnless(os.environ.get('PROCODEX_NATIVE_PACKAGE') and os.environ.get('PROCODEX_TEST_IMAGE'),
                     'requires native release and offline Docker image')
class DiagnosticNativeTest(unittest.TestCase):
    def test_checkpoint_timeout_continuation_and_changed_subject(self):
        package = Path(os.environ['PROCODEX_NATIVE_PACKAGE']).resolve()
        release_stalled = threading.Event()
        requests, errors, review_counts = [], [], {}
        executor_configuration = []
        executor_calls = 0
        with tempfile.TemporaryDirectory(prefix='pc-diagnostic-native-') as temporary:
            root = Path(temporary)
            workspace = root/'workspace'; workspace.mkdir()
            (workspace/'answer.txt').write_text('not ready\n')
            source = root/'source'; source.mkdir()

            def marker(body, name):
                match = re.search(r'"'+name+r'"\s*:\s*"([0-9a-f]{64})"', '\n'.join(text_values(body)))
                if not match: raise AssertionError('missing '+name)
                return match.group(1)

            class Provider(http.server.BaseHTTPRequestHandler):
                protocol_version = 'HTTP/1.1'
                def log_message(self, *_): pass
                def do_POST(self):
                    nonlocal executor_calls
                    try:
                        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                        requests.append(body)
                        if len(requests)>40: raise AssertionError('unexpected fixture loop')
                        props = body.get('text',{}).get('format',{}).get('schema',{}).get('properties',{})
                        message = None
                        if 'differential_cases' in props:
                            message = dict(decision='contract',reason='',requirements=[dict(id='R1',text='answer.txt contains ready',source_id='request:0',inferred=False)],out_of_scope=[],process_constraints=[],differential_cases=[],candidate_tests=False)
                        elif 'assessments' in props:
                            key = body['prompt_cache_key']; n = review_counts.get(key,0)+1; review_counts[key]=n
                            diagnostic = executor_calls in (2,3,4)
                            if n == 1:
                                code = DECODE + r'''
await readDocument(tools.read_evidence,{op:"read",source_id:"contract_terms"});
for(let offset=0;;){const p=decode(await tools.read_evidence({op:"read",source_id:"human_request",offset}));if(p.eof)break;offset=p.next_offset;}
let id;
for(let offset=0;;){const p=decode(await tools.read_evidence({op:"list",source_id:"",offset}));const found=p.entries.find(x=>x.path==="answer.txt");if(found){id=found.source_id;break;}if(p.eof)break;offset=p.next_offset;}
const artifact=decode(await tools.read_evidence({op:"read",source_id:id,offset:0}));
text({fixtureCitation:artifact.citation_id,fixtureAnswer:artifact.text});
'''
                                if diagnostic:
                                    code += r'''
const focus=await readDocument(tools.read_evidence,{op:"read",source_id:"diagnosis_request"});
if(!focus.question.includes("answer.txt"))throw new Error("question missing");
if(focus.question.includes("Continue")) {
 const prior=await readDocument(tools.read_evidence,{op:"read",source_id:"prior_assessment"});
 if(!JSON.stringify(prior).includes("observed not ready"))throw new Error("checkpoint context missing");
 text({priorSeen:true});
}
const ready=artifact.text.trim()==="ready";
const judgment=ready?{status:"supported",evidence:artifact.citation_id}:{status:"defeated",findings:[{location:"answer.txt",counterexample:"observed not ready; required ready"}],missing:""};
const r=decode(await tools.record_review({checkpoint_id:"local-result",review:{assessments:[{requirement_id:"R1",observations:artifact.text,judgment}],terms_gap:[]}}));
if(!r.handle || r.completion_certified!==false)throw new Error("checkpoint receipt missing");
text({checkpointRecorded:r.handle});
'''
                                items = [custom_call(body,code,'review-observe')]
                            elif executor_calls == 2:
                                # The first diagnosis has already committed a checkpoint. Its
                                # final response never arrives before the real native deadline.
                                release_stalled.wait(45)
                                return
                            else:
                                flat = '\n'.join(text_values(body))
                                citation = re.findall(r'"fixtureCitation"\s*:\s*"(e\d+)"',flat)[-1]
                                ready = executor_calls >= 4
                                judgment = dict(status='supported',evidence=citation) if ready else dict(status='defeated',findings=[dict(location='answer.txt',counterexample='observed not ready; required ready')],missing='')
                                message = dict(assessments=[dict(requirement_id='R1',observations='Frozen artifact inspected.',judgment=judgment)],terms_gap=[],missing='')
                        else:
                            executor_calls += 1
                            if executor_calls == 1:
                                code = 'text(await tools.exec_command({cmd:"printf \'not ready\\n\' > answer.txt",yield_time_ms:1000,max_output_tokens:1000}));'
                            elif executor_calls == 2:
                                # Verify the admitted executor, not a file edited after
                                # thread/start: environments are loaded during admission.
                                settings = json.loads((home/'pro_contract/settings.json').read_text())
                                docker = os.environ.get('PROCODEX_TEST_DOCKER','docker')
                                ids = subprocess.check_output([docker,'ps','-q','--filter','label='+settings['progress']['executor_label']],text=True).split()
                                if len(ids)!=1: raise AssertionError('one provisioned executor expected')
                                actual = json.loads(subprocess.check_output([docker,'inspect',ids[0]],text=True))[0]
                                command = ' '.join(actual['Config']['Cmd'])
                                if not re.search(r'--max-process-seconds 180(?:\s|$)',command): raise AssertionError('admitted command limit differs from prepared configuration')
                                if actual['HostConfig']['NetworkMode']!='none': raise AssertionError('executor must be offline')
                                executor_configuration.append(dict(command=command,network='none',container=ids[0]))
                                code = DECODE + 'const r=decode(await tools.publish_progress({request_id:"initial",review:true,question:"Inspect answer.txt for a concrete mismatch.",assessment_secs:20}));text({firstHandle:r.handle,checkpoints:r.review_checkpoints});'
                            elif executor_calls == 3:
                                first = marker(body,'firstHandle')
                                code = DECODE + f'const first="{first}";' + r'''
const prior=await readDocument(tools.contract_read_evidence,{op:"read",handle:first});
if(prior.public.review!==undefined && prior.public.review!==null)throw new Error("timed-out final review fabricated");
const handle=prior.public.review_checkpoints[0];
const checkpoint=await readDocument(tools.contract_read_evidence,{op:"read",handle});
if(!JSON.stringify(checkpoint).includes("observed not ready"))throw new Error("checkpoint lost");
const request={request_id:"continue",review:true,question:"Continue inspecting answer.txt using prior observations.",continue_from:first,assessment_secs:40};
const continued=decode(await tools.publish_progress(request));
if(!continued.checks_reused)throw new Error("unchanged checks were replayed");
const duplicate=decode(await tools.publish_progress(request));
if(duplicate.handle!==continued.handle || !duplicate.reused)throw new Error("duplicate action");
text({continuedHandle:continued.handle,checkpointSurvived:true});
'''
                            elif executor_calls == 4:
                                prior = marker(body,'continuedHandle')
                                code = DECODE + f'const prior="{prior}";' + r'''
text(await tools.exec_command({cmd:"printf 'ready\n' > answer.txt",yield_time_ms:1000,max_output_tokens:1000}));
const changed=decode(await tools.publish_progress({request_id:"changed",review:true,question:"Continue checking answer.txt after repair.",continue_from:prior,assessment_secs:40}));
if(changed.checks_reused)throw new Error("old checks applied to changed subject");
text({changedVersionChecked:true});
'''
                            else:
                                message = 'Ready.'
                            if message is None: items = [custom_call(body,code,'executor-'+str(executor_calls))]
                        if message is not None:
                            items = [dict(type='message',id='msg-'+str(len(requests)),role='assistant',content=[dict(type='output_text',text=json.dumps(message) if isinstance(message,dict) else message)])]
                        response_id = 'local-'+str(len(requests))
                        events = [dict(type='response.created',response=dict(id=response_id))]
                        events += [dict(type='response.output_item.done',item=item) for item in items]
                        events.append(dict(type='response.completed',response=dict(id=response_id,usage=dict(input_tokens=10,output_tokens=10,total_tokens=20))))
                        self.send_response(200); self.send_header('Content-Type','text/event-stream'); self.send_header('Connection','close'); self.end_headers(); self.close_connection=True
                        for event in events:
                            self.wfile.write(('data: '+json.dumps(event)+'\n\n').encode()); self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError): pass
                    except Exception as error:
                        errors.append(str(error)); self.send_error(500)

            provider = http.server.ThreadingHTTPServer(('127.0.0.1',0),Provider); provider.daemon_threads=True
            threading.Thread(target=provider.serve_forever,daemon=True).start()
            (source/'config.toml').write_text(procodex.toml(dict(model_provider='fixture',model_providers=dict(fixture=dict(name='Fixture',base_url=f'http://127.0.0.1:{provider.server_port}/v1',wire_api='responses',supports_websockets=False,request_max_retries=0,stream_max_retries=0)))))
            home, config = procodex.configure(package,workspace,root/'state',source,os.environ['PROCODEX_TEST_IMAGE'],
                "python3 -c 'from pathlib import Path; assert Path(\"answer.txt\").read_text().strip()==\"ready\"'",
                isolation='container-only',successor_sessions=0,task_seconds=getattr(self,'task_seconds',180),continuous_work=True)
            if docker := os.environ.get('PROCODEX_TEST_DOCKER'):
                path=home/'environments.toml'; path.write_text(path.read_text().replace('program="docker"','program='+json.dumps(docker)))
                path=home/'pro_contract/settings.json'; settings=json.loads(path.read_text());settings['evaluation']['check']['docker']=docker;path.write_text(json.dumps(settings))
            if runtime := os.environ.get('PROCODEX_TEST_EXEC_RUNTIME'):
                path=home/'environments.toml';env=tomllib.loads(path.read_text());args=env['environments'][0]['args']
                args[1:1]=['--mount',f'type=bind,src={runtime},dst=/opt/pc-runtime,readonly']
                args[-1]=args[-1].replace('exec /opt/procodex/bin/codex','exec /opt/pc-runtime/ld-linux-x86-64.so.2 --library-path /opt/pc-runtime /opt/procodex/bin/codex')
                path.write_text('default="procodex"\ninclude_local=false\n[[environments]]\nid="procodex"\nprogram='+json.dumps(docker or 'docker')+'\nargs='+json.dumps(args)+'\n')
            path=home/'environments.toml'
            path.write_text(path.read_text().replace('--max-process-seconds 1800','--max-process-seconds 180'))
            server = AppServer(app_server_command(package/'bin/codex','on'),{**os.environ,'CODEX_HOME':str(home)},root/'rpc.jsonl',root/'stderr.log',cwd=workspace)
            tracker = TurnTracker(); status=None
            def handle(message):
                tracker.observe(message)
                if 'id' in message and 'method' in message:server.refuse(message)
            try:
                server.request('initialize',{'clientInfo':{'name':'diagnostic-control','version':'1'},'capabilities':{'experimentalApi':True}},handle);server.notify('initialized')
                thread=server.request('thread/start',dict(model='gpt-5.6-luna',cwd='/workspace',sandbox=config['sandbox_mode'],approvalPolicy='never'),handle)['thread']['id'];tracker.thread_id=thread
                server.request('turn/start',dict(threadId=thread,input=[dict(type='text',text='Make answer.txt contain ready.',text_elements=[])]),handle)
                deadline=time.monotonic()+170
                while time.monotonic()<deadline:
                    try:handle(server.messages.get(timeout=.2))
                    except queue.Empty:pass
                    status=read_status(home/'pro_contract/ledger_1.sqlite',thread)
                    if status and status['resting'] and not tracker.active:break
                self.assertFalse(errors,errors);self.assertEqual(status['phase'],'supported',status)
                self.assertEqual(executor_calls,5)
                with contextlib.closing(sqlite3.connect(home/'pro_contract/ledger_1.sqlite')) as db:
                    events=[json.loads(r[0])['body'] for r in db.execute('select event_json from experiment_events order by seq')]
                    commands=[json.loads(r[0])['command']['type'] for r in db.execute('select command_json from events order by seq')]
                    allocation=json.loads(db.execute("select json from records where kind='succession'").fetchone()[0])
                self.assertEqual(commands,['issue','propose','support'])
                if getattr(self,'task_seconds',180) is None:
                    self.assertIsNone(allocation['deadline_ms']);self.assertIsNone(allocation['grant']['total_secs'])
                    self.assertFalse(any(e.get('phase')=='original_grant_expired' for e in events))
                self.assertEqual(sum(e.get('phase')=='review_checkpoint' for e in events),3)
                publications=[e for e in events if e.get('phase')=='progress_assessed'];self.assertEqual(len(publications),3)
                docs=[json.loads((home/'pro_contract/blobs'/e['public_evidence'][:2]/e['public_evidence']).read_text()) for e in publications]
                self.assertFalse(docs[0]['public'].get('review'));self.assertIn('timed out',docs[0]['public']['review_error'])
                self.assertEqual([d['checks_reused'] for d in docs],[False,True,False])
                self.assertNotEqual(docs[1]['subject_hash'],docs[2]['subject_hash'])
            finally:
                release_stalled.set();server.close();provider.shutdown();provider.server_close()
                if server.process.stdout: server.process.stdout.close()
                if report := os.environ.get('PROCODEX_TEST_REPORT'):
                    out=Path(report)/'diagnostic-continuation';out.mkdir(parents=True,exist_ok=True)
                    shutil.copytree(home/'pro_contract',out/'pro_contract',dirs_exist_ok=True)
                    for name in ('rpc.jsonl','stderr.log'):shutil.copy2(root/name,out/name)
                    (out/'requests.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in requests))
                    (out/'RESULT.json').write_text(json.dumps(dict(status=status,errors=errors,requests=len(requests),executor_calls=executor_calls,review_calls=review_counts,executor_configuration=executor_configuration,real_model_calls=0),indent=2)+'\n')


if __name__=='__main__':unittest.main()
