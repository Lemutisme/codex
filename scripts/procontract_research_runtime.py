#!/usr/bin/env python3
"""Execute retained agent/user choices for a continuing research responsibility.

This supervisor owns admission, transport, lifetime and evidence. Research method,
roles, experiments, continuation and waiting are supplied choices, not Python stages.
"""
import argparse
import contextlib
import copy
import fcntl
import json
import hashlib
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import threading
import time

import procontract_operations as ops
from procontract_evidence_bundle import ingest, import_objects
from procontract_native_operation import build_identity, native, confirm_environment_shutdown, collect_outputs
from procodex_inputs import declarations

REPO = Path(__file__).resolve().parent.parent
SOURCE = 'research-runtime-input'
COMMON = ('describe', 'read', 'get', 'source_read', 'search', 'knowledge', 'incumbent', 'work_status')
CONTROL = ('receive', 'work', 'select', 'cancel_work', 'register')
RESERVED = {'client.py', 'runtime-context.json', 'intake.json'}


def seconds(value):
    if value is not None and (type(value) is not int or not 1 <= value <= (2**64-1)//1000):
        raise ValueError('native action allocation must be positive representable whole seconds')
    return value


def allocation(value):
    if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0):
        raise ValueError('action allocation must be positive and finite')
    return value


def file_digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream, 'sha256').hexdigest()


def relative(value):
    path = PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts or not path.parts or str(path) == '.':
        raise ValueError('expected a project-relative path')
    return path.as_posix()


def project_path(project, name):
    root = Path(project['path'])
    path = root/relative(name)
    if any(part.is_symlink() for part in (path, *path.parents)
           if part == root or part.is_relative_to(root)):
        raise ValueError('project path is redirected')
    return path


