"""Native ProContract operation adapter; workflow and offered tools are caller context."""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import queue
import sqlite3
import stat
import subprocess
import sys
import threading
import tempfile
import time
import tomllib

import procontract_operations as ops
import procontract_evidence
from procontract_operations_rpc import Broker
from procontract_benchmark_runner import AppServer
from procontract_benchmark_gateway import Budget, Gateway
import procodex_config

def build_identity(package):
    """Reproducible definitions; actual request/context bytes stay per-run."""
    def digest(path):
        with path.open('rb') as stream:
            return hashlib.file_digest(stream,'sha256').hexdigest()
    sources={'adapter':Path(__file__), 'operations':Path(ops.__file__), 'evidence':Path(procontract_evidence.__file__),
        'store_binding':Path(ops.kernel.__file__), 'resolver':Path(procodex_config.__file__),
        'inputs':Path(procodex_config.procodex_inputs.__file__),
        'rpc':Path(sys.modules[Broker.__module__].__file__),
        'native_transport':Path(sys.modules[AppServer.__module__].__file__),
        'gateway':Path(sys.modules[Budget.__module__].__file__)}
    return {'package_files':{str(p.relative_to(package)):digest(p) for p in sorted(package.rglob('*'))
                             if p.is_file() and '__pycache__' not in p.parts},
            'host_sources':{name:digest(path) for name,path in sources.items()}}


def observe_build(package, definition):
    observed=build_identity(package)
    expected=definition['build'].get('snapshot')
    if expected is not None and expected != observed:
        raise ValueError('version build/resolver/tool sources differ; no model work admitted')
    # Older definitions remain readable with their original, narrower meaning.
    return observed


def verify_actor_view(home, image):
    """Exercise the configured runtime view before model work; do not infer reach
    from a read-only mount (read-only still permits reading private fixtures)."""
    environment=tomllib.loads((home/'environments.toml').read_text())['environments'][0]
    arguments=environment['args'];end=arguments.index(image)+1
    probe='''import json
from pathlib import Path
assert Path('/opt/procodex/bin/codex').is_file()
assert not Path('/opt/procodex/scripts').exists()
assert not Path('/opt/procodex/procodex-release.json').exists()
print(json.dumps({'runtime_binary': True, 'host_scripts_visible': False, 'host_manifest_visible': False}))
'''
    result=subprocess.run([environment['program'],*arguments[:end],'python3','-c',probe],
                          check=True,capture_output=True,text=True,timeout=20)
    return {'environment_sha256':ops.sha((home/'environments.toml').read_bytes()),
            'observed':json.loads(result.stdout),'mounts':[arguments[i+1] for i,v in enumerate(arguments) if v=='--mount']}


def confirm_environment_shutdown(workspace, home):
    """Reconcile only containers with this invocation's exclusive host mounts."""
    owned=[]
    try:
        roots=(workspace.resolve(),home.resolve())
        def scan():
            ids=subprocess.check_output(['docker','ps','-q','--no-trunc'],text=True,timeout=10).split()
            if not ids:return []
            try:
                raw=subprocess.check_output(['docker','inspect',*ids],text=True,stderr=subprocess.PIPE,timeout=10)
            except subprocess.CalledProcessError as error:
                # Docker returns the inspectable objects even if another listed
                # container disappeared. Recheck omissions instead of treating
                # an unrelated removal as an unknown effect of this operation.
                raw=error.output
            containers=json.loads(raw)
            observed={c['Id'] for c in containers}
            missing=set(ids)-observed
            if missing:
                live=set(subprocess.check_output(['docker','ps','-q','--no-trunc'],text=True,timeout=10).split())
                if missing & live:raise RuntimeError('live container could not be inspected')
            selected=[]
            for container in containers:
                sources=[Path(m['Source']).resolve() for m in container.get('Mounts',[]) if m.get('Source')]
                if any(source==root or source.is_relative_to(root) for source in sources for root in roots):
                    selected.append(container['Id'])
            return selected
        owned=scan()
        removal=None
        if owned:
            # --rm may finish between inspection and this request. The subsequent
            # live-set observation determines lifetime, not the CLI exit alone.
            removed=subprocess.run(['docker','rm','-f',*owned],check=False,capture_output=True,text=True,timeout=10)
            removal={'exit_code':removed.returncode,'stderr':removed.stderr[:2000]}
        remaining=scan()
        return {'confirmed':not remaining,'owned_containers':owned,'remaining_owned':remaining,'removal':removal}
    except Exception as error:
        return {'confirmed':False,'owned_containers':owned,'error':str(error)}


