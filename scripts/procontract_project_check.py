#!/usr/bin/env python3
"""Run a provisioner-declared project check in an offline, scoped container.

The command and control inputs are host-bound. This tool observes execution; it
does not select a validation method, infer whole-task quality or adopt a version.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from procontract_operations import atomic,sha


def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def container_name(assignment):
    # Names live in the daemon's namespace; local operation names may repeat in
    # other research stores. The retained assignment is the actual identity.
    binding={key:assignment[key] for key in ('request','admitted_at','deadline','owner_epoch','implementation','authority','measurement') if key in assignment}
    return 'pc-project-check-'+sha(binding)[:24]


def shutdown(name):
    try:
        removal=subprocess.run(['docker','rm','-f',name],capture_output=True,text=True,timeout=15)
        live=subprocess.check_output(['docker','ps','-q','--filter','name=^/'+name+'$'],text=True,timeout=10).split()
        return {'confirmed':not live,'container':name,'remove_exit':removal.returncode,'remaining':live,
                'remove_error':removal.stderr[-2000:]}
    except Exception as error:return {'confirmed':False,'container':name,'error':str(error)}


def run(path):
    path=Path(path);assignment=json.loads(path.read_text());config=assignment['runtime_inputs']
    directory=path.parent;project=Path(assignment['runtime_project']['path']);name=container_name(assignment)
    if any(c in str(project)+str(directory) for c in (',','\n','\0')):raise ValueError('check paths are not representable as bind mounts')
    command=config['command']
    if not isinstance(command,list) or not command or not all(isinstance(v,str) for v in command):raise ValueError('check command must be a declared argv')
    for source,expected in config.get('source_hashes',{}).items():
        if digest(source)!=expected:raise ValueError('declared check input changed')
    work=directory/'check-work';work.mkdir(exist_ok=True)
    arguments=['docker','run','--rm','--name',name,'--network','none','--cap-drop','ALL',
        '--security-opt','no-new-privileges','--user',f'{os.getuid()}:{os.getgid()}',
        '--mount',f'type=bind,src={project},dst=/project,readonly',
        '--mount',f'type=bind,src={work},dst=/work','--workdir','/work']
    for mount in config.get('mounts',[]):
        source=Path(mount['source']).resolve(strict=True);target=mount['target']
        if not target.startswith('/') or target in ('/project','/work') or any(c in str(source)+target for c in (',','\n','\0')):
            raise ValueError('invalid declared check mount')
        arguments+=['--mount',f'type=bind,src={source},dst={target},readonly']
    for key,value in config.get('environment',{}).items():arguments+=['--env',str(key)+'='+str(value)]
    arguments += [config['image'],*command]
    allocated=assignment['request']['inputs'].get('seconds')
    ends=[v for v in (assignment.get('deadline'),
        assignment['admitted_at']+allocated if allocated is not None else None) if v is not None]
    timeout=max(0,min(ends)-time.time()) if ends else None
    atomic(directory/'project-check-admission.json',{'assignment':sha(assignment),'container':name,
        'command':command,'image':config['image'],'started_at':time.time(),'deadline':min(ends) if ends else None})
    started=time.time();outcome={'admissible':False,'validity':'unavailable','command':command,'command_exit':None}
    try:
        if timeout==0:outcome['execution']='allocation_exhausted'
        else:
            with (directory/'check.stdout').open('wb') as stdout,(directory/'check.stderr').open('wb') as stderr:
                result=subprocess.run(arguments,stdout=stdout,stderr=stderr,timeout=timeout,check=False)
            outcome.update(execution='completed',validity='valid',command_exit=result.returncode)
    except subprocess.TimeoutExpired:outcome['execution']='timed_out'
    except Exception as error:outcome.update(execution='failed',failure=str(error))
    finally:
        cleanup=shutdown(name);outcome['shutdown']=cleanup;outcome['effects_resolved']=cleanup['confirmed']
    streams={}
    for stream in ('stdout','stderr'):
        file=directory/('check.'+stream)
        if file.exists():
            with file.open('rb') as source:
                source.seek(max(0,file.stat().st_size-12000));tail=source.read().decode(errors='replace')
            streams[stream]={'sha256':digest(file),'bytes':file.stat().st_size,'tail':tail,'tail_complete':file.stat().st_size<=12000}
    outcome.update(elapsed_seconds=time.time()-started,streams=streams,
        scope='Declared check execution on the supplied project; public/within-reach checks do not certify deployment or general task quality')
    atomic(directory/'result.json',outcome)


def reconcile(path):
    path=Path(path);assignment=json.loads(path.read_text());name=container_name(assignment)
    result=shutdown(name)
    print(json.dumps({'shutdown_confirmed':result['confirmed'],'adapter':'project-check-container','environment':result}))


if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='reconcile':reconcile(sys.argv[2])
    elif len(sys.argv)==2:run(sys.argv[1])
    else:raise SystemExit('usage: procontract_project_check.py [reconcile] ASSIGNMENT_JSON')
