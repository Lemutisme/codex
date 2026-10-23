"""Native observation selection and read-only planner capabilities; scripted provider."""
import os
import unittest
import test_procodex_native as fixture


@unittest.skipUnless(os.environ.get('PROCODEX_NATIVE_PACKAGE') and os.environ.get('PROCODEX_TEST_IMAGE'),
                     'requires a native package and isolated image')
class NativeWorkSelectionTests(unittest.TestCase):
    def run_selection(self, strategy, expected):
        case=fixture.NativeEvidenceTest('test_real_executor_and_reviewer_use_frozen_handles')
        case.selection_model=strategy
        case.expected_phase=expected
        case.task_seconds=None
        case.debug()
        return case

    def test_rest_preserves_delivery_without_an_automatic_review(self):
        case=self.run_selection(lambda _:dict(choice=dict(action='rest',reason='Retain the partial delivery.')), 'not_verified')
        self.assertEqual(case.native_commands,['issue','propose'])
        self.assertEqual(case.native_counts.get('review',0),0)
        self.assertFalse(any(e['kind']=='verification' for e in case.native_events))
        self.assertTrue(any(e['body'].get('phase')=='task_delivery' for e in case.native_events))

    def test_archive_read_local_check_and_diagnosis_precede_selected_acceptance(self):
        read=False
        def strategy(body):
            nonlocal read
            facts=fixture.continuation_facts(body);stage=facts['assessment']['stage']
            if stage=='handoff' and not read:
                read=True
                return [fixture.custom_call(body, '''
if (ALL_TOOLS.some(t=>t.name === "exec_command")) throw new Error("planner has mutable execution tools");
let index=await tools.contract_read_evidence({op:"index",offset:0});
if(typeof index === "string") index=JSON.parse(index);
text(await tools.contract_read_evidence({op:"read",handle:index.entries[0].handle,offset:0}));
text("planner-read-archive");
''', 'planner-read')]
            if stage=='handoff':
                self.assertIn('planner-read-archive','\n'.join(fixture.text_values(body['input'])))
                return dict(choice=dict(action='check',reason='Inspect the public build.'))
            if stage=='checks':return dict(choice=dict(action='diagnose',question='Does the frozen answer contain exactly ready?'))
            self.assertEqual(stage,'diagnosis')
            return dict(choice=dict(action='verify',reason='Now request full acceptance.'))
        case=self.run_selection(strategy,'supported')
        self.assertEqual(case.native_commands,['issue','propose','support'])
        local=[e['body'] for e in case.native_events if e['body'].get('phase')=='work_assessed']
        self.assertEqual([e['assessment_scope'] for e in local],['checks','diagnosis'])
        runs=[case.native_public[e['public_evidence']]['execution']['run_id'] for e in local]
        self.assertEqual(runs[0],runs[1], 'the diagnosis should reuse the completed check receipt')
        self.assertEqual(sum(e['kind']=='verification' for e in case.native_events),1)
        self.assertTrue(any(e['body'].get('phase')=='evidence_response_finished' for e in case.native_events))


if __name__=='__main__':unittest.main()
