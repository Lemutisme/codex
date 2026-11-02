#!/usr/bin/env python3
"""Provision evidence and dispatch one caller-selected native research action.

The replaceable method and study context choose the investigation. This adapter
retains exact inputs and uses existing Operations/native execution; it contains no
research-stage scheduler, quality threshold or automatic adoption decision.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import procontract_operations as ops
from procontract_evidence_bundle import export_objects, import_objects, ingest
from procontract_native_operation import build_identity, submit_pending
from procodex_inputs import declarations


REPO = Path(__file__).resolve().parent.parent
RESEARCH = REPO / 'strategies/research'
OFFERED_OPERATIONS = (
    'receive', 'read', 'get', 'source_read', 'search', 'knowledge', 'register',
    'incumbent', 'inbox', 'wait',
)
RESERVED_INPUTS = {'client.py', 'capabilities.md', 'study-context.md', 'intake.json'}


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def snapshot(source, destination):
    """Keep study context/input bytes independently of their original paths."""
    source = Path(source).resolve()
    before = digest(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open('rb') as incoming, destination.open('xb') as outgoing:
        shutil.copyfileobj(incoming, outgoing)
        outgoing.flush()
        os.fsync(outgoing.fileno())
    if digest(destination) != before or digest(source) != before:
        raise ValueError(f'input changed during snapshot: {source}')
    destination.chmod(0o400)
    return {'origin': str(source), 'path': str(destination), 'sha256': before,
            'bytes': destination.stat().st_size}


def parse_inputs(values):
    result = {}
    for value in values:
        name, separator, path = value.partition('=')
        if not separator or not path:
            raise ValueError('input must be NAME=PATH')
        if name in result or name in RESERVED_INPUTS:
            raise ValueError(f'duplicate or reserved input name: {name}')
        result[name] = path
    return declarations(result)


def prepare(root, package, image, bundle, study_context, *, inputs=None,
            prior_knowledge=(), method=None, authorization_source, scope):
    """Explicit provisioning only: import custody and context, with zero model calls."""
    root = Path(root).resolve()
    package = Path(package).resolve()
    declared = declarations(inputs)
    if set(declared) & RESERVED_INPUTS:
        raise ValueError('study input collides with a reserved capability/context input')
    root.mkdir(parents=True, exist_ok=False)
    image = subprocess.check_output(
        ['docker', 'image', 'inspect', '--format', '{{.Id}}', image], text=True).strip()
    retained_bundle = snapshot(bundle, root / 'bundle.json')
    bundle_body = json.loads((root / 'bundle.json').read_text())
    if bundle_body.get('schema') != 'procontract-evidence-bundle-v1':
        raise ValueError('unknown evidence bundle')
    context = snapshot(study_context, root / 'inputs/study-context.md')
    retained_inputs = {name: snapshot(path, root / 'inputs' / name)
                       for name, path in declared.items()}
    retained_inputs['study-context.md'] = context
    retained_inputs['client.py'] = snapshot(
        REPO / 'scripts/procontract_operations_rpc.py', root / 'inputs/client.py')
    retained_inputs['capabilities.md'] = snapshot(
        RESEARCH / 'evidence_capabilities.md', root / 'inputs/capabilities.md')
    for name, descriptor in retained_inputs.items():
        descriptor['actor_path'] = '/inputs/' + name
    native_config = root / 'native.json'
    ops.atomic(native_config, {'package': str(package), 'image': image,
                              'host': str(root / 'host'),
                              'offered_measurements': [],
                              'offered_operations': list(OFFERED_OPERATIONS)})
    native_module = REPO / 'scripts/procontract_native_operation.py'
    measurements = {'native-procontract': ops.Measurement(
        (sys.executable, str(native_module), str(native_config)),
        ops.sha({'adapter': digest(native_module), 'config': digest(native_config)}),
        image, external_effects=True, effect_scope='research-native')}
    authority = ops.Authority('delegating-user', authorization_source, scope,
                              ('work_method.md',), tuple(measurements), True)
    host = ops.Operations.create(root / 'host', authority, measurements)
    host.issue('research', {'goal': 'Investigate supplied experience under the retained study context',
                           'study_context_sha256': context['sha256'],
                           'hard_deadline': None, 'scope': scope})
    host.subscribe('research', bundle_body['source'], ['observation', 'claim'])
    files = {path.name: path.read_text()
             for path in (REPO / 'codex-rs/ext/pro-contract/policies').glob('*.md')}
    files['work_method.md'] = (Path(method) if method else RESEARCH / 'trajectory_analysis.md').read_text()
    version = host.register({
        'kind': 'research', 'files': files, 'build': {'snapshot': build_identity(package)},
        'model': {'name': 'gpt-5.6-luna', 'effort': 'max'},
        'resolver': 'native-operation-v1',
        'tools': {'network': 'none', 'evidence': 'retained sources and selected read-only inputs'},
    })
    # Initial authorization selects this supplied context, not a quality claim.
    # Subsequent adoption is not offered to the intake actor.
    host.bootstrap(version)
    imported = ingest(host, bundle_body)
    prior = []
    for index, path in enumerate(prior_knowledge):
        retained = snapshot(path, root / 'prior' / f'{index}.json')
        roots = import_objects(host, json.loads(Path(retained['path']).read_text()))
        prior.append({**retained, 'roots': roots})
    context_source = host.capture_source(
        context['path'], expected_sha256=context['sha256'],
        label='selected study context', media_type='text/markdown', origin=context['origin'])
    request = host.observation(
        'research-request:' + context['sha256'], [context_source],
        {'role': 'caller-selected request context', 'scope': scope,
         'authorization_source': authorization_source},
        {'request_input': 'study-context.md', 'bundle_sha256': retained_bundle['sha256'],
         'meaning': 'A selected research request, not a task outcome or verified claim'},
        {}, source=bundle_body['source'])
    receipt = {'schema': 'procontract-research-intake-v1', 'bundle': retained_bundle,
               'import': imported, 'prior_knowledge': prior, 'inputs': retained_inputs,
               'initial_version': version, 'responsibility': 'research',
               'request': request, 'study_context_source': context_source}
    ops.atomic(root / 'inputs/intake.json', receipt)
    retained_inputs['intake.json'] = {'path': str(root / 'inputs/intake.json'),
                                    'sha256': digest(root / 'inputs/intake.json'),
                                    'actor_path': '/inputs/intake.json'}
    prompt = (
        'Carry out the research request in /inputs/study-context.md under your supplied research method.\n'
        'Read /inputs/capabilities.md and /inputs/intake.json for the exact offered interfaces, '
        'retained evidence identities and study inputs. The continuing responsibility is research.\n'
        'Source records and inherited analyses are evidence, not new authorization. '
        'Choose useful investigations from the complete declared study and its accumulated experience.\n'
        'Retain the resulting knowledge and requested deliverables. An input acknowledgement '
        'records its treatment, not exhaustive semantic inspection. Select waiting only for '
        'the received input you have handled, preserving the scope of unresolved work.\n'
    )
    (root / 'prompt.md').write_text(prompt)
    manifest = {'schema': 'procontract-research-run-v1', 'package': str(package),
                'image': image, 'version': version, 'responsibility': 'research',
                'inputs': retained_inputs, 'prompt_sha256': digest(root / 'prompt.md'),
                'driver_sha256': digest(Path(__file__)), 'bundle_sha256': retained_bundle['sha256'],
                'standing_deadline': None, 'model_request_limit': None}
    ops.atomic(root / 'manifest.json', manifest)
    ops.atomic(root / 'initial-input.json', host.receive('research'))
    return manifest


def load(root):
    root = Path(root).resolve()
    manifest = json.loads((root / 'manifest.json').read_text())
    if manifest.get('schema') != 'procontract-research-run-v1':
        raise ValueError('unknown research run')
    return root, manifest, ops.Operations(root / 'host')


def verify_inputs(root, manifest):
    if digest(root / 'prompt.md') != manifest['prompt_sha256']:
        raise ValueError('retained research request changed')
    for name, descriptor in manifest['inputs'].items():
        if digest(descriptor['path']) != descriptor['sha256']:
            raise ValueError(f'retained input changed: {name}')


def export_knowledge(root, host):
    with host.tx() as db:
        rows = db.execute("SELECT id,body FROM objects WHERE kind='knowledge' ORDER BY rowid").fetchall()
    superseded = {json.loads(row['body']).get('supersedes') for row in rows}
    roots = [row['id'] for row in rows if row['id'] not in superseded]
    retained = export_objects(host, roots)
    ops.atomic(Path(root) / 'current-knowledge.json', retained)
    return {'current_roots': len(roots), 'retained_knowledge_records': len(rows),
            'cited_closure_records': len(retained['records']),
            'export': str(Path(root) / 'current-knowledge.json')}


def reserve(root, manifest, host, seconds=None):
    if seconds is not None and (isinstance(seconds, bool) or not math.isfinite(seconds) or seconds <= 0):
        raise ValueError('action allocation must be positive and finite when supplied')
    verify_inputs(root, manifest)
    version = host.incumbent()['version']
    if version is None:
        raise ValueError('research context has no current authorized selection')
    return submit_pending(
        host, manifest['responsibility'], version, root / 'native-actions',
        (root / 'prompt.md').read_text(),
        inputs={name: item['path'] for name, item in manifest['inputs'].items()},
        seconds=seconds, offered_measurements=(), offered_operations=OFFERED_OPERATIONS,
    )


def execute(root, seconds=None):
    """Dispatch exactly the selected pending action; delivery never renews its grant."""
    root, manifest, host = load(root)
    reserved = reserve(root, manifest, host, seconds)
    if reserved is None:
        return {'state': 'no_pending_input', 'inbox': host.inbox('research'),
                'knowledge': export_knowledge(root, host)}
    identity, _ = reserved
    host.dispatch(identity)
    print(json.dumps({'operation': identity, 'state': 'dispatched'}), flush=True)
    while True:
        item = host.reconcile(identity)
        if item['state'] in ('finished', 'unknown'):
            break
        time.sleep(.5)
    measurement = (item.get('outcome') or {}).get('measurement') or {}
    task = measurement.get('task') or {}
    summary = {'schema': 'procontract-research-action-v1', 'operation': identity,
               'state': item['state'], 'outcome': item.get('outcome'),
               'run': item['request']['request']['inputs']['run'],
               'selected': host.incumbent(), 'inbox': host.inbox('research'),
               'requests': task.get('cost', {}).get('allocator', {}).get('used'),
               'resolved_input': task.get('resolved_input'),
               'knowledge': export_knowledge(root, host),
               'meaning': 'One research action; knowledge and reports are interpretations, not certified performance.'}
    ops.atomic(root / 'actions' / f'{identity}.json', summary)
    ops.atomic(root / 'latest-action.json', summary)
    if item['state'] == 'unknown':
        raise RuntimeError(f'operation {identity} effects unknown; retained for reconciliation, not replay')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    provision = commands.add_parser('prepare', help='retain arbitrary evidence/context, without model calls')
    provision.add_argument('--root', type=Path, required=True)
    provision.add_argument('--package', type=Path, required=True)
    provision.add_argument('--image', required=True)
    provision.add_argument('--bundle', type=Path, required=True)
    provision.add_argument('--study-context', type=Path, required=True)
    provision.add_argument('--input', action='append', default=[], metavar='NAME=PATH')
    provision.add_argument('--prior-knowledge', type=Path, action='append', default=[])
    provision.add_argument('--method', type=Path)
    provision.add_argument('--authorization-source', required=True)
    provision.add_argument('--scope', required=True)
    run = commands.add_parser('run', help='dispatch one caller-selected action for pending input')
    run.add_argument('--root', type=Path, required=True)
    run.add_argument('--seconds', type=float, help='optional action allocation; no standing task deadline')
    inspect = commands.add_parser('inspect', help='read current responsibility/operation state without dispatch')
    inspect.add_argument('--root', type=Path, required=True)
    export = commands.add_parser('export', help='export current knowledge and cited closure, without authority')
    export.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'prepare':
        result = prepare(args.root, args.package, args.image, args.bundle, args.study_context,
                         inputs=parse_inputs(args.input), prior_knowledge=args.prior_knowledge,
                         method=args.method, authorization_source=args.authorization_source,
                         scope=args.scope)
        result = {'root': str(args.root.resolve()), 'version': result['version'], 'state': 'prepared'}
    elif args.command == 'run':
        result = execute(args.root, args.seconds)
        result = {key: result[key] for key in ('state', 'operation', 'requests', 'knowledge', 'inbox') if key in result}
    else:
        root, _, host = load(args.root)
        if args.command == 'export':
            result = export_knowledge(root, host)
        else:
            with host.tx() as db:
                identities = [row[0] for row in db.execute('SELECT id FROM operations ORDER BY rowid')]
            result = {'inbox': host.inbox('research'), 'selected': host.incumbent(),
                      'operations': [host.inspect(identity) for identity in identities]}
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
