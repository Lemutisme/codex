"""One durable case slot: prepare, one solve+grade, then lossless retention."""
from pathlib import Path
import json,os,signal,subprocess,sys,time
ROOT=Path(__file__).resolve().parent
def save(p,d):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(d,indent=2)+'\n');tmp.replace(p)
def cleanup(task):
 run=ROOT/'runs'/task;server=run/'server-process.json'
 if server.exists():
  meta=json.loads(server.read_text());pid=meta['pid'];proc=Path(f'/proc/{pid}')
  try:owned=(proc/'cwd').resolve()==(run/'workspace').resolve() and str((ROOT/'package/bin/codex').resolve()).encode() in (proc/'cmdline').read_bytes()
  except OSError:owned=False
  if owned:
   os.kill(pid,signal.SIGTERM)
   for _ in range(50):
    if not proc.exists():break
    time.sleep(.1)
   if proc.exists():
    try:os.kill(pid,signal.SIGKILL)
    except ProcessLookupError:pass
 from run_case import cleanup as stop_containers, cleanup_grader as stop_grader
 return stop_containers(task)['removed'] + stop_grader(task)['removed']

def main(task):
 plan=json.loads((ROOT/'plan.json').read_text());assert task in plan['tasks']
 run=ROOT/'runs'/task;run.mkdir(exist_ok=True)
 from supervise import identity
 with (run/'job-launch.json').open('x') as f:json.dump({'task':task,**identity(os.getpid()),'at':time.time()},f)
 stage='preparing';result={'task':task,'started_at':time.time()}
 try:
  env={**os.environ,'PC_TASK':task,'PYTHONDONTWRITEBYTECODE':'1'}
  if not (run/'prepared.json').exists():
   with (run/'preparation.log').open('a') as log:subprocess.run([sys.executable,'-B',str(ROOT/'prepare_case.py'),task],env=env,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=3600)
  stage='solver_and_grader'
  with (run/'driver.log').open('x') as log:subprocess.run([sys.executable,'-B',str(ROOT/'run_case.py'),task],env=env,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=plan['wall_time_seconds']+plan['external_grading_seconds']+300)
  if not (run/'RESULT.json').exists():raise RuntimeError('driver ended without a result')
  stage='archiving'
  with (run/'archive.log').open('x') as log:
   archived=subprocess.run([sys.executable,'-B',str(ROOT/'archive_case.py'),task],env=env,stdout=log,stderr=subprocess.STDOUT,timeout=3700)
  result['archive_exit']=archived.returncode
  stage='complete'
 except BaseException as error:
  result['error']={'type':type(error).__name__,'message':str(error)}
  try:result['cleanup_removed']=cleanup(task)
  except Exception as e:result['cleanup_error']=str(e)
 finally:
  result.update(stage=stage,finished_at=time.time());save(run/'JOB_RESULT.json',result)
 if stage!='complete':raise SystemExit(1)
if __name__=='__main__':main(sys.argv[1])
