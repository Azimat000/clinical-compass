#!/usr/bin/env python3
"""Regression probes: omissions and false completion must fail validation."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from validate_plan import ROOT, ready_id, validate


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'HAC'
        # Plan validation needs tracked evidence, not live databases, credentials,
        # installed runtimes or skill caches (which can also be cloud placeholders).
        shutil.copytree(ROOT, self.root, ignore=shutil.ignore_patterns(
            '.git', 'tmp', '__pycache__', 'var', '.venv', 'node_modules',
            'secrets', 'private-data', '.agents', '.claude', '.impeccable', '.taste-skill'))

    def tearDown(self):
        self.temp.cleanup()

    def mutate(self, name, operation):
        path = self.root / name
        data = json.loads(path.read_text())
        operation(data)
        path.write_text(json.dumps(data, ensure_ascii=False))

    def errors(self):
        return validate(self.root, check_git=False)[0]

    def test_valid_plan(self):
        self.assertEqual(self.errors(), [])

    def test_missing_requirement(self):
        self.mutate('plan/coverage.json', lambda d: d['items'].pop(0))
        self.assertTrue(any('Не все исходные' in e for e in self.errors()))

    def test_dependency_cycle(self):
        self.mutate('plan/manifest.json', lambda d: d['slices'][0]['depends_on'].append('S01'))
        self.assertTrue(any('Цикл' in e for e in self.errors()))

    def test_false_fulfilment(self):
        self.mutate('plan/coverage.json', lambda d: d['items'][0].update(fulfilment_status='fulfilled', actual_evidence=[]))
        self.assertTrue(any('без доказательств' in e for e in self.errors()))

    def test_budget_overflow(self):
        self.mutate('memory/BUDGET.json', lambda d: d.update(commitments=5001))
        self.assertTrue(any('Превышен' in e for e in self.errors()))

    def test_source_changed(self):
        with (self.root / 'research/sources/case.pdf').open('ab') as f:
            f.write(b'changed')
        self.assertTrue(any('изменён без' in e for e in self.errors()))

    def test_lost_subcondition(self):
        self.mutate('plan/coverage.json', lambda d: next(r for r in d['items'] if r['id'] == 'M08')['subchecks'].clear())
        self.assertTrue(any('потерян составной' in e for e in self.errors()))

    def test_unauthorized_postcontest(self):
        self.mutate('memory/STATE.json', lambda d: d.update(postcontest_authorized=False))
        self.mutate('memory/STATE.json', lambda d: d['slices']['S23'].update(status='accepted'))
        self.assertTrue(any('условная ветка не разрешена' in e for e in self.errors()))

    def test_independent_work_after_clinical_block(self):
        cards = json.loads((self.root / 'plan/manifest.json').read_text())['slices']
        state = json.loads((self.root / 'memory/STATE.json').read_text())
        state['current_slice'] = None
        for sid, entry in state['slices'].items():
            entry['status'] = 'planned'
        state['slices']['S00']['status'] = 'accepted'
        state['slices']['S01']['status'] = 'accepted'
        state['slices']['S02']['status'] = 'blocked'
        self.assertEqual(ready_id(cards, state), 'S04')

    def test_finalist_cannot_skip_final_preparation(self):
        cards = json.loads((self.root / 'plan/manifest.json').read_text())['slices']
        state = json.loads((self.root / 'memory/STATE.json').read_text())
        state.update(current_slice=None, qualification='qualified', postcontest_authorized=False)
        prefinal = {card['id'] for card in cards[:next(i for i, card in enumerate(cards) if card['id'] == 'S20')]}
        for sid, entry in state['slices'].items():
            entry['status'] = 'accepted' if sid in prefinal else 'planned'
        state['slices']['S20']['status'] = 'blocked'
        self.assertIsNone(ready_id(cards, state))
        state['qualification'] = 'not_qualified'
        self.assertEqual(ready_id(cards, state), 'S21')


if __name__ == '__main__':
    unittest.main(verbosity=2)
