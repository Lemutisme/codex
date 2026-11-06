"""Prepare one slot under the frozen full-corpus protocol; no solver inference."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys,time
ROOT=Path(__file__).resolve().parent
PYTHON='/data/ProContract/research/procontract-programbench-diagnostic-20261015/evaluator/.venv/bin/python'
DOCKER=str(ROOT/'bin/docker')
def sha(p):
 with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def save(p,d):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(d,indent=2)+'\n');tmp.replace(p)
def environment(task):return {**os.environ,'PATH':str(ROOT/'bin')+':'+os.environ['PATH'],'DOCKER_HOST':'unix:///data/ProContract/programbench-full-procontract-20261025/docker.sock','PC_TASK':task,'PROGRAMBENCH_CONTAINER_PREFIX':'prepare-'+task,'PYTHONDONTWRITEBYTECODE':'1','HF_HUB_OFFLINE':'1','PROGRAMBENCH_DOCKER_EXECUTABLE':DOCKER}
def grader_environment(task):
 env=environment(task);env.update(PATH=str(ROOT/'grader-bin')+':'+os.environ['PATH'],DOCKER_HOST='unix:///var/run/docker.sock',PROGRAMBENCH_DOCKER_EXECUTABLE=str(ROOT/'grader-bin/docker'))
 return env

def image(task):
 case=ROOT/'inputs/cases'/task;case.mkdir(parents=True,exist_ok=True)
 pin=json.loads((ROOT/'image-pins.json').read_text())[task];ref=pin['reference']
 env=environment(task)
 result=subprocess.run([DOCKER,'image','inspect',ref],capture_output=True,text=True,env=env)
 cached=result.returncode==0
 if not cached:
  with (case/'image-pull.log').open('a') as log:subprocess.run([DOCKER,'pull',ref],env=env,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=1800)
  result=subprocess.run([DOCKER,'image','inspect',ref],capture_output=True,text=True,env=env,check=True)
 spec=json.loads(result.stdout)[0]
 assert ref in spec['RepoDigests'] and spec['Architecture']=='amd64',(task,spec['Id'])
 if (case/'image.json').exists():
  previous=json.loads((case/'image.json').read_text());assert previous['reference']==ref and previous['config_id']==spec['Id']
 else:
  save(case/'image.json',{'reference':ref,'config_id':spec['Id'],'size_bytes':spec['Size'],'present_before_preparation':cached,'prepared_at':time.time()})
 alias='pc-luna6-20261106/'+task.replace('__','_1776_')+':input'
 subprocess.run([DOCKER,'tag',ref,alias],env=env,check=True)
 return spec['Id'],alias

def provision(task,image_id):
 plan=json.loads((ROOT/'plan.json').read_text())
 sys.path.insert(0,str(ROOT/'controller'))
 import procontract_benchmark_runner as native
 import procodex_inputs
 import yaml
 package=ROOT/'package';run=ROOT/'runs'/task;workspace=run/'workspace'
 workspace.mkdir(parents=True,exist_ok=True)
 env=environment(task)
 if not (run/'manifest.json').exists():
  subprocess.run([DOCKER,'run','--rm','--network','none','--user','0:0','--mount',f'type=bind,src={workspace},dst=/out','--entrypoint','sh',image_id,'-c','cp -a /workspace/. /out/ && chown -R 1000:1000 /out && chown 0:0 /out/executable && chmod 0111 /out/executable'],check=True,env=env,timeout=120)
  home=run/'codex-home';home.mkdir(parents=True,exist_ok=True);(run/'home').mkdir(exist_ok=True)
  if plan['arm']=='on':(home/'pro_contract').mkdir(exist_ok=True)
  inputs=procodex_inputs.provision(home,{'executable':workspace/'executable'})
  label='procontract.task='+hashlib.sha256(str(workspace.resolve()).encode()).hexdigest()[:20]
  official=yaml.safe_load((ROOT/'sources/programbench.yaml').read_text())
  arguments=['run','-i','--rm','--network','none','--cpus','20','--memory','60g','--memory-swap','60g','--user','1000:1000','--cap-drop','SYS_PTRACE','--label',label,'--label','pc.task='+task,
    '--mount',f'type=bind,src={workspace},dst=/workspace','--mount',f'type=bind,src={ROOT}/solver-runtime,dst=/opt/procodex,readonly',
    '--mount',f'type=bind,src={ROOT}/exec-runtime,dst=/opt/pc-runtime,readonly','-w','/workspace']
  for item in inputs:arguments+=['--mount',f'type=bind,src={item["source"]},dst={item["target"]},readonly']
  for k,v in {**official['environment']['env'],'PYTHONDONTWRITEBYTECODE':'1'}.items():arguments+=['-e',f'{k}={v}']
  arguments += [image_id] + (['/opt/procodex/bin/codex-exec-server','--listen','stdio'] if plan['arm']=='goal' else ['/opt/pc-runtime/ld-linux-x86-64.so.2','--library-path','/opt/pc-runtime','/opt/procodex/bin/codex','exec-server','--listen','stdio'])
  arguments=[str(ROOT/'controller/benchmark_exec_limit.py'),'--seconds','180','--receipt',str(run/'process-limits.jsonl'),'--',DOCKER,*arguments]
  (home/'environments.toml').write_text('default="cleanroom"\ninclude_local=false\n[[environments]]\nid="cleanroom"\nprogram='+json.dumps('/usr/bin/python3')+'\nargs='+json.dumps(arguments)+'\n')
  config=dict(model=plan['model'],model_reasoning_effort=plan['effort'],model_context_window=plan['model_context_window'],model_provider='strict-benchmark',approval_policy='never',sandbox_mode='danger-full-access',web_search='disabled',sqlite_home=str(home),log_dir=str(home/'log'),features=dict(pro_contract=True,hooks=False,apps=False,plugins=False,multi_agent=False,multi_agent_v2=False),agents=dict(enabled=False),model_providers={'strict-benchmark':dict(name='Strict benchmark task gateway',base_url='UNARMED',requires_openai_auth=False,supports_websockets=False,wire_api='responses',request_max_retries=5,stream_max_retries=5,wait_on_rate_limits=True)})
  config['features']['goals']=plan['arm']=='goal'
  if plan['arm']=='goal':
   config['features'].pop('pro_contract',None)
   config['features'].pop('multi_agent_v2',None)
   config['model_providers']['strict-benchmark'].pop('wait_on_rate_limits',None)
  save(home/'config-template.json',config)
  if plan['arm']=='on':
   settings=native.settings(workspace,image_id,model=plan['model'],effort=plan['effort'],policy=package/'codex-rs/ext/pro-contract/policies',succession=dict(total_secs=plan['wall_time_seconds']))
   settings['progress'].pop('max_publications',None)
   settings['evaluation']['reference_command']='/inputs/executable'
   settings['evaluation']['check'].update(docker=DOCKER,timeout_secs=180,inputs=[dict(name=x['name'],source=x['source'],digest=x['sha256']) for x in inputs])
   settings['worker']['deadline_secs']=900
   settings['resource_snapshot']=str(run/'budget.resources.json')
   settings['review_execution']=dict(max_calls=8,timeout_secs=30,max_output_bytes=65536)
   save(home/'pro_contract/settings.json',settings)
  shutil.copyfile(ROOT/'inputs/task-prompt.txt',run/'prompt.txt')
  save(run/'manifest.json',dict(instance=task,codex_bin=str(package/'bin/codex'),image=image_id,source_commit=json.loads((ROOT/'source.json').read_text())['source_commit'],model=plan['model'],effort=plan['effort'],label=label,inputs=inputs))
 # Probe the actual executable mount and network/UID, without invoking a model.
 command=[DOCKER,'run','--rm','--network','none','--user','1000:1000','--cap-drop','SYS_PTRACE',
  '--mount',f'type=bind,src={ROOT}/solver-runtime,dst=/opt/procodex,readonly',
  '--mount',f'type=bind,src={ROOT}/exec-runtime,dst=/opt/pc-runtime,readonly','--entrypoint','sh',image_id,'-c',
  'test "$(id -u)" = 1000 && test "$(ls /sys/class/net)" = lo && test ! -e /opt/procodex/scripts && '+ ('/opt/procodex/bin/codex --version' if plan['arm']=='goal' else '/opt/pc-runtime/ld-linux-x86-64.so.2 --library-path /opt/pc-runtime /opt/procodex/bin/codex --version')]
 probe=subprocess.run(command,env=env,capture_output=True,text=True,timeout=90)
 save(run/'runtime-readiness.json',{'exit_code':probe.returncode,'stdout':probe.stdout,'stderr':probe.stderr,'scope':'native binary loader, uid, network namespace and minimal runtime mount; no inference'})
 if probe.returncode:raise RuntimeError('runtime readiness failed')

def prepare_registry(task):
 case=ROOT/'inputs/cases'/task;run=ROOT/'runs'/task
 image_id,ref=image(task)
 metadata=json.loads((ROOT/'fixture-metadata.json').read_text())[task]
 registry=case/'canonical-registry.json';pins=case/'canonical-pins.json'
 if not registry.exists():
  template=json.loads((ROOT/'registry-template.json').read_text())
  if (case/'recovery-config.json').exists():
   override=json.loads((case/'recovery-config.json').read_text())
   for key in ('grader_assets','test_workspace'):
    if key in override:template[key]=override[key]
  template['grader_requirements']=json.loads((ROOT/'grader-requirements-by-task.json').read_text())[task]
  save(registry,{**template,'wheelhouse':template['wheelhouse'],'blob_root':str((ROOT/'inputs/evaluation-blobs').resolve()),'blob_manifest':str(ROOT/'inputs/blob-manifest.json'),'pins_file':str(pins),'tasks':{task:{'image':image_id,'image_tag':ref,'total':metadata['total']}}})
 from grader_image import import_image
 grading_image,grading_tag=import_image(task,image_id)
 current=json.loads(registry.read_text())
 if current['tasks'][task]['image'] != grading_image:
  if pins.exists():raise RuntimeError('grader image changed after pinning')
  current['tasks'][task].update(image=grading_image,image_tag=grading_tag);save(registry,current)
 default_adapter=ROOT/'controller/procontract_canonical.py'
 adapter=Path(json.loads((case/'recovery-config.json').read_text()).get('evaluator_adapter',str(default_adapter))) if (case/'recovery-config.json').exists() else default_adapter
 env=grader_environment(task);args=[PYTHON,str(adapter)]
 flags=['--registry',str(registry),'--registry-sha256',sha(registry)]
 if not pins.exists():
  with (case/'freeze.log').open('a') as log:subprocess.run(args+['freeze']+flags,env=env,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=240)
 return image_id,metadata,registry,pins,adapter

def prepare(task):
 case=ROOT/'inputs/cases'/task;run=ROOT/'runs'/task
 if (run/'launch.json').exists():raise RuntimeError('solver was already launched; preparation cannot overwrite it')
 image_id,metadata,registry,pins,adapter=prepare_registry(task)
 env=grader_environment(task);args=[PYTHON,str(adapter)]
 flags=['--registry',str(registry),'--registry-sha256',sha(registry)]
 if not (case/'readiness/readiness.json').exists():
  with (case/'readiness.log').open('a') as log:subprocess.run(args+['ready']+flags+['--pins-sha256',sha(pins),'--task',task,'--output',str(case/'readiness')],env=env,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=1200)
 readiness=json.loads((case/'readiness/readiness.json').read_text())
 assert readiness['valid'] and readiness['eligible_total']==metadata['total']
 provision(task,image_id)
 paths=[registry,pins,case/'readiness/readiness.json',case/'image.json',run/'manifest.json',run/'prompt.txt',run/'runtime-readiness.json']
 paths += [run/'codex-home'/p for p in ['config-template.json','environments.toml','inputs/manifest.json','inputs/files/executable']]
 if (run/'codex-home/pro_contract/settings.json').exists():paths.append(run/'codex-home/pro_contract/settings.json')
 paths.extend([adapter,case/'grader-image.json'])
 save(run/'prepared.json',{'task':task,'prepared_at':time.time(),'model_calls':0,'evaluator_adapter':str(adapter),'files':{str(p):sha(p) for p in paths}})
 print(json.dumps({'task':task,'prepared':True,'eligible_total':metadata['total']}),flush=True)

if __name__=='__main__':
 task=sys.argv[1]
 if task not in json.loads((ROOT/'selection.json').read_text())['selected']:raise ValueError('task outside selected corpus')
 try:prepare(task)
 except Exception as e:
  save(ROOT/'inputs/cases'/task/'preparation-error.json',{'type':type(e).__name__,'message':str(e),'at':time.time()})
  raise