class AuditedBudget(Budget):
    def reserve_with_context(self, original, forwarded, truncations):
        request,deadline,forwarded=super().reserve_with_context(original,forwarded,truncations)
        target=self.path.parent/'requests';target.mkdir(exist_ok=True)
        # Exact delivered payloads; HTTP authentication is never in these bytes.
        (target/f'{request}.original.json').write_bytes(original)
        (target/f'{request}.forwarded.json').write_bytes(forwarded)
        return request,deadline,forwarded


def collect_outputs(workspace):
    """Retain file identities; never follow actor-controlled links into the host."""
    files={};artifacts={}
    for path in workspace.iterdir():
        if path.is_symlink():
            artifacts[path.name]={'kind':'symlink','target':os.readlink(path)}
            continue
        if not path.is_file():continue
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
        with os.fdopen(fd,'rb') as source:
            metadata=os.fstat(source.fileno())
            if not stat.S_ISREG(metadata.st_mode):continue
            digest=hashlib.file_digest(source,'sha256').hexdigest()
            artifacts[path.name]={'kind':'file','bytes':metadata.st_size,'sha256':digest,'inline_text':False}
            if metadata.st_size<=1<<20:
                source.seek(0)
                try:files[path.name]=source.read().decode('utf-8')
                except UnicodeDecodeError:continue
                artifacts[path.name]['inline_text']=True
    return files,artifacts


def attach_socket(home, socket, image):
    """Socket transport need not inherit the length/layout of durable workspace paths."""
    path=home/'environments.toml'
    environment=tomllib.loads(path.read_text())['environments'][0]
    arguments=environment['args']
    at=arguments.index(image)
    arguments[at:at]=['--mount',f'type=bind,src={socket},dst=/workspace/s,readonly']
    lines=path.read_text().splitlines()
    if sum(line.startswith('args=') for line in lines)!=1:raise ValueError('ambiguous execution environment')
    path.write_text('\n'.join('args='+json.dumps(arguments) if line.startswith('args=') else line for line in lines)+'\n')


