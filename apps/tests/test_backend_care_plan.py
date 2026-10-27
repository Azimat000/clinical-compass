"""BE12 deterministic synthetic planning mechanics; no clinical validation."""
from copy import deepcopy
import json
import secrets
import sqlite3
import unittest
from unittest.mock import patch

from apps.compass import backend_care_plan as plans, backend_analyses as analyses
from apps.compass import backend_jobs as jobs, backend_diagnosis_review as reviews
from apps.compass import backend_risk_rules as risks, records, access, backend_sources
from apps.compass.db import connect
from apps.compass.web import create_app
from apps.tests import test_backend_diagnosis_review as review_tests, test_backend_risk_rules
from apps.tests import test_backend_contracts, test_access


class CarePlanTests(unittest.TestCase):
    setUp = review_tests.DiagnosisReviewTests.setUp
    tearDown = review_tests.DiagnosisReviewTests.tearDown
    post = review_tests.DiagnosisReviewTests.post
    offer = review_tests.DiagnosisReviewTests.offer
    body = review_tests.DiagnosisReviewTests.body
    diary = review_tests.DiagnosisReviewTests.diary
    enable = review_tests.DiagnosisReviewTests.enable
    fixture = review_tests.DiagnosisReviewTests.fixture
    outcome = review_tests.DiagnosisReviewTests.outcome
    request_body = review_tests.DiagnosisReviewTests.request_body
    context = test_backend_risk_rules.RiskRuleTests.context
    store = test_backend_risk_rules.RiskRuleTests.store

    def diagnosis(self, kind='depressive_episode', *, reviewed=True, unknown=None, risk=None, changes=None):
        condition = plans.CONDITIONS[kind]
        self.store(self.context(condition, **(risk or {})))
        run, work, raw = self.fixture(True)
        catalog = plans.diagnostic.criteria.release()
        for i, (branch, fid) in enumerate(plans.diagnostic.fact_index(catalog)):
            if branch != kind:
                raw['facts'][i] = []
                continue
            denied = fid in ('self_harm',) or any(c['state'] == 'denied' and fid in c['facts'] for c in catalog['conditions'][branch]['checks'])
            raw['facts'][i] = [] if fid == unknown else [-1 if denied else 1]
        raw['durations'] = {k: {'value': None, 'refs': []} for k in plans.CONDITIONS}
        raw['durations'][kind] = {'value': 14 if kind == 'depressive_episode' else 6, 'refs': [1]}
        for i, (branch, fid) in enumerate(plans.diagnostic.fact_index(catalog)):
            if branch == kind and changes and fid in changes:
                raw['facts'][i] = changes[fid]
        raw['leading'] = None if unknown or changes else kind
        # Deliberate structured test assertions, not semantic/model quality evidence.
        outcome = {'diagnosis_report': {'context': plans.diagnostic.interpret(work['snapshot'], raw)}}
        self.assertTrue(jobs.finish(self.db, work, outcome))
        value = analyses.read(self.db, self.user, 'D01', run['run_id'])
        self.assertEqual('unsupported' if changes else 'insufficient_data' if unknown else 'ready', value['status'], value)
        if reviewed:
            body = self.request_body('manual' if unknown or changes else 'accept', None if unknown or changes else value)
            if unknown or changes: body['diagnosis_code'] = condition
            reviews.record(self.db, self.user, 'D01', body)
        return value

    def plan(self):
        value = analyses.create(self.db, self.user, 'D01', self.body('plan'))
        self.assertTrue(jobs.process_one(self.db, 'generation'))
        final = analyses.read(self.db, self.user, 'D01', value['run_id'])
        return final

    def report(self, **kw):
        self.diagnosis(**kw)
        value = self.plan()
        self.assertEqual('ready', value['status'], value)
        return value['care_plan_context']['report']

    def test_supported_depression_content_provenance_and_no_actions(self):
        self.diagnosis()
        before = test_backend_contracts.table_rows(self.db)
        value = self.plan();self.assertEqual('ready', value['status'], value)
        report = value['care_plan_context']['report']
        self.assertEqual('physician_diagnosis_draft', report['status'])
        self.assertEqual({'be12-dep-therapy','be12-dep-education','be12-dep-monitor'}, {i['id'] for i in report['items']})
        self.assertTrue(report['diagnosis_reviewed'])
        snapshot=json.loads(self.db.execute('SELECT payload_json FROM analysis_input_snapshots WHERE id=?',(value['snapshot_id'],)).fetchone()[0])
        for item in report['items']:
            self.assertEqual(report['diagnosis_review_id'], item['diagnosis_review_id'])
            self.assertTrue(item['basis']);self.assertTrue(item['goal']);self.assertTrue(item['evidence_refs'])
            for ref in item['evidence_refs']:self.assertIsNotNone(plans.snapshots.resolve(snapshot,ref))
            self.assertEqual(snapshot['backend_sources']['sources']['KR301_3']['source']['sha256'],item['source']['pdf_sha256'])
            self.assertGreater(item['source']['pdf_page'],0)
            self.assertIsNone(item['timing']['interval_days'])
        after=test_backend_contracts.table_rows(self.db)
        for table in before:
            if table not in ('analysis_runs','analysis_input_snapshots','analysis_result_versions','backend_jobs','backend_job_attempts','audit_entries'):
                self.assertEqual(before[table], after[table],table)
        self.assertFalse(report['patient_published']);self.assertFalse(report['applied']);self.assertFalse(report['clinical_ready'])

    def test_gad_different_measures_and_source_bound_monitoring(self):
        report=self.report(kind='generalized_anxiety')
        self.assertEqual('physician_diagnosis_draft',report['status'])
        self.assertEqual({'be12-gad-therapy','be12-gad-education','be12-gad-monitor'},{i['id'] for i in report['items']})
        self.assertTrue(all(i['source']['id']=='KR457_3' for i in report['items']))
        self.assertTrue(any('тревоги' in i['text'] for i in report['items']))

    def test_unreviewed_hypothesis_is_separate_conditional_no_treatment(self):
        report=self.report(reviewed=False)
        self.assertEqual('conditional_clarification',report['status']);self.assertFalse(report['diagnosis_reviewed'])
        self.assertFalse(any(i['kind']=='nonpharmacological' for i in report['items']))
        self.assertTrue(report['diagnosis_run_id']);self.assertIsNone(report['diagnosis_review_id'])

    def test_risk_positive_overrides_ordinary_path_without_erasing_signal(self):
        report=self.report(risk={'suicidal_plan':'present','suicidal_intent':'unknown'})
        self.assertEqual('attention_required',report['risk_status'])
        self.assertIn('DEP-SUICIDE-FACT',report['risk_patterns'])
        self.assertTrue(any(i['kind']=='routing' for i in report['items']))
        self.assertFalse(any(i['kind']=='nonpharmacological' for i in report['items']))
        self.assertTrue(all(i['necessity']=='required_evaluation' for i in report['items'] if i['kind'] in ('risk_review','routing')))

    def test_unknown_medical_cause_specific_question_no_extra_tests(self):
        report=self.report(unknown='organic_cause')
        self.assertEqual('conditional_clarification',report['status'])
        self.assertTrue(any('органическ' in q.lower() for q in report['missing_data']),report)
        self.assertTrue(any(i['kind']=='examination' for i in report['items']))
        self.assertFalse(any(i['kind']=='nonpharmacological' for i in report['items']))
        self.assertNotIn('МРТ',str(report));self.assertNotIn('ЭЭГ',str(report))

    def test_missing_risk_is_unknown_and_blocks_ordinary_path(self):
        self.diagnosis()
        # A new diagnosis after a changed context is required before planning.
        row=self.db.execute('SELECT id FROM clinical_contexts').fetchone()[0]
        self.store(self.context('F32',supersedes_id=row,suicidal_plan='unknown'))
        body=self.request_body();body['diagnosis_code']='F32'
        reviews.record(self.db,self.user,'D01',body)
        value=self.plan();self.assertEqual('ready',value['status'],value)
        report=value['care_plan_context']['report']
        self.assertEqual('unknown',report['risk_status']);self.assertTrue(report['missing_data'])
        self.assertFalse(any(i['kind']=='nonpharmacological' for i in report['items']))

    def test_no_diagnosis_returns_concrete_failure_not_template(self):
        self.enable();value=self.plan()
        self.assertEqual('insufficient_data',value['status']);self.assertIsNone(value['result'])
        self.assertEqual('diagnosis_incomplete',value['errors'][0]['code'])
        self.assertIsNone(value['care_plan_context']['report'])

    def test_manual_supported_code_without_criteria_conditional_and_unsupported_code_refused(self):
        self.enable()
        body=self.request_body();body['diagnosis_code']='F32'
        receipt=reviews.record(self.db,self.user,'D01',body)
        value=self.plan();self.assertEqual('ready',value['status'],value)
        report=value['care_plan_context']['report'];self.assertEqual(receipt['id'],report['diagnosis_review_id'])
        self.assertIsNone(report['diagnosis_run_id']);self.assertTrue(report['missing_data'])
        self.assertTrue(any(i['id']=='be12-dep-mania' for i in report['items']))
        body=self.request_body();body['diagnosis_code']='TEST'
        reviews.record(self.db,self.user,'D01',body)
        value=self.plan();self.assertEqual('unsupported',value['status']);self.assertIsNone(value['result'])

    def test_rejected_never_resurrected_and_stale_review_not_used(self):
        run=self.diagnosis(reviewed=False)
        reviews.record(self.db,self.user,'D01',self.request_body('reject',run))
        value=self.plan();self.assertEqual('diagnosis_rejected',value['errors'][0]['code'])
        self.diary(summary='Новые сведения.')
        value=self.plan();self.assertEqual('diagnosis_review_stale',value['errors'][0]['code'])

    def test_diagnosis_data_runtime_and_risk_state_fence_worker(self):
        self.diagnosis()
        value=analyses.create(self.db,self.user,'D01',self.body('plan'));work=jobs.claim(self.db,'generation')
        outcome=jobs.execute('plan',work['snapshot'])
        reviews.record(self.db,self.user,'D01',self.request_body())
        self.assertTrue(jobs.finish(self.db,work,outcome))
        self.assertEqual('stale',analyses.read(self.db,self.user,'D01',value['run_id'])['status'])
        self.assertNotIn('care_plan_context',analyses._latest(self.db,value['run_id']))

    def test_forged_items_interval_source_review_and_missing_context_rejected(self):
        self.diagnosis()
        for variant in ('text','interval','source','review','context'):
            with self.subTest(variant=variant):
                value=analyses.create(self.db,self.user,'D01',self.body('plan'));work=jobs.claim(self.db,'generation')
                outcome=jobs.execute('plan',work['snapshot'])
                if variant=='text':outcome['result']['output']['items'][0]['text']='Назначить выдуманный препарат.'
                if variant=='interval':outcome['care_plan_context']['report']['items'][0]['timing']['interval_days']=7
                if variant=='source':outcome['care_plan_context']['report']['items'][0]['source']['pdf_page']=999
                if variant=='review':outcome['care_plan_context']['report']['diagnosis_review_id']='other'
                if variant=='context':outcome.pop('care_plan_context')
                self.assertTrue(jobs.finish(self.db,work,outcome))
                self.assertEqual('running',analyses._latest(self.db,value['run_id'])['status'])
                self.db.execute("UPDATE backend_jobs SET state='done' WHERE run_id=?",(value['run_id'],))

    def test_http_access_idempotency_restart_cancel_and_no_patient_publication(self):
        self.diagnosis();client=self.clients['doc-a'];body=self.body('plan')
        response=client.post(self.url,json=body,headers={'X-CSRF-Token':test_access.csrf(client)})
        self.assertEqual(202,response.status_code);run=response.json['run_id'];location=response.headers['Location']
        self.assertTrue(jobs.process_one(self.db,'generation'))
        final=client.get(location);self.assertEqual('ready',final.json['status'])
        self.assertEqual('no-store',final.headers['Cache-Control'])
        repeated=client.post(self.url,json=body,headers={'X-CSRF-Token':test_access.csrf(client)})
        self.assertEqual(final.json,repeated.json)
        restart=create_app(self.path).test_client();restart.set_cookie(access.COOKIE,client.get_cookie(access.COOKIE).value)
        self.assertEqual(final.json,restart.get(location).json)
        for uid in ('pat-a','doc-b'):
            self.assertIn(self.clients[uid].get(location).status_code,(403,404))
        self.assertEqual(403,client.post(self.url,json=self.body('plan')).status_code)
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])

    def test_incomplete_unreviewed_branch_has_exact_questions(self):
        report=self.report(unknown='organic_cause',reviewed=False)
        self.assertEqual('conditional_clarification',report['status'])
        self.assertTrue(any('органическ' in q.lower() for q in report['missing_data']))
        self.assertTrue(any(i['kind']=='clarification' for i in report['items']))
        self.assertFalse(any(i['kind']=='nonpharmacological' for i in report['items']))

    def test_mania_and_self_harm_prevent_ordinary_plan_after_manual_diagnosis(self):
        report=self.report(changes={'mania_hypomania':[1]})
        self.assertEqual('attention_required',report['risk_status'])
        self.assertTrue(any(i['id']=='be12-dep-mania' for i in report['items']))
        self.assertTrue(any(i['kind']=='routing' for i in report['items']))
        self.assertFalse(any(i['kind']=='nonpharmacological' for i in report['items']))

    def test_open_and_closed_be08_episode_versions_are_plan_dependencies(self):
        self.diagnosis()
        from apps.compass.db import now
        run=analyses.create(self.db,self.user,'D01',self.body('risk'))
        relationship=analyses.authorize(self.db,self.user,'D01')
        eid=secrets.token_hex(16)
        self.db.execute('INSERT INTO backend_risk_episodes VALUES(?,?,?,?,?,?)',
            (eid,'D01',relationship,'model_candidate','synthetic_unknown_safety',now()))
        self.db.execute('INSERT INTO backend_risk_episode_versions VALUES(?,?,?,?,?,?,?,?,?)',
            (eid,1,'open','Synthetic mechanics','doc-a',run['run_id'],'{}',None,now()))
        self.db.execute("UPDATE backend_jobs SET state='done' WHERE run_id=?",(run['run_id'],))
        value=self.plan();self.assertEqual('ready',value['status'],value)
        report=value['care_plan_context']['report']
        self.assertIn(eid,report['open_episode_ids']);self.assertEqual('attention_required',report['risk_status'])
        self.db.execute('INSERT INTO backend_risk_episode_versions VALUES(?,?,?,?,?,?,?,?,?)',
            (eid,2,'closed','Synthetic physician closure','doc-a',None,'{}',secrets.token_hex(16),now()))
        self.assertEqual('stale',analyses.read(self.db,self.user,'D01',value['run_id'])['status'])
        fresh=self.plan();self.assertEqual('ready',fresh['status'])
        self.assertEqual([],fresh['care_plan_context']['report']['open_episode_ids'])

    def test_plan_cancel_lease_data_change_and_executor_failure(self):
        self.diagnosis()
        value=analyses.create(self.db,self.user,'D01',self.body('plan'));work=jobs.claim(self.db,'generation')
        outcome=jobs.execute('plan',work['snapshot'])
        jobs.cancel(self.db,self.user,'D01',value['run_id'])
        self.assertFalse(jobs.finish(self.db,work,outcome))
        self.assertEqual('failed',analyses.read(self.db,self.user,'D01',value['run_id'])['status'])
        value=analyses.create(self.db,self.user,'D01',self.body('plan'));work=jobs.claim(self.db,'generation')
        self.db.execute("UPDATE backend_jobs SET lease_until='2000' WHERE run_id=?",(value['run_id'],))
        self.assertFalse(jobs.finish(self.db,work,jobs.execute('plan',work['snapshot'])))
        self.assertTrue(jobs.process_one(self.db,'generation'))
        self.assertEqual('ready',analyses.read(self.db,self.user,'D01',value['run_id'])['status'])
        value=analyses.create(self.db,self.user,'D01',self.body('plan'));work=jobs.claim(self.db,'generation')
        outcome=jobs.execute('plan',work['snapshot']);self.diary(summary='Новые сведения после начала проекта.')
        jobs.finish(self.db,work,outcome)
        self.assertEqual('stale',analyses.read(self.db,self.user,'D01',value['run_id'])['status'])

    def test_source_expiry_and_audit_failure_no_partial_result(self):
        self.diagnosis();value=analyses.create(self.db,self.user,'D01',self.body('plan'))
        work=jobs.claim(self.db,'generation');outcome=jobs.execute('plan',work['snapshot'])
        with patch.object(access,'audit',side_effect=sqlite3.IntegrityError('audit failure')):
            jobs.finish(self.db,work,outcome)
        self.assertNotIn('care_plan_context',analyses._latest(self.db,value['run_id']))
        self.db.execute("UPDATE backend_jobs SET available_at='2000'")
        self.assertTrue(jobs.process_one(self.db,'generation'))
        self.assertEqual('ready',analyses.read(self.db,self.user,'D01',value['run_id'])['status'])
        with patch.object(backend_sources,'clock',return_value=plans.sources.moment('2026-10-28T20:00:00+03:00')):
            self.assertEqual('stale',analyses.read(self.db,self.user,'D01',value['run_id'])['status'])


if __name__=='__main__':unittest.main()
