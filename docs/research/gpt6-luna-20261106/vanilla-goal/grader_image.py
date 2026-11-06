"""Retain the pinned solver image in the qualified grader daemon without changing bytes."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time

ROOT = Path(__file__).resolve().parent
PRIVATE = ['/data/ProContract/research/procontract-programbench-diagnostic-20261015/tools/bin/docker',
           '--host','unix:///data/ProContract/programbench-full-procontract-20261025/docker.sock']
GRADER = ['/usr/bin/docker','--host','unix:///var/run/docker.sock']
CONTENT = ['/usr/bin/ctr','--address','/run/containerd/containerd.sock','--namespace','moby','content','get']


def import_image(task, config_id):
    case = ROOT/'inputs/cases'/task
    alias = 'pc-luna6-grader-20261106/' + task.replace('__','_1776_') + ':input'
    saved = case/'grader-image.json'
    original = json.loads(subprocess.check_output(PRIVATE+['image','inspect',config_id],text=True))[0]
    inspected = subprocess.run(GRADER+['image','inspect',alias],capture_output=True,text=True)
    if inspected.returncode:
        with (case/'image-export.log').open('ab') as error, (case/'image-import.log').open('ab') as output:
            before = output.tell()
            producer = subprocess.Popen(PRIVATE+['image','save',config_id],stdout=subprocess.PIPE,stderr=error)
            consumer = subprocess.Popen(GRADER+['image','load'],stdin=producer.stdout,stdout=output,stderr=output)
            producer.stdout.close()
            try:
                load_code=consumer.wait(timeout=1500);save_code=producer.wait(timeout=60)
            except BaseException:
                for process in [consumer,producer]:
                    if process.poll() is None:process.terminate()
                raise
            if load_code or save_code:raise RuntimeError('pinned image transfer failed')
        text=(case/'image-import.log').read_bytes()[before:].decode(errors='replace')
        matches=re.findall(r'Loaded image ID: (sha256:[0-9a-f]{64})',text)
        if len(matches)!=1:raise RuntimeError('image import did not identify one retained image')
        image=matches[0]
    else:
        image=json.loads(inspected.stdout)[0]['Id']
    actual=json.loads(subprocess.check_output(GRADER+['image','inspect',image],text=True))[0]
    raw=subprocess.check_output(CONTENT+[image]);manifest=json.loads(raw)
    if hashlib.sha256(raw).hexdigest()!=image.removeprefix('sha256:') or manifest['config']['digest']!=config_id:
        raise RuntimeError('grader import does not reference the pinned config')
    raw_config=subprocess.check_output(CONTENT+[config_id])
    if hashlib.sha256(raw_config).hexdigest()!=config_id.removeprefix('sha256:'):
        raise RuntimeError('grader image config bytes changed')
    if original['RootFS']!=actual['RootFS'] or actual['Architecture']!='amd64' or actual['Os']!='linux':
        raise RuntimeError('grader filesystem or architecture differs')
    left=dict(original['Config']);right=dict(actual['Config'])
    left['User']=left.get('User') or '';right['User']=right.get('User') or ''
    if not all(left.get(k)==right.get(k) for k in left.keys()|right.keys()):
        raise RuntimeError('grader runtime config differs')
    if saved.exists():
        prior=json.loads(saved.read_text())
        if prior['config_id']!=config_id or prior['grader_manifest_id']!=image:
            raise RuntimeError('retained grader image binding changed')
    else:
        saved.write_text(json.dumps({'at':time.time(),'task':task,'config_id':config_id,
            'grader_manifest_id':image,'alias':alias,'config_bytes_verified':True,'rootfs_identical':True},indent=2)+'\n')
    subprocess.run(GRADER+['tag',image,alias],check=True)
    return image,alias
