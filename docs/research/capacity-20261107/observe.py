"""Host and cgroup measurements; no execution or allocation mutation."""
from pathlib import Path
import json,os,shutil,subprocess,time,statistics
OUT=Path(__file__).resolve().parent
SHARED=Path('/data/ProContract/programbench-sol61-20261104')
CG=Path('/sys/fs/cgroup')
CLIENTS={'solver':['/data/ProContract/research/procontract-programbench-diagnostic-20261015/tools/bin/docker','--host','unix:///data/ProContract/programbench-full-procontract-20261025/docker.sock'],'grader':['/usr/bin/docker','--host','unix:///var/run/docker.sock']}
def read_kv(path):
 try:return {line.split()[0]:int(line.split()[1]) for line in path.read_text().splitlines()}
 except OSError:return {}
def cgroup(path):
 r={'path':str(path),'stat':read_kv(path/'memory.stat'),'events':read_kv(path/'memory.events')}
 for name in ['memory.current','memory.peak','memory.max','memory.swap.current','pids.current','pids.peak']:
  try:v=(path/name).read_text().strip();r[name]=int(v) if v.isdigit() else v
  except OSError:pass
 if 'memory.current' in r:r['working_set_bytes']=max(0,r['memory.current']-r['stat'].get('inactive_file',0))
 return r
def alive(meta):
 try:
  s=Path(f'/proc/{meta["pid"]}/stat').read_text().rsplit(')',1)[1].split();return s[0]!='Z' and s[19]==meta['start_ticks']
 except (OSError,KeyError):return False
def snapshot():
 m={k:int(v.strip().split()[0])*1024 for k,v in (line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines()) if k in ['MemTotal','MemFree','MemAvailable','Cached','SReclaimable','AnonPages','Shmem','SwapTotal','SwapFree']}
 capacity=json.loads((SHARED/'capacity.json').read_text());jobs=[]
 for root in [SHARED,*map(Path,capacity['external_job_roots'])]:
  for p in (root/'jobs').glob('*.json'):
   entry=json.loads(p.read_text())
   if alive(entry):jobs.append({'root':str(root),**entry})
 containers=[]
 for daemon,client in CLIENTS.items():
  ids=subprocess.check_output(client+['ps','-q'],text=True,timeout=20).split()
  if not ids:continue
  for c in json.loads(subprocess.check_output(client+['inspect',*ids],timeout=25)):
   pid=c['State']['Pid']
   try:path=Path(f'/proc/{pid}/cgroup').read_text().strip().split('::',1)[1]
   except (OSError,IndexError):continue
   containers.append({'daemon':daemon,'id':c['Id'],'pid':pid,'labels':c['Config']['Labels'],'limit_bytes':c['HostConfig']['Memory'],'cpu_limit':c['HostConfig']['NanoCpus']/1e9,'cgroup':cgroup(CG/path.lstrip('/'))})
 services=[]
 for unit in ['procontract-programbench-gpt6-luna-20261106.service','procontract-programbench-sol61-retries-20261106.service','procontract-programbench-score-audit-20261106.service']:
  services.append({'unit':unit,'cgroup':cgroup(CG/'system.slice'/unit)})
 owned=[x for x in containers if any(k.startswith('pc.') for k in x['labels'])]
 ws=sum(x['cgroup'].get('working_set_bytes',0) for x in owned)+sum(x['cgroup'].get('working_set_bytes',0) for x in services)
 pressure={k:Path('/proc/pressure/'+k).read_text() for k in ['memory','cpu','io']}
 cpu=[int(x) for x in Path('/proc/stat').read_text().splitlines()[0].split()[1:]]
 return {'at':time.time(),'capacity':capacity,'host_memory':m,'cpu_count':os.cpu_count(),'cpu_affinity_count':len(os.sched_getaffinity(0)),'load':os.getloadavg(),'cpu_ticks':cpu,'pressure':pressure,'oom_kill_total':read_kv(Path('/proc/vmstat')).get('oom_kill'),'disk_free_bytes':shutil.disk_usage(SHARED).free,'active_jobs':jobs,'containers':containers,'services':services,'owned_working_set_bytes':ws,'scope':'Current and lifetime peak cgroup charges include cache. Working set subtracts inactive_file; sum of separate lifetime peaks is not a concurrent peak. Other host workloads are observed, not controlled.'}
def record():
 value=snapshot()
 with (OUT/'observations.jsonl').open('a') as f:f.write(json.dumps(value)+'\n')
 p=OUT/'latest.json';tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(value,indent=2)+'\n');tmp.replace(p)
 print(json.dumps({'at':value['at'],'target':value['capacity']['max_concurrent_attempts'],'active':len(value['active_jobs']),'available_gib':round(value['host_memory']['MemAvailable']/1024**3,2),'owned_working_set_gib':round(value['owned_working_set_bytes']/1024**3,2),'load':value['load'],'oom_kill_total':value['oom_kill_total']}),flush=True)
 return value
if __name__=='__main__':
 import sys
 if '--watch' in sys.argv:
  while True:
   try:record()
   except Exception as e:print(json.dumps({'at':time.time(),'error':str(e)}),flush=True)
   time.sleep(30)
 else:record()
