"""Mechanics only. Real semantic evaluation is separate fixed synthetic corpus."""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch
from apps.compass import backend_diagnosis_service as service, backend_analyses as analyses
from apps.compass import backend_jobs as jobs,backend_risk_context as context
from apps.tests import test_backend_diagnoses as legacy,test_backend_contracts,test_access
from apps.tests.diagnosis_fixtures import BranchModel, named_responses

class DiagnosisIntegrationTests(unittest.TestCase):
    setUp=legacy.DiagnosisTests.setUp
    tearDown=legacy.DiagnosisTests.tearDown
    post=legacy.DiagnosisTests.post
    offer=legacy.DiagnosisTests.offer
    body=legacy.DiagnosisTests.body
    diary=legacy.DiagnosisTests.diary
    visit=legacy.DiagnosisTests.visit
    questionnaire=legacy.DiagnosisTests.questionnaire
    snapshot=legacy.DiagnosisTests.snapshot

    def enable(self):
        self.db.execute('UPDATE backend_job_settings SET enabled=1,generation_version=?',(service.EXECUTION_VERSION,))

    def fixture(self,positive=False):
        self.enable();self.diary(summary='Авторское вымышленное основание технического теста, не медицинский случай: 14 дней, 6 месяцев.')
        run=analyses.create(self.db,self.user,'D01',self.body('diagnosis'));work=jobs.claim(self.db,'generation')
        raw={'quotes':[],'facts':[[] for _ in range(56)],'durations':{k:{'value':None,'refs':[]} for k in service.legacy.KINDS[:2]},'leading':None}
        if positive:
            u=next(u for u in context.prepare_snapshot(work['snapshot']) if u['code']=='summary')
            raw['quotes']=[{'u':u['unit_id'],'q':u['text']}]
            catalog=service.criteria.release()
            for i,(kind,fid) in enumerate(service.fact_index(catalog)):
                if kind!='depressive_episode':continue
                denied=any(c['state']=='denied' and fid in c['facts'] for c in catalog['conditions'][kind]['checks'])
                raw['facts'][i]=[-1 if denied else 1]
            raw['durations']['depressive_episode']={'value':14,'refs':[1]};raw['leading']='depressive_episode'
        return run,work,raw

    def outcome(self,work,raw):
        return service.execute('diagnosis',work['snapshot'],BranchModel(named_responses(raw)))

    def test_ready_atomic_http_idempotency_details_no_clinical_actions(self):
        run,work,raw=self.fixture(True);before=test_backend_contracts.table_rows(self.db)
        self.assertTrue(jobs.finish(self.db,work,self.outcome(work,raw)))
        value=analyses.read(self.db,self.user,'D01',run['run_id']);self.assertEqual('ready',value['status'])
        self.assertFalse(value['diagnosis_context']['clinical_ready']);self.assertEqual('unreviewed',value['diagnosis_context']['status'])
        self.assertFalse(jobs.finish(self.db,work,self.outcome(work,raw)))
        path=self.url+'/'+run['run_id']+'/diagnosis-context'
        response=self.clients['doc-a'].get(path);self.assertEqual(200,response.status_code)
        self.assertEqual('no-store',response.headers['Cache-Control']);report=response.json['report']
        self.assertEqual('depressive_episode',report['leading']);self.assertEqual(4,len(report['hypotheses']))
        self.assertIsNone(report['established_diagnosis']);self.assertIsNone(report['plan'])
        self.assertTrue(report['hypotheses'][1]['distinguishing_questions'])
        self.assertEqual(200,self.clients['doc-a'].head(path).status_code)
        for uid in ('doc-b','pat-a'):
            self.assertIn(self.clients[uid].get(path).status_code,(403,404))
        self.assertEqual(400,self.clients['doc-a'].get(path+'?bad=1').status_code)
        after=test_backend_contracts.table_rows(self.db)
        for table in ('care_actions','clinical_entries','first_visit_versions','patients','treatment_plan_versions'):
            if table in before:self.assertEqual(before[table],after[table],table)
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])

    def test_unknown_keeps_questions_all_alternatives_not_denied(self):
        run,work,raw=self.fixture();jobs.finish(self.db,work,self.outcome(work,raw))
        value=analyses.read(self.db,self.user,'D01',run['run_id']);self.assertEqual('insufficient_data',value['status'])
        report=service.details(self.db,self.user,'D01',run['run_id'])['report']
        self.assertTrue(all(h['distinguishing_questions'] for h in report['hypotheses']))
        self.assertIsNone(value['result']);self.assertEqual(0,self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])

    def test_exact_quote_refs_conflicts_duration_codes_and_false_leading_rejected(self):
        _,work,raw=self.fixture(True)
        for variant in ('quote','zero','missing','duplicate','same_conflict','duration','probability','leading'):
            bad=deepcopy(raw)
            if variant=='quote':bad['quotes'][0]['q']='invented'
            if variant=='zero':bad['facts'][0]=[0]
            if variant=='missing':bad['facts'].pop()
            if variant=='duplicate':bad['facts'][0]=[1,1]
            if variant=='same_conflict':bad['facts'][0]=[1,-1]
            if variant=='duration':bad['durations']['depressive_episode']['value']=True
            if variant=='probability':bad['probability']=99
            if variant=='leading':bad['facts'][0]=[]
            with self.assertRaises((ValueError,TypeError)):service.interpret(work['snapshot'],bad)

    def test_cancel_stale_lease_role_version_and_source_fence(self):
        for variant in ('cancel','data','lease','role','version','source'):
            with self.subTest(variant=variant):
                run,work,raw=self.fixture(True);outcome=self.outcome(work,raw)
                if variant=='cancel':jobs.cancel(self.db,self.user,'D01',run['run_id'])
                if variant=='data':self.diary(summary='Новая синтетическая запись.')
                if variant=='lease':self.db.execute("UPDATE backend_jobs SET lease_until='2000' WHERE run_id=?",(run['run_id'],))
                if variant=='role':self.db.execute("UPDATE users SET disabled=1 WHERE id='doc-a'")
                if variant=='version':self.db.execute("UPDATE backend_job_settings SET generation_version='changed'")
                if variant=='source':
                    outcome['diagnosis_report']['context']['runtime']['engine_sha256']='changed'
                jobs.finish(self.db,work,outcome)
                latest=analyses._latest(self.db,run['run_id']);self.assertNotIn('diagnosis_context',latest)
                self.assertNotEqual('ready',latest['status'])
                self.db.execute("UPDATE users SET disabled=0 WHERE id='doc-a'")
                # Finish pending work before the next independent fixture.
                self.db.execute("UPDATE backend_jobs SET state='done',token=NULL,lease_until=NULL WHERE state IN ('pending','running')")

    def test_existing_queue_retry_recovers_format_without_partial_publication(self):
        run,work,raw=self.fixture(True)
        # Return the initial lease through the same technical retry transition.
        self.assertTrue(jobs.finish(self.db,work,error='executor_error'))
        self.assertNotIn('diagnosis_context',analyses._latest(self.db,run['run_id']))
        self.db.execute("UPDATE backend_jobs SET available_at='2000'")
        self.assertTrue(jobs.process_one(self.db,'generation',executor=lambda op,snapshot:self.outcome({'snapshot':snapshot},raw)))
        value=analyses.read(self.db,self.user,'D01',run['run_id'])
        self.assertEqual('ready',value['status'])
        attempts=self.db.execute('SELECT outcome FROM backend_job_attempts WHERE run_id=? ORDER BY attempt',(run['run_id'],)).fetchall()
        self.assertEqual(['retry','done'],[r[0] for r in attempts])
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])

    def test_publication_rollback_and_default_executor_missing_credentials(self):
        run,work,raw=self.fixture(True);outcome=self.outcome(work,raw)
        with patch.object(analyses,'_append',side_effect=sqlite3.IntegrityError('synthetic')):
            jobs.finish(self.db,work,outcome)
        self.assertEqual('running',analyses._latest(self.db,run['run_id'])['status'])
        self.assertEqual('pending',self.db.execute('SELECT state FROM backend_jobs WHERE run_id=?',(run['run_id'],)).fetchone()[0])
        self.db.execute("UPDATE backend_jobs SET available_at='2000'")
        with patch.dict('os.environ',{},clear=True):
            jobs.process_one(self.db,'generation')
        self.assertNotEqual('ready',analyses._latest(self.db,run['run_id'])['status'])
        self.assertNotIn('diagnosis_context',analyses._latest(self.db,run['run_id']))


