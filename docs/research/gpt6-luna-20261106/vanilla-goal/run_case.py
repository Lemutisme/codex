"""One pre-registered solve, freeze after stopping writers, then independent scoring."""
import hashlib
import json
import os
from pathlib import Path
import queue
import signal
import sqlite3
import subprocess
import sys
import threading
import time

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'controller'))
import benchmark_native_goal as goals
import procodex
import procontract_benchmark_runner as native
import procontract_benchmark_gateway as wire
import procontract_canonical as canonical
import procontract_delivery as delivery


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def save(path,value):
    path=Path(path);temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value,indent=2)+'\n');temp.replace(path)


def cleanup(task):
    docker=str(ROOT/'bin/docker')
    ids=subprocess.check_output([docker,'ps','-aq','--filter','label=pc.luna6=vanilla-goal','--filter','label=pc.task='+task],text=True,timeout=15).split()
    removed=None
    if ids:
        removed=subprocess.run([docker,'rm','-f',*ids],capture_output=True,timeout=30)
    remaining=subprocess.check_output([docker,'ps','-aq','--filter','label=pc.luna6=vanilla-goal','--filter','label=pc.task='+task],text=True,timeout=15).split()
    end=time.monotonic()+30
    while remaining and time.monotonic()<end:
        time.sleep(.2)
        remaining=subprocess.check_output([docker,'ps','-aq','--filter','label=pc.luna6=vanilla-goal','--filter','label=pc.task='+task],text=True,timeout=15).split()
    if remaining:raise RuntimeError('task containers remain')
    return {'removed':ids,'remaining':remaining,'at':time.time(),'removal_exit':removed.returncode if removed else None,'removal_diagnostic':removed.stderr.decode(errors='replace') if removed and removed.returncode else None}



def cleanup_grader(task):
 docker=str(ROOT/'grader-bin/docker');flags=['--filter','label=pc.luna6-grading=vanilla-goal','--filter','label=pc.task='+task]
 ids=subprocess.check_output([docker,'ps','-aq',*flags],text=True).split()
 if ids:subprocess.run([docker,'rm','-f',*ids],capture_output=True,timeout=30)
 return {'removed':ids,'remaining':subprocess.check_output([docker,'ps','-aq',*flags],text=True).split()}


def lane_stop(status,tracker,counters):
    rejection=counters['last_rejection']
    if rejection and rejection!='model_request_budget_exhausted':
        return 'gateway_rejection'
    if native.is_done('on',status,turn_active=tracker.active,turns_completed=tracker.completed):
        if status.get('class')=='budget_exhausted' and counters.get('requests') is not None and counters['used']>=counters['requests']:return 'model_request_limit'
        return 'execution_interrupted' if status.get('class')=='execution_interrupted' else 'controller_resting'
    return None



class RequestEvidenceBudget(wire.Budget):
    def reserve_with_context(self, original, forwarded, truncations):
        identity, deadline, actual = super().reserve_with_context(original, forwarded, truncations)
        if identity == 1:
            (self.path.parent/"first-request-original.json").write_bytes(original)
            (self.path.parent/"first-request-forwarded.json").write_bytes(actual)
        return identity, deadline, actual


class ObservedBudget(RequestEvidenceBudget):
    """Record the actual post-allocation forwarded context without changing requests."""
    def reserve_with_context(self, original, forwarded, truncations):
        identity, deadline, actual = super().reserve_with_context(original, forwarded, truncations)
        marker = self.path.parent/'strategy-observed.json'
        if not marker.exists():
            expected = (ROOT/'package/codex-rs/ext/pro-contract/policies/work_method.md').read_text()
            def strings(value):
                if isinstance(value, str): yield value
                elif isinstance(value, list):
                    for item in value: yield from strings(item)
                elif isinstance(value, dict):
                    for item in value.values(): yield from strings(item)
            def delivered(payload):
                return any(expected in text for item in json.loads(payload).get('input', [])
                           if item.get('role') == 'developer' for text in strings(item))
            if delivered(original) and delivered(actual):
                with self.lock:
                    if not marker.exists():
                        (self.path.parent/'strategy-original.json').write_bytes(original)
                        (self.path.parent/'strategy-forwarded.json').write_bytes(actual)
                        save(marker, {'request': identity, 'work_method_sha256': hashlib.sha256(expected.encode()).hexdigest(),
                            'original_sha256': hashlib.sha256(original).hexdigest(), 'forwarded_sha256': hashlib.sha256(actual).hexdigest(),
                            'scope': 'Exact strategy text in actual original and gateway-forwarded developer context; recording changes neither payload nor grant.'})
        return identity, deadline, actual


