"""BE10A internal mechanics only. Fixtures are NOT diagnostic quality evidence."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from apps.compass import backend_diagnoses as diagnoses, backend_risk_context as context
from apps.compass import backend_analyses as analyses, backend_sources as sources, backend_jobs as jobs
from apps.compass.backend_model import Budget, Config, DeepSeek, ModelError
from apps.tests import test_access, test_backend_contracts, test_backend_snapshot, test_backend_risk_context

Model = test_backend_risk_context.Model


def hypothesis(kind, catalog, unit=None, state='unknown'):
    return {'kind': kind, 'criteria': [
        {'id': d, 'state': state, 'evidence': [] if unit is None else [
            {'unit_id': unit['unit_id'], 'quote': unit['text']}]} for d in catalog['kinds'][kind]]}


def positive(catalog, unit):
    return {'disposition': 'candidates',
            'leading': hypothesis('depressive_episode', catalog, unit, 'supporting'),
            'alternatives': [hypothesis(k, catalog) for k in diagnoses.KINDS[1:]]}


class DiagnosisTests(unittest.TestCase):
    setUp = test_backend_contracts.BackendContractTests.setUp
    tearDown = test_access.AccessTests.tearDown
    post = test_access.AccessTests.post
    offer = test_access.AccessTests.offer
    body = test_backend_contracts.BackendContractTests.body
    diary = test_backend_snapshot.BackendSnapshotTests.diary
    visit = test_backend_snapshot.BackendSnapshotTests.visit
    questionnaire = test_backend_snapshot.BackendSnapshotTests.questionnaire

    def snapshot(self):
        return json.loads(analyses.capture(self.db, 'D01', analyses.authorize(self.db, self.user, 'D01')))

    def fixture(self):
        self.diary(summary='Авторская вымышленная запись для проверки цитирования, не клинический случай.')
        snapshot = self.snapshot()
        units = context.prepare_snapshot(snapshot)
        unit = next(u for u in units if u['code'] == 'summary')
        catalog = diagnoses.release()
        return snapshot, units, unit, catalog, positive(catalog, unit)

    def check(self, value, units, catalog):
        return diagnoses.verify(value, units, catalog,
                                {'age_min':35,'age_max':35,'population':'synthetic_adults_only'}, 'sha')

    def test_all_four_sources_full_metadata_and_read_only_result(self):
        self.visit();self.questionnaire(missing=True)
        snapshot, units, unit, catalog, value = self.fixture()
        before = test_backend_contracts.table_rows(self.db)
        original = deepcopy(snapshot);model = Model(value)
        report = diagnoses.analyze_snapshot(snapshot, model, synthetic=True)
        self.assertEqual('unreviewed', report['status'], report['errors'])
        self.assertIsNone(report['established_diagnosis']);self.assertIsNone(report['plan'])
        self.assertFalse(report['clinical_ready']);self.assertTrue(report['model_metadata']['test_double'])
        self.assertEqual([], report['missing_categories'])
        self.assertEqual(snapshot, original);self.assertEqual(before, test_backend_contracts.table_rows(self.db))
        self.assertEqual({'questionnaires','wellbeing','anamnesis','visits'},
                         {c for u in units for c in u['categories']})
        evidence = report['candidates']['leading']['supporting_evidence'][0]
        self.assertEqual(unit['text'], evidence['text'][evidence['start']:evidence['end']])
        self.assertEqual(unit['metadata'], evidence['metadata'])
        self.assertEqual(unit['source_ref'], evidence['source_ref'])
        self.assertIsNone(report['candidates']['leading']['diagnosis_code'])
        self.assertEqual('hypothesis_unreviewed', report['candidates']['leading']['interpretation'])

    def test_external_payload_full_lossless_units_without_identifiers(self):
        snapshot, units, unit, catalog, value = self.fixture()
        model = Model(value);diagnoses.analyze_snapshot(snapshot, model, synthetic=True)
        rows = model.data['units'];columns = model.data['columns']
        self.assertEqual(len(units), len(rows))
        for u, row in zip(units, rows):
            decoded = dict(zip(columns,row))
            self.assertEqual(u['text'],decoded['text']);self.assertEqual(u['metadata']['event_at'],decoded['event_at'])
            self.assertEqual(u['metadata']['current_revision'],decoded['current_revision'])
        encoded = json.dumps(model.data, ensure_ascii=False)
        for private in ('source_ref','source_sha256','author_id','patient_id','D01','doc-a','pat-a'):
            self.assertNotIn(private, encoded)
        self.assertEqual(True, model.kw['synthetic'])

    def test_forged_missing_duplicate_quotes_or_domains_reject_atomically(self):
        snapshot, units, unit, catalog, valid = self.fixture()
        variants=[]
        for key, bad in [('unit_id','invented'),('quote','Выдуманная цитата')]:
            value=deepcopy(valid);value['leading']['criteria'][0]['evidence'][0][key]=bad;variants.append(value)
        value=deepcopy(valid);value['leading']['criteria'][0]['evidence']*=2;variants.append(value)
        value=deepcopy(valid);value['leading']['criteria'][0]['id']='invented';variants.append(value)
        value=deepcopy(valid);value['leading']['criteria']*=2;variants.append(value)
        value=deepcopy(valid);value['leading']['criteria'].pop();variants.append(value)
        value=deepcopy(valid);value['confidence']=99;variants.append(value)
        value=deepcopy(valid);value['leading']['code']='F32';variants.append(value)
        for value in variants:
            with self.assertRaises(diagnoses.DiagnosisError): self.check(value, units, catalog)
            report=diagnoses.analyze_snapshot(snapshot,Model(value),synthetic=True)
            self.assertEqual('not_evaluated',report['status']);self.assertIsNone(report['candidates'])

    def test_mandatory_differentials_and_no_bipolar_leading_diagnosis(self):
        _,units,unit,catalog,value=self.fixture()
        for removed in diagnoses.KINDS[2:]:
            bad=deepcopy(value);bad['alternatives']=[h for h in bad['alternatives'] if h['kind']!=removed]
            with self.assertRaisesRegex(diagnoses.DiagnosisError,'missing_essential'):self.check(bad,units,catalog)
        bad=deepcopy(value);bad['leading']=hypothesis('bipolar_differential',catalog,unit,'supporting')
        with self.assertRaises(diagnoses.DiagnosisError):self.check(bad,units,catalog)
        bad=deepcopy(value);bad['alternatives'].append(deepcopy(bad['leading']))
        with self.assertRaises(diagnoses.DiagnosisError):self.check(bad,units,catalog)

    def test_missing_and_conflicting_evidence_preserve_questions_and_both_bases(self):
        snapshot,units,unit,catalog,value=self.fixture()
        self.diary(summary='Другая вымышленная запись: прежнее утверждение отрицаю.')
        snapshot=self.snapshot();units=context.prepare_snapshot(snapshot)
        pair=[u for u in units if u['code']=='summary']
        h=hypothesis('depressive_episode',catalog)
        h['criteria'][0].update(state='conflicting',evidence=[{'unit_id':u['unit_id'],'quote':u['text']} for u in pair])
        raw={'disposition':'insufficient_data','leading':None,'alternatives':[h]}
        report=diagnoses.analyze_snapshot(snapshot,Model(raw),synthetic=True)
        self.assertEqual('unreviewed',report['status'])
        actual=report['candidates']['alternatives'][0]
        self.assertEqual(2,len(actual['supporting_evidence']));self.assertEqual(2,len(actual['contradicting_evidence']))
        self.assertEqual(3,len(actual['distinguishing_questions']))
        raw['alternatives'][0]['criteria'][0]['evidence'].pop()
        with self.assertRaisesRegex(diagnoses.DiagnosisError,'conflict_requires'):self.check(raw,units,catalog)

    def test_screening_numeric_value_old_unknown_or_noncurrent_cannot_support_leading(self):
        _,units,unit,catalog,value=self.fixture()
        for mutation in ('numeric','questionnaire','old','unknown','undated','family'):
            changed=deepcopy(units);u=next(u for u in changed if u['unit_id']==unit['unit_id'])
            if mutation=='numeric':u['value']=20
            if mutation=='questionnaire':u['categories']=['questionnaires']
            if mutation=='old':u['metadata']['current_revision']=False
            if mutation=='unknown':u['metadata']['status']='unknown'
            if mutation=='undated':u['metadata']['event_at']=None
            if mutation=='family':u['metadata']['context']='family'
            with self.assertRaisesRegex(diagnoses.DiagnosisError,'inapplicable_leading'):self.check(value,changed,catalog)

    def test_leading_requires_resolved_domains_but_no_diagnostic_threshold_claim(self):
        _,units,unit,catalog,value=self.fixture()
        for state in ('unknown','conflicting','contradicting'):
            bad=deepcopy(value);c=bad['leading']['criteria'][0];c['state']=state
            if state=='unknown':c['evidence']=[]
            with self.assertRaises(diagnoses.DiagnosisError):self.check(bad,units,catalog)
        bad=deepcopy(value);bad['disposition']='unsupported'
        with self.assertRaises(diagnoses.DiagnosisError):self.check(bad,units,catalog)

    def test_unsupported_and_insufficient_are_explanatory_without_random_leading(self):
        snapshot,_,_,catalog,_=self.fixture()
        for disposition in ('unsupported','insufficient_data'):
            raw={'disposition':disposition,'leading':None,
                 'alternatives':[hypothesis(k,catalog) for k in diagnoses.KINDS]}
            report=diagnoses.analyze_snapshot(snapshot,Model(raw),synthetic=True)
            self.assertEqual(disposition,report['candidates']['disposition'])
            self.assertIsNone(report['candidates']['leading'])
            self.assertTrue(all(h['distinguishing_questions'] for h in report['candidates']['alternatives']))

    def test_unknown_missing_conflicting_minor_age_block_before_model(self):
        snapshot,_,_,_,value=self.fixture();model=Model(value)
        for years,status in ((None,'unknown'),(None,'conflicting'),(17,'known')):
            modified=deepcopy(snapshot);modified['patients'][0].update(age_status=status,age_years=years)
            report=diagnoses.analyze_snapshot(modified,model,synthetic=True)
            self.assertEqual('not_evaluated',report['status']);self.assertIsNone(report['candidates'])
            self.assertFalse(hasattr(model,'data'))

    def test_real_inputs_or_absent_attestation_rejected_before_source_or_model(self):
        snapshot,_,_,_,value=self.fixture()
        with patch.object(diagnoses,'release',side_effect=AssertionError('must not run')):
            with self.assertRaises(ModelError):diagnoses.analyze_snapshot(snapshot,Model(value))
            snapshot['patients'][0]['synthetic']=0
            with self.assertRaises(ModelError):diagnoses.analyze_snapshot(snapshot,Model(value),synthetic=True)

    def test_source_expiry_revocation_change_and_corrupt_input_fail_before_model(self):
        snapshot,_,_,_,value=self.fixture()
        modified=deepcopy(snapshot);modified['backend_sources']['sources']['KR301_3']['reasons']=['revoked']
        model=Model(value);report=diagnoses.analyze_snapshot(modified,model,synthetic=True)
        self.assertEqual('source_snapshot_changed',report['errors'][0]['code']);self.assertFalse(hasattr(model,'data'))
        changed=deepcopy(snapshot['backend_sources'])
        changed['claims']['be03-KR301_3-F01']['reasons']=['current_status_review_expired']
        modified=deepcopy(snapshot);modified['backend_sources']=changed
        with patch.object(sources,'capture',return_value=changed):
            report=diagnoses.analyze_snapshot(modified,model,synthetic=True)
        self.assertEqual('not_evaluated',report['status']);self.assertFalse(hasattr(model,'data'))
        modified=deepcopy(snapshot);modified['patient_history']['complete']=False
        self.assertEqual('not_evaluated',diagnoses.analyze_snapshot(modified,model,synthetic=True)['status'])

    def test_change_during_model_call_discards_all_candidates(self):
        snapshot,_,_,_,value=self.fixture();model=Model(value)
        first=deepcopy(snapshot['backend_sources']);second=deepcopy(first);second['mode']='changed'
        with patch.object(sources,'capture',side_effect=[first,second]):
            report=diagnoses.analyze_snapshot(snapshot,model,synthetic=True)
        self.assertEqual('sources_or_engine_changed',report['errors'][0]['code']);self.assertIsNone(report['candidates'])

    def test_real_adapter_missing_key_no_transport_no_reservation_and_no_safe_claim(self):
        snapshot,_,_,_,_=self.fixture()
        with tempfile.TemporaryDirectory() as tmp:
            model=DeepSeek(Config(model='deepseek-flash'),Budget(Path(tmp)/'budget.sqlite3'))
            with patch.dict('os.environ',{},clear=True):
                report=diagnoses.analyze_snapshot(snapshot,model,synthetic=True)
            import sqlite3
            from contextlib import closing
            with closing(sqlite3.connect(model.budget.path)) as db:
                self.assertEqual(0,db.execute('SELECT count(*) FROM calls').fetchone()[0])
        self.assertEqual('missing_credentials',report['errors'][0]['code'])
        self.assertEqual('not_evaluated',report['status']);self.assertIsNone(report['candidates'])
        self.assertIsNone(report['model_metadata']);self.assertFalse(report['clinical_ready'])

    def test_model_failure_or_secret_exception_never_reports_hypothesis_or_exception(self):
        snapshot,_,_,_,value=self.fixture()
        for failure in ('timeout','budget_exceeded','context_limit','cancelled','provider SECRET'):
            report=diagnoses.analyze_snapshot(snapshot,Model(value,error=failure),synthetic=True)
            self.assertEqual('not_evaluated',report['status']);self.assertIsNone(report['candidates'])
            self.assertNotIn('SECRET',json.dumps(report))
        model=Model(value)
        with patch.object(model,'generate',side_effect=RuntimeError('SECRET')):
            report=diagnoses.analyze_snapshot(snapshot,model,synthetic=True)
        self.assertEqual('model_internal_error',report['errors'][0]['code']);self.assertNotIn('SECRET',json.dumps(report))

    def test_no_queue_integration_no_ready_publication_no_new_diagnosis_or_plan(self):
        snapshot,_,_,_,value=self.fixture()
        before=test_backend_contracts.table_rows(self.db)
        report=diagnoses.analyze_snapshot(snapshot,Model(value),synthetic=True)
        for _ in range(2):
            with self.assertRaises(ModelError):jobs.execute('diagnosis',snapshot)
        self.assertEqual(before,test_backend_contracts.table_rows(self.db))
        with self.assertRaises(analyses.AnalysisError):analyses.validate('Result',report)
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])


if __name__=='__main__':unittest.main()
