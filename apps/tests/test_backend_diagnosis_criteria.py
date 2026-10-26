"""Structured-logic fixtures only; never model/clinical diagnostic quality."""
from copy import deepcopy
import itertools
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from apps.compass import backend_diagnosis_criteria as criteria
from apps.compass import backend_risk_context as context, backend_sources as sources
from apps.tests import test_backend_diagnoses as legacy
from apps.tests import test_backend_contracts


class CriteriaTests(unittest.TestCase):
    setUp = legacy.DiagnosisTests.setUp
    tearDown = legacy.DiagnosisTests.tearDown
    post = legacy.DiagnosisTests.post
    offer = legacy.DiagnosisTests.offer
    body = legacy.DiagnosisTests.body
    diary = legacy.DiagnosisTests.diary
    visit = legacy.DiagnosisTests.visit
    questionnaire = legacy.DiagnosisTests.questionnaire
    snapshot = legacy.DiagnosisTests.snapshot

    def fixture(self, kind='depressive_episode'):
        self.diary(summary='Авторское вымышленное основание для структурированного теста, не клиническая оценка.')
        snapshot = self.snapshot()
        units = context.prepare_snapshot(snapshot)
        unit = next(u for u in units if u['code'] == 'summary')
        catalog = criteria.release()
        condition = catalog['conditions'][kind]
        ev = [{'unit_id': unit['unit_id'], 'quote': unit['text']}]
        facts = {fid: {'state': 'present', 'evidence': deepcopy(ev)} for fid in condition['facts']}
        for check in condition['checks']:
            if check['state'] == 'denied':
                for fid in check['facts']:
                    facts[fid]['state'] = 'denied'
        value = {'kind': kind, 'facts': facts, 'duration': {
            'state': 'known', 'value': condition['duration']['minimum'],
            'unit': condition['duration']['unit'], 'evidence': deepcopy(ev)}}
        return snapshot, value, condition, units

    def result(self, snapshot, value):
        report = criteria.evaluate(snapshot, value, synthetic=True)
        self.assertEqual('unreviewed', report['status'], report['errors'])
        self.assertFalse(report['clinical_ready'])
        for key in ('established_diagnosis', 'diagnosis_code', 'plan'):
            self.assertIsNone(report[key])
        return report['assessment']

    def test_both_supported_structured_cases_and_all_four_sources_no_writes(self):
        self.visit();self.questionnaire(missing=True)
        for kind in ('depressive_episode', 'generalized_anxiety'):
            snapshot, value, _, units = self.fixture(kind)
            before = test_backend_contracts.table_rows(self.db)
            original = deepcopy(snapshot), deepcopy(value)
            with patch('apps.compass.backend_model.DeepSeek.generate', side_effect=AssertionError('no model')):
                result = self.result(snapshot, value)
            self.assertEqual('criteria_supported_unreviewed', result['outcome'])
            self.assertEqual({'questionnaires', 'wellbeing', 'anamnesis', 'visits'},
                             {c for u in units for c in u['categories']})
            self.assertEqual(before, test_backend_contracts.table_rows(self.db))
            self.assertEqual(original, (snapshot, value))
            self.assertTrue(all(c['check'] == 'met' for c in result['checks']))
            self.assertEqual([], result['unresolved_facts'])

    def test_duration_below_at_above_threshold_and_units(self):
        for kind in ('depressive_episode', 'generalized_anxiety'):
            snapshot, value, c, _ = self.fixture(kind)
            for n, expected in [(c['duration']['minimum'] - 1, 'criteria_not_demonstrated'),
                                (c['duration']['minimum'], 'criteria_supported_unreviewed'),
                                (c['duration']['minimum'] + 1, 'criteria_supported_unreviewed')]:
                value['duration']['value'] = n
                self.assertEqual(expected, self.result(snapshot, value)['outcome'])
            value['duration']['unit'] = 'days' if c['duration']['unit'] == 'months' else 'months'
            self.assertEqual('not_evaluated', criteria.evaluate(snapshot, value, synthetic=True)['status'])

    def test_each_count_threshold_below_and_at_minimum(self):
        for kind in ('depressive_episode', 'generalized_anxiety'):
            snapshot, original, condition, _ = self.fixture(kind)
            for check in condition['checks']:
                if check['state'] != 'present' or len(check['facts']) < 2:
                    continue
                for count, expected in [(check['minimum'] - 1, 'not_met'), (check['minimum'], 'met')]:
                    value = deepcopy(original)
                    for i, fid in enumerate(check['facts']):
                        value['facts'][fid]['state'] = 'present' if i < count else 'denied'
                    result = self.result(snapshot, value)
                    self.assertEqual(expected, next(c['check'] for c in result['checks'] if c['id'] == check['id']))

    def test_each_fact_unknown_remains_unresolved_never_supported(self):
        for kind in ('depressive_episode', 'generalized_anxiety'):
            snapshot, original, condition, _ = self.fixture(kind)
            for fid in condition['facts']:
                value = deepcopy(original)
                value['facts'][fid] = {'state': 'unknown', 'evidence': []}
                result = self.result(snapshot, value)
                self.assertEqual('insufficient_data', result['outcome'], fid)
                self.assertIn(fid, result['unresolved_facts'])
                self.assertIn(condition['facts'][fid]['question'], result['distinguishing_questions'])

    def test_all_explicit_exclusions_block_scope(self):
        for kind in ('depressive_episode', 'generalized_anxiety'):
            snapshot, original, condition, _ = self.fixture(kind)
            for fid in condition['unsupported_if']:
                value = deepcopy(original);value['facts'][fid]['state'] = 'present'
                result = self.result(snapshot, value)
                self.assertEqual('unsupported', result['outcome'], fid)
                self.assertIn(fid, result['scope_blockers'])

    def test_conflicting_current_assertions_preserve_both_quotes(self):
        snapshot, value, _, _ = self.fixture()
        self.diary(summary='Второе авторское вымышленное основание, противоречащее первому.')
        snapshot = self.snapshot();units = context.prepare_snapshot(snapshot)
        quotes = [{'unit_id': u['unit_id'], 'quote': u['text']} for u in units if u['code'] == 'summary']
        self.assertEqual(2, len(quotes))
        fid = next(iter(value['facts']))
        value['facts'][fid] = {'state': 'conflicting', 'evidence': quotes}
        result = self.result(snapshot, value)
        self.assertEqual('insufficient_data', result['outcome'])
        self.assertEqual(2, len(result['facts'][fid]['evidence']))
        value['facts'][fid]['evidence'].pop()
        self.assertEqual('not_evaluated', criteria.evaluate(snapshot, value, synthetic=True)['status'])

    def test_unknown_or_conflicting_duration_does_not_use_record_date(self):
        snapshot, value, _, _ = self.fixture()
        value['duration'].update(state='unknown', value=None, evidence=[])
        result = self.result(snapshot, value)
        self.assertEqual('insufficient_data', result['outcome'])
        self.assertTrue(result['distinguishing_questions'])
        value['duration'].update(state='conflicting')
        self.assertEqual('not_evaluated', criteria.evaluate(snapshot, value, synthetic=True)['status'])

    def test_full_fact_set_required_unknown_duplicate_fields_or_screening_rejected(self):
        snapshot, original, _, _ = self.fixture()
        variants = []
        value = deepcopy(original);value['facts'].pop(next(iter(value['facts'])));variants.append(value)
        value = deepcopy(original);value['facts']['screening_score'] = 27;variants.append(value)
        value = deepcopy(original);value['probability'] = 0.99;variants.append(value)
        value = deepcopy(original);value['diagnosis_code'] = 'F32';variants.append(value)
        value = deepcopy(original);value['kind'] = 'bipolar';variants.append(value)
        for value in variants:
            r = criteria.evaluate(snapshot, value, synthetic=True)
            self.assertEqual('not_evaluated', r['status']);self.assertIsNone(r['assessment'])

    def test_forged_empty_duplicate_and_overlong_evidence_reject_atomically(self):
        snapshot, original, _, _ = self.fixture();fid = next(iter(original['facts']))
        for change in ('quote', 'id', 'empty', 'duplicate', 'overlong', 'state', 'unknown_with_quote'):
            value = deepcopy(original);fact = value['facts'][fid]
            if change == 'quote':fact['evidence'][0]['quote'] = 'Несуществующая цитата'
            if change == 'id':fact['evidence'][0]['unit_id'] = 'invented'
            if change == 'empty':fact['evidence'] = []
            if change == 'duplicate':fact['evidence'] *= 2
            if change == 'overlong':fact['evidence'][0]['quote'] = 'x' * 4001
            if change == 'state':fact['state'] = 'probably'
            if change == 'unknown_with_quote':fact['state'] = 'unknown'
            r = criteria.evaluate(snapshot, value, synthetic=True)
            self.assertEqual('not_evaluated', r['status']);self.assertIsNone(r['assessment'])

    def test_bad_duration_values_cannot_pass(self):
        snapshot, original, _, _ = self.fixture()
        for bad in (True, -1, 14.0, '14', None, 50001):
            value = deepcopy(original);value['duration']['value'] = bad
            self.assertEqual('not_evaluated', criteria.evaluate(snapshot, value, synthetic=True)['status'])

    def test_old_family_undated_unknown_future_or_score_evidence_cannot_support(self):
        snapshot, value, _, units = self.fixture()
        uid = next(iter(value['facts'].values()))['evidence'][0]['unit_id']
        for change in ('old', 'family', 'undated', 'unknown', 'future', 'score', 'questionnaire'):
            changed = deepcopy(units);u = next(u for u in changed if u['unit_id'] == uid)
            if change == 'old':u['metadata']['current_revision'] = False
            if change == 'family':u['metadata']['context'] = 'family'
            if change == 'undated':u['metadata']['event_at'] = None
            if change == 'unknown':u['metadata']['status'] = 'unknown'
            if change == 'future':u['metadata']['event_at'] = '2099-01-01'
            if change == 'score':u['value'] = 27
            if change == 'questionnaire':u['categories'] = ['questionnaires']
            with patch.object(context, 'prepare_snapshot', return_value=changed):
                r = criteria.evaluate(snapshot, value, synthetic=True)
            self.assertEqual('not_evaluated', r['status']);self.assertIsNone(r['assessment'])

    def test_source_change_or_catalog_change_during_check_discard_all(self):
        snapshot, value, _, _ = self.fixture()
        altered = deepcopy(snapshot['backend_sources']);altered['mode'] = 'changed'
        with patch.object(sources, 'capture', side_effect=[snapshot['backend_sources'], altered]):
            r = criteria.evaluate(snapshot, value, synthetic=True)
        self.assertEqual('sources_or_criteria_changed', r['errors'][0]['code'])
        self.assertIsNone(r['assessment'])
        catalog = criteria.release();altered = deepcopy(catalog);altered['engine_sha256'] = 'changed'
        with patch.object(criteria, 'release', side_effect=[catalog, altered]):
            r = criteria.evaluate(snapshot, value, synthetic=True)
        self.assertEqual('sources_or_criteria_changed', r['errors'][0]['code'])

    def test_expired_sources_unknown_minor_conflicting_ages_and_real_data_fail(self):
        snapshot, value, _, _ = self.fixture()
        for years, status in ((None, 'unknown'), (17, 'known'), (None, 'conflicting')):
            modified = deepcopy(snapshot);modified['patients'][0].update(age_status=status, age_years=years)
            self.assertEqual('not_evaluated', criteria.evaluate(modified, value, synthetic=True)['status'])
        modified = deepcopy(snapshot);modified['patients'][0]['synthetic'] = 0
        self.assertEqual('not_evaluated', criteria.evaluate(modified, value, synthetic=True)['status'])
        altered = deepcopy(snapshot['backend_sources'])
        for claim in altered['claims'].values():claim['reasons'] = ['current_status_review_expired']
        modified = deepcopy(snapshot);modified['backend_sources'] = altered
        with patch.object(sources, 'capture', return_value=altered):
            self.assertEqual('not_evaluated', criteria.evaluate(modified, value, synthetic=True)['status'])
        with self.assertRaises(criteria.CriteriaError):criteria.evaluate(snapshot, value)

    def test_metadata_offsets_locators_and_interpretation_are_preserved(self):
        snapshot, value, condition, units = self.fixture()
        result = self.result(snapshot, value);indexed = {u['unit_id']: u for u in units}
        for fid, fact in result['facts'].items():
            self.assertEqual(condition['facts'][fid], fact['basis'])
            self.assertEqual('assertion_unreviewed', fact['interpretation'])
            for e in fact['evidence']:
                unit = indexed[e['unit_id']]
                self.assertEqual(unit['text'][e['start']:e['end']], e['quote'])
                self.assertEqual(unit['metadata'], e['metadata'])
                self.assertEqual(unit['source_ref'], e['source_ref'])
                self.assertEqual(unit['source_sha256'], e['source_sha256'])

    def test_catalog_uses_exact_reviewed_icd10_counts_and_locators(self):
        catalog = criteria.release()
        dep = catalog['conditions']['depressive_episode']
        gad = catalog['conditions']['generalized_anxiety']
        dc = {c['id']: c for c in dep['checks']}
        gc = {c['id']: c for c in gad['checks']}
        self.assertEqual((3, 2), (len(dc['core']['facts']), dc['core']['minimum']))
        self.assertEqual((7, 2), (len(dc['additional']['facts']), dc['additional']['minimum']))
        self.assertEqual((22, 4), (len(gc['symptoms']['facts']), gc['symptoms']['minimum']))
        self.assertEqual((4, 1), (len(gc['autonomic']['facts']), gc['autonomic']['minimum']))
        self.assertEqual({'palpitations','sweating','tremor','dry_mouth'}, set(gc['autonomic']['facts']))
        self.assertEqual(('days', 14, 13), tuple(dep['duration'][k] for k in ('unit','minimum','pdf_page')))
        self.assertEqual(('months', 6, 11), tuple(gad['duration'][k] for k in ('unit','minimum','pdf_page')))
        self.assertNotIn('functional_difficulty', gad['facts'])
        self.assertEqual('hac_scope_policy', dep['facts']['same_current_period']['origin'])
        self.assertEqual('hac_scope_policy', dc['function']['origin'])
        self.assertEqual(13, dc['core']['pdf_page'])
        self.assertEqual(12, gad['facts']['dizziness']['pdf_page'])

    def test_changed_catalog_cannot_reuse_old_scoped_content_review(self):
        catalog = json.loads(criteria.CATALOG.read_text())
        catalog['conditions']['generalized_anxiety']['duration']['minimum'] = 1
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'changed.json';path.write_text(json.dumps(catalog))
            with patch.object(criteria, 'CATALOG', path):
                with self.assertRaisesRegex(criteria.CriteriaError, 'content_review_mismatch'):
                    criteria.release()

    def test_errors_never_include_exception_or_secret(self):
        snapshot, value, _, _ = self.fixture()
        with patch.object(criteria, 'release', side_effect=RuntimeError('SECRET provider body')):
            report = criteria.evaluate(snapshot, value, synthetic=True)
        self.assertNotIn('SECRET', json.dumps(report));self.assertIsNone(report['assessment'])


class ThresholdTests(unittest.TestCase):
    def test_uncertainty_matches_all_possible_known_completions(self):
        # A positive threshold must hold for every way unknown/conflicting
        # observations could later resolve. A negative must fail in every way.
        for n in range(1, 5):
            for values in itertools.product(criteria.STATES, repeat=n):
                options = [('present', 'denied') if v in ('unknown', 'conflicting') else (v,)
                           for v in values]
                completions = list(itertools.product(*options))
                for expected in ('present', 'denied'):
                    for minimum in range(1, n + 1):
                        outcomes = {sum(v == expected for v in resolved) >= minimum
                                    for resolved in completions}
                        actual = criteria._threshold(values, expected, minimum)
                        if outcomes == {True}:self.assertEqual('met', actual)
                        elif outcomes == {False}:self.assertEqual('not_met', actual)
                        else:self.assertIn(actual, ('unknown', 'conflicting'))


if __name__ == '__main__':
    unittest.main()