class AdmissionAndCancelTests(unittest.TestCase):
    setUp=DiagnosisIntegrationTests.setUp
    tearDown=DiagnosisIntegrationTests.tearDown
    post=DiagnosisIntegrationTests.post
    offer=DiagnosisIntegrationTests.offer
    body=DiagnosisIntegrationTests.body
    diary=DiagnosisIntegrationTests.diary
    enable=DiagnosisIntegrationTests.enable
    fixture=DiagnosisIntegrationTests.fixture
    outcome=DiagnosisIntegrationTests.outcome

    def test_failed_quality_blocks_default_before_budget_or_transport(self):
        _,work,_=self.fixture()
        with patch.object(service.json,'loads',return_value={'pass':False}), patch('apps.compass.backend_model.DeepSeek',side_effect=AssertionError('must not initialize')):
            with self.assertRaisesRegex(ValueError,'diagnosis_quality_not_admitted'):
                service.execute('diagnosis',work['snapshot'])
        self.assertTrue(jobs.finish(self.db,work,error='diagnosis_quality_not_admitted'))
        self.assertNotIn('diagnosis_context',analyses._latest(self.db,work['run']['id']))

    def test_http_cancel_csrf_roles_repetition_late_result_and_no_side_effect_get(self):
        run,work,raw=self.fixture(True);outcome=self.outcome(work,raw)
        path=self.url+'/'+run['run_id']+'/cancel';client=self.clients['doc-a']
        self.assertEqual(405,client.get(path).status_code)
        self.assertEqual(403,client.post(path,json={}).status_code)
        self.assertEqual(400,client.post(path,json={'extra':1},headers={'X-CSRF-Token':test_access.csrf(client)}).status_code)
        for uid in ('doc-b','pat-a'):
            c=self.clients[uid];self.assertIn(c.post(path,json={},headers={'X-CSRF-Token':test_access.csrf(c)}).status_code,(403,404))
        for _ in range(2):
            response=client.post(path,json={},headers={'X-CSRF-Token':test_access.csrf(client)})
            self.assertEqual(200,response.status_code);self.assertEqual('failed',response.json['status'])
        self.assertFalse(jobs.finish(self.db,work,outcome))
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])

