"""BE15 mechanical acceptance in disposable synthetic databases, not clinical review."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
import json
import secrets
import sqlite3
from threading import Barrier
import unittest
from unittest.mock import patch

from apps.compass import backend_plan_review as review, decisions, medications, records, access
from apps.compass import backend_analyses as analyses, backend_sources as sources, communication
from apps.compass.db import connect, migrate
from apps.compass.web import create_app
from apps.tests import test_backend_therapy_integration as ti, test_backend_contracts, test_access


class PlanReviewTests(unittest.TestCase):
    setUp = ti.TherapyIntegrationTests.setUp
    tearDown = ti.TherapyIntegrationTests.tearDown
    post = ti.TherapyIntegrationTests.post
    offer = ti.TherapyIntegrationTests.offer
    body = ti.TherapyIntegrationTests.body
    diary = ti.TherapyIntegrationTests.diary
    enable = ti.TherapyIntegrationTests.enable
    fixture = ti.TherapyIntegrationTests.fixture
    outcome = ti.TherapyIntegrationTests.outcome
    request_body = ti.TherapyIntegrationTests.request_body
    context = ti.TherapyIntegrationTests.context
    store = ti.TherapyIntegrationTests.store
    diagnosis = ti.TherapyIntegrationTests.diagnosis
    reconciliation = ti.TherapyIntegrationTests.reconciliation
    reconcile = ti.TherapyIntegrationTests.reconcile
    work = ti.TherapyIntegrationTests.work
    generate = ti.TherapyIntegrationTests.generate

    def ready_plan(self, **kw):
        self.diagnosis(**kw)
        self.reconcile()
        value, _, _ = self.generate()
        return value

    def edit_body(self, value, medication=True, **kw):
        latest = review.head(self.db, 'D01')
        options = value['care_plan_context']['therapy']['report']['recommendations']
        med = options[0] if medication else None
        return {'request_key': secrets.token_hex(16), 'analysis_revision': value['revision'],
            'snapshot_id': value['snapshot_id'], 'expected_version': latest['version'] if latest else 0,
            'parent_id': latest['proposal_id'] if latest else None,
            'items': [{'id': i['id'], 'due_on': (records.today()+timedelta(days=1)).isoformat()}
                for i in value['care_plan_context']['report']['items']],
            'medication': {'recommendation_id': med['id'], 'candidate': deepcopy(med['candidate']),
                'start': records.today().isoformat(), 'days': 14,
                'times': ['23:59'] if med['candidate']['times_per_day']==1 else ['12:00','23:59']} if med else None,
            'routing': None, 'basis': 'Явное решение вымышленного врача.',
            'uncertainties': 'Синтетическая проверка, клинический допуск отсутствует.', 'reviewed': True}|kw

    def draft_plan(self, value=None, body=None):
        value = value or self.ready_plan()
        return review.create(self.db, self.user, 'D01', value['run_id'], body or self.edit_body(value))

    def confirmation(self, receipt, **kw):
        return {'version': receipt['proposal_version'], 'decision': 'approved',
                'rationale': 'Отдельное решение врача по точной версии.', 'reviewed': True}|kw

    def approve(self, receipt):
        return review.confirm(self.db, self.user, 'D01', receipt['proposal_id'], self.confirmation(receipt))

    def test_edit_separate_approval_single_action_calendar_tasks_and_history(self):
        value = self.ready_plan();body = self.edit_body(value)
        first = self.draft_plan(value, body)
        body2 = self.edit_body(value);body2['medication']['days']=21
        body2['medication']['times']=['22:30']
        second = self.draft_plan(value, body2)
        patient = {'id':'pat-a','role':'patient'}
        self.assertEqual([], decisions.history(self.db, patient, 'D01'))
        self.assertFalse(medications.approved(self.db,'D01'))
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM adherence_tasks').fetchone()[0])
        with self.assertRaises(analyses.AnalysisError):self.approve(first)
        approved = self.approve(second)
        self.assertEqual('approved',approved['decision'])
        self.assertEqual(1,self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])
        history=decisions.history(self.db,patient,'D01');self.assertEqual([second['proposal_id']],[h['id'] for h in history])
        self.assertEqual(21,medications.calendar(self.db,'D01')['current_medications'][0]['days'])
        self.assertEqual('22:30',medications.calendar(self.db,'D01')['current_medications'][0]['slots'][0]['time'])
        self.assertEqual(len(body2['items']),len(communication.view(self.db,patient,'D01')['tasks']))
        self.assertFalse(approved['payload']['automatic']);self.assertEqual('blocked',approved['clinical_release'])
        with self.assertRaises(sqlite3.IntegrityError):self.db.execute('DELETE FROM backend_plan_reviews')
        with self.assertRaises(sqlite3.IntegrityError):self.db.execute('DELETE FROM proposals WHERE id=?',(first['proposal_id'],))

    def test_rejection_never_applies_and_exact_retries_survive_data_change(self):
        value=self.ready_plan();body=self.edit_body(value);draft=self.draft_plan(value,body)
        rejection=self.confirmation(draft,decision='rejected')
        result=review.confirm(self.db,self.user,'D01',draft['proposal_id'],rejection)
        self.diary(summary='Новые сведения после отклонения.')
        self.assertEqual(result,review.create(self.db,self.user,'D01',value['run_id'],body))
        self.assertEqual(result,review.confirm(self.db,self.user,'D01',draft['proposal_id'],rejection))
        self.assertEqual([],medications.approved(self.db,'D01'))
        self.assertEqual([],decisions.history(self.db,{'role':'patient'},'D01'))
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM adherence_tasks').fetchone()[0])
        with self.assertRaises(analyses.AnalysisError):self.approve(draft)

    def test_stale_diary_diagnosis_therapy_context_risk_and_source_block_direct_confirmation(self):
        value=self.ready_plan();draft=self.draft_plan(value)
        self.diary(summary='Новая критически важная вымышленная запись.')
        with self.assertRaises((analyses.AnalysisError,decisions.DecisionError)):
            decisions.confirm(self.db,self.user,'D01',draft['proposal_id'],
                dict(self.confirmation(draft),version=str(draft['proposal_version']),reviewed='yes'))
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])

    def test_reconciliation_and_diagnosis_fence(self):
        value=self.ready_plan();draft=self.draft_plan(value)
        self.reconcile(response='partial')
        with self.assertRaises(analyses.AnalysisError):self.approve(draft)
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM doctor_confirmations').fetchone()[0])

    def test_new_diagnosis_blocks_exact_plan(self):
        from apps.compass import backend_diagnosis_review
        value=self.ready_plan();draft=self.draft_plan(value)
        backend_diagnosis_review.record(self.db,self.user,'D01',self.request_body())
        with self.assertRaises(analyses.AnalysisError):self.approve(draft)
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])

    def test_new_risk_episode_blocks_confirmation_and_alert_remains_deliverable(self):
        from apps.compass import backend_alerts, events
        from apps.compass.db import now, transaction
        value=self.ready_plan();draft=self.draft_plan(value)
        relationship=analyses.authorize(self.db,self.user,'D01');eid=secrets.token_hex(16)
        risk_run=analyses.create(self.db,self.user,'D01',self.body('risk'))
        with transaction(self.db):
            self.db.execute('INSERT INTO backend_risk_episodes VALUES(?,?,?,?,?,?)',
                (eid,'D01',relationship,'model_candidate','synthetic_unknown_safety',now()))
            self.db.execute('INSERT INTO backend_risk_episode_versions VALUES(?,?,?,?,?,?,?,?,?)',
                (eid,1,'open','Synthetic mechanics','doc-a',risk_run['run_id'],'{}',None,now()))
            backend_alerts.enqueue_pending(self.db)
        with self.assertRaises(analyses.AnalysisError):self.approve(draft)
        self.assertEqual(1,self.db.execute('SELECT count(*) FROM backend_alerts').fetchone()[0])
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])

    def test_existing_medication_mark_survives_replacement_and_atomic_failure(self):
        from apps.compass.db import now
        value=self.ready_plan();draft=self.draft_plan(value);self.approve(draft)
        self.db.execute('''INSERT INTO medication_marks
            (patient_id,proposal_id,med_index,slot_index,dose_on,actor_id,actual_quarters,recorded_at,request_key)
            VALUES(?,?,?,?,?,?,?,?,?)''',('D01',draft['proposal_id'],0,0,records.today().isoformat(),
            'pat-a',4,now(),secrets.token_hex(16)))
        marks=[tuple(r) for r in self.db.execute('SELECT * FROM medication_marks')]
        tasks=[tuple(r) for r in self.db.execute('SELECT * FROM adherence_tasks')]
        old_context=self.db.execute('SELECT id FROM clinical_contexts').fetchone()[0]
        original_context=self.context
        with patch.object(self,'context',side_effect=lambda condition,**kw:original_context(condition,supersedes_id=old_context,**kw)):
            self.diagnosis()
        candidate=draft['payload']['selected_medication']['candidate']
        from apps.compass import backend_medication_regimens
        product=backend_medication_regimens.release()['products'][candidate['product_id']]
        med={k:candidate[k] for k in ('product_id','form','unit','strength_mg','daily_dose_mg','times_per_day')}
        med.update(ingredient=product['ingredient'],state='current',prescribed=True,actual=True)
        self.reconcile(goal='maintenance',response='effective',medications=[med])
        value,_,_=self.generate();body=self.edit_body(value)
        changed=self.draft_plan(value,body);self.approve(changed)
        actions=self.db.execute('SELECT * FROM care_actions ORDER BY effective_at').fetchall()
        self.assertEqual(actions[0]['id'],actions[1]['supersedes_id'])
        self.assertEqual(marks,[tuple(r) for r in self.db.execute('SELECT * FROM medication_marks')])
        self.assertTrue(all(t in [tuple(r) for r in self.db.execute('SELECT * FROM adherence_tasks')] for t in tasks))
        self.assertEqual(changed['proposal_id'],medications.base_id(self.db,'D01'))
        self.assertEqual(2,len(decisions.history(self.db,{'role':'patient'},'D01')))

    def test_source_revocation_runtime_and_expiry_fence(self):
        value=self.ready_plan();draft=self.draft_plan(value)
        original=sources.capture()
        changed=deepcopy(original);changed['sources']['KR301_3']['reasons']=['withdrawn']
        with patch.object(sources,'capture',return_value=changed):
            with self.assertRaises(analyses.AnalysisError):self.approve(draft)
        with patch.object(review,'runtime',return_value='changed'):
            with self.assertRaises(analyses.AnalysisError):self.approve(draft)
        from apps.compass import backend_medication_regimens as regimens
        original=regimens.release
        def expired():
            c=original()
            for s in c['sources'].values():s['review_due_at']='2000-01-01T00:00:00+03:00'
            return c
        with patch.object(regimens,'release',side_effect=expired):
            with self.assertRaises((analyses.AnalysisError,ValueError)):self.approve(draft)
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])

    def test_edit_dose_unit_product_frequency_unknown_and_duplicate_fail_closed(self):
        value=self.ready_plan()
        for change in ({'daily_dose_mg':999},{'unit':'ml'},{'product_id':'unknown'},
                       {'times_per_day':2},{'phase':'stop'}):
            body=self.edit_body(value);body['medication']['candidate'].update(change)
            with self.assertRaises(analyses.AnalysisError):self.draft_plan(value,body)
        body=self.edit_body(value);body['items'].append(body['items'][0])
        with self.assertRaises(analyses.AnalysisError):self.draft_plan(value,body)
        body=self.edit_body(value);body['medication']['times']=['00:00','01:00']
        with self.assertRaises(analyses.AnalysisError):self.draft_plan(value,body)
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM proposals').fetchone()[0])

    def test_audit_and_task_storage_failure_roll_back_everything(self):
        value=self.ready_plan();draft=self.draft_plan(value)
        before=test_backend_contracts.table_rows(self.db)
        with patch.object(access,'audit',side_effect=sqlite3.IntegrityError('test audit failure')):
            with self.assertRaises(sqlite3.IntegrityError):self.approve(draft)
        self.assertEqual(before,test_backend_contracts.table_rows(self.db))
        self.db.execute("CREATE TRIGGER test_task_failure BEFORE INSERT ON adherence_tasks BEGIN SELECT RAISE(ABORT,'test task write failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.approve(draft)
        self.assertEqual(before,test_backend_contracts.table_rows(self.db))
        self.db.execute('DROP TRIGGER test_task_failure')
        self.assertEqual('approved',self.approve(draft)['decision'])

    def test_retry_conflicts_no_second_action_and_parallel_confirmation(self):
        value=self.ready_plan();body=self.edit_body(value);draft=self.draft_plan(value,body)
        conflict=deepcopy(body);conflict['basis']='Другая редакция'
        with self.assertRaises(analyses.AnalysisError):self.draft_plan(value,conflict)
        barrier=Barrier(2)
        def call():
            db=connect(self.path)
            try:
                barrier.wait();return review.confirm(db,self.user,'D01',draft['proposal_id'],self.confirmation(draft))
            finally:db.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:call(),range(2)))
        self.assertEqual(results[0],results[1])
        self.assertEqual(1,self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])
        self.assertEqual(len(body['items']),self.db.execute('SELECT count(*) FROM adherence_tasks').fetchone()[0])
        self.diary(summary='Новые сведения после подтверждения.')
        self.assertEqual(results[0],self.approve(draft))

    def test_http_auth_csrf_exact_versions_restart_and_patient_projection(self):
        value=self.ready_plan();body=self.edit_body(value)
        url=f"/api/v1/patients/D01/analyses/{value['run_id']}/plan-reviews"
        client=self.clients['doc-a'];headers={'X-CSRF-Token':test_access.csrf(client)}
        self.assertEqual(403,client.post(url,json=body).status_code)
        response=client.post(url,json=body,headers=headers);self.assertEqual(200,response.status_code,response.json)
        draft=response.json;path='/api/v1/patients/D01/plan-reviews/'+draft['proposal_id']
        self.assertEqual('no-store',response.headers['Cache-Control'])
        for uid in ('pat-a','doc-b'):
            self.assertIn(self.clients[uid].get(path).status_code,(403,404))
        self.assertEqual(401,self.app.test_client().get(path).status_code)
        self.assertEqual(400,client.get(path+'?bad=1').status_code)
        self.assertEqual(403,client.post(path,json=self.confirmation(draft)).status_code)
        bad=self.confirmation(draft,version=999)
        self.assertEqual(409,client.post(path,json=bad,headers=headers).status_code)
        restart=create_app(self.path).test_client();restart.set_cookie(access.COOKIE,client.get_cookie(access.COOKIE).value)
        r=restart.post(path,json=self.confirmation(draft),headers=headers)
        self.assertEqual(200,r.status_code,r.json)
        patient=self.clients['pat-a'].get('/api/patients/D01/decisions')
        self.assertEqual([draft['proposal_id']],[d['id'] for d in patient.json['decisions']])
        self.assertEqual(409,client.post('/api/patients/D01/actions',json={},headers=headers).status_code)
        self.assertEqual(403,self.clients['pat-a'].post(path,json=self.confirmation(draft),headers={'X-CSRF-Token':test_access.csrf(self.clients['pat-a'])}).status_code)
        migrate(self.db);self.assertEqual('ok',self.db.execute('PRAGMA integrity_check').fetchone()[0])
        self.assertEqual([],self.db.execute('PRAGMA foreign_key_check').fetchall())

    def test_patient_cannot_confirm_disabled_doctor_and_old_schema_compatibility(self):
        value=self.ready_plan();draft=self.draft_plan(value)
        for user in ({'id':'pat-a','role':'patient'},{'id':'doc-b','role':'doctor'}):
            with self.assertRaises((analyses.AnalysisError,decisions.DecisionError)):
                review.confirm(self.db,user,'D01',draft['proposal_id'],self.confirmation(draft))
        self.db.execute("UPDATE users SET disabled=1 WHERE id='doc-a'")
        with self.assertRaises((analyses.AnalysisError,decisions.DecisionError)):self.approve(draft)
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])

    def test_routing_requires_explicit_review_and_risk_cannot_be_removed(self):
        value=self.ready_plan(risk={'suicidal_plan':'present','suicidal_intent':'unknown'})
        body=self.edit_body(value,medication=False)
        with self.assertRaises(analyses.AnalysisError):self.draft_plan(value,body)
        body['routing']={'category':'mandatory','urgency':'urgent','severity_status':'known',
            'population_status':'known','specialty':'Психиатр','severity':'Отдельная оценка врача.',
            'population':'Взрослый','evidence':'Вымышленный пример, не медицинская рекомендация.',
            'unavailable':'Неизвестность сохраняется.','age_years':'35'}
        draft=self.draft_plan(value,body);self.approve(draft)
        self.assertEqual(1,self.db.execute('SELECT count(*) FROM referrals').fetchone()[0])
        self.assertEqual([],medications.approved(self.db,'D01'))
        self.assertTrue(communication.current_action(self.db,'D01'))

if __name__=='__main__':unittest.main()
