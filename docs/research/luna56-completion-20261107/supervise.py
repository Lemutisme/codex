"""Three explicit completion jobs under the shared capacity; no attempt resumes."""
from pathlib import Path
import collections,fcntl,hashlib,json,os,shutil,subprocess,sys,time
ROOT=Path(__file__).resolve().parent
SHARED=Path('/data/ProContract/programbench-sol61-20261104')
def save(path,value):
 path=Path(path);temp=path.with_suffix(path.suffix+'.tmp');temp.write_text(json.dumps(value,indent=2)+'\n');temp.replace(path)
def identity(pid):return {'pid':pid,'start_ticks':Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[19]}
def alive(rec):
 try:
  s=Path(f'/proc/{rec["pid"]}/stat').read_text().rsplit(')',1)[1].split();return s[0]!='Z' and s[19]==rec['start_ticks']
 except (OSError,KeyError):return False
def live_jobs(root):
 return [r for p in (Path(root)/'jobs').glob('*.json') if alive(r:=json.loads(p.read_text()))]
def key(unit):return unit['root']+'/'+unit['task']
def report(units,active,capacity,reason):
 rows=[]
 for u in units:
  run=Path(u['root'])/'runs'/u['task'];row={**u,'state':'queued'}
  job=run/'JOB_RESULT.json';score=run/'benchmark-score.json'
  if score.exists():
   s=json.loads(score.read_text());valid=s.get('available') and (u['kind']=='artifact_only_measurement' or s.get('valid_instance',False))
   if valid:row['score']=s['selected']
  if job.exists():row['state']='scored' if 'score' in row else 'needs_review';row['job']=json.loads(job.read_text())
  elif (run/'runtime-result.json').exists():row['state']='grading'
  elif (run/'original-budget.json').exists():row['state']='solving'
  elif (run/'progress.json').exists():row['state']=json.loads((run/'progress.json').read_text()).get('stage','preparing')
  elif key(u) in active:row['state']='preparing'
  rows.append(row)
 baseline=json.loads((ROOT/'BASELINE.json').read_text());values=dict(baseline['values']);measurements=[];audit_pending=False
 for row in rows:
  if 'score' not in row:continue
  projection=Path(row['root'])/'runs'/row['task']/'benchmark-score.json'
  audit=Path('/data/ProContract/programbench-score-audit-20261106/cases')/Path(row['root']).name/(row['task']+'.json')
  check=json.loads(audit.read_text()) if audit.exists() else {}
  verified=bool(check.get('available') and check.get('matched') and check.get('evidence_sha256',{}).get(str(projection))==hashlib.sha256(projection.read_bytes()).hexdigest())
  row['independently_verified']=verified
  if verified:
   values[row['task']]=row['score']['scorer_percent'];measurements.append({'task':row['task'],'source':str(projection),'score_percent':row['score']['scorer_percent']})
  else:audit_pending=True
 save(ROOT/'COMPLETION.json',{'at':time.time(),'valid_instances':len(values),'total':200,'remaining':sorted(set(baseline['missing'])-values.keys()),'mean_percent':sum(values.values())/len(values),'complete':len(values)==200,'values':values,'new_measurements':measurements,'baseline_sha256':hashlib.sha256((ROOT/'BASELINE.json').read_bytes()).hexdigest(),'scope':'Frozen197 valid cases plus independently verified declared completion jobs. No best-of selection.'})
 save(ROOT/'STATUS.json',{'at':time.time(),'rows':rows,'states':dict(collections.Counter(r['state'] for r in rows)),'scored':sum('score' in r for r in rows),'total':len(rows),'active_jobs':len(active),'authorized_shared_capacity':capacity['authorized_max'],'admission_wait_reason':reason,'audit_pending':audit_pending,'scope':'Only the three missing Luna5.6 results; designated retries/corrected measurements, never maximum-score selection.'})
