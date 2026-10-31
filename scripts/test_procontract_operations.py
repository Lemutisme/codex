"""Fault controls for generic operations; no model inference."""
import dataclasses
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
import tempfile

import procontract_operations as ops


class OperationsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runner = self.root / 'measure.py'
        self.runner.write_text('''import json,sys,time
from pathlib import Path
p=Path(sys.argv[1]);a=json.loads(p.read_text())
q=a['request']['inputs'];counter=Path(q['counter'])
with counter.open('a') as f:f.write('effect\\n')
time.sleep(q.get('sleep',0))
(p.parent/'result.json').write_text(json.dumps({'validity':'valid','admissible':True,'quality':1}))
''')
        authority = ops.Authority('test-owner', 'fixture-authorization', 'isolated-test', ('tool.py',), ('control',), True)
        self.host = ops.Operations.create(self.root / 'host', authority, {
            'control': ops.Measurement((sys.executable, str(self.runner)), ops.sha(self.runner.read_bytes()), 'fixture', True)})
        self.host.subscribe('research', 'task', ['observation', 'operation_outcome'])
        self.version = self.host.register({'kind': 'task', 'files': {'tool.py': 'print(0)', 'work_method.md': 'inspect', 'continuation.md': 'choose'},
            'build': {'code': 'fixture'}, 'model': {'name': 'fixture'}, 'resolver': 'fixture-v1', 'tools': {}})

    def submit(self, name='run', sleep=0, seconds=None):
        return self.host.submit(name, 'research', self.version, 'control', {'counter': str(self.root/'counter'), 'sleep': sleep}, 'fault control', seconds)

    def complete(self, name='run'):
        self.host.dispatch(name)
        end = time.monotonic()+10
        while time.monotonic()<end:
            state = self.host.reconcile(name)
            if state['state']=='finished':return state
            time.sleep(.025)
        self.fail('operation did not finish')

    def test_duplicate_delivery_and_restart_do_not_duplicate_dispatch_or_renew_allocation(self):
        original = self.submit(seconds=2)
        self.host.dispatch('run')
        self.host.dispatch('run')
        self.host = ops.Operations(self.host.root)
        done = self.complete()
        self.assertEqual((self.root/'counter').read_text(), 'effect\n')
        self.assertEqual(done['request'], original['request'])
        self.assertTrue(done['outcome']['shutdown_confirmed'])
        with self.assertRaisesRegex(ValueError,'conflicts'):
            self.submit(seconds=3)

    def test_lost_worker_does_not_reexecute_unknown_effect(self):
        self.submit(sleep=30)
        self.host.dispatch('run')
        end=time.monotonic()+5
        while not (self.root/'counter').exists() and time.monotonic()<end:time.sleep(.01)
        item=self.host.inspect('run')
        os.kill(item['owner']['pid'],signal.SIGKILL)
        while ops.alive(item['owner']) and time.monotonic()<end:time.sleep(.01)
        self.assertEqual(self.host.reconcile('run')['state'],'unknown')
        self.assertEqual(self.host.dispatch('run')['state'],'unknown')
        self.assertEqual((self.root/'counter').read_text(),'effect\n')
        child=json.loads((self.host.operation_dir('run')/'child.json').read_text())
        if ops.alive(child):os.killpg(child['pid'],signal.SIGKILL)

    def test_result_reconciliation_is_idempotent_after_receipt_before_commit(self):
        self.submit()
        real = self.host.reconcile
        with patch.object(self.host, 'reconcile', side_effect=RuntimeError('crash after receipt')):
            with self.assertRaises(RuntimeError):self.host.run_worker('run')
        result=real('run')
        self.assertEqual(result['state'],'finished')
        self.assertEqual(real('run'),result)
        self.assertEqual(len(self.host.read(kinds=['operation_outcome'])['events']),1)

    def test_cancellation_and_timeout_are_outcomes_not_zero_quality(self):
        self.submit(sleep=30, seconds=.15)
        done=self.complete()
        self.assertEqual(done['outcome']['execution'],'timed_out')
        self.assertIsNone(done['outcome']['measurement'])
        self.submit('cancel',sleep=30)
        self.host.cancel('cancel')
        done=self.complete('cancel')
        self.assertEqual(done['outcome']['execution'],'cancelled')
        self.assertEqual((self.root/'counter').read_text(),'effect\n')

    def test_pending_input_survives_selector_failure_and_selected_wait_coalesces(self):
        ids=[self.host.observation(self.version, [], {'measurement':'unavailable'}, {'quality':None}, {},source='task')]
        self.host.decision_failed('research','transport failure')
        before=self.host.inbox('research')
        self.assertIsNotNone(before['pending'])
        self.assertEqual(ops.Operations(self.host.root).wakes()[0],before)
        self.host.wait('research',0,before['pending'],{'event':'observation'})
        self.assertEqual(self.host.wakes(),[])
        for i in range(3):ids.append(self.host.observation(self.version,ids[-1:],{}, {'i':i},{},source='task'))
        self.assertEqual(len(self.host.wakes()),1)
        self.host.cancel_responsibility('research')
        self.assertEqual(self.host.wakes(),[])
        with self.assertRaisesRegex(ValueError,'stale'):
            self.host.wait('research',0,before['pending'],{})

    def test_knowledge_does_not_adopt_and_version_kind_and_scope_are_fenced(self):
        observation=self.host.observation(self.version,[],{}, {'quality':None}, {},source='task')
        self.host.knowledge(self.version,[observation],'possibly a method error','not measured')
        self.assertEqual(self.host.incumbent()['version'],None)
        definition=self.host.get(self.version)['definition']
        definition['kind']='research'
        with self.assertRaisesRegex(ValueError,'lineage'):self.host.register(definition,self.version)
        definition['kind']='task';definition['files']['continuation.md']='override'
        with self.assertRaisesRegex(ValueError,'scope'):self.host.register(definition,self.version)
        self.assertEqual(self.host.get(self.version)['definition']['files']['continuation.md'],'choose')

    def test_actual_kernel_adoption_lost_ack_stale_fence_and_delegated_provenance(self):
        self.host.bootstrap(self.version)
        incumbent=self.host.incumbent()
        definition=self.host.get(self.version)['definition']
        definition['files']['tool.py']='print(1)'
        candidate=self.host.register(definition,self.version)
        self.host.submit('candidate','research',candidate,'control',{'counter':str(self.root/'counter')},'sealed scope check')
        result=self.complete('candidate')['outcome']['object']
        adopt=ops.kernel.adopt
        def lost(*args,**kwargs):
            adopt(*args,**kwargs)
            raise RuntimeError('lost adoption acknowledgement')
        with patch.object(ops.kernel,'adopt',lost):
            with self.assertRaisesRegex(RuntimeError,'lost'):
                self.host.adopt('decision',candidate,incumbent['seq'],result,'scoped trial')
        committed=self.host.adopt('decision',candidate,incumbent['seq'],result,'scoped trial')
        self.assertEqual(committed['standing'],'discharged')
        self.assertEqual(self.host.incumbent()['version'],candidate)
        self.assertEqual(self.host.adopt('decision',candidate,incumbent['seq'],result,'scoped trial'),committed)
        with self.assertRaisesRegex(RuntimeError,'[Ii]ncumbent'):
            self.host.adopt('stale',candidate,incumbent['seq'],result,'another decision')
        with self.host.tx() as db:
            command=json.loads(db.execute("SELECT command FROM decisions WHERE id='decision'").fetchone()[0])
        self.assertEqual(command['provenance'],'delegate')
        self.assertEqual(command['command']['decision']['type'],'presumed')
        with self.assertRaises(ValueError):
            self.host.adopt('forged',self.version,self.host.incumbent()['seq'],result,'wrong version')

    def test_no_deadline_is_not_a_finite_sentinel(self):
        self.submit()
        self.assertIsNone(self.host.inspect('run')['request']['deadline'])
        altered=dataclasses.replace(self.host.authority,deadline=time.time()+100)
        with self.assertRaisesRegex(ValueError,'renewed'):
            ops.Operations.create(self.host.root,altered,{'control':ops.Measurement((),'', '')})

    def test_changed_measurement_is_unavailable_not_a_quality_score(self):
        self.submit()
        self.runner.write_text('raise RuntimeError("replaced evaluator")')
        result=self.complete()['outcome']
        self.assertEqual(result['execution'],'configuration_changed')
        self.assertIsNone(result['measurement'])
        self.assertFalse((self.root/'counter').exists())

    def test_cancelled_owner_cannot_adopt_and_nonfinite_limits_are_rejected(self):
        self.host.cancel_responsibility('research')
        with self.assertRaisesRegex(ValueError,'cancelled'):
            self.host.adopt('late',self.version,None,'unavailable','late',owner=('research',0))
        with self.assertRaises(ValueError):self.submit(seconds=float('nan'))

    def test_capability_socket_cannot_replace_authority_or_choose_unoffered_measurement(self):
        from procontract_operations_rpc import Broker
        with Broker(self.root/'socket',self.host,'research',measurements=('control',)) as broker:
            with self.assertRaisesRegex(ValueError,'scope'):
                broker.invoke('register',{'parent':self.version,'files':{'continuation.md':'overridden'}})
            with self.assertRaisesRegex(ValueError,'host-bound'):
                broker.invoke('adopt',{'owner':['research',0]})
            with self.assertRaisesRegex(ValueError,'not offered'):
                broker.invoke('submit',{'measurement':'untrusted'})
            with self.assertRaisesRegex(ValueError,'offered'):
                broker.invoke('bootstrap',{'version':self.version})


if __name__=='__main__':unittest.main()
