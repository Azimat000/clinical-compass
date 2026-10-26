"""BE08A internal boundary; SQLite snapshots plus adversarial model responses."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from apps.compass import backend_analyses as analyses, backend_risk_context as context
from apps.compass import backend_risk_rules as rules, backend_snapshot as snapshots, records
from apps.compass.backend_model import ModelError
from apps.tests import test_access, test_backend_contracts, test_backend_snapshot


class Model:
    def __init__(self, value=None, error=None):
        self.value, self.error = value or {'candidates': []}, error

    def generate(self, data, schema, **kw):
        self.data, self.schema, self.kw = data, schema, kw
        if self.error:
            raise ModelError(self.error)
        return {'value': deepcopy(self.value), 'metadata': {'test_double': True}}


def candidate(unit, quote, topic='safety_concern'):
    return {'topic': topic, 'evidence': [{'unit_id': unit, 'quote': quote}]}


class RiskContextTests(unittest.TestCase):
    setUp = test_backend_contracts.BackendContractTests.setUp
    tearDown = test_access.AccessTests.tearDown
    post = test_access.AccessTests.post
    offer = test_access.AccessTests.offer
    diary = test_backend_snapshot.BackendSnapshotTests.diary
    visit = test_backend_snapshot.BackendSnapshotTests.visit
    questionnaire = test_backend_snapshot.BackendSnapshotTests.questionnaire

    def snapshot(self):
        return json.loads(analyses.capture(self.db, 'D01', analyses.authorize(self.db, self.user, 'D01')))

    def evaluate(self, model=None):
        return context.analyze_snapshot(self.snapshot(), model, synthetic=True)

    def positive(self):
        payload = {'condition': 'F32', 'severity': 'unknown', 'basis': 'Вымышленный факт.',
                   'supersedes_id': None, **{k: 'denied' for k in rules.FLAGS}, 'suicidal_plan': 'present'}
        rules.record_context(self.db, self.user, 'D01', records.today().isoformat(), payload, 'a' * 32)

    def test_four_sources_exact_fields_metadata_versions_and_no_mutation(self):
        self.visit(); self.diary(); self.questionnaire(missing=True)
        frozen = self.snapshot(); original = deepcopy(frozen)
        units = context.prepare_snapshot(frozen)
        self.assertEqual(set(context.CATEGORIES), {c for u in units for c in u['categories']})
        history = next(u for u in units if 'anamnesis' in u['categories'])
        self.assertEqual({'visits', 'anamnesis'}, set(history['categories']))
        self.assertEqual('2020-01-01', history['metadata']['event_at'])
        self.assertTrue(history['metadata']['recorded_at'])
        answers = next(u for u in units if u['code'] == 'answers')
        self.assertIn('null', answers['text']); self.assertEqual('incomplete', answers['metadata']['state'])
        model = Model(); result = context.analyze_snapshot(frozen, model, synthetic=True)
        self.assertEqual([], result['missing_categories'])
        self.assertEqual(frozen, original)
        for unit in units:
            source = snapshots.resolve(frozen, unit['source_ref'])
            self.assertEqual(source['sha256'], unit['source_sha256'])
        for unit in model.data['units']:
            self.assertNotIn('source_ref', unit); self.assertNotIn('author_id', unit['metadata'])

    def test_semantic_candidates_keep_full_denial_family_context_and_dates(self):
        self.diary(summary='У отца были мысли о смерти. Я сейчас таких мыслей не отмечаю.')
        units = context.prepare_snapshot(self.snapshot())
        unit = next(u for u in units if u['code'] == 'summary')
        # Even semantically wrong model output stays explicitly unreviewed, not a rule.
        model = Model({'candidates': [candidate(unit['unit_id'], 'мысли о смерти')]})
        result = self.evaluate(model); item = result['model_candidates'][0]
        self.assertIn('не отмечаю', item['evidence'][0]['text'])
        self.assertEqual('model_suspicion_unreviewed', item['interpretation'])
        self.assertEqual('not_established', result['assessment'])
        self.assertFalse(result['clinical_ready'])

    def test_invented_cross_source_or_added_clinical_claim_atomic_rejection(self):
        self.diary(summary='Вымышленная тревога.')
        units = context.prepare_snapshot(self.snapshot())
        unit = next(u for u in units if u['code'] == 'summary')
        good = candidate(unit['unit_id'], 'тревога')
        for bad in (candidate('foreign', 'тревога'), candidate(unit['unit_id'], 'несуществующее'),
                    {**good, 'diagnosis': 'F32'}, {**good, 'causality': 'drug'},
                    candidate(unit['unit_id'], 'тревога', 'urgent'), good):
            result = self.evaluate(Model({'candidates': [good, bad]}))
            self.assertEqual([], result['model_candidates']); self.assertTrue(result['errors'])
            self.assertEqual('not_evaluated', result['model_evaluation'])

    def test_quote_unicode_offsets_empty_values_and_structured_json(self):
        self.diary(summary='Ёж: не сплю 🌒.')
        self.questionnaire(missing=True)
        units = context.prepare_snapshot(self.snapshot())
        text = next(u for u in units if u['code'] == 'summary')
        numeric = next(u for u in units if u['code'] == 'answers')
        for unit, quote in ((text, 'не сплю 🌒'), (numeric, 'null')):
            value = context.verify({'candidates': [candidate(unit['unit_id'], quote)]}, units, 'sha')
            span = value[0]['evidence'][0]
            self.assertEqual(quote, span['text'][span['start']:span['end']])
            self.assertEqual('original_text' if unit is text else 'canonical_json_value', span['offset_basis'])
        self.assertTrue(any(u['value'] in ('', None) for u in units))

    def test_changed_row_field_or_duplicate_metadata_refused(self):
        self.visit(); frozen = self.snapshot()
        for mutation in ('row', 'field', 'duplicate', 'incomplete', 'reference'):
            s = deepcopy(frozen)
            entry = next(e for e in s['patient_history']['entries'] if e['category'] == 'anamnesis')
            if mutation == 'row': s['first_visit_versions'][0]['payload_json'] = '{}'
            if mutation == 'field': entry['fields'][0]['value'] = 'выдумка'
            if mutation == 'duplicate': entry['fields'][0]['event_at'] = '2015-01-01'
            if mutation == 'incomplete': s['patient_history']['truncated'] = True
            if mutation == 'reference': entry['fields'][0]['source_ref'] = 'foreign'
            with self.assertRaises(context.ContextError): context.prepare_snapshot(s)

    def test_positive_rule_preserved_across_every_model_failure_and_empty_success(self):
        self.positive(); self.diary()
        for code in ('timeout', 'authentication_failed', 'budget_exceeded', 'context_limit', 'cancelled'):
            result = self.evaluate(Model(error=code))
            self.assertEqual('potential_risk', result['structured']['result']['output']['assessment'])
            self.assertEqual('partial', result['status']); self.assertEqual('not_established', result['assessment'])
            self.assertEqual(code, result['errors'][0]['code'])
        self.assertEqual('potential_risk', self.evaluate(Model())['structured']['result']['output']['assessment'])
        self.assertEqual('model_unavailable', self.evaluate()['errors'][0]['code'])

    def test_unknown_time_missing_categories_and_no_empty_safe_claim(self):
        result = self.evaluate(Model())
        self.assertEqual('partial', result['status']); self.assertFalse(result['clinical_ready'])
        # Shared fixture already has a legacy physician encounter.
        self.assertEqual({'questionnaires', 'wellbeing', 'anamnesis'}, set(result['missing_categories']))
        self.diary(); units = context.prepare_snapshot(self.snapshot())
        unit = next(u for u in units if u['code'] == 'summary')
        unit['metadata']['event_at'] = None
        item = context.verify({'candidates': [candidate(unit['unit_id'], 'Вымышленная')]}, units, 'sha')[0]
        self.assertEqual('unknown', item['temporal_relation']); self.assertEqual([], item['record_days'])

    def test_temporal_relationship_is_record_chronology_not_causality(self):
        self.diary(summary='Вымышленная жалоба.', observed_on='2026-10-20')
        self.diary(summary='Вымышленная жалоба усилилась.', observed_on='2026-10-22')
        units = context.prepare_snapshot(self.snapshot())
        chosen = [u for u in units if u['code'] == 'summary']
        value = {'topic': 'reported_change', 'evidence': [
            {'unit_id': u['unit_id'], 'quote': u['text']} for u in reversed(chosen)]}
        item = context.verify({'candidates': [value]}, units, 'sha')[0]
        self.assertEqual('different_record_days', item['temporal_relation'])
        self.assertEqual(['2026-10-20', '2026-10-22'], item['record_days'])
        self.assertEqual('not_established', item['clinical_causality'])
        value['evidence'].reverse()
        self.assertEqual(item['id'], context.verify({'candidates': [value]}, units, 'sha')[0]['id'])

    def test_duplicate_evidence_and_blank_quotes_rejected(self):
        self.diary(); units = context.prepare_snapshot(self.snapshot()); unit = units[0]
        bad = candidate(unit['unit_id'], ' ')
        with self.assertRaises(context.ContextError): context.verify({'candidates': [bad]}, units, 'sha')
        bad = candidate(unit['unit_id'], unit['text']); bad['evidence'] *= 2
        with self.assertRaises(context.ContextError): context.verify({'candidates': [bad]}, units, 'sha')

    def test_real_data_blocked_before_rules_or_provider(self):
        s = self.snapshot()
        with patch.object(rules, 'evaluate', side_effect=AssertionError('never reached')):
            with self.assertRaisesRegex(ModelError, 'synthetic_only'): context.analyze_snapshot(s, Model())
            s['patients'][0]['synthetic'] = 0
            with self.assertRaisesRegex(ModelError, 'synthetic_only'):
                context.analyze_snapshot(s, Model(), synthetic=True)

    def test_default_queue_executor_remains_independent_of_candidate_model(self):
        self.positive()
        from apps.compass import backend_jobs
        with patch.object(context, 'analyze_snapshot', side_effect=AssertionError('internal only')):
            self.assertEqual('potential_risk', backend_jobs.execute('risk', self.snapshot())['result']['output']['assessment'])
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])


if __name__ == '__main__':
    unittest.main()