def native(run, package, image, version, host, prompt, *, inputs, seconds=None, socket_host=None, measurements=None, offered_operations=None):
    run.mkdir(parents=True,exist_ok=True)
    with (run/'native-admission.json').open('x') as admission:
        json.dump({'version':version,'prompt_sha256':ops.sha(prompt.encode()),'seconds':seconds,'at':time.time()},admission)
        admission.flush();os.fsync(admission.fileno())
    workspace=run/'w';workspace.mkdir(exist_ok=True)
    strategy=run/'strategy';strategy.mkdir(exist_ok=True)
    definition=host.get(version,'version')['definition']
    actual_build=observe_build(package,definition)
    for name,content in definition['files'].items():
        if name.endswith('.md'):
            (strategy/name).parent.mkdir(parents=True,exist_ok=True)
            (strategy/name).write_text(content)
    source=run/'source';source.mkdir(exist_ok=True)
    model=definition['model']['name'];effort=definition['model']['effort']
    budget=AuditedBudget(run/'requests.sqlite',seconds=seconds,requests=None,model=model,effort=effort)
    gateway=Gateway(budget,'http://127.0.0.1:8317/v1',api_key=os.environ.get('OPENAI_API_KEY'))
    threading.Thread(target=gateway.serve_forever,daemon=True).start();budget.arm()
    (source/'config.toml').write_text(procodex_config.toml({'model_provider':'episode','model_providers':{'episode':{
        'name':'Recorded real-model route','base_url':gateway.base_url,'wire_api':'responses',
        'supports_websockets':False,'requires_openai_auth':False,'request_max_retries':0,'stream_max_retries':0}}}))
    (run/'state').mkdir(exist_ok=True)
    (run/'state/config.toml').write_text(procodex_config.toml({'model':model,'model_reasoning_effort':effort}))
    home,config=procodex_config.configure(package,workspace,run/'state',source,image,None,
        isolation='container-only',successor_sessions=0,task_seconds=seconds,continuous_work=True,
        inputs=inputs,strategy=strategy)
    config['approval_policy']='never'
    config['developer_instructions']+='\nHost allocation bindings (observed facts):\n'+json.dumps({
        'observation_phase':'native_admission',
        'standing_responsibility':socket_host,'standing_authority_scope':host.authority.scope,
        'standing_authority_deadline':host.authority.deadline,
        'native_invocation_allocation':budget.status()},sort_keys=True)
    (home/'config.toml').write_text(procodex_config.toml(config))
    settings_path=home/'pro_contract/settings.json';settings=json.loads(settings_path.read_text())
    settings['evaluation']['excluded_paths'].append('s')
    settings['resource_snapshot']=str(budget.resource_path)
    settings_path.write_text(json.dumps(settings))
    broker=None;ipc=None
    if socket_host:
        ipc=tempfile.TemporaryDirectory(prefix='pc-ipc-')
        broker=Broker(Path(ipc.name)/'s',host,socket_host,measurements=measurements,operations=offered_operations)
        attach_socket(home,broker.path,image)
        threading.Thread(target=broker.serve_forever,daemon=True).start()
    actor_view=verify_actor_view(home,image)
    ops.atomic(run/'actor-view.json',actor_view)
    resolved=host.resolved(version,{'prompt':prompt,'configuration':config,'policies':{k:v for k,v in definition['files'].items() if k.endswith('.md')}},
        {k:ops.sha(Path(v).read_bytes()) for k,v in inputs.items()}, {'image':image,'network':'none','model':model,'effort':effort,'seconds':seconds,'requests':None,
        'build_observation':actual_build,'actor_view':actor_view})
    env={**os.environ,'CODEX_HOME':str(home)}
    server=AppServer([str(package/'bin/codex'),'--enable','pro_contract','--disable','hooks','app-server'],env,run/'rpc.jsonl',run/'stderr.log',workspace)
    completed=[]
    def handle(value):
        if 'id' in value and 'method' in value:server.refuse(value)
        if value.get('method')=='turn/completed' and value['params'].get('threadId')==thread:
            completed.append(value['params']['turn'])
    status=None;started=time.time();thread=None;disposition=None
    try:
        server.request('initialize',{'clientInfo':{'name':'rsi-qualification','version':'1'},'capabilities':{'experimentalApi':True}},handle)
        server.notify('initialized')
        thread=server.request('thread/start',{'model':model,'cwd':'/workspace','sandbox':'danger-full-access','approvalPolicy':'never'},handle)['thread']['id']
        server.request('turn/start',{'threadId':thread,'input':[{'type':'text','text':prompt,'text_elements':[]}]},handle)
        allocation=budget.status()
        while allocation['deadline'] is None or time.time()<allocation['deadline']+45:
            try:handle(server.messages.get(timeout=.5))
            except queue.Empty:pass
            db=home/'pro_contract/ledger_1.sqlite'
            if db.exists():
                with contextlib.closing(sqlite3.connect(db.as_uri()+'?mode=ro',uri=True)) as connection:
                    row=connection.execute("SELECT json FROM records WHERE kind='status' AND key=?",(thread,)).fetchone()
                if row:
                    status=json.loads(row[0])
                    if status.get('resting') and completed:
                        disposition='native_rest'
                        break
            if socket_host and completed:
                selected=host.inbox(socket_host)
                if selected and selected['pending'] is None and selected['wake'] is not None:
                    # Execute the actor's retained wait. An unrelated legacy
                    # preparation worker must not keep this invocation alive.
                    disposition='selected_wait'
                    break
            if server.process.poll() is not None:break
    finally:
        shutdown=server.close()
        environment_shutdown=confirm_environment_shutdown(workspace,home)
        ops.atomic(run/'shutdown.json',{'native':shutdown,'environment':environment_shutdown})
        if broker:broker.shutdown();broker.server_close();(workspace/'s').unlink(missing_ok=True)
        if ipc:ipc.cleanup()
        gateway.shutdown();gateway.server_close()
    usage=[]
    with budget.lock:
        usage=[json.loads(row[0]) for row in budget.db.execute('SELECT usage FROM requests WHERE usage IS NOT NULL')]
        models=[list(row) for row in budget.db.execute('SELECT * FROM response_identity')]
    cost={'allocator':budget.status(),'usage':usage,'model_responses':models,'elapsed_seconds':time.time()-started}
    budget.close()
    files,artifacts=collect_outputs(workspace)
    result={'version':version,'resolved_input':resolved,'thread':thread,'status':status,'disposition':disposition,'shutdown':shutdown,
            'environment_shutdown':environment_shutdown,'cost':cost,
            'files':files,'artifacts':artifacts,'completed_turns':completed}
    ops.atomic(run/'result.json',result)
    return result


