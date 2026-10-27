"""Physician reconciliation and plan publication mechanics, no clinical claims."""
from copy import deepcopy
from datetime import datetime,timezone
import json
import secrets
import sqlite3
import unittest
from unittest.mock import patch
from apps.compass import backend_therapy as therapy, backend_therapy_context as contexts
from apps.compass import backend_analyses as analyses, backend_care_plan as plans, backend_jobs as jobs
from apps.compass import access, backend_sources as sources
from apps.compass.web import create_app
from apps.tests import test_backend_care_plan as cp, test_backend_contracts, test_access

class ChoiceModel:
    def __init__(self,changes=None,raw=None):self.changes=changes or {};self.raw=raw;self.calls=0
    def generate(self,data,schema,**kwargs):
        self.calls+=1
        raw=self.raw if self.raw is not None else {'candidates':[dict(data['eligible_options'][0],**self.changes)]}
        return {'value':deepcopy(raw),'metadata':{'test_double':True}}

class TherapyIntegrationTests(unittest.TestCase):
    setUp=cp.CarePlanTests.setUp
    tearDown=cp.CarePlanTests.tearDown
    post=cp.CarePlanTests.post
    offer=cp.CarePlanTests.offer
    body=cp.CarePlanTests.body
    diary=cp.CarePlanTests.diary
    enable=cp.CarePlanTests.enable
    fixture=cp.CarePlanTests.fixture
    outcome=cp.CarePlanTests.outcome
    request_body=cp.CarePlanTests.request_body
    context=cp.CarePlanTests.context
    store=cp.CarePlanTests.store
    diagnosis=cp.CarePlanTests.diagnosis

    def reconciliation(self,**kw):
        state=contexts.view(self.db,self.user,'D01')
        return {'request_key':secrets.token_hex(16),'expected_version':state['expected_version'],
            'base_sha256':state['base_sha256'],'goal':'initiation','facts':{k:False for k in contexts.FLAGS},
            'allergies':[],'allergies_complete':True,'medications':[],'medications_complete':True,
            'response':'unknown','tolerability':'good','prior_first_line':'ineffective',
            'basis':'Явная авторская структурированная сверка для механического вымышленного случая; не клиническая экспертиза.',
            'reviewed':True}|kw
    def reconcile(self,**kw):return contexts.record(self.db,self.user,'D01',self.reconciliation(**kw))
    def work(self):
        run=analyses.create(self.db,self.user,'D01',self.body('plan'))
        return run,jobs.claim(self.db,'generation')
    def generate(self,model=None):
        run,work=self.work();outcome=plans.execute('plan',work['snapshot'],model=model or ChoiceModel())
        self.assertTrue(jobs.finish(self.db,work,outcome))
        value=analyses.read(self.db,self.user,'D01',run['run_id'])
        self.assertEqual('ready',value['status'],value)
        return value,work,outcome
    def test_positive_source_bound_plan_no_treatment_changes(self):
        self.diagnosis();receipt=self.reconcile()
        before=test_backend_contracts.table_rows(self.db)
        value,work,_=self.generate();extension=value['care_plan_context']['therapy'];report=extension['report']
        self.assertEqual('synthetic_physician_draft',report['status']);self.assertEqual(receipt['id'],report['context_id'])
        self.assertTrue(report['recommendations']);self.assertFalse(report['clinical_release']);self.assertFalse(report['applied'])
        for rec in report['recommendations']:
            self.assertIsNone(rec['duration_days']);self.assertTrue(rec['source']['pages'])
            self.assertIsNotNone(therapy.history.resolve(work['snapshot'],rec['evidence_refs'][0]))
            self.assertTrue(next(r['safety']['synthetic_eligible'] for r in report['candidate_reviews'] if r['candidate']==rec['candidate']))
        after=test_backend_contracts.table_rows(self.db)
        for table in before:
            if table not in ('analysis_runs','analysis_input_snapshots','analysis_result_versions','backend_jobs','backend_job_attempts','audit_entries'):
                self.assertEqual(before[table],after[table],table)
    def test_gad_second_line_and_no_universal_aviandr(self):
        self.diagnosis(kind='generalized_anxiety');self.reconcile()
        value,_,_=self.generate();rec=value['care_plan_context']['therapy']['report']['recommendations'][0]
        self.assertEqual('aviandr',rec['candidate']['product_id']);self.assertIn('второй линии',rec['basis'])
        self.assertEqual(40,rec['candidate']['daily_dose_mg']);self.assertIn('30 минут',rec['administration'])
        self.reconcile(prior_first_line='not_tried');model=ChoiceModel();value,_,_=self.generate(model)
        self.assertEqual(0,model.calls);self.assertEqual([],value['care_plan_context']['therapy']['report']['recommendations'])
    def test_exact_maintenance_response_and_adherence(self):
        self.diagnosis()
        med=dict(product_id='elicea',ingredient='escitalopram',state='current',prescribed=True,actual=True,
                 daily_dose_mg=10,strength_mg=10,times_per_day=1,unit='mg',form='film_coated_tablet')
        self.reconcile(goal='maintenance',response='effective',medications=[med])
        value,_,_=self.generate();self.assertTrue(value['care_plan_context']['therapy']['report']['recommendations'])
        self.reconcile(goal='maintenance',response='effective',medications=[dict(med,actual=False)])
        model=ChoiceModel();value,_,_=self.generate(model)
        self.assertEqual(0,model.calls);self.assertFalse(value['care_plan_context']['therapy']['report']['recommendations'])
    def test_post_generation_wrong_unit_dose_product_and_phase_removed(self):
        self.diagnosis();self.reconcile()
        for changes in ({'unit':'ml'},{'daily_dose_mg':999},{'product_id':'unknown'},
                        {'phase':'change'},{'indication':'adult_gad'}):
            model=ChoiceModel(changes);value,_,_=self.generate(model)
            report=value['care_plan_context']['therapy']['report']
            self.assertEqual(1,model.calls);self.assertEqual([],report['recommendations']);self.assertTrue(report['questions'])
    def test_unknown_medications_allergy_caution_and_recent_stop_no_model(self):
        self.diagnosis()
        for changes in ({'medications_complete':None},{'allergies':['lactose_monohydrate','sertraline']},
                        {'facts':dict.fromkeys(contexts.FLAGS,None)}, {'tolerability':'adverse'}):
            self.reconcile(**changes);model=ChoiceModel();value,_,_=self.generate(model)
            self.assertEqual(0,model.calls);self.assertFalse(value['care_plan_context']['therapy']['report']['recommendations'])
            self.assertTrue(value['care_plan_context']['therapy']['report']['questions'])
    def test_change_stop_are_clarifications_without_invented_regimen(self):
        self.diagnosis()
        for goal in ('change','stop'):
            self.reconcile(goal=goal);model=ChoiceModel();value,_,_=self.generate(model)
            report=value['care_plan_context']['therapy']['report'];self.assertEqual(0,model.calls)
            self.assertFalse(report['recommendations']);self.assertTrue(report['preconditions']);self.assertEqual(goal,report['goal'])
    def test_context_http_roles_csrf_exact_retry_and_version_conflict(self):
        self.diagnosis();url='/api/v1/patients/D01/therapy-context';client=self.clients['doc-a']
        body=self.reconciliation();headers={'X-CSRF-Token':test_access.csrf(client)}
        self.assertEqual(200,client.get(url).status_code)
        self.assertEqual(403,client.post(url,json=body).status_code)
        response=client.post(url,json=body,headers=headers);self.assertEqual(200,response.status_code,response.json)
        self.assertEqual(response.json,client.post(url,json=body,headers=headers).json)
        old=dict(body,request_key=secrets.token_hex(16));self.assertEqual(409,client.post(url,json=old,headers=headers).status_code)
        for uid in ('pat-a','doc-b'):
            self.assertIn(self.clients[uid].get(url).status_code,(403,404))
        self.assertEqual(401,self.app.test_client().get(url).status_code)
        self.assertEqual('no-store',response.headers['Cache-Control'])
        with self.assertRaises(sqlite3.IntegrityError):self.db.execute('DELETE FROM backend_therapy_contexts')
    def test_data_and_context_changes_fence_inflight_result(self):
        self.diagnosis();self.reconcile();run,work=self.work();outcome=plans.execute('plan',work['snapshot'],model=ChoiceModel())
        self.reconcile(response='partial');jobs.finish(self.db,work,outcome)
        self.assertEqual('stale',analyses.read(self.db,self.user,'D01',run['run_id'])['status'])
        run,work=self.work();self.diary(summary='Новые сведения после сверки.')
        jobs.finish(self.db,work,plans.execute('plan',work['snapshot'],model=ChoiceModel()))
        self.assertEqual('stale',analyses.read(self.db,self.user,'D01',run['run_id'])['status'])
        self.assertFalse(contexts.view(self.db,self.user,'D01')['current']['fresh'])
    def test_forged_projection_raw_source_or_eligibility_rejected(self):
        self.diagnosis();self.reconcile()
        for change in ('text','dose','safety','missing'):
            run,work=self.work();out=plans.execute('plan',work['snapshot'],model=ChoiceModel())
            extension=out['care_plan_context']['therapy']
            if change=='text':out['result']['output']['items'][-1]['text']='Forged regimen'
            if change=='dose':extension['report']['recommendations'][0]['candidate']['daily_dose_mg']=999
            if change=='safety':extension['report']['candidate_reviews'][0]['safety']['state']='block'
            if change=='missing':out['care_plan_context'].pop('therapy')
            jobs.finish(self.db,work,out)
            self.assertEqual('running',analyses._latest(self.db,run['run_id'])['status'])
            self.db.execute("UPDATE backend_jobs SET state='done' WHERE run_id=?",(run['run_id'],))
    def test_no_quality_admission_blocks_default_model_and_failures_do_not_publish(self):
        from apps.compass.backend_model import ModelError
        self.diagnosis();self.reconcile();run,work=self.work()
        from pathlib import Path
        with patch.object(therapy,'QUALITY_PATH',Path(self.tmp.name)/'missing-quality.json'):
            with self.assertRaises(ModelError) as caught:plans.execute('plan',work['snapshot'])
        self.assertEqual('therapy_quality_not_admitted',caught.exception.code)
        jobs.finish(self.db,work,error='timeout')
        self.assertNotIn('care_plan_context',analyses._latest(self.db,run['run_id']))
    def test_schema_rejects_bool_number_nonfinite_extra_fields_and_fake_attestation(self):
        self.diagnosis()
        for changes in ({'reviewed':False},{'facts':dict.fromkeys(contexts.FLAGS,1)}, {'eligible':True},
                        {'medications':[{'name':'no drugs'}]}):
            with self.assertRaises(analyses.AnalysisError):contexts.record(self.db,self.user,'D01',self.reconciliation(**changes))
        for value in (True,float('nan'),float('inf'),'10 мг'):
            with self.assertRaises(analyses.AnalysisError):analyses.validate_schema(value,{'type':'number'})
    def test_reconciliation_stale_base_and_audit_rollback(self):
        self.diagnosis();body=self.reconciliation();self.diary(summary='Изменение до сохранения сверки.')
        with self.assertRaises(analyses.AnalysisError):contexts.record(self.db,self.user,'D01',body)
        body=self.reconciliation()
        with patch.object(access,'audit',side_effect=sqlite3.IntegrityError('test audit failure')):
            with self.assertRaises(sqlite3.IntegrityError):contexts.record(self.db,self.user,'D01',body)
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM backend_therapy_contexts').fetchone()[0])

if __name__=='__main__':unittest.main()
