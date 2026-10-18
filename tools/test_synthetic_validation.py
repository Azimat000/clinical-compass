"""Deliberate corruption checks for the frozen benchmark's integrity gate."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from validate_synthetic import ROOT, validate


class DatasetIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(ROOT / 'data/synthetic', self.root / 'data/synthetic')

    def mutate(self, name, change):
        path = self.root / 'data/synthetic' / name
        data = json.loads(path.read_text())
        change(data)
        path.write_text(json.dumps(data, ensure_ascii=False))

    def fails_with(self, fragment):
        errors, _ = validate(self.root)
        self.assertTrue(any(fragment in e for e in errors), errors)

    def test_frozen_text_change_rejected(self):
        self.mutate('extraction-holdout.json', lambda d: d['records'][0].update(text='tampered text'))
        self.fails_with('frozen checksum mismatch')

    def test_profile_leakage_rejected(self):
        self.mutate('extraction-holdout.json', lambda d: d['records'][0].update(profile_id='SYN-DEV01'))
        self.fails_with('profile leakage')

    def test_age_and_date_only_paraphrase_rejected(self):
        dev = json.loads((self.root / 'data/synthetic/extraction-development.json').read_text())['records'][0]
        def change(data):
            record = data['records'][0]
            record['facts'] = dev['facts']
            record['critical_missing_fields'] = dev['critical_missing_fields']
            record['facts'][0]['value'] = 99
        self.mutate('extraction-holdout.json', change)
        self.fails_with('duplicate clinical input profile')

    def test_invented_source_span_rejected(self):
        self.mutate('extraction-development.json', lambda d: d['records'][0]['facts'][0].update(quote='absent'))
        self.fails_with('source span mismatch')

    def test_active_recommendation_rejected(self):
        self.mutate('cases.json', lambda d: d['cases'][0]['treatment_recommendations'].update(active=True))
        self.fails_with('action gate')

    def test_false_clinical_validation_rejected(self):
        self.mutate('extraction-holdout.json', lambda d: d['records'][0]['provenance'].update(clinical_gold=True))
        self.fails_with('unsupported clinical gold')

    def test_unknown_replaced_with_no_risk_rejected(self):
        self.mutate('extraction-development.json', lambda d: d['records'][3]['facts'][4].update(value=False))
        self.fails_with('unknown not null')


if __name__ == '__main__':
    unittest.main()
