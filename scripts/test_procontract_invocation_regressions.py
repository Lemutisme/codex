import json
from pathlib import Path
import unittest
from procontract_invocation_outcomes import classify_execution, artifact_measurement_available, measurement_result, execution_digest, protocol_adjudication

class RetainedCaseTests(unittest.TestCase):
    def test_two_real_cancel_then_root_deadline_chains(self):
        cases=json.loads((Path(__file__).parent/'testdata/invocation-outcomes/pilot2_cases.json').read_text())
        self.assertEqual(len(cases),2)
        for c in cases:
            with self.subTest(case=c['task']):
                execution=classify_execution(c['requests'],cancellation_bindings=c['cancellation_bindings'],main_turn_status=c['main_turn_status'])
                reviewer=next(r for r in execution['requests'] if r['request_id']==c['cancellation_bindings'][0]['request_id'])
                self.assertEqual(reviewer['classification'],'cancellation_correlated_legacy_transport')
                self.assertEqual(reviewer['failure_origin'],'unknown')
                self.assertEqual(execution['main_turn_status'],'failed')
                self.assertEqual(execution['requests'][-1]['classification'],'original_deadline')
                self.assertTrue(artifact_measurement_available(effects_closed=c['effects_closed'],artifact_frozen=True,artifact_complete=c['frozen_artifact']['valid_artifact'],environment_qualified=True))
                incomplete=measurement_result(expected=c['expected_tests'],outcomes=[True],effects_closed=True)
                self.assertIsNone(incomplete['value']);self.assertFalse(incomplete['admissible'])
                # Test explicit trusted protocol review, not a mutation of real adjudication/outcome.
                decision={'execution_sha256':execution_digest(execution),'authority_ref':'test-owner-authority',
                          'evidence_refs':c['cancellation_bindings'][0]['source_ids'],'decision':'eligible'}
                self.assertTrue(protocol_adjudication(execution,decision,authorized_authority_refs=['test-owner-authority'])['eligible'])
                self.assertEqual(reviewer['failure_origin'],'unknown')

if __name__=='__main__':unittest.main()