def main(task):
    plan=json.loads((ROOT/'plan.json').read_text())
    if task not in plan['tasks']:raise ValueError('task outside frozen plan')
    prepared=json.loads((ROOT/'runs'/task/'prepared.json').read_text())
    for path,expected in {**plan['files'],**prepared['files']}.items():
        if sha(path)!=expected:raise ValueError('frozen input drift: '+path)
    run=ROOT/'runs'/task;home=run/'codex-home';workspace=run/'workspace'
    with (run/'launch.json').open('x') as f:json.dump({'plan_sha256':sha(ROOT/'plan.json'),'at':time.time(),'pid':os.getpid()},f)
    budget=(ObservedBudget if plan['arm']=='on' else RequestEvidenceBudget)(run/'budget.sqlite',seconds=plan['wall_time_seconds'],requests=plan['max_model_requests_shared_all_roles'],model=plan['model'],effort=plan['effort'])
    gateway=wire.Gateway(budget,plan['upstream'])
    gate_thread=threading.Thread(target=gateway.serve_forever,daemon=True);gate_thread.start()
    config=json.loads((home/'config-template.json').read_text())
    config['model_providers'][config['model_provider']]['base_url']=gateway.base_url
    (home/'config.toml').write_text(procodex.toml(config))
    env={**os.environ,'PATH':str(ROOT/'bin')+':'+os.environ['PATH'],'DOCKER_HOST':'unix:///data/ProContract/programbench-full-procontract-20261025/docker.sock',
         'CODEX_HOME':str(home),'HOME':str(run/'home'),'PYTHONDONTWRITEBYTECODE':'1','PC_TASK':task,
         'PROGRAMBENCH_CONTAINER_PREFIX':task,'PROGRAMBENCH_DOCKER_EXECUTABLE':str(ROOT/'bin/docker'), 'HF_HUB_OFFLINE':'1'}
    for key in ('OPENAI_API_KEY','OPENAI_API_KEY_FILE','CODEX_ROLLOUT_TRACE_ROOT'):env.pop(key,None)
    grading_env={**env,'PATH':str(ROOT/'grader-bin')+':'+os.environ['PATH'],'DOCKER_HOST':'unix:///var/run/docker.sock','PROGRAMBENCH_DOCKER_EXECUTABLE':str(ROOT/'grader-bin/docker')}
    server=native.AppServer((native.app_server_command(Path(plan['package'])/'bin/codex','on') if plan['arm']=='on' else goals.command(Path(plan['package'])/'bin/codex')),env,run/'rpc.jsonl',run/'stderr.log',cwd=workspace)
    save(run/'server-process.json',{'pid':server.process.pid,'cwd':str(workspace),'at':time.time()})
    tracker=native.TurnTracker();thread=None;status=None;failure=None;stop_reason=None;started=None;timer=None
    deadline_stopped=threading.Event();post_shutdown_stop=None
    def handle(message):
        tracker.observe(message)
        if 'id' in message and 'method' in message:server.refuse(message)
    def deadline_stop():
        deadline_stopped.set()
        try:save(run/'deadline-executor-stop.json',cleanup(task))
        except Exception as error:save(run/'deadline-executor-stop.json',{'error':str(error)})
    try:
        server.request('initialize',{'clientInfo':{'name':'strict-programbench','version':'1'},'capabilities':{'experimentalApi':True}},handle)
        server.notify('initialized')
        thread=server.request('thread/start',dict(model=plan['model'],config={'model_reasoning_effort':plan['effort'],'model_context_window':plan['model_context_window']},cwd='/workspace',sandbox='danger-full-access',approvalPolicy='never'),handle)['thread']['id']
        tracker.thread_id=thread
        allocation=budget.arm();started=allocation['started'];save(run/'original-budget.json',allocation)
        timer=threading.Timer(max(0,allocation['deadline']-time.time()),deadline_stop);timer.daemon=True;timer.start()
        manifest=json.loads((run/'manifest.json').read_text());manifest['thread_id']=thread;save(run/'runtime-manifest.json',manifest)
        server.request('turn/start',{'threadId':thread,'input':[{'type':'text','text':(run/'prompt.txt').read_text(),'text_elements':[]}]},handle)
        if plan['arm']=='goal':
            save(run/'goal-activation.json',goals.activate(server,thread,handle))
        next_poll=0
        while True:
            try:
                message=server.messages.get(timeout=.2);handle(message)
                if message.get('method')=='runner/eof':raise RuntimeError('app-server EOF')
            except queue.Empty:pass
            now=time.time()
            if now<next_poll:continue
            next_poll=now+1
            status=(native.read_status(home/'pro_contract/ledger_1.sqlite',thread) if plan['arm']=='on' else goals.read(server,thread,handle))
            counters=budget.status()
            save(run/'progress.json',{'at':now,'elapsed':now-started,'budget':counters,'status':status,'turn_statuses':tracker.statuses})
            if now>=allocation['deadline'] or deadline_stopped.is_set():stop_reason='wall_time_limit';break
            # The allocator rejects new calls at the quota; admitted work drains.
            stop_reason=(lane_stop(status,tracker,counters) if plan['arm']=='on' else ('gateway_rejection' if counters['last_rejection'] else goals.stop_reason(status,turn_active=tracker.active)))
            if stop_reason:
                if stop_reason=='gateway_rejection':failure={'type':'GatewayRejected','message':counters['last_rejection']}
                elif stop_reason=='execution_interrupted':failure={'type':'NativeExecutionInterrupted','message':status.get('detail','')}
                break
    except BaseException as error:
        failure={'type':type(error).__name__,'message':str(error)[:2000]};stop_reason=stop_reason or 'infrastructure_failure'
    finally:
        if timer:timer.cancel()
        # Stop workspace writers before capturing a terminal submission.
        try:save(run/'executor-stop.json',cleanup(task))
        except Exception as error:failure={'type':'CleanupFailure','message':str(error)}
        shutdown=server.close()
        try:
            post_shutdown_stop=cleanup(task)
            save(run/'post-shutdown-executor-stop.json',post_shutdown_stop)
        except Exception as error:failure={'type':'CleanupFailure','message':str(error)}
        gateway.shutdown();gateway.server_close();gate_thread.join()
        counters=budget.status()
        save(run/'runtime-result.json',dict(task=task,thread_id=thread,stop_reason=stop_reason,failure=failure,
            shutdown=shutdown,budget=counters,status=status,turn_statuses=tracker.statuses,turn_errors=tracker.errors,
            elapsed=time.time()-started if started else None))
    result=dict(task=task,stop_reason=stop_reason,failure=failure,budget=counters,status=status,
        internal_support=bool(status and status.get('phase')=='supported') if plan['arm']=='on' else None,model_attempts=1)
    try:
        result['natural_delivery']=delivery.snapshot(run,thread) if thread and plan['arm']=='on' else None
        if shutdown.get('status')!='exited' or post_shutdown_stop is None or post_shutdown_stop.get('remaining')!=[]:raise RuntimeError('cannot freeze active or unresolved writers')
        archive=canonical.package_submission(run)
        result['submission_sha256']=sha(archive)
        result['submission_kind']='stopped_workspace';save(run/'frozen-submission.json',dict(sha256=sha(archive),at=time.time(),stop_reason=stop_reason))
        case=ROOT/'inputs/cases'/task;registry=case/'canonical-registry.json'
        args=[plan['evaluator_python'],prepared.get('evaluator_adapter',str(ROOT/'controller/procontract_canonical.py')),'evaluate','--registry',str(registry),
            '--registry-sha256',sha(registry),'--pins-sha256',sha(case/'canonical-pins.json'),
            '--task',task,'--archive',str(archive),'--output',str(run/'evaluation')]
        with (run/'evaluation.log').open('x') as log:
            evaluator=subprocess.Popen(args,env=grading_env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            try:code=evaluator.wait(timeout=plan['external_grading_seconds'])
            except subprocess.TimeoutExpired:
                os.killpg(evaluator.pid,signal.SIGTERM)
                try:evaluator.wait(timeout=30)
                except subprocess.TimeoutExpired:os.killpg(evaluator.pid,signal.SIGKILL);evaluator.wait()
                code=124
        result['evaluator_exit']=code
        score=run/'evaluation/canonical-result.json'
        result['external']=json.loads(score.read_text()) if score.exists() else {'valid':False,'reason':'evaluator_time_limit' if code==124 else 'evaluator_failed'}
        if sha(archive)!=result['submission_sha256']:raise RuntimeError('submission changed during scoring')
    except BaseException as error:result['evaluation_failure']={'type':type(error).__name__,'message':str(error)[:2000]}
    finally:
        try:result['cleanup']=cleanup(task);result['grader_cleanup']=cleanup_grader(task)
        except Exception as error:result['cleanup_error']=str(error)
        try:
            with (run/'score-projection.log').open('x') as log:
                subprocess.run([plan['evaluator_python'], '-B', str(ROOT/'record_score.py'), task],
                    env=grading_env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=240)
            result['benchmark_score']=json.loads((run/'benchmark-score.json').read_text())
        except Exception as error:result['score_projection_error']={'type':type(error).__name__,'message':str(error)}
        save(run/'RESULT.json',result);budget.close()
    print(json.dumps(result),flush=True)


if __name__=='__main__':main(sys.argv[1])