def native_measure(assignment_path):
    path=Path(assignment_path);assignment=json.loads(path.read_text())
    config=json.loads(Path(assignment['measurement']['argv'][-1]).read_text())
    request=assignment['request'];params=request['inputs']
    try:
        result=native(Path(params['run']),Path(config['package']),config['image'],request['version'],
            ops.Operations(Path(config['host'])),params['prompt'],inputs={k:Path(v) for k,v in params['inputs'].items()},
            seconds=params.get('seconds'),socket_host=params.get('socket_host'),
            measurements=params.get('offered_measurements',config.get('offered_measurements')),
            offered_operations=params.get('offered_operations',config.get('offered_operations')))
    except BaseException as error:
        shutdown_path=Path(params['run'])/'shutdown.json'
        shutdown=json.loads(shutdown_path.read_text()) if shutdown_path.exists() else {}
        ops.atomic(path.parent/'result.json',{'validity':'unavailable','quality':None,'admissible':False,
            'effects_resolved':shutdown.get('native',{}).get('status')=='exited' and shutdown.get('environment',{}).get('confirmed') is True,
            'failure':type(error).__name__,'shutdown':shutdown,'task':None})
        raise
    actual=result['files'].get('answer.txt')
    quality=actual==params['expected'] if actual is not None and 'expected' in params else None
    ops.atomic(path.parent/'result.json',{'validity':'valid' if actual is not None or 'expected' not in params else 'unavailable',
        'quality':quality,'actual':actual,'expected':params.get('expected'),'task':result,
        'effects_resolved':result['shutdown']['status']=='exited' and result['environment_shutdown']['confirmed'],
        'conditions':params.get('conditions',{}),'admissible':False})


def run_assigned(host, identity, responsibility, version, params):
    host.submit(identity,responsibility,version,'native-procontract',params,'declared native task',seconds=params['seconds']+90 if params.get('seconds') is not None else None)
    host.dispatch(identity)
    while True:
        item=host.reconcile(identity)
        if item['state']=='finished':
            result=item['outcome'].get('measurement')
            if result is None:raise RuntimeError(f'native operation failed: {item}')
            return result['task'],item['outcome']['object']
        if item['state']=='unknown':raise RuntimeError('native operation effects unknown; no replay')
        time.sleep(.2)


def submit_pending(host, responsibility, version, run_root, prompt, *, inputs,
                   seconds=None, offered_measurements=None, offered_operations=None):
    """Reserve the caller-selected native action for the current retained input.

    Duplicate delivery resolves to the same assignment. This neither acknowledges
    the input nor chooses experiments/retries/adoption; those remain actor/context work.
    """
    view=host.receive(responsibility)
    if view['cancelled'] or (view['pending'] is None and not view['time_due']):return None
    identity='input.'+ops.sha([responsibility,view['epoch'],view['pending'],view['wait'].get('after')])[:32]
    params={'run':str(Path(run_root)/identity),'prompt':prompt,'inputs':{k:str(v) for k,v in inputs.items()},
            'seconds':seconds,'socket_host':responsibility}
    if offered_measurements is not None:params['offered_measurements']=list(offered_measurements)
    if offered_operations is not None:params['offered_operations']=list(offered_operations)
    params['conditions']={'input_delivery':view,'purpose':'selected work on retained pending input'}
    item=host.submit(identity,responsibility,version,'native-procontract',params,
        'caller-selected native action for retained input',seconds=seconds+90 if seconds is not None else None)
    return identity,item



if __name__=='__main__':
    native_measure(sys.argv[-1])
