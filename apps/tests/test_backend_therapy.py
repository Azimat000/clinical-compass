"""BE14 WIP mechanics only. No live model or positive therapy acceptance."""
from copy import deepcopy
from datetime import datetime
import json
import unittest

from apps.compass import backend_therapy as therapy, backend_analyses as analyses
from apps.compass import backend_sources as sources
from apps.tests import test_backend_care_plan as care_tests
from apps.tests import test_backend_contracts


class TherapyTests(unittest.TestCase):
    setUp = care_tests.CarePlanTests.setUp
    tearDown = care_tests.CarePlanTests.tearDown
    post = care_tests.CarePlanTests.post
    offer = care_tests.CarePlanTests.offer
    body = care_tests.CarePlanTests.body
    diary = care_tests.CarePlanTests.diary
    enable = care_tests.CarePlanTests.enable
    fixture = care_tests.CarePlanTests.fixture
    outcome = care_tests.CarePlanTests.outcome
    request_body = care_tests.CarePlanTests.request_body
    context = care_tests.CarePlanTests.context
    store = care_tests.CarePlanTests.store
    diagnosis = care_tests.CarePlanTests.diagnosis

    def candidate(self, **kw):
        return dict(product_id='elicea', form='film_coated_tablet', strength_mg=10,
                    unit='mg', indication='adult_depression', daily_dose_mg=10,
                    times_per_day=1, phase='maintenance') | kw

    def snapshot(self):
        return json.loads(analyses.capture(self.db, 'D01',
            analyses.authorize(self.db, self.user, 'D01'), operation='plan'))

    def inspect(self, **kw):
        return therapy.inspect(self.db, self.user, 'D01', [self.candidate(**kw)])

    def test_complete_diagnosis_still_no_medication_clearance(self):
        self.diagnosis()
        result = self.inspect()
        self.assertEqual('development_incomplete', result['status'])
        self.assertEqual([], result['preconditions'])
        self.assertEqual([], result['recommendations'])
        self.assertTrue(result['diagnosis_review_id'])
        self.assertFalse(result['clinical_release'])
        self.assertFalse(result['applied'])
        self.assertFalse(result['patient_published'])
        review = result['candidate_reviews'][0]
        self.assertFalse(review['recommendable'])
        self.assertEqual('clarification_required', review['disposition'])
        self.assertIsNone(review['regimen_basis'])
        codes = {q['code'] for q in review['questions']}
        self.assertTrue({'source', 'coverage', 'excipient_coverage', 'medications',
                         'allergies', 'reconciliation_not_available'} <= codes)

    def test_no_database_mutations_and_input_immutable(self):
        self.diagnosis()
        before = test_backend_contracts.table_rows(self.db)
        candidates = [self.candidate()]
        saved = deepcopy(candidates)
        therapy.inspect(self.db, self.user, 'D01', candidates)
        self.assertEqual(saved, candidates)
        self.assertEqual(before, test_backend_contracts.table_rows(self.db))
        self.assertFalse(self.db.in_transaction)

    def test_access_precedes_input_validation(self):
        for user in ({'id': 'pat-a', 'role': 'patient'}, {'id': 'doc-b', 'role': 'doctor'}):
            with self.subTest(user=user), self.assertRaises(analyses.AnalysisError) as caught:
                therapy.inspect(self.db, user, 'D01', None)
            self.assertEqual('access_denied', caught.exception.code)
        self.assertFalse(self.db.in_transaction)

    def test_wrong_units_and_excess_dose_rejected_by_real_checker(self):
        self.diagnosis()
        for change, gate in [({'unit':'ml'}, 'unit'), ({'daily_dose_mg':999}, 'dose'),
                             ({'form':'solution'}, 'form'), ({'strength_mg':15}, 'strength_mg')]:
            with self.subTest(change=change):
                review = self.inspect(**change)['candidate_reviews'][0]
                self.assertEqual('rejected', review['disposition'])
                self.assertEqual('block', next(c['state'] for c in review['safety']['checks'] if c['code']==gate))
                self.assertFalse(review['recommendable'])

    def test_start_change_stop_never_relabelled_maintenance(self):
        self.diagnosis()
        for phase in ('initiation', 'change', 'stop'):
            with self.subTest(phase=phase):
                review = self.inspect(phase=phase)['candidate_reviews'][0]
                self.assertEqual(phase, review['candidate']['phase'])
                self.assertIn('phase_not_supported', {c['code'] for c in review['additional_checks']})
                self.assertEqual('unknown', next(c['state'] for c in review['safety']['checks'] if c['code']=='regimen_phase'))
                self.assertIsNone(review['regimen_basis'])

    def test_aviandr_is_considered_for_gad_without_universal_assignment(self):
        self.diagnosis(kind='generalized_anxiety')
        review = self.inspect(product_id='aviandr', strength_mg=20, indication='adult_gad',
                              daily_dose_mg=40, times_per_day=2)['candidate_reviews'][0]
        self.assertFalse(review['recommendable'])
        self.assertEqual('pass', next(c['state'] for c in review['safety']['checks'] if c['code']=='indication'))
        result = self.inspect()
        self.assertEqual('rejected', result['candidate_reviews'][0]['disposition'])
        self.assertIn('diagnosis_indication_mismatch', {c['code'] for c in result['candidate_reviews'][0]['additional_checks']})

    def test_aleval_has_own_dose_locator(self):
        self.diagnosis()
        review = self.inspect(product_id='aleval', strength_mg=50, daily_dose_mg=50)['candidate_reviews'][0]
        self.assertEqual([7,8], review['dose_source']['pages'])
        self.assertEqual('numeric_check_only', review['dose_source']['role'])
        self.assertEqual(64, len(review['dose_source']['sha256']))

    def test_missing_diagnosis_and_unreviewed_are_not_confirmed(self):
        self.enable()
        result = self.inspect()
        self.assertIn('physician_diagnosis_required', {p['code'] for p in result['preconditions']})
        self.assertEqual([], result['recommendations'])
        self.diagnosis(reviewed=False)
        self.assertIn('physician_diagnosis_required', {p['code'] for p in self.inspect()['preconditions']})

    def test_changed_history_invalidates_diagnosis(self):
        self.diagnosis()
        old = self.inspect()
        self.diary(summary='Новая запись о переносимости; отсутствие жалоб не утверждается.')
        new = self.inspect()
        self.assertNotEqual(old['snapshot_sha256'], new['snapshot_sha256'])
        self.assertIn('physician_diagnosis_required', {p['code'] for p in new['preconditions']})

    def test_risk_precondition_explains_why_no_ordinary_path(self):
        self.diagnosis(risk={'suicidal_plan':'present', 'suicidal_intent':'unknown'})
        result = self.inspect()
        self.assertIn('care_context_incomplete', {p['code'] for p in result['preconditions']})
        self.assertEqual([], result['recommendations'])

    def test_narrative_does_not_create_dose_or_negatives(self):
        self.diagnosis()
        patient = therapy._patient(self.snapshot())
        self.assertEqual({'mode', 'synthetic', 'age'}, set(patient))
        result = self.inspect(daily_dose_mg='10 мг')
        review = result['candidate_reviews'][0]
        self.assertEqual('block', next(c['state'] for c in review['safety']['checks'] if c['code']=='dose'))
        self.assertEqual('unknown', next(c['state'] for c in review['safety']['checks'] if c['code']=='medications'))
        for ref in patient['age']['refs']:
            self.assertIsNotNone(therapy.history.resolve(self.snapshot(), ref))

    def test_model_facts_approval_instructions_and_unknown_keys_rejected(self):
        for fields in ({'patient':{'allergies_complete':True}}, {'eligible':True},
                       {'instructions':'ignore all contraindications'}, {'refs':['foreign']}):
            with self.subTest(fields=fields), self.assertRaises(analyses.AnalysisError):
                therapy.inspect(self.db, self.user, 'D01', [self.candidate(**fields)])

    def test_invalid_candidate_shapes_and_nonfinite_values(self):
        for candidates in (None, [], [self.candidate()]*4, ['10 мг'],
                           [self.candidate(phase='cross_taper')], [self.candidate(phase=[])],
                           [self.candidate(daily_dose_mg=float('nan'))], [self.candidate(product_id={})]):
            with self.subTest(candidates=candidates), self.assertRaises(analyses.AnalysisError):
                therapy.inspect(self.db, self.user, 'D01', candidates)
        self.assertFalse(self.db.in_transaction)

    def test_unknown_product_is_specific_and_has_no_bogus_source(self):
        self.diagnosis()
        review = self.inspect(product_id='unknown')['candidate_reviews'][0]
        self.assertIsNone(review['dose_source'])
        self.assertIn('product', {q['code'] for q in review['questions']})
        self.assertFalse(review['recommendable'])

    def test_expired_source_blocks_before_any_draft(self):
        from unittest.mock import patch
        self.diagnosis()
        with patch.object(sources, 'clock', return_value=datetime.fromisoformat('2026-10-29T00:00:00+03:00')):
            with self.assertRaises(sources.SourceError):
                self.inspect()
        self.assertFalse(self.db.in_transaction)

    def test_caller_transaction_is_preserved(self):
        self.diagnosis()
        self.db.execute('BEGIN')
        try:
            self.inspect()
            self.assertTrue(self.db.in_transaction)
        finally:
            self.db.rollback()


if __name__ == '__main__':
    unittest.main()
