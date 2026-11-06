"""Append independent retries after original admissions, sharing the same16 slots."""
import collections,fcntl,hashlib,json,os,shutil,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
ORIGINAL=Path('/data/ProContract/programbench-sol61-20261104')
def save(path,value):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(value,indent=2)+'\n');tmp.replace(path)
def identity(pid):
 return {'pid':pid,'start_ticks':Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[19]}
def alive(record):
 try:
  parts=Path(f'/proc/{record["pid"]}/stat').read_text().rsplit(')',1)[1].split();return parts[0]!='Z' and parts[19]==record['start_ticks']
 except (OSError,KeyError):return False
def live_jobs(root):
 result=[]
 for path in (Path(root)/'jobs').glob('*.json'):
  record=json.loads(path.read_text())
  if alive(record):result.append(record)
 return result
def original_admissions_finished():
 tasks=json.loads((ORIGINAL/'selection.json').read_text())['selected']
 return all((ORIGINAL/'jobs'/(task+'.json')).exists() for task in tasks)
def report(plan,active,external,reason,capacity):
 rows=[]
 for task in plan['tasks']:
  run=ROOT/'runs'/task;row={'task':task,'state':'queued','independent_retry':False}
  for file,key in [('original-budget.json','allocation'),('progress.json','progress'),('JOB_RESULT.json','job'),('benchmark-score.json','benchmark_score')]:
   if (run/file).exists():row[key]=json.loads((run/file).read_text())
  if 'job' in row:row['state']='finished' if row['job'].get('stage')=='complete' else 'job_failed'
  elif (run/'runtime-result.json').exists():row['state']='archiving' if (run/'RESULT.json').exists() else 'grading'
  elif 'allocation' in row:row['state']='solving'
  elif task in active:row['state']='preparing'
  score=row.pop('benchmark_score',None)
  if score and score.get('available'):
   row['artifact_score']=score['selected']
   if score.get('valid_instance',False):row['score']=score['selected']
   else:row['validity_review']={'solver_failure':score.get('solver_failure'),'terminal_goal_resource_stop':score.get('terminal_goal_resource_stop')}
  rows.append(row)
 scored=[r for r in rows if 'score' in r]
 status={'at':time.time(),'root':str(ROOT),'states':dict(collections.Counter(r['state'] for r in rows)),
  'selected':len(rows),'active_jobs':len(active),'other_active_jobs':len(external),'combined_active_jobs':len(active)+len(external),
  'shared_capacity':capacity['max_concurrent_attempts'],'admission_wait_reason':reason,'model':plan['model'],'effort':plan['effort'],
  'solver_seconds':plan['wall_time_seconds'],'request_limit':None,'scored':len(scored),
  'scored_mean_percent':sum(r['score']['scorer_percent'] for r in scored)/len(scored) if scored else None,
  'at_least_95_percent_count':sum(r['score']['scorer_percent']>=95 for r in scored),
  'fully_resolved_count':sum(r['score']['passed']==r['score']['eligible'] for r in scored),
  'scope':'Independent GPT-6-Luna/max first attempts; fixed arm, shared six-hour allocation, unlimited requests.'}
 save(ROOT/'RESULTS.json',{**status,'rows':rows});save(ROOT/'STATUS.json',status)
def recover(plan):
 active={}
 for task in plan['tasks']:
  run=ROOT/'runs'/task
  if (run/'JOB_RESULT.json').exists():continue
  meta=ROOT/'jobs'/(task+'.json');fallback=run/'job-launch.json'
  if not meta.exists() and not fallback.exists():continue
  record=json.loads((meta if meta.exists() else fallback).read_text())
  if alive(record):active[task]=record
  else:save(run/'JOB_RESULT.json',{'task':task,'stage':'interrupted_job','at':time.time(),'solver_restarted':False,'last_process':record})
 return active
def main():
 with (ROOT/'supervisor.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);save(ROOT/'supervisor-process.json',identity(os.getpid()))
  plan_bytes=(ROOT/'plan.json').read_bytes();plan=json.loads(plan_bytes)
  qualification=json.loads((ROOT/'QUALIFIED.json').read_text())
  if qualification.get('plan_sha256')!=hashlib.sha256(plan_bytes).hexdigest():raise RuntimeError('qualification does not bind the frozen retry plan')
  active=recover(plan);children={}
  while True:
   for task,record in list(active.items()):
    child=children.get(task);running=child.poll() is None if child else alive(record)
    if running:continue
    if not (ROOT/'runs'/task/'JOB_RESULT.json').exists():save(ROOT/'runs'/task/'JOB_RESULT.json',{'task':task,'stage':'worker_exited_without_receipt','exit':child.returncode if child else None,'at':time.time(),'solver_restarted':False})
    active.pop(task);children.pop(task,None)
   capacity=json.loads((ORIGINAL/'capacity.json').read_text());assert str(ROOT) in capacity['external_job_roots']
   external=live_jobs(ORIGINAL)
   for other in capacity['external_job_roots']:
    if Path(other)!=ROOT:external+=live_jobs(Path(other))
   pending=[t for t in plan['tasks'] if t not in active and not (ROOT/'runs'/t/'JOB_RESULT.json').exists()]
   reason=None
   if not (ROOT/'QUALIFIED.json').exists():reason='qualification_pending'
   elif not original_admissions_finished():reason='original_first_attempt_queue_has_priority'
   elif (ROOT/'PAUSE_ADMISSIONS').exists() or (ORIGINAL/'PAUSE_ADMISSIONS').exists():reason='admission_hold'
   elif len(active)+len(external)>=capacity['max_concurrent_attempts']:reason='shared_capacity'
   elif shutil.disk_usage(ROOT).free<capacity['disk_admission_reserve_bytes']:reason='disk_reserve'
   elif next(int(x.split()[1])*1024 for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:'))<capacity['admission_memory_reserve_bytes']:reason='memory_reserve'
   if pending and reason is None:
    # Original admissions are permanently finished before this dispatcher can
    # launch. Other future controllers must use the same shared admission lock.
    with (ORIGINAL/'shared-admission.lock').open('a') as admission:
     fcntl.flock(admission,fcntl.LOCK_EX)
     capacity=json.loads((ORIGINAL/'capacity.json').read_text())
     external=live_jobs(ORIGINAL)
     for other in capacity['external_job_roots']:
      if Path(other)!=ROOT:external+=live_jobs(Path(other))
     if len(active)+len(external)>=capacity['max_concurrent_attempts']:
      report(plan,active,external,'shared_capacity',capacity)
      continue
     task=pending[0]
     with (ROOT/'jobs'/(task+'.log')).open('x') as log:
      child=subprocess.Popen([sys.executable,'-B',str(ROOT/'job.py'),task],cwd=ROOT,stdout=log,stderr=log,start_new_session=True,
       env={**os.environ,'PC_TASK':task,'PYTHONDONTWRITEBYTECODE':'1'})
     entry={**identity(child.pid),'task':task,'admitted_at':time.time(),'attempt_kind':'independent_first_attempt'}
     save(ROOT/'jobs'/(task+'.json'),entry);active[task]=entry;children[task]=child
   report(plan,active,external,reason,capacity)
   if not active and not pending:save(ROOT/'terminal.json',{'at':time.time(),'all_jobs_terminal':True});return
   time.sleep(10)
if __name__=='__main__':main()
