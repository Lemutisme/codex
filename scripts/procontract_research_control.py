#!/usr/bin/env python3
"""Local owner control for /rsi. Research workflow remains supplied context."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import socket
import socketserver
import subprocess
import sys
import time
import uuid


SCHEMA='procontract-research-control-v1'
OPERATIONS={'start','resume','status','cancel','input'}


def profile(path):
    path=Path(path).expanduser().resolve(strict=True)
    raw=path.read_bytes();body=json.loads(raw)
    if body.get('schema')!=SCHEMA:raise ValueError('unknown research control configuration')
    root=Path(body['root']).expanduser()
    if not root.is_absolute():raise ValueError('research runtime root must be absolute')
    return path,root.resolve(),body['runtime'],hashlib.sha256(raw).hexdigest()


def endpoint(path):
    identity=hashlib.sha256((str(os.getuid())+':'+str(Path(path).resolve())).encode()).hexdigest()[:20]
    directory=Path('/tmp')/('pc-rsi-'+identity)
    if directory.is_symlink():raise ValueError('redirected research control directory')
    directory.mkdir(mode=0o700,exist_ok=True)
    if directory.stat().st_uid!=os.getuid():raise ValueError('research control directory has another owner')
    directory.chmod(0o700)
    return directory/'s'


def prepare(path):
    from procontract_research_runtime import ResearchRuntime
    path,root,config,_=profile(path)
    store=Path(config['package'])/'bin/pro-contract-store'
    os.environ['PRO_CONTRACT_STORE_BIN']=str(store)
    return ResearchRuntime.create(root,config)


def invoke(path,operation,request=None,*,request_id=None,thread_id=None,timeout=10):
    envelope={'schema':1,'request_id':request_id or str(uuid.uuid4()),'operation':operation,
        'request':request,'thread_id':thread_id}
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
        client.settimeout(timeout);client.connect(str(path))
        client.sendall((json.dumps(envelope)+'\n').encode())
        with client.makefile('rb') as stream:raw=stream.readline((1<<20)+1)
    if len(raw)>1<<20 or not raw.endswith(b'\n'):raise ValueError('incomplete or oversized control response')
    response=json.loads(raw)
    if response.get('error'):raise RuntimeError(response['error'])
    return response['result']


class ControlServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads=True

    def __init__(self,path,runtime,profile_sha256):
        self.runtime=runtime;self.profile_sha256=profile_sha256
        super().__init__(str(path),ControlHandler)
        Path(path).chmod(0o600)

    def control(self,message):
        if set(message)-{'schema','request_id','operation','request','thread_id'}:raise ValueError('unknown control field')
        if type(message.get('schema')) is not int or message['schema']!=1:raise ValueError('unknown control request')
        operation=message.get('operation');identity=message.get('request_id')
        if operation not in OPERATIONS or not isinstance(identity,str) or not identity:raise ValueError('control needs an operation and request identity')
        request=message.get('request');thread=message.get('thread_id')
        if request is not None and not isinstance(request,str):raise ValueError('research request must be text')
        if thread is not None and not isinstance(thread,str):raise ValueError('thread identity must be text')
        if operation in ('start','input') and not (request and request.strip()):raise ValueError('research goal or input is empty')
        if operation not in ('start','input') and request is not None:raise ValueError('control operation does not accept a new goal')
        result=self.runtime.control(operation,identity,request,thread)
        return {**result,'profile_sha256':self.profile_sha256}


class ControlHandler(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(10)
        try:
            raw=self.rfile.readline((1<<20)+1)
            if len(raw)>1<<20 or not raw.endswith(b'\n'):raise ValueError('incomplete or oversized control request')
            response={'result':self.server.control(json.loads(raw))}
        except Exception as error:response={'error':str(error)}
        try:self.wfile.write((json.dumps(response)+'\n').encode())
        except (BrokenPipeError,ConnectionResetError):pass  # The retained request may already have been admitted.


def serve(path):
    from procontract_research_runtime import ResearchRuntime
    from procontract_operations import atomic,process_identity
    path,root,config,identity=profile(path);socket_path=endpoint(path)
    os.environ['PRO_CONTRACT_STORE_BIN']=str(Path(config['package'])/'bin/pro-contract-store')
    runtime=ResearchRuntime(root)
    with socket_path.with_name('server.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if socket_path.is_symlink():raise ValueError('redirected research control socket')
        socket_path.unlink(missing_ok=True)
        with ControlServer(socket_path,runtime,identity) as server:
            atomic(root/'control-process.json',{'process':process_identity(os.getpid()),'socket':str(socket_path),'profile_sha256':identity})
            try:server.serve_forever()
            finally:socket_path.unlink(missing_ok=True)


def ensure(path,*,provision=True):
    """Ensure the owner endpoint only. Starting this service does not start a model."""
    from procontract_operations import atomic,process_identity
    path,root,_,identity=profile(path);socket_path=endpoint(path)
    with socket_path.with_name('launch.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        try:current=invoke(socket_path,'status',timeout=2)
        except (ConnectionError,FileNotFoundError,socket.timeout):current=None
        if current is not None:
            if current.get('profile_sha256')!=identity:raise ValueError('control profile changed; select a separate admitted configuration')
            return socket_path
        if provision:prepare(path)
        root.mkdir(parents=True,exist_ok=True)
        with (root/'control.log').open('ab') as log:
            process=subprocess.Popen([sys.executable,'-B',str(Path(__file__).resolve()),'serve','--config',str(path)],
                stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,start_new_session=True)
        atomic(root/'control-launch.json',{'process':process_identity(process.pid),'profile_sha256':identity})
        end=time.monotonic()+10
        while time.monotonic()<end:
            if process.poll() is not None:raise RuntimeError('research control exited; inspect '+str(root/'control.log'))
            try:
                result=invoke(socket_path,'status',timeout=1)
                if result.get('profile_sha256')!=identity:raise ValueError('research control identity differs')
                return socket_path
            except (ConnectionError,FileNotFoundError,socket.timeout):time.sleep(.05)
        raise RuntimeError('research control startup is unconfirmed; inspect retained launch before starting another service')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['prepare','serve','ensure',*sorted(OPERATIONS)])
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--request',help='research goal or fresh feedback')
    parser.add_argument('--request-id',help='reuse this identity only for the same request')
    parser.add_argument('--thread-id')
    args=parser.parse_args()
    if args.operation=='prepare':prepare(args.config);result={'state':'prepared','model_started':False}
    elif args.operation=='serve':serve(args.config);return
    elif args.operation=='ensure':result={'socket':str(ensure(args.config)),'model_started':False}
    else:
        socket_path=ensure(args.config)
        result=invoke(socket_path,args.operation,args.request,request_id=args.request_id,thread_id=args.thread_id)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
