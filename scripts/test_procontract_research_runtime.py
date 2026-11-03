"""Durable choice, control and scope fault controls; no model inference."""
import copy
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import procontract_operations as ops
from procontract_operations_rpc import Broker
import procontract_research_runtime as runtime


class RuntimeTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.package = self.base/'package'; (self.package/'bin').mkdir(parents=True)
        (self.package/'bin/codex').write_text('runtime fixture')
        self.method = self.base/'method.md'; self.method.write_text('Choose useful work and explicit waiting.')
        self.project = self.base/'project'; (self.project/'policies').mkdir(parents=True)
        (self.project/'policies/work_method.md').write_text('target context A')
        (self.project/'tool.py').write_text('print("A")\n')
        self.runner = self.base/'runner.py'
        self.runner.write_text('''import json,sys
from pathlib import Path
p=Path(sys.argv[-1]);a=json.loads(p.read_text())
(p.parent/'result.json').write_text(json.dumps({'validity':'valid','admissible':False,'effects_resolved':True,'observed':a['runtime_inputs']}))
''')
        self.config = {
            'schema': 'procontract-research-runtime-v1', 'package': str(self.package), 'image': 'fixture',
            'model': {'name': 'fixture', 'effort': 'max'}, 'strategy': str(self.method),
            'authority': {'principal': 'fixture-owner', 'source': 'fixture authorization', 'scope': 'isolated runtime test'},
            'inputs': {}, 'projects': {
                'target': {'path': str(self.project), 'writable': ['policies'], 'excluded': []},
                'target-read': {'path': str(self.project), 'writable': [], 'excluded': []}},
            'capabilities': {
                'research': {'kind': 'native', 'project': None, 'inputs': [], 'select': ['research', 'measure', 'edit', 'exercise']},
                'edit': {'kind': 'native', 'project': 'target', 'inputs': [], 'select': []},
                'exercise': {'kind': 'native', 'project': 'target-read', 'inputs': [], 'select': [],
                             'strategy_files': {'work_method.md': 'policies/work_method.md'}},
                'measure': {'kind': 'measurement', 'project': None, 'measurement': {
                    'argv': [sys.executable, str(self.runner)], 'identity': 'fixture measurement',
                    'environment': 'local controlled process', 'external_effects': False},
                    'inputs': {'declared': 'fixed trusted input'}},
            },
            'initial': {'capability': 'research', 'prompt': 'Inspect the retained goal.', 'seconds': None},
        }
        self.dispatched = []
        self.original_dispatch = ops.Operations.dispatch
        def record(host, identity):
            self.dispatched.append(identity)
            return host.inspect(identity)
        patches = [patch.object(runtime.subprocess, 'check_output', return_value='sha256:fixture\n'),
                   patch.object(runtime.ResearchRuntime, 'ensure_supervisor'),
                   patch.object(ops.Operations, 'dispatch', autospec=True, side_effect=record)]
        self.mocks = [item.start() for item in patches]
        for item in patches:self.addCleanup(item.stop)
        self.root = self.base/'runtime'
        self.runtime = runtime.ResearchRuntime.create(self.root, self.config)

    def start(self):
        response = self.runtime.control('start', 'owner-start', 'Improve the authorized project.')
        self.runtime.tick()
        choice = next(item for item in self.runtime.choices() if item['id'] == response['selected_choice'])
        self.operation = choice['operation']
        with self.runtime.host.tx() as db:
            db.execute("UPDATE operations SET state='running',owner=? WHERE id=?",
                       (ops.encoded(ops.process_identity(os.getpid())), self.operation))
        return self.runtime.receive(self.operation)

    def finish(self, identity=None, execution='completed', shutdown=True):
        identity = identity or self.operation
        item = self.runtime.host.inspect(identity)
        ops.atomic(self.runtime.host.operation_dir(identity)/'receipt.json', {
            'id': identity, 'assignment': ops.sha(item['request']), 'execution': execution,
            'shutdown_confirmed': shutdown, 'measurement': {'validity': 'valid', 'admissible': False}})
        return self.runtime.host.reconcile(identity)

    def native_result(self, identity, files=None, messages=(), binary=None):
        item = self.runtime.host.inspect(identity)
        workspace = self.runtime.root/'native-actions'/identity/'w';workspace.mkdir(parents=True,exist_ok=True)
        files = files or {};artifacts = {}
        for name, text in files.items():
            raw=text.encode();(workspace/name).write_bytes(raw)
            artifacts[name]={'kind':'file','bytes':len(raw),'sha256':ops.sha(raw),'inline_text':True}
        for name, raw in (binary or {}).items():
            (workspace/name).write_bytes(raw)
            artifacts[name]={'kind':'file','bytes':len(raw),'sha256':ops.sha(raw),'inline_text':False}
        task={'version':item['request']['request']['version'],'files':files,'artifacts':artifacts,
              'completed_turns':[{'id':'turn-fixture','items':[{'type':'agentMessage','phase':'final_answer','id':'message-'+str(i),'text':text} for i,text in enumerate(messages)]}]}
        ops.atomic(self.runtime.host.operation_dir(identity)/'receipt.json', {
            'id':identity,'assignment':ops.sha(item['request']),'execution':'completed',
            'shutdown_confirmed':True,'measurement':{'validity':'valid','admissible':False,'effects_resolved':True,'task':task}})
        return self.runtime.host.reconcile(identity)

    def select(self, view, **kwargs):
        return self.runtime.choose(self.operation, 'next', view['delivery_token'], **kwargs)

    def test_create_is_zero_work_exactly_idempotent_and_incomplete_root_not_admitted(self):
        self.assertEqual(self.runtime.choices(), [])
        reopened = runtime.ResearchRuntime.create(self.root, copy.deepcopy(self.config))
        self.assertEqual(reopened.config, self.runtime.config)
        changed = copy.deepcopy(self.config); changed['authority']['scope'] = 'different'
        with self.assertRaisesRegex(ValueError, 'configuration changed'):
            runtime.ResearchRuntime.create(self.root, changed)
        (self.root/'provisioned.json').unlink()
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            runtime.ResearchRuntime.create(self.root, self.config)
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            self.runtime.control('start', 'not-ready', 'goal')

    def test_control_lost_ack_reconciles_start_and_reensures_supervisor(self):
        with patch.object(self.runtime, 'status', side_effect=RuntimeError('lost transport')):
            with self.assertRaisesRegex(RuntimeError, 'lost transport'):
                self.runtime.control('start', 'owner-start', 'goal')
        self.assertTrue(self.runtime.state()['started'])
        reopened = runtime.ResearchRuntime(self.root)
        first = reopened.control('start', 'owner-start', 'goal')
        self.assertEqual(len(reopened.choices()), 1)
        with patch.object(reopened, 'ensure_supervisor') as ensure:
            self.assertEqual(reopened.control('start', 'owner-start', 'goal'), first)
            ensure.assert_called_once()
        with self.assertRaisesRegex(ValueError, 'conflicts'):
            reopened.control('start', 'owner-start', 'changed goal')

    def test_owner_input_mutation_is_once_even_if_reply_is_lost(self):
        self.start()
        with patch.object(self.runtime, 'status', side_effect=RuntimeError('lost reply')):
            with self.assertRaises(RuntimeError):self.runtime.control('input', 'input-1', 'new constraint')
        generation = self.runtime.state()['generation']
        self.runtime.control('input', 'input-1', 'new constraint')
        self.assertEqual(self.runtime.state()['generation'], generation)
        with self.runtime.host.tx() as db:
            bodies = [json.loads(row[0]) for row in db.execute("SELECT body FROM objects WHERE kind='observation'")]
        self.assertEqual(sum(item['subject'] == 'owner-request:input-1' for item in bodies), 1)
        self.assertEqual(sum(item['body'].get('origin', {}).get('owner_request') == 'input-1' for item in self.runtime.choices()), 1)

    def test_cancel_reply_retry_after_resume_cannot_cancel_new_owner_work(self):
        self.start()
        with patch.object(self.runtime, 'status', side_effect=RuntimeError('lost cancel reply')):
            with self.assertRaises(RuntimeError):self.runtime.control('cancel', 'cancel-1')
        self.finish()
        resumed = self.runtime.control('resume', 'resume-1')
        self.runtime.tick()
        new = next(item for item in self.runtime.choices() if item['id'] == resumed['selected_choice'])
        self.assertNotEqual(new['operation'], self.operation)
        self.runtime.control('cancel', 'cancel-1')
        self.assertFalse(self.runtime.host.inbox('research')['cancelled'])
        self.assertFalse((self.runtime.host.operation_dir(new['operation'])/'cancel.json').exists())
        self.assertFalse((self.root/'native-actions'/new['operation']/'cancel.json').exists())

    def test_actor_selected_next_work_waits_for_return_and_survives_restart(self):
        view = self.start()
        chosen = self.select(view, work={'capability': 'research', 'prompt': 'Continue with the evidence.', 'seconds': None})
        self.assertEqual(self.select(view, work={'capability': 'research', 'prompt': 'Continue with the evidence.', 'seconds': None}), chosen)
        self.runtime.tick()
        next_choice = next(item for item in self.runtime.choices() if item['id'] == chosen['choice'])
        self.assertIsNone(next_choice['operation'])
        self.finish()
        self.runtime = runtime.ResearchRuntime(self.root); self.runtime.tick()
        next_choice = next(item for item in self.runtime.choices() if item['id'] == chosen['choice'])
        before = self.runtime.host.inspect(next_choice['operation'])['request']
        self.assertIsNone(before['deadline'])
        with self.runtime.host.tx() as db:db.execute("UPDATE rsi_choices SET state='admitting' WHERE id=?", (chosen['choice'],))
        self.runtime = runtime.ResearchRuntime(self.root); self.runtime.tick()
        self.assertEqual(self.runtime.host.inspect(next_choice['operation'])['request'], before)
        self.assertEqual(len(self.runtime.choices()), 2)

    def test_selected_wait_wakes_once_for_passive_input_and_no_failure_is_retried(self):
        view = self.start()
        waiting = self.select(view, wait={'condition': {'event': True},
            'work': {'capability': 'research', 'prompt': 'Interpret the selected new event.'}})
        self.finish(execution='failed'); self.runtime.tick()
        self.assertEqual(len(self.runtime.choices()), 2)
        self.runtime.host.observation('external event', [], {}, {'new': 'fact'}, {}, source=runtime.SOURCE)
        self.runtime.tick(); self.runtime.tick()
        count = len(self.runtime.choices()); self.runtime.tick()
        self.assertEqual(len(self.runtime.choices()), count)
        self.assertEqual(count, 3)
        self.assertEqual(next(item for item in self.runtime.choices() if item['id'] == waiting['choice'])['state'], 'activated')
        self.assertEqual(sum(item['operation'] == self.operation for item in self.runtime.choices()), 1)

    def test_owner_input_replaces_old_mutating_wait_and_fences_even_fresh_token_from_old_actor(self):
        view = self.start()
        old = self.select(view, wait={'condition': {'event': True}, 'work': {'capability': 'measure'}})
        self.runtime.control('input', 'changed-owner-input', 'Do not run that mutation; reassess.')
        self.assertEqual(next(item for item in self.runtime.choices() if item['id'] == old['choice'])['state'], 'replaced')
        fresh = self.runtime.receive(self.operation)
        with self.assertRaisesRegex(ValueError, 'stale'):
            self.runtime.choose(self.operation, 'old-actor-new-choice', fresh['delivery_token'], work={'capability': 'measure'}, delegated=True)
        self.finish(); self.runtime.tick()
        self.assertFalse(any(item['body'].get('work', {}).get('capability') == 'measure' and item['operation'] for item in self.runtime.choices() if item['body'].get('work')))

    def test_delivery_token_cannot_ack_unreceived_page_or_another_invocation(self):
        view = self.start()
        with self.assertRaisesRegex(ValueError, 'delivered input'):
            self.runtime.choose(self.operation, 'forged', 'not-a-token', work={'capability': 'research', 'prompt': 'anything'})
        self.runtime.control('input', 'new-input', 'new owner condition')
        with self.assertRaisesRegex(ValueError, 'stale'):
            self.select(view, work={'capability': 'research', 'prompt': 'stale'})

    def test_actor_cannot_choose_host_paths_or_unoffered_capabilities(self):
        view = self.start()
        for work in ({'capability': 'research', 'prompt': 'x', 'run': '/private'},
                     {'capability': 'research', 'prompt': 'x', 'inputs': {'secret': '/private'}},
                     {'capability': 'unknown', 'prompt': 'x'}):
            with self.subTest(work=work), self.assertRaises(ValueError):
                self.runtime.choose(self.operation, 'bad', view['delivery_token'], work=work, delegated=True)
        broker = Broker(self.base/'socket', self.runtime.host, 'research', operations=runtime.COMMON+runtime.CONTROL,
                        controller=runtime.RuntimeController(self.runtime, self.operation))
        self.addCleanup(broker.server_close)
        with self.assertRaisesRegex(ValueError, 'not offered'):
            broker.invoke('submit', {'measurement': 'cap.research', 'inputs': {'run': '/private'}})
        with self.assertRaisesRegex(ValueError, 'not offered'):
            broker.invoke('reconcile_effects', {'identity': self.operation})

    def test_project_aliases_share_effect_scope_and_target_context_is_task_lineage(self):
        cfg = copy.deepcopy(self.config); cfg['capabilities']['research']['project'] = 'target-read'
        other = runtime.ResearchRuntime.create(self.base/'aliases', cfg)
        self.runtime = other
        view = self.start()
        child = self.runtime.choose(self.operation, 'exercise', view['delivery_token'], work={'capability': 'exercise', 'prompt': 'Use the selected target context.'}, delegated=True)
        self.runtime.tick()
        self.assertIsNone(next(item for item in self.runtime.choices() if item['id'] == child['choice'])['operation'])
        (self.project/'policies/work_method.md').write_text('target context B selected for this task')
        self.finish(); self.runtime.tick()
        selected = next(item for item in self.runtime.choices() if item['id'] == child['choice'])
        assignment = self.runtime.host.inspect(selected['operation'])['request']
        definition = self.runtime.host.get(assignment['request']['version'], 'version')['definition']
        self.assertEqual(definition['kind'], 'task')
        self.assertEqual(definition['files']['work_method.md'], 'target context B selected for this task')
        self.assertEqual(self.runtime.host.get(self.runtime.host.incumbent()['version'], 'version')['definition']['kind'], 'research')
        self.assertEqual(self.runtime.host.config['measurements']['cap.edit']['effect_scope'], self.runtime.host.config['measurements']['cap.exercise']['effect_scope'])

    def test_project_policy_symlink_is_not_a_host_reader(self):
        view = self.start()
        (self.project/'policies/work_method.md').unlink()
        (self.project/'policies/work_method.md').symlink_to(self.method)
        chosen = self.runtime.choose(self.operation, 'escaped-policy', view['delivery_token'], work={'capability': 'exercise', 'prompt': 'Use context.'}, delegated=True)
        self.runtime.tick()
        item = next(item for item in self.runtime.choices() if item['id'] == chosen['choice'])
        self.assertEqual(item['state'], 'rejected')
        self.assertIn('regular project file', item['error'])

    def test_unmapped_task_policy_does_not_inherit_research_method(self):
        (self.project/'policies/continuation.md').write_text('task continuation under study')
        cfg = copy.deepcopy(self.config)
        cfg['capabilities']['exercise']['strategy_files'] = {'continuation.md': 'policies/continuation.md'}
        self.runtime = runtime.ResearchRuntime.create(self.base/'task-template', cfg)
        view = self.start()
        chosen = self.runtime.choose(self.operation, 'target-context', view['delivery_token'],
                                     work={'capability': 'exercise', 'prompt': 'Task context fixture.'}, delegated=True)
        self.runtime.tick()
        choice = next(item for item in self.runtime.choices() if item['id'] == chosen['choice'])
        assignment = self.runtime.host.inspect(choice['operation'])['request']
        definition = self.runtime.host.get(assignment['request']['version'], 'version')['definition']
        self.assertEqual(definition['files']['work_method.md'], self.runtime.config['task_policies']['work_method.md'])
        self.assertNotEqual(definition['files']['work_method.md'], self.method.read_text())
        self.assertEqual(definition['files']['continuation.md'], 'task continuation under study')

    def test_streamed_copy_and_snapshot_do_not_use_whole_file_read_bytes(self):
        source = self.base/'large'; source.write_bytes(b'x'*(2<<20))
        original_read_bytes = Path.read_bytes
        def bounded(path):
            if path == source or path == self.project/'tool.py':raise AssertionError('whole-file materialization')
            return original_read_bytes(path)
        with patch.object(Path, 'read_bytes', bounded):
            runtime.pinned_copy(source, self.base/'retained')
            snapshot = self.runtime.project_snapshot('target', 'streamed fixture')
        body = self.runtime.host.get(snapshot, 'project_snapshot')
        self.assertIn('tool.py', body['files'])

    def test_content_digest_separates_observation_identity_and_represents_modes_and_empty_directories(self):
        first = self.runtime.project_snapshot('target', 'first observation')
        second = self.runtime.project_snapshot('target-read', 'another observation of the same bytes')
        left = self.runtime.host.get(first); right = self.runtime.host.get(second)
        self.assertNotEqual(first, second)
        self.assertEqual(left['content_digest'], right['content_digest'])
        (self.project/'empty').mkdir()
        third = self.runtime.host.get(self.runtime.project_snapshot('target', 'empty directory added'))
        self.assertEqual(third['files']['empty']['kind'], 'directory')
        self.assertNotEqual(third['content_digest'], left['content_digest'])
        (self.project/'tool.py').chmod(0o755)
        fourth = self.runtime.host.get(self.runtime.project_snapshot('target', 'executable bit changed'))
        self.assertNotEqual(fourth['content_digest'], third['content_digest'])
        self.assertEqual(fourth['files']['tool.py']['sha256'], third['files']['tool.py']['sha256'])

    def test_external_reconciliation_keeps_original_receipt_and_does_not_regrant(self):
        self.start()
        original = self.finish(execution='failed', shutdown=False)
        receipt = self.runtime.host.operation_dir(self.operation)/'receipt.json'
        original_bytes = receipt.read_bytes()
        with self.assertRaisesRegex(ValueError, 'not stopped'):
            self.runtime.host.reconcile_effects(self.operation, {'shutdown_confirmed': True})
        with self.runtime.host.tx() as db:
            db.execute('UPDATE operations SET owner=NULL WHERE id=?', (self.operation,))
        reconciled = self.runtime.host.reconcile_effects(self.operation,
            {'shutdown_confirmed': True, 'adapter': 'fixture scoped external observation'},
            {'validity': 'unavailable', 'quality': None, 'admissible': True})
        self.assertTrue(reconciled['outcome']['shutdown_confirmed'])
        self.assertFalse(reconciled['outcome']['measurement']['admissible'])
        self.assertEqual(reconciled['request'], original['request'])
        self.assertNotEqual(reconciled['outcome']['object'], original['outcome']['object'])
        self.assertEqual(receipt.read_bytes(), original_bytes)
        self.assertFalse(self.runtime.host.get(original['outcome']['object'])['shutdown_confirmed'])
        self.assertEqual(self.runtime.host.reconcile_effects(self.operation, {'shutdown_confirmed': True}), reconciled)

    def test_external_measurement_reconciler_is_bound_and_preserves_unavailable_result(self):
        reconciler = self.base/'reconcile.py'
        reconciler.write_text('import json; print(json.dumps({"shutdown_confirmed":True,"adapter":"fixture"}))\n')
        cfg = copy.deepcopy(self.config)
        cfg['capabilities']['measure']['measurement']['external_effects'] = True
        cfg['capabilities']['measure']['reconcile_argv'] = [sys.executable, str(reconciler)]
        self.runtime = runtime.ResearchRuntime.create(self.base/'external', cfg)
        view = self.start()
        selected = self.runtime.choose(self.operation, 'external-check', view['delivery_token'], work={'capability': 'measure'}, delegated=True)
        self.runtime.tick()
        choice = next(item for item in self.runtime.choices() if item['id'] == selected['choice'])
        self.finish(choice['operation'], execution='failed', shutdown=False)
        with self.runtime.host.tx() as db:db.execute('UPDATE operations SET owner=NULL WHERE id=?', (choice['operation'],))
        # Reconciliation receives the complete original assignment, as a real
        # runner would have retained it before external work.
        item = self.runtime.host.inspect(choice['operation'])
        ops.atomic(self.runtime.host.operation_dir(choice['operation'])/'assignment.json', item['request'])
        actual = self.runtime._reconcile(choice)
        self.assertTrue(actual['outcome']['shutdown_confirmed'])
        self.assertEqual(actual['outcome']['execution'], 'failed')

    def test_measurement_runner_is_fixed_and_real_return_wakes_selected_handler(self):
        view = self.start()
        chosen = self.runtime.choose(self.operation, 'check', view['delivery_token'], work={'capability': 'measure', 'seconds': 5}, delegated=True)
        self.select(view, wait={'condition': {'event': True}, 'work': {'capability': 'research', 'prompt': 'Use the actual returned check.'}})
        self.finish(); self.runtime.tick()
        child = next(item for item in self.runtime.choices() if item['id'] == chosen['choice'])
        self.original_dispatch(self.runtime.host, child['operation'])
        until = time.monotonic()+10
        while time.monotonic() < until:
            item = self.runtime.host.reconcile(child['operation'])
            if item['state'] == 'finished':break
            time.sleep(.025)
        self.assertEqual(item['state'], 'finished')
        self.assertEqual(item['outcome']['measurement']['observed'], {'declared': 'fixed trusted input'})
        self.runtime.tick(); self.runtime.tick()
        self.assertTrue(any(choice['id'].startswith('wake.') for choice in self.runtime.choices()))

    def test_work_index_and_current_choice_context_are_inspectable(self):
        self.start()
        controller = runtime.RuntimeController(self.runtime, self.operation)
        index = controller.invoke('work_status', {})
        self.assertEqual(index['choices'][0]['operation'], self.operation)
        self.assertEqual(index['choices'][0]['origin']['owner_request'], 'owner-start')

    def test_atomic_leaf_call_returns_once_without_owner_stage_selection_and_reuses_reservation(self):
        view=self.start()
        call={'work':{'capability':'measure','purpose':'A caller-selected question','seconds':5},
              'return_to':{'capability':'research','prompt':'Use the returned result and decide what matters next.','seconds':9}}
        selected=self.select(view,call=call)
        self.assertEqual(self.select(view,call=call),selected)
        self.runtime.tick()
        leaf=next(x for x in self.runtime.choices() if x['id']==selected['choice'])
        self.assertIsNone(leaf['operation'])
        self.finish();self.runtime.tick()
        leaf=next(x for x in self.runtime.choices() if x['id']==selected['choice'])
        original_leaf=self.runtime.host.inspect(leaf['operation'])['request']
        self.original_dispatch(self.runtime.host,leaf['operation'])
        until=time.monotonic()+10
        while time.monotonic()<until:
            outcome=self.runtime.host.reconcile(leaf['operation'])
            if outcome['state']=='finished':break
            time.sleep(.025)
        self.assertEqual(outcome['state'],'finished')
        self.runtime=runtime.ResearchRuntime(self.root);self.runtime.tick()
        returning=next(x for x in self.runtime.choices() if x['id'].startswith('return.'))
        self.assertEqual(returning['body']['work']['prompt'],call['return_to']['prompt'])
        self.assertEqual(returning['body']['origin']['return_of']['outcome'],outcome['outcome']['object'])
        original_return=self.runtime.host.inspect(returning['operation'])['request']
        self.assertEqual(original_return['request']['inputs']['seconds'],9)
        with self.runtime.host.tx() as db:db.execute("UPDATE rsi_choices SET state='admitting' WHERE id=?",(returning['id'],))
        self.runtime=runtime.ResearchRuntime(self.root);self.runtime.tick();self.runtime.tick()
        self.assertEqual(self.runtime.host.inspect(returning['operation'])['request'],original_return)
        self.assertEqual(self.runtime.host.inspect(leaf['operation'])['request'],original_leaf)
        with self.runtime.host.tx() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM rsi_returns').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT count(*) FROM rsi_control').fetchone()[0],1)

    def test_wait_leaf_call_returns_on_failed_result_and_inert_wait_stays_inert(self):
        view=self.start()
        selected=self.select(view,wait={'condition':{'event':True},'call':{
            'work':{'capability':'measure'},'return_to':{'capability':'research','prompt':'Inspect actual result, including failure.'}}})
        self.finish();self.runtime.tick()
        self.assertFalse(any(x['body']['role']=='call' for x in self.runtime.choices()))
        self.runtime.host.observation('available input',[],{}, {'new':'fact'}, {}, source=runtime.SOURCE)
        self.runtime.tick();self.runtime.tick()
        leaf=next(x for x in self.runtime.choices() if x['body']['role']=='call')
        self.finish(leaf['operation'],execution='failed');self.runtime.tick()
        returning=next(x for x in self.runtime.choices() if x['id'].startswith('return.'))
        self.assertEqual(returning['body']['work']['capability'],'research')
        self.assertEqual(self.runtime.host.get(returning['body']['origin']['return_of']['outcome'])['execution'],'failed')
        with self.runtime.host.tx() as db:
            db.execute("UPDATE operations SET state='running',owner=? WHERE id=?",(ops.encoded(ops.process_identity(os.getpid())),returning['operation']))
        token=self.runtime.receive(returning['operation'])
        self.runtime.choose(returning['operation'],'deliberate-rest',token['delivery_token'],wait={'condition':{'event':True}})
        self.finish(returning['operation']);self.runtime.tick()
        before=len(self.runtime.choices())
        self.runtime.host.observation('another event',[],{}, {}, {}, source=runtime.SOURCE)
        self.runtime.tick()
        self.assertEqual(len(self.runtime.choices()),before)
        self.assertEqual(self.runtime.status()['state'],'waiting')

    def test_invalid_call_is_atomic_and_owner_change_fences_late_return(self):
        view=self.start();before=self.runtime.host.inbox('research')
        with self.assertRaisesRegex(ValueError,'return_to'):
            self.select(view,call={'work':{'capability':'measure'}})
        with self.assertRaisesRegex(ValueError,'able to select'):
            self.select(view,call={'work':{'capability':'measure'},'return_to':{'capability':'edit','prompt':'not a continuation authority'}})
        self.assertEqual(self.runtime.host.inbox('research'),before)
        self.assertEqual(len(self.runtime.choices()),1)
        selected=self.select(view,call={'work':{'capability':'measure'},'return_to':{'capability':'research','prompt':'Old owner continuation'}})
        self.finish();self.runtime.tick()
        leaf=next(x for x in self.runtime.choices() if x['id']==selected['choice'])
        self.runtime.control('input','owner-change','New constraint replaces the old pending work.')
        self.finish(leaf['operation']);self.runtime.tick()
        returning=next(x for x in self.runtime.choices() if x['id'].startswith('return.'))
        self.assertEqual(returning['state'],'stale');self.assertIsNone(returning['operation'])

    def test_unknown_effects_do_not_activate_a_project_return(self):
        cfg=copy.deepcopy(self.config);cfg['capabilities']['research']['project']='target-read'
        self.runtime=runtime.ResearchRuntime.create(self.base/'unknown-return',cfg)
        view=self.start();selected=self.select(view,call={'work':{'capability':'edit','prompt':'Selected leaf'},
            'return_to':{'capability':'research','prompt':'Selected return'}})
        self.finish();self.runtime.tick()
        leaf=next(x for x in self.runtime.choices() if x['id']==selected['choice'])
        self.finish(leaf['operation'],execution='failed',shutdown=False)
        with patch.object(self.runtime,'_reconcile',side_effect=lambda choice:self.runtime.host.inspect(choice['operation'])):
            self.runtime.tick()
        self.assertFalse(any(x['id'].startswith('return.') for x in self.runtime.choices()))
        self.runtime.host.reconcile_effects(leaf['operation'],{'shutdown_confirmed':True,'adapter':'independent fixture cleanup'})
        self.runtime.tick()
        self.assertTrue(any(x['id'].startswith('return.') and x['operation'] for x in self.runtime.choices()))

    def test_call_admission_rejection_returns_its_actual_reason(self):
        view=self.start();selected=self.select(view,call={
            'work':{'capability':'exercise','prompt':'Use missing policy'},
            'return_to':{'capability':'research','prompt':'Inspect the admission result'}})
        (self.project/'policies/work_method.md').unlink()
        self.finish();self.runtime.tick();self.runtime.tick()
        leaf=next(x for x in self.runtime.choices() if x['id']==selected['choice'])
        self.assertEqual(leaf['state'],'rejected')
        returning=next(x for x in self.runtime.choices() if x['id'].startswith('return.'))
        context=self.runtime.returned_context(returning['body'])
        self.assertIn('policies/work_method.md',context[0]['admission_rejection']['error'])
        self.assertIsNone(returning['body']['origin']['return_of']['operation'])

    def test_return_context_and_bounded_outputs_use_actual_producer_artifacts(self):
        view=self.start();selected=self.select(view,call={'work':{'capability':'edit','prompt':'Produce a report'},
            'return_to':{'capability':'research','prompt':'Inspect actual returned artifacts'}})
        self.finish();self.runtime.tick()
        leaf=next(x for x in self.runtime.choices() if x['id']==selected['choice'])
        completed=self.native_result(leaf['operation'],{'research-report.md':'Actual per-invocation report.\n'},['Actual public review response.'],{'bytes.bin':b'\xff\x00abc'})
        self.runtime.tick();returning=next(x for x in self.runtime.choices() if x['id'].startswith('return.'))
        index=self.runtime.work_output(leaf['id'])
        self.assertEqual({x['output'] for x in index['outputs']},{'file:research-report.md','file:bytes.bin','message:0'})
        page=self.runtime.work_output(leaf['id'],'file:research-report.md',offset=7,length=8)
        self.assertEqual(base64.b64decode(page['base64']),b'per-invo')
        self.assertFalse(page['view_complete']);self.assertEqual(page['elision']['omitted_before'],7)
        binary=self.runtime.work_output(leaf['id'],'file:bytes.bin',length=2)
        self.assertIsNone(binary['text']);self.assertEqual(base64.b64decode(binary['base64']),b'\xff\x00')
        self.assertEqual(self.runtime.work_output(leaf['id'],'message:0')['text'],'Actual public review response.')
        context_seen=[]
        def native_fixture(*args,**kwargs):
            context_seen.append(json.loads(Path(kwargs['inputs']['runtime-context.json']).read_text()))
            return {'shutdown':{'status':'exited'},'environment_shutdown':{'confirmed':True},'files':{},'artifacts':{},'completed_turns':[]}
        assignment=self.runtime.host.inspect(returning['operation'])['request']
        path=self.runtime.host.operation_dir(returning['operation'])/'assignment.json';ops.atomic(path,assignment)
        with self.runtime.host.tx() as db:db.execute("UPDATE operations SET state='running',owner=? WHERE id=?",(ops.encoded(ops.process_identity(os.getpid())),returning['operation']))
        with patch.object(runtime,'native',side_effect=native_fixture):self.runtime.measure('research',path)
        actual=context_seen[0]
        self.assertEqual(actual['returned_work'][0]['outcome'],completed['outcome']['object'])
        self.assertNotIn('measurement',actual['predecessor_outcome'])
        self.assertEqual(actual['returned_work'][0]['outputs'][0]['producer_workspace'],'/workspace')
        self.assertIn('not consumer/project root',actual['returned_work'][0]['outputs'][0]['location_scope'])
        (self.runtime.root/'native-actions'/leaf['operation']/'w/bytes.bin').unlink()
        unavailable=self.runtime.work_output(leaf['id'],'file:bytes.bin')
        self.assertFalse(unavailable['available']);self.assertEqual(unavailable['descriptor']['bytes'],5)

    def test_capability_facts_expose_selection_rights_and_real_output_scope(self):
        self.start();view=runtime.RuntimeController(self.runtime,self.operation).describe()
        self.assertTrue(view['offered']['research']['can_select'])
        self.assertFalse(view['offered']['edit']['can_select'])
        self.assertEqual(view['offered']['edit']['select'],[])
        self.assertEqual(view['offered']['edit']['project_writable'],['policies'])
        self.assertEqual(view['offered']['edit']['output_scope']['per_invocation_workspace'],'/workspace')
        self.assertFalse(view['offered']['exercise']['project_mounted'])
        self.assertEqual(view['offered']['exercise']['project_writable'],[])

    def test_cancelled_responsibility_cannot_activate_a_late_call_return(self):
        view=self.start();selected=self.select(view,call={
            'work':{'capability':'measure'},'return_to':{'capability':'research','prompt':'Retained return'}})
        self.finish();self.runtime.tick()
        leaf=next(x for x in self.runtime.choices() if x['id']==selected['choice'])
        self.runtime.control('cancel','cancel-call')
        self.finish(leaf['operation'],execution='cancelled');self.runtime.tick()
        returning=next(x for x in self.runtime.choices() if x['id'].startswith('return.'))
        self.assertEqual(returning['state'],'stale')
        self.assertIsNone(returning['operation'])
        self.assertTrue(self.runtime.host.inbox('research')['cancelled'])

    def test_output_view_preserves_inline_bytes_and_never_follows_redirected_large_artifact(self):
        view=self.start();selected=self.select(view,call={
            'work':{'capability':'edit','prompt':'Retain outputs'},
            'return_to':{'capability':'research','prompt':'Use retained outputs'}})
        self.finish();self.runtime.tick()
        leaf=next(x for x in self.runtime.choices() if x['id']==selected['choice'])
        self.native_result(leaf['operation'],{'report.txt':'captured report'},binary={'raw.bin':b'x'*3000})
        workspace=self.runtime.root/'native-actions'/leaf['operation']/'w'
        (workspace/'report.txt').unlink()
        self.assertEqual(self.runtime.work_output(leaf['id'],'file:report.txt')['text'],'captured report')
        private=self.base/'private';private.write_bytes(b'private bytes must not be read')
        (workspace/'raw.bin').unlink();(workspace/'raw.bin').symlink_to(private)
        with self.assertRaises(OSError):self.runtime.work_output(leaf['id'],'file:raw.bin')
        (workspace/'raw.bin').unlink();(workspace/'raw.bin').write_bytes(b'y'*3000)
        with self.assertRaisesRegex(ValueError,'hash differs'):
            self.runtime.work_output(leaf['id'],'file:raw.bin')
        with self.assertRaisesRegex(ValueError,'retained manifest'):
            self.runtime.work_output(leaf['id'],'file:../../private')


if __name__ == '__main__':unittest.main()
