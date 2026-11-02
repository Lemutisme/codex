import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from programbench_research_corpus import case,wanted


class RetainedCorpusControls(unittest.TestCase):
    def test_completed_first_admission_keeps_real_counters_and_exact_source_positions(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);run=root/'run';state=run/'codex-home/pro_contract';state.mkdir(parents=True)
            connection=sqlite3.connect(state/'ledger_1.sqlite')
            connection.executescript('CREATE TABLE experiment_events(seq INTEGER,event_json TEXT); CREATE TABLE subjects(subject_hash TEXT);')
            event={'kind':'execution','body':{'phase':'successor_returned','exit':'handoff'}}
            connection.execute('INSERT INTO experiment_events VALUES(1,?)',(json.dumps(event),))
            connection.execute("INSERT INTO subjects VALUES('artifact')");connection.commit();connection.close()
            rollout=run/'codex-home/sessions/rollout-fixture.jsonl';rollout.parent.mkdir()
            records=[{'type':'session_meta','payload':{'id':'root','source':'cli'}},
                {'type':'response_item','payload':{'type':'custom_tool_call','call_id':'c','name':'exec','input':'inspect'}},
                {'type':'response_item','payload':{'type':'custom_tool_call_output','call_id':'c','output':'observed'}},
                {'type':'response_item','payload':{'type':'message','role':'assistant','content':[{'text':'a hypothesis'}]}}]
            raw=''.join(json.dumps(r)+'\n' for r in records).encode();rollout.write_bytes(raw)
            result=run/'RESULT.json';result.write_text(json.dumps({'budget':{'used':7},'status':{'repairs_used':0}}))
            row={'task':'owner__case.rev','completion_result':str(result),'external':{'valid':True,'pass_rate':.8}}
            dossier=case(row,run,root/'index',True)
            self.assertEqual(dossier['result_source']['path'],str(result))
            self.assertEqual(dossier['native_status_snapshot']['repairs_used'],0)
            self.assertEqual(dossier['ledger']['phases']['successor_returned'],1)
            self.assertEqual(dossier['ledger']['distinct_captured_subjects'],1)
            session=dossier['sessions'][0]
            self.assertEqual(session['source']['sha256'],hashlib.sha256(raw).hexdigest())
            indexed=json.loads(Path(session['tool_index']['path']).read_text())
            for key,expected in [('call',records[1]),('output',records[2])]:
                location=indexed[key]
                self.assertEqual(json.loads(raw[location['offset']:location['offset']+location['length']]),expected)
            self.assertEqual(dossier['coverage']['semantic_root_cause_review'],'not asserted by this mechanical index')
            self.assertEqual(row['external']['pass_rate'],.8)
            self.assertEqual(case(row,run,root/'index',True),dossier)
            changed={**row,'external':{'valid':True,'pass_rate':.9}}
            with self.assertRaisesRegex(ValueError,'different inputs'):
                case(changed,run,root/'index',True)

    def test_archive_selection_cannot_escape_or_include_mutable_workspace(self):
        self.assertTrue(wanted('./codex-home/sessions/rollout-example.jsonl'))
        for path in ['../codex-home/sessions/rollout-example.jsonl','/codex-home/pro_contract/ledger_1.sqlite','workspace/result.json']:
            self.assertFalse(wanted(path))


if __name__=='__main__':unittest.main()
