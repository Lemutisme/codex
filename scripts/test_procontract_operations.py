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
        # A retained outcome may precede the last metadata launcher's exit.
        # Join our own control processes before deleting their journal fixture.
        spawned=[]
        original_popen=ops.subprocess.Popen
        def launch(*args,**kwargs):
            process=original_popen(*args,**kwargs);spawned.append(process);return process
        patcher=patch.object(ops.subprocess,'Popen',side_effect=launch)
        patcher.start();self.addCleanup(patcher.stop)
        self.addCleanup(lambda: [process.wait(timeout=10) for process in spawned])
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
            'control': ops.Measurement((sys.executable, str(self.runner)), ops.sha(self.runner.read_bytes()), 'fixture', True, effect_scope='fixture-counter')})
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
        self.host.subscribe('monitor','research',['operation_outcome'])
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
        self.assertIsNotNone(self.host.inbox('monitor')['pending'])
        with self.assertRaisesRegex(ValueError,'effect scope'):self.submit('conflicting')
        end=time.monotonic()+5
        while ops.alive(child) and time.monotonic()<end:time.sleep(.01)
        reconciled=self.host.reconcile('run')
        self.assertEqual(reconciled['outcome']['execution'],'interrupted')
        self.assertTrue(reconciled['outcome']['shutdown_confirmed'])
        self.assertIsNone(reconciled['outcome']['measurement'])
        self.assertEqual(self.submit('next')['state'],'reserved')

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
        # The fixture must reach the running child to exercise timeout cleanup.
        # A sub-second reservation can expire during process admission on a cold
        # interpreter; that is a different, valid execution outcome.
        self.submit(sleep=30, seconds=3)
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
        original_authority=self.host.authority
        self.host.authority=dataclasses.replace(original_authority,deadline=time.time()-1)
        committed=self.host.adopt('decision',candidate,incumbent['seq'],result,'scoped trial')
        self.host.authority=original_authority
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

    def test_imported_outcome_cannot_authorize_a_different_same_named_assignment(self):
        from procontract_evidence_bundle import export_objects,import_objects
        self.submit();original=self.complete();proof=original['outcome']['object']
        target=ops.Operations.create(self.root/'other',self.host.authority,{
            'control':ops.Measurement((sys.executable,str(self.runner)),ops.sha(self.runner.read_bytes()),'fixture',True)})
        target.subscribe('research','task',['observation'])
        definition=self.host.get(self.version)['definition'];definition['files']['tool.py']='unmeasured version'
        version=target.register(definition)
        target.submit('run','research',version,'control',{'counter':str(self.root/'new-counter')},'different assignment')
        import_objects(target,export_objects(self.host,[proof]))
        self.assertEqual(target.get(proof),self.host.get(proof))
        with self.assertRaisesRegex(ValueError,'another assignment'):
            target.adopt('decision',version,None,proof,'historical result is not this measurement')
        self.assertIsNone(target.incumbent()['version'])
        self.assertEqual(target.inspect('run')['state'],'reserved')
        self.assertFalse((self.root/'new-counter').exists())

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

    def test_owner_cancellation_stops_an_active_operation_without_renewing_its_assignment(self):
        original=self.submit(sleep=30)
        self.host.dispatch('run')
        until=time.monotonic()+5
        while not (self.root/'counter').exists() and time.monotonic()<until:time.sleep(.01)
        try:
            self.host.cancel_responsibility('research')
            while time.monotonic()<until:
                done=self.host.reconcile('run')
                if done['state']=='finished':break
                time.sleep(.01)
            self.assertEqual(done['outcome']['execution'],'cancelled')
            self.assertEqual(done['request'],original['request'])
        finally:
            self.host.cancel('run')
            while self.host.reconcile('run')['state']=='running' and time.monotonic()<until:time.sleep(.01)

    def test_initializer_recovers_after_configuration_before_schema_commit(self):
        import shutil
        recovery=self.root/'incomplete';recovery.mkdir()
        shutil.copy2(self.host.root/'host.json',recovery/'host.json')
        restored=ops.Operations.create(recovery,self.host.authority,{'control':ops.Measurement((sys.executable,str(self.runner)),ops.sha(self.runner.read_bytes()),'fixture',True,effect_scope='fixture-counter')})
        self.assertEqual(restored.read()['events'],[])

    def test_identical_submit_remains_readable_after_authority_expires(self):
        original=self.submit()
        self.host.authority=dataclasses.replace(self.host.authority,deadline=time.time()-1)
        self.assertEqual(self.submit(),original)

    def test_committed_adoption_receipt_remains_readable_after_authority_expires(self):
        original=self.host.bootstrap(self.version)
        with self.host.tx() as db:
            request=json.loads(db.execute("SELECT request FROM decisions WHERE id='bootstrap'").fetchone()[0])
        self.host.authority=dataclasses.replace(self.host.authority,deadline=time.time()-1)
        self.assertEqual(self.host.adopt('bootstrap',request['version'],None,request['evidence'],request['rationale']),original)

    def test_a_research_version_cannot_inherit_the_task_deployment_scope(self):
        self.host.bootstrap(self.version)
        definition=self.host.get(self.version)['definition'];definition['kind']='research'
        research=self.host.register(definition)
        self.host.submit('research-proof','research',research,'control',{'counter':str(self.root/'counter')},'scoped measurement')
        proof=self.complete('research-proof')['outcome']['object']
        with self.assertRaisesRegex(ValueError,'version kind'):
            self.host.adopt('wrong-scope',research,self.host.incumbent()['seq'],proof,'not a task version')

    def test_external_lifetime_requires_adapter_attestation_even_after_client_success(self):
        definition=self.host.get(self.version)['definition']
        self.host=ops.Operations.create(self.root/'external',self.host.authority,{'control':ops.Measurement(
            (sys.executable,str(self.runner)),ops.sha(self.runner.read_bytes()),'fixture',True,
            external_effects=True,effect_scope='external-test')})
        self.host.subscribe('research','task',['observation'])
        self.version=self.host.register(definition)
        self.submit();result=self.complete()['outcome']
        self.assertEqual(result['execution'],'completed')
        self.assertFalse(result['shutdown_confirmed'])
        with self.assertRaisesRegex(ValueError,'effect scope'):self.submit('conflicting')

    def test_boolean_event_wait_and_reconstructed_delivery_preserve_unacknowledged_input(self):
        self.host.wait('research',0,0,{'event':True})
        observation=self.host.observation(self.version,[],{}, {'quality':None},{},source='task')
        self.assertIsNotNone(self.host.inbox('research')['pending'])
        with self.host.tx() as db:
            db.execute("UPDATE inbox SET pending=NULL WHERE id='research'")
        restored=ops.Operations(self.host.root)
        pending=restored.wakes()[0]['pending']
        self.assertEqual(restored.read(after=pending-1)['events'][0]['object_id'],observation)
        restored.wait('research',0,pending,{'event':True})
        self.assertEqual(restored.wakes(),[])
        with self.assertRaisesRegex(ValueError,'subscription'):
            restored.wait('research',0,pending,{'event':'unoffered-event'})

    def test_defeated_settlement_is_not_a_current_incumbent_or_a_new_bootstrap(self):
        state=self.host.bootstrap(self.version)
        selected=self.host.incumbent()
        ops.kernel.apply(self.host.store,'defeat-exposed-basis',{'contract_id':state['id'],
            'expected_version':state['version'],'role':'verifier','provenance':'automation',
            'command':{'type':'defeat','target':{'type':'settlement','coordinate':state['settlement']['coordinate']},
                       'defeater':ops.kernel.digest('defeater','the claimed private evidence was reachable')}})
        current=self.host.incumbent()
        self.assertEqual(current['seq'],selected['seq'])
        self.assertIsNone(current['version'])
        self.assertEqual(current['selected_version'],self.version)
        with self.assertRaisesRegex(ValueError,'bootstrap'):
            self.host.bootstrap(self.version)


if __name__=='__main__':unittest.main()