def pinned_copy(source, destination):
    source = Path(source).resolve(strict=True)
    before = file_digest(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open('rb') as incoming, destination.open('xb') as stream:
        shutil.copyfileobj(incoming, stream, 1 << 20); stream.flush(); os.fsync(stream.fileno())
    if file_digest(destination) != before or file_digest(source) != before:
        raise ValueError('input changed during provisioning')
    destination.chmod(0o400)
    return {'path': str(destination), 'sha256': before, 'origin': str(source)}


class ResearchRuntime:
    def __init__(self, root):
        self.root = Path(root).resolve()
        if not (self.root/'provisioned.json').exists():
            raise ValueError('research provisioning is incomplete; no execution admitted')
        self.config = json.loads((self.root/'runtime.json').read_text())
        expected = self.config.get('store_binary')
        if expected:
            current = os.environ.get('PRO_CONTRACT_STORE_BIN')
            if current and Path(current).resolve() != Path(expected).resolve():
                raise ValueError('process kernel binding differs from the protected runtime configuration')
            os.environ.setdefault('PRO_CONTRACT_STORE_BIN', expected)
        self.host = ops.Operations(self.root/'host')

    @classmethod
    def create(cls, root, config):
        """Protected provisioning. No model calls; repeat only the exact config."""
        root = Path(root).resolve()
        original = json.loads(ops.encoded(config))
        fingerprint = ops.sha(original)
        existing = root/'runtime.json'
        if existing.exists():
            retained = json.loads(existing.read_text())
            if retained['provisioning_sha256'] != fingerprint:
                raise ValueError('research configuration changed; explicit migration or a new root is required')
            if not (root/'provisioned.json').exists():
                raise ValueError('provisioning is incomplete; no execution admitted; preserve this root for explicit recovery')
            return cls(root)
        if original.get('schema') != 'procontract-research-runtime-v1':
            raise ValueError('unknown research runtime config')
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        cfg = copy.deepcopy(original)
        cfg['provisioning_sha256'] = fingerprint
        cfg['package'] = str(Path(cfg['package']).resolve(strict=True))
        cfg['store_binary'] = str(Path(cfg.get('store_binary', os.environ.get('PRO_CONTRACT_STORE_BIN', str(Path(cfg['package'])/'bin/pro-contract-store')))).resolve())
        os.environ.setdefault('PRO_CONTRACT_STORE_BIN', cfg['store_binary'])
        cfg['image'] = subprocess.check_output(
            ['docker', 'image', 'inspect', '--format', '{{.Id}}', cfg['image']], text=True).strip()
        cfg['inputs'] = {name: pinned_copy(path, root/'inputs'/name)
                         for name, path in declarations(cfg.get('inputs')).items()
                         if name not in RESERVED}
        if set(original.get('inputs', {})) & RESERVED:
            raise ValueError('input name is reserved by the runtime')
        cfg['inputs']['client.py'] = pinned_copy(
            REPO/'scripts/procontract_operations_rpc.py', root/'inputs/client.py')
        for name, project in cfg.get('projects', {}).items():
            if not re.fullmatch(r'[A-Za-z0-9_.-]+', name):raise ValueError('invalid project handle')
            path = Path(project['path']).resolve(strict=True)
            if not path.is_dir() or root.is_relative_to(path) or Path(__file__).resolve().is_relative_to(path) or Path(cfg['package']).is_relative_to(path):
                raise ValueError('project must not expose the protected host/runtime/package')
            project['path'] = str(path)
            project['writable'] = [relative(item) for item in project.get('writable', [])]
            project['excluded'] = [relative(item) for item in project.get('excluded', [])]
            for item in project['writable']:
                selected = project_path(project, item)
                if not selected.exists():raise ValueError('writable project paths must be provisioned first')
                files = selected.rglob('*') if selected.is_dir() else [selected]
                if any(p.is_file() and not p.is_symlink() and p.stat().st_nlink > 1 for p in files):
                    raise ValueError('writable project files must not share host hardlinks')
        capabilities = cfg['capabilities']
        for name, cap in capabilities.items():
            if not re.fullmatch(r'[A-Za-z0-9_.-]+', name):raise ValueError('invalid capability name')
            if cap['kind'] not in ('native', 'measurement'):raise ValueError('unknown capability kind')
            if cap.get('project') not in (None, *cfg.get('projects', {})):
                raise ValueError('capability names an unavailable project')
            if set(cap.get('select', []))-capabilities.keys():raise ValueError('unknown descendant capability')
            if cap['kind'] == 'native':
                seconds(cap.get('max_seconds'))
                if cap.get('assessment_project') and (not cap.get('project') or (cap.get('strategy_files') and not cap.get('mount_project', False))):
                    raise ValueError('project assessment requires the capability to mount its project')
                if set(cap.get('inputs', []))-cfg['inputs'].keys():raise ValueError('unknown named native input')
                for policy, path in cap.get('strategy_files', {}).items():
                    if policy not in {p.name for p in (REPO/'codex-rs/ext/pro-contract/policies').glob('*.md')}:
                        raise ValueError('strategy resolver names an unsupported policy key')
                    if not cap.get('project'):raise ValueError('strategy resolver requires a bound project')
                    project_path(cfg['projects'][cap['project']], path)
            else:
                measurement = cap['measurement']
                allocation(measurement.get('max_seconds'))
                cap['runner_sources'] = {arg: file_digest(arg) for arg in
                    [*measurement['argv'], *cap.get('reconcile_argv', [])] if Path(arg).is_file()}
        if cfg['initial']['capability'] not in capabilities or capabilities[cfg['initial']['capability']]['kind'] != 'native':
            raise ValueError('initial research capability must be an admitted native invocation')
        seconds(cfg['initial'].get('seconds'))
        cfg['task_policies'] = {p.name: p.read_text() for p in (REPO/'codex-rs/ext/pro-contract/policies').glob('*.md')}
        cfg['policies'] = copy.deepcopy(cfg['task_policies'])
        cfg['policies']['work_method.md'] = Path(cfg['strategy']).read_text()
        cfg['build'] = build_identity(Path(cfg['package']))
        ops.atomic(existing, cfg)
        measurements = {}
        for name, cap in capabilities.items():
            declared = cap.get('measurement', {})
            measurements['cap.'+name] = ops.Measurement(
                (sys.executable, str(Path(__file__).resolve()), 'measure', str(existing), name),
                ops.sha({'runtime': ops.sha(Path(__file__).read_bytes()), 'config': ops.sha(cfg),
                         'declared': declared.get('identity')}),
                declared.get('environment', cfg['image']),
                beyond_reach=declared.get('beyond_reach', False),
                max_seconds=declared.get('max_seconds'), external_effects=cap['kind'] == 'native' or declared.get('external_effects', False),
                effect_scope='project:'+ops.sha(cfg['projects'][cap['project']]['path']) if cap.get('project') else 'capability:'+name)
        authority = cfg['authority']
        editable = {'work_method.md'} | {name for cap in capabilities.values() for name in cap.get('strategy_files', {})}
        host = ops.Operations.create(root/'host', ops.Authority(
            authority['principal'], authority['source'], authority['scope'], tuple(sorted(editable)),
            tuple(measurements), True, authority.get('deadline'), authority.get('operation_limit')), measurements)
        with host.tx() as db:
            db.executescript('''
                CREATE TABLE rsi_state (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL);
                CREATE TABLE rsi_control (id TEXT PRIMARY KEY, request TEXT NOT NULL, response TEXT, effect TEXT);
                CREATE TABLE rsi_choices (id TEXT PRIMARY KEY, body TEXT NOT NULL, state TEXT NOT NULL,
                    operation TEXT, params TEXT, announcement TEXT, error TEXT);
                CREATE TABLE rsi_deliveries (token TEXT PRIMARY KEY, operation TEXT NOT NULL, body TEXT NOT NULL);
            ''')
            db.execute('INSERT INTO rsi_state VALUES(1,?)', (ops.encoded({'started': False, 'goal': None, 'generation': 0, 'versions': {}}),))
        host.subscribe('research', SOURCE, ['observation', 'claim'])
        definition = {'kind': 'research', 'files': cfg['policies'], 'build': {'snapshot': cfg['build']},
                      'model': cfg['model'], 'resolver': 'research-runtime-v1',
                      'tools': {'network': 'none', 'capabilities': list(capabilities)}}
        primary = host.register(definition); host.bootstrap(primary)
        versions = {'research': primary}
        for name, cap in capabilities.items():
            if cap.get('strategy_files'):
                task = copy.deepcopy(definition); task['kind'] = 'task'; task['files'] = cfg['task_policies']
                versions[name] = host.register(task)
        with host.tx() as db:
            state = json.loads(db.execute('SELECT body FROM rsi_state').fetchone()[0]); state['versions'] = versions
            db.execute('UPDATE rsi_state SET body=?', (ops.encoded(state),))
        imports = [ingest(host, json.loads(Path(path).read_text())) for path in cfg.get('bundles', [])]
        prior = [import_objects(host, json.loads(Path(path).read_text())) for path in cfg.get('prior_knowledge', [])]
        merged = {}
        for item in imports:
            for key, value in item['identities'].items():
                if key in merged and merged[key] != value:raise ValueError('evidence bundle keys collide')
                merged[key] = value
        ops.atomic(root/'inputs/intake.json', {'schema': 'procontract-runtime-intake-v1', 'imports': imports,
                                             'import': {'identities': merged}, 'prior_knowledge_roots': prior})
        ops.atomic(root/'provisioned.json', {'config_sha256': ops.sha(cfg), 'initial_version': primary,
                                           'intake_sha256': file_digest(root/'inputs/intake.json')})
        return cls(root)

    def state(self):
        with self.host.tx() as db:return json.loads(db.execute('SELECT body FROM rsi_state').fetchone()[0])

    @contextlib.contextmanager
    def control_lock(self):
        with (self.root/'control.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX); yield

    def _queue(self, identity, body):
        encoded = ops.encoded(body)
        with self.host.tx() as db:
            previous = db.execute('SELECT body FROM rsi_choices WHERE id=?', (identity,)).fetchone()
            if previous and previous[0] != encoded:raise ValueError('choice identity conflicts')
            db.execute("INSERT OR IGNORE INTO rsi_choices(id,body,state) VALUES(?,?,'queued')", (identity, encoded))
        return identity

    def _work(self, value, allowed=None, current_version=None):
        if set(value)-{'capability', 'prompt', 'purpose', 'version', 'seconds', 'sources'}:
            raise ValueError('work accepts capability handles and retained sources, not host paths or arbitrary parameters')
        cap_name = value['capability']; cap = self.config['capabilities'].get(cap_name)
        if cap is None or (allowed is not None and cap_name not in allowed):raise ValueError('capability is not offered')
        work = copy.deepcopy(value)
        (seconds if cap['kind'] == 'native' else allocation)(work.get('seconds'))
        if cap['kind'] == 'native' and not isinstance(work.get('prompt'), str):raise ValueError('native work needs a prompt')
        if cap.get('strategy_files') and 'version' in work:raise ValueError('project context is resolved by its admitted capability')
        if 'version' not in work:
            work['version'] = current_version or self.host.incumbent()['version']
        if work['version'] is None:raise ValueError('no authorized research context selected')
        version = self.host.get(work['version'], 'version')
        if version['definition']['kind'] != 'research':raise ValueError('caller-selected context must belong to research lineage')
        sources = work.get('sources', {})
        declarations(sources)
        if set(sources) & (RESERVED | set(self.config['inputs'])):raise ValueError('retained source input name collides')
        for source in sources.values():self.host.get(source, 'source')
        return work

    def _owner_work(self, request_id, reason):
        state = self.state(); initial = copy.deepcopy(self.config['initial'])
        initial['prompt'] = initial.get('prompt', '')+'\nOriginal user request:\n'+state['goal']+'\nOwner action: '+reason
        work = self._work(initial)
        inbox = self.host.inbox('research')
        return self._queue('owner.'+ops.sha(request_id)[:32], {
            'role': 'continuation', 'origin': {'owner_request': request_id}, 'work': work,
            'epoch': inbox['epoch'], 'generation': state['generation'], 'after_operation': None})

    def _owner_body(self, request_id, reason, state, inbox):
        initial = copy.deepcopy(self.config['initial'])
        initial['prompt'] = initial.get('prompt', '')+'\nOriginal user request:\n'+state['goal']+'\nOwner action: '+reason
        return 'owner.'+ops.sha(request_id)[:32], {
            'role': 'continuation', 'origin': {'owner_request': request_id}, 'work': self._work(initial),
            'epoch': inbox['epoch'], 'generation': state['generation'], 'after_operation': None}

    def _owner_observation(self, db, request_id, envelope, generation):
        body = {'subject': 'owner-request:'+request_id, 'sources': [],
                'conditions': {'thread_id': envelope['thread_id'], 'generation': generation},
                'outcome': envelope, 'costs': {}}
        identity = ops.sha({'schema': 1, 'kind': 'observation', 'body': body})
        fresh = db.execute("INSERT OR IGNORE INTO objects VALUES(?,'observation',?)", (identity, ops.encoded(body))).rowcount
        if fresh:self.host._event(db, 'observation', SOURCE, identity)
        return identity

    def control(self, operation, request_id, request=None, thread_id=None):
        if operation not in ('start', 'resume', 'status', 'cancel', 'input'):raise ValueError('unknown control operation')
        if not isinstance(request_id, str) or not request_id:raise ValueError('request_id is required')
        if request is not None and not isinstance(request, str):raise ValueError('request must be text or null')
        if not (self.root/'provisioned.json').exists():raise ValueError('research provisioning is incomplete')
        envelope = {'operation': operation, 'request': request, 'thread_id': thread_id}
        with self.control_lock():
            with self.host.tx() as db:
                prior = db.execute('SELECT * FROM rsi_control WHERE id=?', (request_id,)).fetchone()
                if prior and prior['request'] != ops.encoded(envelope):raise ValueError('control request_id conflicts')
                if prior and prior['response']:
                    response = json.loads(prior['response'])
                    if operation != 'status':self.ensure_supervisor()
                    return response
                db.execute('INSERT OR IGNORE INTO rsi_control VALUES(?,?,NULL,NULL)', (request_id, ops.encoded(envelope)))
            effect = json.loads(prior['effect']) if prior and prior['effect'] else None
            if effect is None:
                state = self.state(); inbox = self.host.inbox('research'); selected = None; publish = False
                if operation == 'start':
                    if state['started']:raise ValueError('research already started; use resume or input')
                    if not request or not request.strip():raise ValueError('start needs the explicit user request')
                    if state['goal'] is not None and (state['goal'] != request or state.get('start_request') != request_id):
                        raise ValueError('initial request is already bound')
                    state.update(goal=request, start_request=request_id)
                    with self.host.tx() as db:db.execute('UPDATE rsi_state SET body=?', (ops.encoded(state),))
                    self.host.issue('research', {'goal': request, 'scope': self.host.authority.scope,
                                                 'hard_deadline': self.host.authority.deadline})
                    selected = self._owner_body(request_id, 'explicit start', state, inbox)
                    state['started'] = True; publish = True
                elif operation in ('resume', 'input', 'cancel'):
                    if not state['started']:raise ValueError('research has not been started')
                    if operation == 'input':
                        if not request or not request.strip():raise ValueError('input needs text')
                        state['generation'] += 1; publish = True
                        selected = self._owner_body(request_id, 'explicit owner input:\n'+request, state, inbox)
                    elif operation == 'resume':
                        active = any(item['state'] in ('queued', 'admitting', 'running') for item in self.choices())
                        if inbox['cancelled'] or not active:
                            state['generation'] += 1; publish = True
                            selected = self._owner_body(request_id, 'explicit owner resume; inspect retained progress and choose next work', state, inbox)
                        elif request:
                            state['generation'] += 1; publish = True
                effect = {'choice': selected[0] if selected else None, 'cancel': operation == 'cancel'}
                with self.host.authority_lock(), self.host.tx() as db:
                    if operation == 'cancel':
                        effect['cancel_operations'] = [row[0] for row in db.execute(
                            'SELECT operation FROM rsi_choices WHERE operation IS NOT NULL')]
                        db.execute("UPDATE inbox SET cancelled=1,epoch=epoch+1 WHERE id='research' AND cancelled=0")
                        db.execute("UPDATE rsi_choices SET state='cancelled' WHERE state IN ('queued','waiting','admitting')")
                    elif operation == 'resume' and selected:
                        db.execute("UPDATE inbox SET cancelled=0,wake=NULL WHERE id='research'")
                        db.execute("UPDATE rsi_choices SET state='replaced' WHERE state='waiting'")
                    elif operation == 'input':
                        db.execute("UPDATE rsi_choices SET state='replaced' WHERE state='waiting'")
                        db.execute("UPDATE inbox SET wake=NULL WHERE id='research'")
                    db.execute('UPDATE rsi_state SET body=?', (ops.encoded(state),))
                    if publish:effect['observation'] = self._owner_observation(db, request_id, envelope, state['generation'])
                    if selected:
                        db.execute("INSERT OR IGNORE INTO rsi_choices(id,body,state) VALUES(?,?,'queued')", (selected[0], ops.encoded(selected[1])))
                    db.execute('UPDATE rsi_control SET effect=? WHERE id=?', (ops.encoded(effect), request_id))
            if effect['cancel']:
                for item in self.choices():
                    if item['operation'] in effect.get('cancel_operations', []):self._cancel(item)
            result = self.status()
            result.update(message={'start': 'Research started under the retained scope.', 'resume': 'Research resumed from retained progress and choices.',
                                   'input': 'Owner input retained and a research turn selected; older queued choices are fenced.',
                                   'cancel': 'Cancellation requested; retained work and original allocations remain.',
                                   'status': 'Current research execution state.'}[operation], request_id=request_id)
            if effect.get('choice'):result['selected_choice'] = effect['choice']
            with self.host.tx() as db:db.execute('UPDATE rsi_control SET response=? WHERE id=?', (ops.encoded(result), request_id))
        if operation != 'status':self.ensure_supervisor()
        return result

    def choices(self):
        with self.host.tx() as db:
            rows = list(db.execute('SELECT * FROM rsi_choices ORDER BY rowid'))
        return [{**dict(row), 'body': json.loads(row['body']),
                 'params': json.loads(row['params']) if row['params'] else None} for row in rows]

    def status(self):
        choices = self.choices(); inbox = self.host.inbox('research')
        state = self.state(); active = []; unresolved = []
        for choice in choices:
            if not choice['operation']:continue
            try:item = self.host.inspect(choice['operation'])
            except ValueError:continue
            if item['state'] in ('reserved', 'running', 'unknown'):active.append(choice['operation'])
            if item['state'] == 'unknown' or (item.get('outcome') and not item['outcome']['shutdown_confirmed']):unresolved.append(choice['operation'])
        return {'root': str(self.root), 'goal': state['goal'], 'state': 'prepared' if not state['started'] else 'cancelled' if inbox['cancelled'] else
                'running' if active else 'queued' if any(item['state'] in ('queued','admitting') for item in choices) else
                'waiting' if any(item['state'] == 'waiting' for item in choices) else 'needs_selection',
                'started': state['started'], 'active_operations': active, 'unresolved_operations': unresolved,
                'pending_cursor': inbox['pending'], 'acknowledged_cursor': inbox['cursor'],
                'owner_epoch': inbox['epoch'], 'generation': state['generation'],
                'choices': [{'id': item['id'], 'state': item['state'], 'operation': item['operation'], 'error': item['error']} for item in choices]}

    def ensure_supervisor(self):
        path = self.root/'supervisor.json'
        if path.exists() and ops.alive(json.loads(path.read_text()).get('process')):return
        with (self.root/'supervisor.log').open('ab') as log:
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), 'supervise', '--root', str(self.root)],
                                       stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
            threading.Thread(target=process.wait, daemon=True).start()

    def receive(self, operation, limit=100):
        with self.control_lock():
            view = self.host.receive('research', limit=limit)
            view['generation'] = self.state()['generation']
            token = ops.sha({'operation': operation, 'view': view})
            with self.host.tx() as db:
                db.execute('INSERT OR IGNORE INTO rsi_deliveries VALUES(?,?,?)', (token, operation, ops.encoded(view)))
        return {**view, 'delivery_token': token}

    def choose(self, operation, identity, delivery, work=None, wait=None, delegated=False):
        if not isinstance(identity, str) or not identity:raise ValueError('choice identity is required')
        current = self.host.inspect(operation)
        parent_choice = current['request']['request']['inputs']['choice']
        parent = next(item for item in self.choices() if item['id'] == parent_choice)
        capability = self.config['capabilities'][parent['body']['work']['capability']]
        allowed = capability.get('select', [])
        if not allowed:raise ValueError('this invocation cannot select work')
        if delegated and (work is None or wait is not None):raise ValueError('delegation needs work')
        if not delegated and (work is None) == (wait is None):raise ValueError('select exactly one next work or wait')
        selected = self._work(work, allowed, parent['body']['work']['version']) if work is not None else None
        if wait is not None:
            if set(wait)-{'condition', 'work'}:raise ValueError('unknown wait fields')
            condition = wait['condition']
            if set(condition)-{'event', 'after'}:raise ValueError('unknown wake condition')
            if not isinstance(condition.get('event', True), (str, bool)):raise ValueError('invalid wake event')
            if condition.get('after') is not None:
                import math
                if type(condition['after']) not in (int, float) or not math.isfinite(condition['after']):raise ValueError('invalid wake timestamp')
            if wait.get('work') is not None:wait = {**wait, 'work': self._work(wait['work'], allowed, parent['body']['work']['version'])}
        choice_id = 'choice.'+ops.sha([operation, identity])[:32]
        with self.host.tx() as db:
            delivered = db.execute('SELECT * FROM rsi_deliveries WHERE token=? AND operation=?', (delivery, operation)).fetchone()
            if not delivered:raise ValueError('selection needs this invocation\'s delivered input token')
            view = json.loads(delivered['body']); state = json.loads(db.execute('SELECT body FROM rsi_state').fetchone()[0])
            inbox = db.execute("SELECT * FROM inbox WHERE id='research'").fetchone()
            body = {'role': 'delegated' if delegated else 'wait' if wait is not None else 'continuation',
                    'origin': {'operation': operation, 'identity': identity, 'delivery': delivery},
                    'epoch': view['epoch'], 'generation': view['generation'], 'through': view['through'],
                    'work': selected, 'wait': wait, 'after_operation': None if delegated else operation}
            encoded = ops.encoded(body)
            prior = db.execute('SELECT * FROM rsi_choices WHERE id=?', (choice_id,)).fetchone()
            if prior:
                if prior['body'] != encoded:raise ValueError('choice identity conflicts')
                return {'choice': choice_id, 'state': prior['state']}
            if inbox['cancelled'] or inbox['epoch'] != view['epoch'] or state['generation'] != view['generation'] or parent['body']['generation'] != view['generation'] or inbox['cursor'] != view['acknowledged']:
                raise ValueError('selection input/owner is stale; receive current input before choosing')
            if current['state'] != 'running':raise ValueError('selecting invocation is not running')
            if not delegated:
                for row in db.execute("SELECT body FROM rsi_choices WHERE state IN ('queued','waiting','admitting','running')"):
                    previous = json.loads(row[0])
                    if previous['role'] != 'delegated' and previous.get('origin', {}).get('operation') == operation:
                        raise ValueError('this invocation already selected a disposition')
                condition = wait['condition'] if wait is not None else {'event': True}
                event = condition.get('event', True)
                if isinstance(event, str) and event not in json.loads(inbox['kinds']):raise ValueError('wake event is not admitted')
                pending = inbox['pending'] if (inbox['pending'] or 0) > view['through'] else None
                db.execute("UPDATE inbox SET cursor=?,pending=?,wake=? WHERE id='research'",
                           (view['through'], pending, ops.encoded(condition)))
            db.execute('INSERT INTO rsi_choices(id,body,state) VALUES(?,?,?)',
                       (choice_id, encoded, 'waiting' if wait is not None else 'queued'))
        return {'choice': choice_id, 'state': 'waiting' if wait is not None else 'queued'}

    def _cancel(self, choice):
        try:item = self.host.inspect(choice['operation'])
        except ValueError:return None
        if item['state'] == 'finished':return item
        if item['state'] == 'reserved':
            self.host.cancel(choice['operation']);self.host.dispatch(choice['operation'])
            return item
        cap = self.config['capabilities'][choice['body']['work']['capability']]
        if cap['kind'] == 'native':
            ops.atomic(self.root/'native-actions'/choice['operation']/'cancel.json', {'requested_at': time.time()})
        else:self.host.cancel(choice['operation'])
        return item

    def _reconcile(self, choice):
        try:item = self.host.reconcile(choice['operation'])
        except ValueError:return None
        if item['state'] == 'reserved' or (item.get('outcome') or {}).get('shutdown_confirmed'):return item
        directory = self.host.operation_dir(choice['operation'])
        child_path = directory/'child.json'; child = json.loads(child_path.read_text()) if child_path.exists() else None
        if ops.alive(item.get('owner')) or ops.alive(child) or (child and ops.group_alive(child['pid'])):return item
        cap = self.config['capabilities'][choice['body']['work']['capability']]
        if cap['kind'] == 'native':
            run = self.root/'native-actions'/choice['operation']
            shutdown = confirm_environment_shutdown(run/'w', run/'state')
            if not shutdown['confirmed']:return item
            observation = {'shutdown_confirmed': True, 'adapter': 'native-owned-mounts', 'environment': shutdown,
                           'local_child': child, 'local_group_ended': True}
            measurement = None
            if (run/'result.json').exists():
                result = json.loads((run/'result.json').read_text())
                if result['version'] != item['request']['request']['version']:raise ValueError('recovered native version differs')
                measurement = {'validity': 'unavailable', 'task': result, 'effects_resolved': True,
                               'scope': 'Recovered retained adapter result after caller loss; no quality certification'}
            return self.host.reconcile_effects(choice['operation'], observation, measurement)
        if cap.get('reconcile_argv'):
            for source, expected in cap.get('runner_sources', {}).items():
                if file_digest(source) != expected:raise ValueError('reconciler source changed')
            result = subprocess.run([*cap['reconcile_argv'], str(directory/'assignment.json')],
                                    capture_output=True, text=True, timeout=30, check=True)
            observation = json.loads(result.stdout)
            if observation.get('shutdown_confirmed') is True:
                return self.host.reconcile_effects(choice['operation'], observation)
        return item

    def project_snapshot(self, handle, label):
        if handle is None:return None
        project = self.config['projects'][handle]; root = Path(project['path']); files = {}
        excluded = [PurePosixPath(value) for value in project.get('excluded', [])]
        files['.'] = {'kind': 'directory', 'mode': stat.S_IMODE(root.stat().st_mode)}
        for directory, directories, names in os.walk(root, followlinks=False):
            at = Path(directory)
            directories[:] = [name for name in directories if not any((at/name).relative_to(root).is_relative_to(p) for p in excluded)]
            for name in [*directories, *names]:
                path = at/name; relative_name = path.relative_to(root).as_posix()
                if any(PurePosixPath(relative_name).is_relative_to(p) for p in excluded):continue
                metadata = path.lstat(); mode = stat.S_IMODE(metadata.st_mode)
                if path.is_symlink():files[relative_name] = {'kind': 'symlink', 'target': os.readlink(path), 'mode': mode}
                elif path.is_dir():files[relative_name] = {'kind': 'directory', 'mode': mode}
                elif path.is_file():
                    source = self.host.capture_source(path, expected_sha256=file_digest(path),
                                                      label='project:'+handle+':'+relative_name,
                                                      media_type='application/octet-stream')
                    after = path.lstat()
                    if (metadata.st_size, metadata.st_mtime_ns, metadata.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                        raise ValueError('project file changed during snapshot')
                    descriptor = self.host.get(source, 'source')
                    files[relative_name] = {'kind': 'file', 'source': source, 'sha256': descriptor['sha256'],
                                            'bytes': descriptor['bytes'], 'mode': mode}
                else:files[relative_name] = {'kind': 'special', 'mode': metadata.st_mode}
        content = {'schema': 'project-content-v1', 'entries': {name: {key: value for key, value in item.items() if key != 'source'}
                    for name, item in files.items()}, 'excluded': sorted(project.get('excluded', []))}
        return self.host.put('project_snapshot', {'project': handle, 'files': files, 'excluded': project.get('excluded', []), 'label': label,
            'content_digest': ops.sha(content),
            'content_scope': 'Relative paths/types, regular file bytes and modes, symlink targets/modes, directory modes (including empty directories), declared exclusions. Capture label/alias/source IDs are excluded; ownership, timestamps, xattrs and hardlink relationships are not represented.'})

    def _parameters(self, choice, operation):
        work = choice['body']['work']; cap = self.config['capabilities'][work['capability']]
        provisioned = json.loads((self.root/'provisioned.json').read_text())
        if file_digest(self.root/'inputs/intake.json') != provisioned['intake_sha256']:
            raise ValueError('retained evidence index changed')
        for name, value in self.config['inputs'].items():
            if file_digest(value['path']) != value['sha256']:raise ValueError('retained input changed: '+name)
        limits = [v for v in (work.get('seconds'), cap.get('max_seconds') if cap['kind'] == 'native' else cap['measurement'].get('max_seconds')) if v is not None]
        params = {'choice': choice['id'], 'seconds': min(limits) if limits else None,
                  'version': work['version']}
        if cap.get('strategy_files'):
            before = self.project_snapshot(cap['project'], 'context:'+operation)
            base = self.state()['versions'][work['capability']]
            definition = self.host.get(base, 'version')['definition']
            snapshot = self.host.get(before, 'project_snapshot')
            for policy, name in cap['strategy_files'].items():
                entry = snapshot['files'][relative(name)]
                if entry['kind'] != 'file':raise ValueError('strategy source must be a regular project file')
                digest = self.host.get(entry['source'], 'source')['sha256']
                definition['files'][policy] = (self.host.root/'sources'/digest).read_text()
            params['version'] = self.host.register(definition, base)
            params['project_before'] = before
        return params

    def _scope_busy(self, name, own_operation):
        scope = self.host.config['measurements']['cap.'+name]['effect_scope']
        with self.host.tx() as db:
            for row in db.execute('SELECT id,request,state,outcome FROM operations'):
                if row['id'] == own_operation:continue
                if json.loads(row['request'])['measurement'].get('effect_scope') != scope:continue
                outcome = json.loads(row['outcome']) if row['outcome'] else {}
                if row['state'] in ('reserved','running','unknown') or not outcome.get('shutdown_confirmed'):
                    return True
        return False

    def tick(self):
        """One recovery/dispatch pass. No research question or retry is selected here."""
        for choice in self.choices():
            if not choice['operation']:continue
            try:item = self._reconcile(choice)
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                item = self.host.inspect(choice['operation'])
                with self.host.tx() as db:db.execute('UPDATE rsi_choices SET error=? WHERE id=?', ('reconciliation: '+str(error), choice['id']))
            if item is None:continue
            if item['state'] == 'finished':
                with self.host.tx() as db:
                    db.execute("UPDATE rsi_choices SET state='finished' WHERE id=?", (choice['id'],))
            if item['state'] not in ('finished', 'unknown'):continue
            if choice['body']['role'] == 'delegated' and choice['announcement'] != item['outcome']['object']:
                observation = self.host.observation('work:'+choice['id'], [item['outcome']['object']],
                    {'operation': choice['operation'], 'capability': choice['body']['work']['capability']},
                    {'returned': item['outcome']['execution'], 'shutdown_confirmed': item['outcome']['shutdown_confirmed']}, {}, source=SOURCE)
                with self.host.tx() as db:db.execute('UPDATE rsi_choices SET announcement=? WHERE id=?', (item['outcome']['object'], choice['id']))
        state = self.state(); inbox = self.host.inbox('research')
        if inbox['cancelled']:
            for choice in self.choices():
                if choice['operation']:self._cancel(choice)
            return self.status()
        for choice in self.choices():
            if choice['state'] not in ('waiting', 'queued', 'admitting'):continue
            state = self.state(); inbox = self.host.inbox('research')
            if inbox['cancelled']:break
            body = choice['body']; dependency = body.get('after_operation')
            if dependency:
                prior = self.host.reconcile(dependency)
                if prior['state'] != 'finished' or not prior['outcome']['shutdown_confirmed']:continue
            if choice['state'] == 'waiting':
                with self.control_lock():
                    wait = body['wait']; condition = wait['condition']; view = self.host.receive('research', limit=1000)
                    due = condition.get('after') is not None and time.time() >= condition['after']
                    if wait.get('work') is None or not (view['pending'] is not None or due):continue
                    state = self.state()
                    identity = 'wake.'+ops.sha([choice['id'], view['epoch'], view['acknowledged'], view['pending'], state['generation']])[:32]
                    activated = {'role': 'continuation', 'origin': {'wait': choice['id'], 'trigger': view}, 'work': wait['work'],
                                 'epoch': view['epoch'], 'generation': state['generation'], 'after_operation': dependency}
                    with self.host.tx() as db:
                        row = db.execute('SELECT state FROM rsi_choices WHERE id=?', (choice['id'],)).fetchone()
                        if row[0] != 'waiting' or view['cancelled']:continue
                        db.execute("INSERT OR IGNORE INTO rsi_choices(id,body,state) VALUES(?,?,'queued')", (identity, ops.encoded(activated)))
                        db.execute("UPDATE rsi_choices SET state='activated' WHERE id=?", (choice['id'],))
                continue
            if body['epoch'] != inbox['epoch'] or body['generation'] != state['generation']:
                if choice['operation']:
                    self._cancel(choice)
                with self.host.tx() as db:db.execute("UPDATE rsi_choices SET state='stale' WHERE id=?", (choice['id'],))
                continue
            operation = choice['operation'] or 'work.'+ops.sha(choice['id'])[:32]
            if self._scope_busy(body['work']['capability'], operation):continue
            try:
                params = choice['params'] or self._parameters(choice, operation)
                with self.host.tx() as db:
                    current = json.loads(db.execute('SELECT body FROM rsi_state').fetchone()[0])
                    owner = db.execute("SELECT epoch,cancelled FROM inbox WHERE id='research'").fetchone()
                    if owner['cancelled'] or owner['epoch'] != body['epoch'] or current['generation'] != body['generation']:
                        db.execute("UPDATE rsi_choices SET state='stale' WHERE id=?", (choice['id'],));continue
                    db.execute("UPDATE rsi_choices SET state='admitting',operation=?,params=? WHERE id=?",
                               (operation, ops.encoded(params), choice['id']))
                limit = params['seconds']
                native_kind = self.config['capabilities'][body['work']['capability']]['kind'] == 'native'
                item = self.host.submit(operation, 'research', params['version'],
                    'cap.'+body['work']['capability'], params, body['work'].get('purpose', 'Explicitly selected work'),
                    seconds=limit+(90 if native_kind else 0) if limit is not None else None)
                self.host.dispatch(operation)
                with self.host.tx() as db:db.execute("UPDATE rsi_choices SET state='running',error=NULL WHERE id=?", (choice['id'],))
            except (ValueError, OSError, KeyError, UnicodeError) as error:
                if 'conflicting effect scope' in str(error):continue
                with self.host.tx() as db:db.execute("UPDATE rsi_choices SET state='rejected',error=? WHERE id=?", (str(error), choice['id']))
                self.host.observation('work:'+choice['id'], [], {'admission': True}, {'error': str(error)}, {}, source=SOURCE)
        return self.status()

    def supervise(self):
        with (self.root/'supervisor.lock').open('a') as lock:
            try:fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:return
            ops.atomic(self.root/'supervisor.json', {'process': ops.process_identity(os.getpid()), 'started_at': time.time()})
            while True:
                status = self.tick()
                ops.atomic(self.root/'status.json', status)
                if status['state'] == 'cancelled' and not status['active_operations']:return
                time.sleep(.5)

    def measure(self, capability_name, assignment_path):
        path = Path(assignment_path); assignment = json.loads(path.read_text()); request = assignment['request']
        choice = next(item for item in self.choices() if item['id'] == request['inputs']['choice'])
        if choice['operation'] != request['id'] or choice['body']['work']['capability'] != capability_name:
            raise ValueError('assignment is not bound to this selected capability')
        cap = self.config['capabilities'][capability_name]; body = choice['body']; work = body['work']
        inbox = self.host.inbox('research')
        if inbox['cancelled'] or body['epoch'] != inbox['epoch'] or body['generation'] != self.state()['generation']:
            ops.atomic(path.parent/'result.json', {'validity': 'unavailable', 'admissible': False, 'effects_resolved': True, 'failure': 'stale selected input/owner'})
            return
        before = request['inputs'].get('project_before') or self.project_snapshot(cap.get('project'), 'before:'+request['id'])
        if cap['kind'] == 'measurement':
            for source, digest in cap.get('runner_sources', {}).items():
                if file_digest(source) != digest:raise ValueError('measurement runner source changed')
            supplied = {**assignment, 'runtime_project': self.config.get('projects', {}).get(cap.get('project')),
                        'runtime_project_snapshot': before, 'runtime_inputs': cap.get('inputs', {}), 'selected_work': work}
            protected = path.parent/'capability-assignment.json'; ops.atomic(protected, supplied)
            result = subprocess.run([*cap['measurement']['argv'], str(protected)], cwd=path.parent, check=False)
            if result.returncode:raise RuntimeError('admitted measurement runner failed')
            result_path = path.parent/'result.json'
            measured = json.loads(result_path.read_text())
        else:
            run = self.root/'native-actions'/request['id']; run.mkdir(parents=True, exist_ok=True)
            version = request['version']
            names = cap.get('inputs', [])
            inputs = {name: Path(self.config['inputs'][name]['path']) for name in names}
            inputs['client.py'] = Path(self.config['inputs']['client.py']['path'])
            inputs['intake.json'] = self.root/'inputs/intake.json'
            for name, identity in work.get('sources', {}).items():
                inputs[name] = self.host.root/'sources'/self.host.get(identity, 'source')['sha256']
            context = run/'runtime-context.json'
            predecessor = self.host.inspect(body['after_operation']) if body.get('after_operation') else None
            ops.atomic(context, {'goal': self.state()['goal'], 'selected_choice_id': choice['id'],
                                 'selected_choice': body, 'operation': request['id'],
                                 'predecessor_operation': body.get('after_operation'),
                                 'predecessor_outcome': predecessor.get('outcome') if predecessor else None,
                                 'pending_input': self.host.receive('research', limit=1000),
                                 'generation': body['generation'], 'project_before': before,
                                 'capabilities': RuntimeController(self, request['id']).describe()})
            inputs['runtime-context.json'] = context
            project = self.config.get('projects', {}).get(cap.get('project'))
            if cap.get('strategy_files') and not cap.get('mount_project', False):project = None
            ends = [value for value in (
                assignment['admitted_at']+request['inputs']['seconds'] if request['inputs']['seconds'] is not None else None,
                self.host.authority.deadline) if value is not None]
            remaining = math.floor(min(ends)-time.time()) if ends else None
            if remaining is not None and remaining < 1:
                ops.atomic(path.parent/'result.json', {'validity': 'unavailable', 'admissible': False,
                    'effects_resolved': True, 'failure': 'original action allocation expired before native admission'})
                return
            try:
                task = native(run, Path(self.config['package']), self.config['image'], version, self.host,
                              work['prompt']+'\nRead /inputs/runtime-context.json for this invocation and its offered operations.',
                              inputs=inputs, seconds=remaining, socket_host='research',
                              measurements=(), offered_operations=COMMON+(CONTROL if cap.get('select') else ()),
                              project=project, controller=RuntimeController(self, request['id']), cancel_path=run/'cancel.json',
                              assessment_project=cap.get('assessment_project', False))
                measured = {'validity': 'valid', 'admissible': False, 'task': task,
                            'effects_resolved': task['shutdown']['status'] == 'exited' and task['environment_shutdown']['confirmed']}
            except BaseException as error:
                shutdown = json.loads((run/'shutdown.json').read_text()) if (run/'shutdown.json').exists() else {}
                ops.atomic(path.parent/'result.json', {'validity': 'unavailable', 'admissible': False,
                    'effects_resolved': shutdown.get('native', {}).get('status') in ('exited', 'not_started') and shutdown.get('environment', {}).get('confirmed') is True,
                    'failure': str(error), 'shutdown': shutdown})
                raise
        measured['project_before'] = before
        measured['project_after'] = self.project_snapshot(cap.get('project'), 'after:'+request['id'])
        measured['capability'] = capability_name
        ops.atomic(path.parent/'result.json', measured)


class RuntimeController:
    def __init__(self, runtime, operation):
        self.runtime, self.operation = runtime, operation

    def handles(self, operation):
        return operation in ('describe', 'receive', 'work', 'select', 'work_status', 'cancel_work')

    def interrupted(self):
        choice = self.choice(); inbox = self.runtime.host.inbox('research')
        return bool(inbox['cancelled'] or inbox['epoch'] != choice['body']['epoch'] or
                    self.runtime.state()['generation'] != choice['body']['generation'])

    def authorize(self, operation):
        if operation in ('knowledge', 'register', 'work', 'select', 'cancel_work') and self.interrupted():
            raise ValueError('owner input superseded this invocation; no stale mutation admitted')

    def choice(self):
        item = self.runtime.host.inspect(self.operation)
        identity = item['request']['request']['inputs']['choice']
        return next(choice for choice in self.runtime.choices() if choice['id'] == identity)

    def describe(self):
        choice = self.choice(); cap = self.runtime.config['capabilities'][choice['body']['work']['capability']]
        return {'operation': self.operation, 'responsibility': 'research',
                'offered': {name: {'kind': self.runtime.config['capabilities'][name]['kind'],
                                  'project': self.runtime.config['capabilities'][name].get('project'),
                                  'strategy_files': self.runtime.config['capabilities'][name].get('strategy_files', {}),
                                  'project_mounted': bool(self.runtime.config['capabilities'][name].get('project')) and (not self.runtime.config['capabilities'][name].get('strategy_files') or self.runtime.config['capabilities'][name].get('mount_project', False)),
                                  'max_seconds': self.runtime.config['capabilities'][name].get('max_seconds') if self.runtime.config['capabilities'][name]['kind'] == 'native' else self.runtime.config['capabilities'][name]['measurement'].get('max_seconds')}
                            for name in cap.get('select', [])},
                'project': cap.get('project'), 'input_names': [*cap.get('inputs', []), 'client.py', 'intake.json'],
                'interface': 'Call python3 /inputs/client.py /workspace/s OP JSON. receive returns a delivery_token. work {identity,delivery,work:{capability,prompt,seconds?,sources?}} delegates selected work. select {identity,delivery,work:{...}} records a next action after this invocation; select {identity,delivery,wait:{condition:{event:true},work:{...}}} selects a future event handler; omit wait.work for an inert wait. work_status {identity:CHOICE_ID} reads outcome; cancel_work cancels that choice. No host paths or arbitrary commands are accepted by these control operations. Finish the turn after select; the supervisor executes only retained choices.'}

    def invoke(self, operation, arguments):
        if operation == 'describe':return self.describe()
        if operation == 'receive':return self.runtime.receive(self.operation, **arguments)
        if operation in ('work', 'select'):
            return self.runtime.choose(self.operation, delegated=operation == 'work', **arguments)
        if operation == 'work_status' and 'identity' not in arguments:
            after, limit = arguments.get('after', 0), arguments.get('limit', 100)
            if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 1000:
                raise ValueError('invalid work index page')
            choices = self.runtime.choices(); page = choices[after:after+limit]
            return {'cursor': after+len(page), 'more': after+len(page) < len(choices),
                    'choices': [{'id': item['id'], 'state': item['state'], 'operation': item['operation'],
                                 'origin': item['body'].get('origin'), 'work': item['body'].get('work'),
                                 'error': item['error']} for item in page]}
        choice = next((item for item in self.runtime.choices() if item['id'] == arguments['identity']), None)
        if choice is None:raise ValueError('unknown selected work')
        if operation == 'cancel_work':
            own = self.choice(); allowed = self.runtime.config['capabilities'][own['body']['work']['capability']].get('select', [])
            if not choice['body'].get('work') or choice['body']['work']['capability'] not in allowed:
                raise ValueError('work is outside this invocation\'s capability scope')
            with self.runtime.host.tx() as db:db.execute("UPDATE rsi_choices SET state='cancelled' WHERE id=?", (choice['id'],))
            if choice['operation']:self.runtime._cancel(choice)
        return {'choice': choice['id'], 'state': choice['state'],
                'operation': self.runtime.host.inspect(choice['operation']) if choice['operation'] else None}

    def selected_disposition(self):
        for choice in self.runtime.choices():
            if choice['body'].get('origin', {}).get('operation') == self.operation and choice['body']['role'] != 'delegated' and choice['state'] not in ('stale', 'cancelled'):
                return 'selected_wait' if choice['body']['role'] == 'wait' else 'selected_work'
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    create = sub.add_parser('create'); create.add_argument('--root', type=Path, required=True); create.add_argument('--config', type=Path, required=True)
    supervise = sub.add_parser('supervise'); supervise.add_argument('--root', type=Path, required=True)
    control = sub.add_parser('control'); control.add_argument('--root', type=Path, required=True); control.add_argument('request_json')
    measure = sub.add_parser('measure'); measure.add_argument('root', type=Path); measure.add_argument('capability'); measure.add_argument('assignment', type=Path)
    args = parser.parse_args()
    if args.command == 'create':print(json.dumps(ResearchRuntime.create(args.root, json.loads(args.config.read_text())).status()))
    elif args.command == 'supervise':ResearchRuntime(args.root).supervise()
    elif args.command == 'control':print(json.dumps(ResearchRuntime(args.root).control(**json.loads(args.request_json))))
    else:ResearchRuntime(args.root.parent if args.root.name == 'runtime.json' else args.root).measure(args.capability, args.assignment)


if __name__ == '__main__':main()
