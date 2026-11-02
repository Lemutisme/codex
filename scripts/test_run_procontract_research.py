"""Intake custody and invocation-allocation controls; no model inference."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import procontract_operations as ops
import run_procontract_research as research


class ResearchIntakeTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source.txt'
        self.source.write_text('Observed user feedback\nThe revision was measured under condition A.\n')
        self.context = self.root / 'context.md'
        self.context.write_text('Study this continuing connected task. No hard deadline was supplied.\n')
        self.index = self.root / 'index.json'
        self.index.write_text('{"population":["ordinary-task"]}\n')
        self.bundle = self.root / 'bundle.json'
        self.bundle.write_text(json.dumps({
            'schema': 'procontract-evidence-bundle-v1', 'source': 'arbitrary-experience',
            'sources': {'raw': {'path': str(self.source), 'sha256': research.digest(self.source)}},
            'records': [
                {'key': 'observation', 'subject': 'ordinary-task:attempt-1', 'sources': ['raw'],
                 'conditions': {'network': 'connected', 'hard_deadline': None},
                 'outcome': {'revision': 'measured'}},
                {'key': 'interpretation', 'subject': 'ordinary-task:attempt-1',
                 'sources': ['observation'], 'claim': True,
                 'outcome': {'hypothesis': 'Feedback was useful; necessary effect untested'}},
            ],
        }))
        self.package = self.root / 'package'
        (self.package / 'bin').mkdir(parents=True)
        (self.package / 'bin/codex').write_text('fixture-runtime')
        # Kernel/bootstrap is already controlled by the Operations suite. Here we
        # isolate input custody, caller choice and the native assignment boundary.
        for name in ('issue', 'bootstrap'):
            patcher = patch.object(ops.Operations, name)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(research.subprocess, 'check_output', return_value='sha256:fixture\n')
        self.image_inspect = patcher.start()
        self.addCleanup(patcher.stop)

    def prepare(self):
        self.run = self.root / 'run'
        manifest = research.prepare(
            self.run, self.package, 'fixture', self.bundle, self.context,
            inputs={'index.json': self.index}, authorization_source='fixture-user',
            scope='retain and investigate supplied evidence in isolation',
        )
        self.host = ops.Operations(self.run / 'host')
        self.manifest = manifest
        return manifest

    def test_arbitrary_population_inputs_keep_exact_bytes_and_distinct_claim_status(self):
        manifest = self.prepare()
        receipt = json.loads((self.run / 'inputs/intake.json').read_text())
        identities = receipt['import']['identities']
        observation = self.host.get(identities['observation'], 'observation')
        claim = self.host.get(identities['interpretation'], 'claim')
        self.assertEqual(observation['subject'], 'ordinary-task:attempt-1')
        self.assertEqual(claim['sources'], [identities['observation']])
        self.assertIsNone(self.host.authority.deadline)
        self.assertIsNone(manifest['model_request_limit'])
        self.assertEqual(receipt['inputs']['index.json']['actor_path'], '/inputs/index.json')
        self.source.write_text('Original file changed after retention')
        self.context.write_text('Changed later context')
        self.index.unlink()
        research.verify_inputs(self.run, manifest)
        self.assertIn('condition A', self.host.source_read(identities['raw'])['text'])
        self.assertIn('No hard deadline', Path(manifest['inputs']['study-context.md']['path']).read_text())
        self.assertEqual(len(self.host.receive('research')['events']), 3)
        self.assertEqual(self.host.read(kinds=['operation_outcome'])['events'], [])

    def test_changed_retained_context_fails_before_reservation_or_dispatch(self):
        manifest = self.prepare()
        path = Path(manifest['inputs']['study-context.md']['path'])
        path.chmod(0o600)
        path.write_text('silently replaced')
        with self.assertRaisesRegex(ValueError, 'retained input changed'):
            research.reserve(self.run, manifest, self.host)
        with self.host.tx() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM operations').fetchone()[0], 0)

    def test_duplicate_action_keeps_original_allocation_and_does_not_offer_adoption(self):
        manifest = self.prepare()
        with patch.object(self.host, 'incumbent', return_value={'version': manifest['version']}):
            first = research.reserve(self.run, manifest, self.host, seconds=60)
            repeated = research.reserve(self.run, manifest, self.host, seconds=60)
            self.assertEqual(first, repeated)
            with self.assertRaisesRegex(ValueError, 'conflicts'):
                research.reserve(self.run, manifest, self.host, seconds=61)
        assignment = first[1]['request']
        params = assignment['request']['inputs']
        self.assertEqual(params['seconds'], 60)
        self.assertEqual(params['offered_measurements'], [])
        self.assertIn('register', params['offered_operations'])
        self.assertNotIn('adopt', params['offered_operations'])
        self.assertNotIn('submit', params['offered_operations'])
        self.assertEqual(self.host.inspect(first[0])['state'], 'reserved')

    def test_no_action_deadline_and_no_pending_input_do_not_create_new_work(self):
        manifest = self.prepare()
        with patch.object(self.host, 'incumbent', return_value={'version': manifest['version']}):
            selected = research.reserve(self.run, manifest, self.host)
            self.assertIsNone(selected[1]['request']['request']['inputs']['seconds'])
            self.assertIsNone(selected[1]['request']['deadline'])
            page = self.host.receive('research')
            self.host.wait('research', page['epoch'], page['through'], {'event': True})
            self.assertIsNone(research.reserve(self.run, manifest, self.host))
        self.assertIsNone(self.host.authority.deadline)

    def test_invalid_action_allocation_fails_before_native_grace_can_mask_it(self):
        manifest = self.prepare()
        for seconds in (-30, 0, float('nan'), float('inf'), True):
            with self.subTest(seconds=seconds), self.assertRaisesRegex(ValueError, 'allocation'):
                research.reserve(self.run, manifest, self.host, seconds)
        with self.host.tx() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM operations').fetchone()[0], 0)

    def test_sources_only_bundle_still_delivers_the_caller_selected_study_request(self):
        bundle = json.loads(self.bundle.read_text())
        bundle['records'] = []
        self.bundle.write_text(json.dumps(bundle))
        self.prepare()
        receipt = json.loads((self.run / 'inputs/intake.json').read_text())
        events = self.host.receive('research')['events']
        self.assertEqual([event['object_id'] for event in events], [receipt['request']])
        request = self.host.get(receipt['request'], 'observation')
        self.assertEqual(request['sources'], [receipt['study_context_source']])
        self.assertIn('selected research request', request['outcome']['meaning'])

    def test_export_keeps_correction_and_counterevidence_closure_without_authority(self):
        self.prepare()
        receipt = json.loads((self.run / 'inputs/intake.json').read_text())
        observation = receipt['import']['identities']['observation']
        original = self.host.knowledge('ordinary-task:attempt-1', [observation], 'Method caused success', 'untested')
        corrected = self.host.knowledge(
            'ordinary-task:attempt-1', [observation], 'Association only', 'Causal effect unknown',
            supersedes=original, counterevidence=[observation], applicability='condition A',
        )
        result = research.export_knowledge(self.run, self.host)
        bundle = json.loads(Path(result['export']).read_text())
        self.assertEqual(bundle['roots'], [corrected])
        self.assertIn(original, [record['id'] for record in bundle['records']])
        self.assertEqual(result['retained_knowledge_records'], 2)
        self.assertFalse({'authorization', 'version', 'operation_outcome'} &
                         {record['kind'] for record in bundle['records']})

    def test_reserved_duplicate_and_path_input_names_are_rejected(self):
        for inputs in (['client.py=source'], ['a=x', 'a=y'], ['../escape=x'], ['missing-equals']):
            with self.subTest(inputs=inputs), self.assertRaises(ValueError):
                research.parse_inputs(inputs)


if __name__ == '__main__':
    unittest.main()