def main():
 with (ROOT/'supervisor.lock').open('a') as own:
  fcntl.flock(own,fcntl.LOCK_EX|fcntl.LOCK_NB)
  save(ROOT/'supervisor-process.json',identity(os.getpid()))
  units=json.loads((ROOT/'QUEUE.json').read_text())['rows'];armed=json.loads((ROOT/'QUEUE_ARMED.json').read_text())
  assert hashlib.sha256((ROOT/'QUEUE.json').read_bytes()).hexdigest()==armed['queue_sha256']
  assert hashlib.sha256((ROOT/'BASELINE.json').read_bytes()).hexdigest()==armed['baseline_sha256']
  assert json.loads((ROOT/'qualification/model-result.json').read_text())['passed']
  for root in {u['root'] for u in units}:
   p=Path(root);assert hashlib.sha256((p/'plan.json').read_bytes()).hexdigest()==json.loads((p/'QUALIFIED.json').read_text())['plan_sha256']==armed['plan_sha256'][root]
  active={};children={}
  for u in units:
   run=Path(u['root'])/'runs'/u['task'];meta=Path(u['root'])/'jobs'/(u['task']+'.json')
   if (run/'JOB_RESULT.json').exists():continue
   p=meta if meta.exists() else next((p for p in [run/'job-launch.json',run/'launch.json'] if p.exists()),None)
   if p is not None:
    rec=json.loads(p.read_text())
    if alive(rec):active[key(u)]=rec
    else:save(run/'JOB_RESULT.json',{'task':u['task'],'stage':'interrupted_job','at':time.time(),'solver_restarted':False})
  while True:
   for k,rec in list(active.items()):
    child=children.get(k)
    if (child.poll() is None) if child else alive(rec):continue
    u=next(u for u in units if key(u)==k);run=Path(u['root'])/'runs'/u['task']
    if not (run/'JOB_RESULT.json').exists():save(run/'JOB_RESULT.json',{'task':u['task'],'stage':'worker_exited_without_receipt','at':time.time(),'solver_restarted':False})
    active.pop(k);children.pop(k,None)
   pending=[u for u in units if key(u) not in active and not (Path(u['root'])/'runs'/u['task']/'JOB_RESULT.json').exists()]
   reason=None
   with (SHARED/'shared-admission.lock').open('a') as admission:
    fcntl.flock(admission,fcntl.LOCK_EX)
    capacity=json.loads((SHARED/'capacity.json').read_text())
    assert all(u['root'] in capacity['external_job_roots'] for u in units)
    total=sum(len(live_jobs(r)) for r in [SHARED,*map(Path,capacity['external_job_roots'])])
    memory=next(int(x.split()[1])*1024 for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:'))
    if (ROOT/'PAUSE_ADMISSIONS').exists() or (SHARED/'PAUSE_ADMISSIONS').exists():reason='admission_hold'
    elif total>=capacity['authorized_max']:reason='shared_capacity'
    elif memory<capacity['admission_memory_reserve_bytes']:reason='memory_reserve'
    elif shutil.disk_usage(ROOT).free<capacity['disk_admission_reserve_bytes']:reason='disk_reserve'
    if pending and reason is None:
     u=pending[0];root=Path(u['root']);task=u['task']
     with (root/'jobs'/(task+'.log')).open('x') as log:
      child=subprocess.Popen([sys.executable,'-B',str(root/'job.py'),task],cwd=root,stdout=log,stderr=log,start_new_session=True,env={**os.environ,'PC_TASK':task,'PYTHONDONTWRITEBYTECODE':'1'})
     rec={**identity(child.pid),'task':task,'kind':u['kind'],'admitted_at':time.time()};save(root/'jobs'/(task+'.json'),rec);active[key(u)]=rec;children[key(u)]=child
    reservation=capacity.get('measurement_slot_reservation')
    admitted=all((Path(u['root'])/'jobs'/(u['task']+'.json')).exists() for u in units)
    if admitted and reservation and reservation['owner']==str(ROOT):
     capacity['max_concurrent_attempts']=reservation['base_target'];capacity.pop('measurement_slot_reservation');capacity.update(at=time.time(),reason='All three Luna5.6 completion jobs admitted under shared24; ordinary admissions restored. Existing allocations unchanged.')
     save(SHARED/'capacity.json',capacity)
     with (SHARED/'capacity-history.jsonl').open('a') as h:h.write(json.dumps(capacity)+'\n')
   report(units,active,capacity,reason)
   if not pending and not active and not json.loads((ROOT/'STATUS.json').read_text())['audit_pending']:save(ROOT/'terminal.json',{'at':time.time(),'all_jobs_terminal':True});return
   time.sleep(3)
if __name__=='__main__':main()