class ExactAdmissionTests(AdmissionAndCancelTests):
    # Reuse only the mechanics helpers; avoid inheriting the previous test methods.
    test_failed_quality_blocks_default_before_budget_or_transport=None
    test_http_cancel_csrf_roles_repetition_late_result_and_no_side_effect_get=None

    def grade(self, value):
        original=Path.read_text
        target=service.criteria.ROOT/'evidence/BE10/diagnosis-quality.json'
        def read(path,*args,**kw):
            return json.dumps(value) if path==target else original(path,*args,**kw)
        return patch.object(Path,'read_text',new=read)

    def test_pass_from_another_runtime_cannot_initialize_adapter(self):
        _,work,_=self.fixture()
        with self.grade({'pass':True,'runtime_sha256':'wrong'}), patch('apps.compass.backend_model.DeepSeek',side_effect=AssertionError('must not initialize')):
            with self.assertRaisesRegex(ValueError,'diagnosis_quality_not_admitted'):
                service.execute('diagnosis',work['snapshot'])

    def test_exact_synthetic_admission_uses_unchanged_ceiling_without_real_network(self):
        _,work,raw=self.fixture(True);adapter=BranchModel(named_responses(raw))
        runtime=service.snapshots.digest(service.release())
        with self.grade({'pass':True,'runtime_sha256':runtime}), patch('apps.compass.backend_model.Budget',return_value=object()) as budget, patch('apps.compass.backend_model.DeepSeek',return_value=adapter) as constructor:
            report=service.execute('diagnosis',work['snapshot'])
        self.assertEqual('depressive_episode',report['diagnosis_report']['context']['leading'])
        budget.assert_called_once();constructor.assert_called_once()
        cfg=constructor.call_args.args[0]
        self.assertEqual(4000000,cfg.total_micro_usd);self.assertEqual(20000,cfg.per_call_micro_usd)
        self.assertEqual(2,len(adapter.calls))

if __name__=='__main__':unittest.main()
