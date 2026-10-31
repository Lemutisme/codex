"""A local capability socket for one admitted responsibility.

Mount only the socket into the actor's offline environment. The database, sealed
measurements and original authority stay outside it. This is a transport adapter;
it neither chooses operations nor launches a research workflow.
"""
import json
from pathlib import Path
import socket
import socketserver
import threading


class Broker(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True

    def __init__(self, path, host, responsibility, measurements=None):
        self.host, self.responsibility = host, responsibility
        self.measurements = tuple(measurements or host.authority.measurements)
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        super().__init__(str(path), Handler)

    def invoke(self, operation, arguments):
        host = self.host
        inbox = host.inbox(self.responsibility)
        if inbox is None or inbox['cancelled']:
            raise ValueError('responsibility is cancelled or unavailable')
        if operation == 'read':return host.read(**arguments)
        if operation == 'get':return host.get(**arguments)
        if operation == 'incumbent':return host.incumbent()
        if operation == 'inbox':return inbox
        if operation == 'knowledge':return host.knowledge(**arguments)
        if operation == 'register':
            parent=arguments['parent']
            definition=host.get(parent,'version')['definition']
            definition['files'].update(arguments['files'])
            for field,value in arguments.get('definition_fields',{}).items():
                if field not in ('build','model','resolver','tools'):raise ValueError('unknown version definition field')
                definition[field]=value
            return host.register(definition,parent)
        if operation == 'submit':
            if 'responsibility' in arguments:raise ValueError('actor identity is host-bound')
            if arguments['measurement'] not in self.measurements:raise ValueError('measurement not offered to this actor')
            result=host.submit(responsibility=self.responsibility,**arguments)
            host.dispatch(arguments['identity'])
            return result
        if operation in ('inspect','reconcile','cancel'):
            if host.inspect(arguments['identity'])['request']['request']['responsibility'] != self.responsibility:
                raise ValueError('operation belongs to another responsibility')
            return getattr(host,operation)(**arguments)
        if operation == 'adopt':
            if 'owner' in arguments:raise ValueError('decision authority is host-bound')
            return host.adopt(**arguments,owner=(self.responsibility,inbox['epoch']))
        if operation == 'wait':return host.wait(self.responsibility,**arguments)
        raise ValueError('operation is not an offered capability')


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(30)
        raw=self.rfile.readline((2<<20)+1)
        try:
            if len(raw)>2<<20:raise ValueError('request exceeds transport bound')
            request=json.loads(raw)
            result={'result':self.server.invoke(request['operation'],request.get('arguments',{}))}
        except Exception as error:
            result={'error':str(error)}
        self.wfile.write((json.dumps(result)+'\n').encode())


def call(path, operation, arguments):
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
        client.connect(str(path))
        client.sendall((json.dumps({'operation':operation,'arguments':arguments})+'\n').encode())
        with client.makefile('r') as stream:
            response=json.loads(stream.readline())
    if 'error' in response:raise RuntimeError(response['error'])
    return response['result']


if __name__=='__main__':
    import sys
    print(json.dumps(call(sys.argv[1],sys.argv[2],json.loads(sys.argv[3]) if len(sys.argv)>3 else {}),indent=2))
