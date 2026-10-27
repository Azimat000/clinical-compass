"""Author's synthetic mechanics checks, not independent clinical validation."""
from copy import deepcopy
from datetime import datetime, timedelta
import unittest

from apps.compass import backend_medication_safety as safety


class MedicationSafetyTests(unittest.TestCase):
    def setUp(self):
        self.catalog = safety.release()
        self.pid = 'elicea'
        self.candidate = dict(product_id=self.pid, form='film_coated_tablet',
            strength_mg=10, unit='mg', indication='adult_depression',
            daily_dose_mg=10, times_per_day=1, phase='maintenance')
        self.patient = {'mode': 'synthetic_only', 'synthetic': True}
        self.fact('age', 40)
        for p in self.catalog['products'].values():
            for field in p['required_facts']:
                self.fact(field, False)
        self.fact('allergies', [])
        self.fact('allergies_complete', True)
        self.fact('medications', [])
        self.fact('medications_complete', True)
        self.at = datetime.fromisoformat(self.catalog['sources']['elicea']['checked_at'])

    def fact(self, key, value):
        self.patient[key] = {'value': value, 'refs': ['synthetic:reviewed:' + key]}

    def result(self):
        return safety.evaluate(self.candidate, self.patient, at=self.at)

    def gate(self, key):
        return next(c for c in self.result()['checks'] if c['code'] == key)

    def med(self, **kwargs):
        self.fact('medications', [dict(state='current', refs=['synthetic:med'], **kwargs)])

    def test_catalog_substantive_and_facts_pinned(self):
        self.assertEqual(set(self.catalog['products']), {'elicea', 'aleval', 'aviandr'})
        for p in self.catalog['products'].values():
            self.assertGreaterEqual(len(p['required_facts']), 5)
            self.assertGreaterEqual(len(p['interactions']), 2)
            src = self.catalog['sources'][p['source_id']]
            self.assertTrue(src['pdf_url'].startswith('https://grls.rosminzdrav.ru/'))
            self.assertEqual(len(src['pdf_sha256']), 64)
            for section in ('form', 'age', 'indications', 'contraindications', 'cautions', 'dose', 'interactions'):
                self.assertTrue(src['locators'][section])

    def test_no_safety_or_release_inference(self):
        report = self.result()
        self.assertEqual(report['state'], 'unknown')
        self.assertFalse(report['eligible'])
        self.assertFalse(report['clinical_release'])
        self.assertFalse(report['applied'])
        self.assertEqual(self.gate('dose')['state'], 'pass')
        self.assertEqual(self.gate('coverage')['state'], 'unknown')

    def test_duplicate_same_ingredient_another_name(self):
        self.med(ingredient='escitalopram', name='Иное торговое название')
        self.assertEqual(self.gate('medication_0')['state'], 'block')
        self.assertEqual(self.result()['state'], 'block')

    def test_same_product_mapping_and_contradiction(self):
        self.med(product_id='elicea')
        self.assertEqual(self.gate('medication_0')['state'], 'block')
        self.med(product_id='elicea', ingredient='sertraline')
        self.assertEqual(self.gate('medication_0')['state'], 'unknown')

    def test_maoi_and_pimozide(self):
        for ingredient in ('irreversible_nonselective_maoi', 'pimozide'):
            with self.subTest(ingredient=ingredient):
                self.med(ingredient=ingredient)
                self.assertEqual(self.gate('medication_0')['state'], 'block')
                self.assertTrue(self.gate('medication_0')['source']['pages'])

    def test_unknown_interaction_and_recent_stopped(self):
        self.med(ingredient='unknown_medicine')
        self.assertEqual(self.gate('medication_0')['state'], 'unknown')
        self.fact('medications', [{'ingredient': 'maoi', 'state': 'recently_stopped', 'refs': ['synthetic:med']}])
        self.assertEqual(self.gate('medication_0')['state'], 'unknown')

    def test_absent_current_medications_not_empty(self):
        del self.patient['medications']
        self.assertEqual(self.gate('medications')['state'], 'unknown')
        self.fact('medications', [])
        del self.patient['medications_complete']
        self.assertEqual(self.gate('medications_complete')['state'], 'unknown')

    def test_allergy_and_completeness(self):
        self.fact('allergies', ['escitalopram'])
        self.assertEqual(self.gate('allergies')['state'], 'block')
        self.fact('allergies', [])
        del self.patient['allergies_complete']
        self.assertEqual(self.gate('allergies_complete')['state'], 'unknown')

    def test_missing_or_narrative_individual_fact(self):
        key = self.catalog['products'][self.pid]['required_facts'][0]
        for value in (None, 'нет', {'value': False}, {'value': False, 'refs': []}):
            with self.subTest(value=value):
                self.patient[key] = value
                self.assertEqual(self.gate(key)['state'], 'unknown')

    def test_positive_contraindication(self):
        for key in self.catalog['products'][self.pid]['contraindicated_facts']:
            with self.subTest(key=key):
                self.fact(key, True)
                self.assertEqual(self.gate(key)['state'], 'block')
                self.fact(key, False)

    def test_caution_never_clearance(self):
        p = self.catalog['products'][self.pid]
        key = next(k for k in p['required_facts'] if k not in p['contraindicated_facts'])
        self.fact(key, True)
        self.assertEqual(self.gate(key)['state'], 'unknown')

    def test_wrong_unit_form_strength(self):
        for key, value in [('unit', 'ml'), ('form', 'solution'), ('strength_mg', 15), ('strength_mg', True)]:
            with self.subTest(key=key, value=value):
                original = self.candidate[key]
                self.candidate[key] = value
                self.assertEqual(self.gate(key)['state'], 'block')
                self.candidate[key] = original

    def test_free_text_dose_and_invalid_numeric(self):
        for value in ('10 мг', '10', True, 0, -1, 21, float('inf'), float('nan')):
            with self.subTest(value=value):
                self.candidate['daily_dose_mg'] = value
                if type(value) is float and (value != value or value == float('inf')):
                    with self.assertRaises(ValueError): self.result()
                else: self.assertEqual(self.gate('dose')['state'], 'block')

    def test_age_and_elderly_maximum(self):
        for value, state in [(None, 'unknown'), (True, 'unknown'), ('40', 'unknown'), (17, 'block'), (40, 'pass')]:
            self.fact('age', value)
            self.assertEqual(self.gate('age')['state'], state)
        self.fact('age', 70)
        self.candidate['daily_dose_mg'] = 20
        self.assertEqual(self.gate('dose')['state'], 'block')

    def test_unsupported_indication_phase_and_frequency(self):
        self.candidate['indication'] = 'free_text_diagnosis'
        self.assertEqual(self.gate('indication')['state'], 'unknown')
        self.candidate['phase'] = 'titration'
        self.assertEqual(self.gate('regimen_phase')['state'], 'unknown')
        self.candidate['times_per_day'] = 2
        self.assertEqual(self.gate('frequency')['state'], 'block')

    def test_aviandr_and_aleval_differ(self):
        for pid, strength, daily, times, indication in [
            ('aleval', 50, 50, 1, 'adult_depression'),
            ('aviandr', 20, 40, 2, 'adult_gad')]:
            self.candidate.update(product_id=pid, strength_mg=strength,
                                  daily_dose_mg=daily, times_per_day=times, indication=indication)
            self.assertEqual(self.gate('dose')['state'], 'pass')
            self.assertEqual(self.gate('indication')['state'], 'pass')
            self.assertFalse(self.result()['eligible'])
        self.fact('age', 18)
        self.assertEqual(self.gate('age')['state'], 'unknown')
        self.fact('age', 19)
        self.assertEqual(self.gate('age')['state'], 'pass')
        self.fact('hepatic_failure_child_pugh_a_b_c', True)
        self.assertEqual(self.gate('hepatic_failure_child_pugh_a_b_c')['state'], 'block')

    def test_source_expiry_and_clock_boundaries(self):
        self.assertEqual(self.gate('source_freshness')['state'], 'pass')
        self.assertEqual(self.gate('source')['state'], 'unknown')
        due = datetime.fromisoformat(self.catalog['sources'][self.pid]['review_due_at'])
        self.at = due
        self.assertEqual(self.gate('source_freshness')['state'], 'unknown')
        self.at = datetime.fromisoformat(self.catalog['sources'][self.pid]['checked_at']) - timedelta(seconds=1)
        self.assertEqual(self.gate('source_freshness')['state'], 'unknown')

    def test_unknown_product_and_real_mode(self):
        self.candidate['product_id'] = 'not_registered_here'
        self.assertEqual(self.gate('product')['state'], 'unknown')
        self.patient['synthetic'] = False
        self.assertEqual(self.result()['state'], 'block')

    def test_input_is_immutable_and_hash_bound(self):
        before = deepcopy((self.candidate, self.patient))
        report = self.result()
        self.assertEqual(before, (self.candidate, self.patient))
        self.fact('age', 41)
        self.assertNotEqual(report['input_sha256'], self.result()['input_sha256'])
        report['checks'][0]['state'] = 'block'
        with self.assertRaises(ValueError): safety.verify(*before, report, at=self.at)

    def test_malformed_entry_is_unknown(self):
        for entry in ('не принимает', {'ingredient': 'maoi'}, {'ingredient': 'maoi', 'refs': ['x']}):
            self.fact('medications', [entry])
            self.assertEqual(self.gate('medication_0')['state'], 'unknown')

    def test_integrity_verification_and_expiry(self):
        report = self.result()
        self.assertTrue(safety.verify(self.candidate, self.patient, report, at=self.at))
        with self.assertRaises(ValueError):
            safety.verify(self.candidate, self.patient, report, at=datetime.fromisoformat(report['expires_at']))
        with self.assertRaises(ValueError):
            safety.verify(self.candidate, self.patient, report, at=self.at - timedelta(seconds=1))

    def test_tablet_divisibility_is_not_assumed(self):
        self.candidate.update(product_id='aleval', strength_mg=50, daily_dose_mg=75)
        self.assertEqual(self.gate('tablet_divisibility')['state'], 'unknown')
        self.candidate.update(product_id='elicea', strength_mg=10, daily_dose_mg=15)
        self.assertEqual(self.gate('tablet_divisibility')['state'], 'pass')

    def test_evidence_and_catalog_tampering(self):
        import json
        from pathlib import Path
        import tempfile
        report = self.result()
        root, path = safety.ROOT, safety.CATALOG
        with tempfile.TemporaryDirectory() as tmp:
            try:
                safety.ROOT = Path(tmp)
                safety.CATALOG = Path(tmp) / 'catalog.json'
                cat = deepcopy(self.catalog)
                evidence = Path(tmp) / cat['evidence']
                evidence.parent.mkdir(parents=True)
                evidence.write_bytes((root / cat['evidence']).read_bytes())
                safety.CATALOG.write_text(json.dumps(cat))
                self.assertTrue(safety.verify(self.candidate, self.patient, report, at=self.at))
                cat['products'][self.pid]['daily_mg'][1] = 30
                safety.CATALOG.write_text(json.dumps(cat))
                with self.assertRaises(ValueError): safety.verify(self.candidate, self.patient, report, at=self.at)
                evidence.write_text('Подменено')
                with self.assertRaises(ValueError): safety.release()
            finally:
                safety.ROOT, safety.CATALOG = root, path

    def test_explicit_structured_input_required(self):
        with self.assertRaises(ValueError): safety.evaluate('10 мг', self.patient)
        with self.assertRaises(ValueError): safety.evaluate({}, self.patient)
        with self.assertRaises(ValueError): safety.evaluate(self.candidate, self.patient, at=datetime(2026, 10, 27))


if __name__ == '__main__':
    unittest.main()
