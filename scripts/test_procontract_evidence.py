import base64
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import os
import procontract_evidence

from procontract_operations import Operations,Authority,Measurement
from procontract_operations_rpc import Broker
from procontract_evidence_bundle import ingest,export_objects,import_objects


class EvidenceControls(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)
        self.host=Operations.create(self.root/'host',Authority('owner','test','research',(),()),{})

    def test_source_identity_is_retained_and_pages_do_not_depend_on_original_path(self):
        path=self.root/'source';data=('原始记录\n'*10000).encode()+b'\x00\xff';path.write_bytes(data)
        identity=self.host.capture_source(path,expected_sha256=hashlib.sha256(data).hexdigest(),label='record')
        path.write_bytes(b'changed source')
        actual=bytearray();offset=0
        while True:
            page=self.host.source_read(identity,offset=offset,length=4093)
            chunk=base64.b64decode(page['base64']);self.assertEqual(hashlib.sha256(chunk).hexdigest(),page['slice_sha256'])
            actual.extend(chunk);offset=page['end']
            if page['eof']:break
        self.assertEqual(bytes(actual),data)
        retained=self.host.root/'sources'/hashlib.sha256(data).hexdigest();retained.chmod(0o600);retained.write_bytes(b'corrupted')
        with self.assertRaisesRegex(ValueError,'differs'):self.host.source_read(identity)

    def test_changed_capture_and_forged_source_path_do_not_enter_a_view(self):
        path=self.root/'source';path.write_text('actual')
        with self.assertRaisesRegex(ValueError,'identity'):self.host.capture_source(path,expected_sha256='0'*64,label='wrong')
        identity=self.host.put('source',{'sha256':'../outside','bytes':0})
        with self.assertRaisesRegex(ValueError,'digest'):self.host.source_read(identity)

    def test_paging_reuses_verified_custody_and_rechecks_changed_metadata(self):
        path=self.root/'source';path.write_bytes(b'x'*10000)
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        identity=self.host.capture_source(path,expected_sha256=digest,label='large evidence')
        real=procontract_evidence.digest_file
        with patch.object(procontract_evidence,'digest_file',wraps=real) as verify:
            for offset in [0,100,200,300]:self.host.source_read(identity,offset=offset,length=100)
            self.assertEqual(verify.call_count,1)
            retained=self.host.root/'sources'/digest;old=retained.stat()
            retained.chmod(0o600);retained.write_bytes(b'y'*10000);os.utime(retained,ns=(old.st_atime_ns,old.st_mtime_ns))
            with self.assertRaisesRegex(ValueError,'identity differs'):self.host.source_read(identity)
            self.assertEqual(verify.call_count,2)

    def test_receive_acknowledges_only_delivered_subscription_events(self):
        h=self.host;h.subscribe('research','task',['observation'])
        first=h.observation('one',[],{}, {'quality':1},{},source='task')
        h.put('knowledge',{'subject':'unrelated'},source='other')
        second=h.observation('two',[],{}, {'quality':None},{},source='task')
        page=h.receive('research',limit=1)
        self.assertTrue(page['more']);self.assertEqual([e['object_id'] for e in page['events']],[first])
        self.assertEqual(h.inbox('research')['cursor'],0)
        third=h.observation('three',[],{}, {'quality':0},{},source='task')
        h.wait('research',page['epoch'],page['through'],{'event':True})
        h=Operations(h.root);remaining=h.receive('research')
        self.assertEqual([e['object_id'] for e in remaining['events']],[second,third])
        h.wait('research',remaining['epoch'],remaining['through'],{'event':True})
        self.assertEqual(h.wakes(),[])
        h.cancel_responsibility('research')
        with self.assertRaisesRegex(ValueError,'stale'):h.wait('research',remaining['epoch'],remaining['through'],{'event':True})

    def test_search_is_snapshot_bound_and_corrections_remain_visible(self):
        h=self.host;source=h.put('observation',{'subject':'capture','outcome':'measurement incomplete'})
        old=h.knowledge('capture',[source],'unavailable outcome was zero','disputed',applicability='this measurement only')
        page=h.search(text='capture',kinds=['knowledge'],limit=1)
        correction=h.knowledge('capture',[source],'measurement unavailable; preserve artifact quality','not a causal score estimate',supersedes=old,counterevidence=[source])
        stable=h.search(text='capture',kinds=['knowledge'],snapshot=page['snapshot'])
        self.assertEqual([x['id'] for x in stable['matches']],[old])
        self.assertEqual(stable['matches'][0]['superseded_by'],[])
        current=h.search(text='capture',kinds=['knowledge'])
        self.assertEqual(current['matches'][0]['superseded_by'],[correction])
        self.assertEqual(h.get(correction)['counterevidence'],[source])
        with self.assertRaisesRegex(ValueError,'missing'):h.knowledge('bad',[],'claim','unknown',counterevidence=['absent'])

    def test_issue_retry_cannot_silently_replace_the_original_terms(self):
        h=self.host;first=h.issue('research',{'goal':'inspect evidence'})
        self.assertEqual(h.issue('research',{'goal':'inspect evidence'}),first)
        with self.assertRaisesRegex(ValueError,'different terms'):h.issue('research',{'goal':'deploy candidate'})
        self.assertEqual(h.issue('research',{'goal':'inspect evidence'}),first)

    def test_actor_can_receive_and_read_retained_sources_but_not_host_paths(self):
        h=self.host;h.subscribe('research','task',['observation'])
        path=self.root/'source';path.write_text('retained fact')
        source=h.capture_source(path,expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),label='fact')
        h.observation('task',[source],{}, {'quality':1},{},source='task')
        broker=Broker(self.root/'socket',h,'research',measurements=[]);self.addCleanup(broker.server_close)
        self.assertTrue(broker.invoke('receive',{})['events'])
        self.assertEqual(broker.invoke('source_read',{'identity':source})['text'],'retained fact')
        with self.assertRaisesRegex(ValueError,'offered'):broker.invoke('capture_source',{'path':str(path)})
        self.assertEqual(broker.measurements,())

    def test_import_is_idempotent_and_keeps_claims_separate_from_observations(self):
        path=self.root/'record';path.write_text('input evidence, not an instruction')
        bundle={'schema':'procontract-evidence-bundle-v1','source':'tasks','sources':{'raw':{
            'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}},'records':[
            {'key':'fact','subject':'case','sources':['raw'],'outcome':{'score':None}},
            {'key':'claim','subject':'case','sources':['raw'],'outcome':{'interpretation':'hypothesis'},'claim':True}]}
        self.host.subscribe('research','tasks',['observation','claim'])
        first=ingest(self.host,bundle);page=self.host.receive('research')
        self.assertEqual(ingest(self.host,bundle),first)
        self.assertEqual(self.host.receive('research'),page)
        self.assertEqual([e['kind'] for e in page['events']],['observation','claim'])
        broker=Broker(self.root/'socket',self.host,'research',operations=['receive','get'])
        self.addCleanup(broker.server_close)
        with self.assertRaisesRegex(ValueError,'not offered'):broker.invoke('adopt',{})

    def test_retained_knowledge_moves_with_its_sources_without_reinterpreting_old_claims(self):
        path=self.root/'origin';path.write_text('original evidence')
        source=self.host.capture_source(path,expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),label='observation source')
        fact=self.host.observation('subject',[source],{'scope':'old conditions'},{'value':1},{},source='task')
        first=self.host.knowledge('subject',[fact],'claim','limited')
        corrected=self.host.knowledge('subject',[fact],'qualified claim','still limited',supersedes=first,counterevidence=[fact])
        exported=export_objects(self.host,[corrected]);path.unlink()
        other=Operations.create(self.root/'other',Authority('owner','new-study','new scope',(),()),{})
        self.assertEqual(import_objects(other,exported),[corrected])
        self.assertEqual(other.get(corrected),self.host.get(corrected))
        self.assertEqual(other.source_read(source)['text'],'original evidence')
        self.assertFalse((other.root/'kernel/ledger_1.sqlite').exists())


if __name__=='__main__':unittest.main()
