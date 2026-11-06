"""Interleave two independent arms under the existing shared admission capacity."""
from pathlib import Path
import collections,fcntl,hashlib,importlib.util,json,os,shutil,subprocess,sys,time
ROOT=Path(__file__).resolve().parent
ORIGINAL=Path('/data/ProContract/programbench-sol61-20261104')
def save(p,v):
 p=Path(p);temp=p.with_suffix(p.suffix+'.tmp');temp.write_text(json.dumps(v,indent=2)+'\n');temp.replace(p)
def module(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
ARMS={arm:module('scheduler_'+arm.replace('-','_'),ROOT/arm/'supervise.py') for arm in ['procontract','vanilla-goal']}
helper=ARMS['procontract']
def main():
 with (ROOT/'supervisor.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  save(ROOT/'supervisor-process.json',helper.identity(os.getpid()))
  plans={arm:json.loads((ROOT/arm/'plan.json').read_text()) for arm in ARMS}
  for arm in ARMS:
   q=json.loads((ROOT/arm/'QUALIFIED.json').read_text())
   assert q['plan_sha256']==hashlib.sha256((ROOT/arm/'plan.json').read_bytes()).hexdigest()
  active={arm:m.recover(plans[arm]) for arm,m in ARMS.items()};children={}
  order=[(arm,task) for task in plans['procontract']['tasks'] for arm in ARMS]
  assert plans['procontract']['tasks']==plans['vanilla-goal']['tasks']
  while True:
   for arm in ARMS:
    for task,record in list(active[arm].items()):
     child=children.get((arm,task));running=child.poll() is None if child else helper.alive(record)
     if running:continue
     result=ROOT/arm/'runs'/task/'JOB_RESULT.json'
     if not result.exists():save(result,{'task':task,'stage':'worker_exited_without_receipt','at':time.time(),'solver_restarted':False})
     active[arm].pop(task);children.pop((arm,task),None)
   pending=[(arm,task) for arm,task in order if task not in active[arm] and not (ROOT/arm/'runs'/task/'JOB_RESULT.json').exists()]
   with (ORIGINAL/'shared-admission.lock').open('a') as admission:
    fcntl.flock(admission,fcntl.LOCK_EX)
    capacity=json.loads((ORIGINAL/'capacity.json').read_text())
    roots=[ORIGINAL,*map(Path,capacity['external_job_roots'])]
    assert all(ROOT/arm in roots for arm in ARMS)
    live=[record for r in roots for record in helper.live_jobs(r)]
    reason=None
    if (ROOT/'PAUSE_ADMISSIONS').exists() or (ORIGINAL/'PAUSE_ADMISSIONS').exists():reason='admission_hold'
    elif len(live)>=capacity['max_concurrent_attempts']:reason='shared_capacity'
    elif shutil.disk_usage(ROOT).free<capacity['disk_admission_reserve_bytes']:reason='disk_reserve'
    elif next(int(x.split()[1])*1024 for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:'))<capacity['admission_memory_reserve_bytes']:reason='memory_reserve'
    if pending and reason is None:
     arm,task=pending[0];root=ROOT/arm
     with (root/'jobs'/(task+'.log')).open('x') as log:
      child=subprocess.Popen([sys.executable,'-B',str(root/'job.py'),task],cwd=root,stdout=log,stderr=log,start_new_session=True,env={**os.environ,'PC_TASK':task,'PYTHONDONTWRITEBYTECODE':'1'})
     record={**helper.identity(child.pid),'task':task,'arm':arm,'admitted_at':time.time(),'attempt_kind':'independent_first_attempt'}
     save(root/'jobs'/(task+'.json'),record);active[arm][task]=record;children[arm,task]=child
   for arm,m in ARMS.items():
    external=[record for r in roots if r!=ROOT/arm for record in helper.live_jobs(r)]
    m.report(plans[arm],active[arm],external,reason,capacity)
   save(ROOT/'STATUS.json',{'at':time.time(),'states':{arm:json.loads((ROOT/arm/'STATUS.json').read_text()) for arm in ARMS},'admission_wait_reason':reason,'shared_capacity':capacity['max_concurrent_attempts'],'pair_order':'interleaved, original fixed task order','rsi_candidates_activated':False})
   if not pending and not any(active.values()):save(ROOT/'terminal.json',{'at':time.time(),'all_jobs_terminal':True});return
   time.sleep(10)
if __name__=='__main__':main()
