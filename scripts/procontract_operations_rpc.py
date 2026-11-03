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


def operation_descriptions(host, controller, operations):
    """Host-only argument discovery, filtered to the actual offered surface.

    Keep non-stdlib imports lazy: this module is also the standalone actor client.
    These descriptions expose call contracts, not extra authority or workflow.
    """
    import inspect
    offered = set(operations)
    targets = {name: getattr(host, name) for name in
               ('get', 'read', 'source_read', 'knowledge', 'incumbent') if name in offered}
    if 'search' in offered:
        from procontract_evidence import Evidence
        targets['search'] = Evidence(host).search
    if controller is not None:
        if 'describe' in offered:targets['describe'] = controller.describe
        if 'work_output' in offered:targets['work_output'] = controller.runtime.work_output
    descriptions = {}
    for name, target in targets.items():
        required, optional = [], {}
        for parameter in inspect.signature(target).parameters.values():
            if parameter.kind in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD):continue
            if parameter.default is inspect.Parameter.empty:required.append(parameter.name)
            else:optional[parameter.name] = {'default': parameter.default}
        descriptions[name] = {'required': required, 'optional': optional}
    fixed = {
        'receive': {'required': [], 'optional': {'limit': {'default': 100}}},
        'work_status': {'required': [], 'optional': {'identity': {'on_omission': 'page the index; explicit null is not a choice identity'}, 'after': {'default': 0}, 'limit': {'default': 100}}},
        'work': {'required': ['identity', 'delivery', 'work'], 'optional': {}},
        'select': {'required': ['identity', 'delivery'], 'optional': {'work': {'default': None}, 'wait': {'default': None}, 'call': {'default': None}}},
        'cancel_work': {'required': ['identity'], 'optional': {}},
        'register': {'required': ['parent', 'files'], 'optional': {'definition_fields': {'default': {}}}},
    }
    descriptions.update({name: value for name, value in fixed.items() if name in offered})
    notes = {
        'get': 'identity is an immutable object ID. Optional kind requires that object kind; this is not a path reader.',
        'read': 'after is an event-index cursor. kinds filters kinds; limit is 1..1000. Reading does not acknowledge inputs.',
        'source_read': 'identity is a retained SOURCE OBJECT ID, not a path, filename or content hash. offset is a nonnegative byte offset; length is 1..65536. Returned offset/end/eof and slice digest describe exact bytes.',
        'search': 'text is a literal metadata query (not query=). It does not search source bodies. after/snapshot page the query, not input acknowledgement; limit is 1..100.',
        'knowledge': 'sources/counterevidence contain existing object IDs; supersedes is a prior knowledge ID. interpretation, uncertainty and applicability are actor-authored context, not adoption or certified truth.',
        'incumbent': 'No arguments. Returns the exact retained research selection; it grants no new authority.',
        'describe': 'No arguments. Only names in operations are offered to this invocation.',
        'receive': 'limit is 1..1000. Returns an invocation-bound delivery_token and actual delivered page; does not acknowledge.',
        'work_status': 'Supply identity for one selected work item; otherwise page its index using after/limit.',
        'work_output': 'identity is a selected CHOICE ID. Omit output for the producer manifest; use one listed output key for bytes. offset is nonnegative; length is 1..65536. A producer output is not a consumer-project path.',
        'work': 'Asynchronous work specification: capability, native prompt when applicable; optional purpose, seconds, version, sources (new input name -> source object ID). No host paths or arbitrary commands.',
        'select': 'Choose exactly one work, call or wait. call={work,return_to} retains a leaf and responsible return atomically. wait={condition,work? or call?}; omit both for inert waiting. No quality-based stage is selected by the host.',
        'cancel_work': 'identity is a choice within this invocation\'s admitted descendant capability scope.',
        'register': 'parent is a version ID; files maps authorized file names to complete UTF-8 content. This registers a candidate, not a deployment. definition_fields cannot exceed the original authority.',
    }
    for name, value in descriptions.items():value['description'] = notes[name]
    return descriptions


class Broker(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True

    def __init__(self, path, host, responsibility, measurements=None, operations=None,
                 controller=None):
        self.host, self.responsibility = host, responsibility
        self.measurements = tuple(host.authority.measurements if measurements is None else measurements)
        self.operations = None if operations is None else frozenset(operations)
        self.controller = controller
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        super().__init__(str(path), Handler)

    def invoke(self, operation, arguments):
        if self.operations is not None and operation not in self.operations:
            raise ValueError('operation not offered to this invocation')
        host = self.host
        inbox = host.inbox(self.responsibility)
        if inbox is None or inbox['cancelled']:
            raise ValueError('responsibility is cancelled or unavailable')
        if self.controller is not None:
            self.controller.authorize(operation)
        if self.controller is not None and self.controller.handles(operation):
            result = self.controller.invoke(operation, arguments)
            if operation == 'describe':
                offered = self.operations if self.operations is not None else self.controller.offered_operations()
                result = {**result, 'operations': operation_descriptions(host, self.controller, offered)}
            return result
        if operation == 'read':return host.read(**arguments)
        if operation == 'receive':return host.receive(self.responsibility,**arguments)
        if operation == 'get':return host.get(**arguments)
        if operation == 'source_read':return host.source_read(**arguments)
        if operation == 'search':return host.search(**arguments)
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
