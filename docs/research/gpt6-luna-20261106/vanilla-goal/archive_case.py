"""Losslessly archive only this study's stopped run after grading."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys,time
ROOT=Path(__file__).resolve().parent
def sha(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def main(task):
 run=ROOT/'runs'/task
 result=json.loads((run/'RESULT.json').read_text())
 assert result['cleanup']['remaining']==[]
 native=json.loads((run/'runtime-result.json').read_text())
 assert native['shutdown']['status']=='exited'
 if (run/'retention.json').exists():return
 names=[n for n in ('codex-home','home','workspace','rpc.jsonl','stderr.log') if (run/n).exists()]
 archive=run/'retained-work.tar.zst';partial=run/'retained-work.tar.zst.partial'
 if archive.exists():raise RuntimeError('unrecorded archive: inspect before changing originals')
 before=sum(p.stat().st_size for n in names for p in ([run/n] if (run/n).is_file() else (run/n).rglob('*')) if p.is_file() and not p.is_symlink())
 subprocess.run(['tar','-I','zstd -T2 -3','-cf',str(partial),'-C',str(run),*names],check=True,capture_output=True,timeout=1800)
 subprocess.run(['tar','-I','zstd -T2','-df',str(partial),'-C',str(run)],check=True,capture_output=True,timeout=1800)
 partial.replace(archive)
 record={'schema':1,'at':time.time(),'archive':str(archive),'sha256':sha(archive),'bytes':archive.stat().st_size,'original_regular_bytes':before,'members':names,'verification':'GNU tar compare against stopped original files before removal','scope':'lossless original run data; final submission and evaluation remain separately available'}
 (run/'retention.json').write_text(json.dumps(record,indent=2)+'\n')
 for n in names:
  p=run/n
  if p.is_dir() and not p.is_symlink():shutil.rmtree(p)
  else:p.unlink()
 print(json.dumps({'task':task,'archived_bytes':record['bytes'],'original_bytes':before}))
if __name__=='__main__':main(sys.argv[1])
