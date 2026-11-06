"""Seal the paired deployment after actual native qualification, before admission."""
from pathlib import Path
import hashlib,json,subprocess,time,tomllib
ROOT=Path(__file__).resolve().parent
REPO=Path('/data/ProContract/worktrees/procontract-continuous-work-20261016')
def sha(p):
 with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def save(p,v):p.write_text(json.dumps(v,indent=2)+'\n')
def main():
 adapter_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()
 qualification={
  'vanilla-goal':ROOT/'qualification/goal/result.json',
  'procontract':ROOT/'qualification/procontract-fixed/capability-result.json',
 }
 assert all(json.loads(p.read_text())['passed'] for p in qualification.values())
 assert 'Ran 1 test in 180.' in Path('/data/ProContract/programbench-gpt6-luna-planning-20261106/exec-180s-tests.log').read_text()
 assert Path('/data/ProContract/programbench-gpt6-luna-planning-20261106/exec-180s-tests.log').read_text().strip().endswith('OK')
 hashes={}
 for arm in ['procontract','vanilla-goal']:
  root=ROOT/arm
  assert not (root/'QUALIFIED.json').exists()
  assert not list((root/'runs').glob('*/launch.json'))
  plan=json.loads((root/'plan.json').read_text())
  assert plan['model']=='gpt-6-luna' and plan['effort']=='max'
  assert plan['wall_time_seconds']==21600 and plan['max_model_requests_shared_all_roles'] is None
  assert len(set(plan['tasks']))==200
  for name in ['benchmark_exec_limit.py','benchmark_native_goal.py']:
   assert sha(root/'controller'/name)==sha(REPO/'scripts'/name)
  assert sha(root/'package/bin/codex')==sha(root/'solver-runtime/bin/codex')
  for prepared in (root/'runs').glob('*/prepared.json'):
   record=json.loads(prepared.read_text())
   assert all(sha(p)==expected for p,expected in record['files'].items())
   run=prepared.parent;config=json.loads((run/'codex-home/config-template.json').read_text())
   assert config['features']['goals']==(arm=='vanilla-goal')
   assert config['model']=='gpt-6-luna' and config['model_reasoning_effort']=='max'
   env=tomllib.loads((run/'codex-home/environments.toml').read_text())
   assert env['include_local'] is False
   args=env['environments'][0]['args'];assert args[args.index('--seconds')+1]=='180'
   assert args[args.index('--network')+1]=='none'
   assert args[args.index('--cpus')+1]=='20'
   assert args[args.index('--memory')+1]=='60g'
   if arm=='vanilla-goal':
    assert 'pro_contract' not in config['features']
    assert not (run/'codex-home/pro_contract/settings.json').exists()
  paths=[]
  for name in ['package','controller','solver-runtime','exec-runtime','sources']:
   paths += [p for p in (root/name).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc']
  paths += list(root.glob('*.py'))+[root/n for n in ['bin/docker','grader-bin/docker','source.json','selection.json','registry-template.json','image-pins.json','fixture-metadata.json','grader-requirements-by-task.json','vals-reference.json','inputs/task-prompt.txt','inputs/blob-manifest.json']]
  paths += list((root/'inputs/cases').glob('*/recovery-config.json'))
  plan.update(adapter_source_commit=adapter_commit,frozen_at=time.time(),qualification={'path':str(qualification[arm]),'sha256':sha(qualification[arm]),'scope':json.loads(qualification[arm].read_text()).get('qualification_scope','Actual native goal activation, automatic continuation and completion; offline execution; GPT-6-Luna/max')},scheduler_sha256=sha(ROOT/'supervise_pairs.py'),files={str(p):sha(p) for p in sorted(set(paths))})
  save(root/'plan.json',plan)
  plan_sha=sha(root/'plan.json');hashes[arm]=plan_sha
  save(root/'QUALIFIED.json',{'at':time.time(),'plan_sha256':plan_sha,'qualified':True,'model':'gpt-6-luna','effort':'max','solver_binary_sha256':sha(root/'package/bin/codex'),'native_qualification_sha256':sha(qualification[arm]),'process_limit_seconds':180,'solver_allocations_started':0,'rsi_candidates_activated':False})
  print(json.dumps({'arm':arm,'files':len(plan['files']),'plan_sha256':plan_sha}),flush=True)
 assert sha(ROOT/'procontract/inputs/task-prompt.txt')==sha(ROOT/'vanilla-goal/inputs/task-prompt.txt')
 assert json.loads((ROOT/'procontract/plan.json').read_text())['tasks']==json.loads((ROOT/'vanilla-goal/plan.json').read_text())['tasks']
 save(ROOT/'STUDY.json',{'at':time.time(),'state':'qualified','plans':hashes,'tasks_per_arm':200,'model':'gpt-6-luna','effort':'max','rsi_candidates_activated':False,'adapter_source_commit':adapter_commit})
if __name__=='__main__':main()
