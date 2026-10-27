"""BE11 mechanics in disposable synthetic SQLite; no clinical validation."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
import secrets
import sqlite3
from threading import Barrier
import unittest
from unittest.mock import patch

from apps.compass import backend_diagnosis_review as review, backend_analyses as analyses
from apps.compass import backend_jobs as jobs, decisions, access
from apps.compass.db import connect
from apps.compass.web import create_app
from apps.tests import test_access, test_backend_contracts
from apps.tests import test_backend_diagnosis_integration as integration


class DiagnosisReviewTests(unittest.TestCase):
    setUp = integration.DiagnosisIntegrationTests.setUp
    tearDown = integration.DiagnosisIntegrationTests.tearDown
    post = integration.DiagnosisIntegrationTests.post
    offer = integration.DiagnosisIntegrationTests.offer
    body = integration.DiagnosisIntegrationTests.body
    diary = integration.DiagnosisIntegrationTests.diary
    enable = integration.DiagnosisIntegrationTests.enable
    fixture = integration.DiagnosisIntegrationTests.fixture
    outcome = integration.DiagnosisIntegrationTests.outcome

    url_review = '/api/v1/patients/D01/diagnosis-review'

    def ready(self):
        run, work, raw = self.fixture(True)
        self.assertTrue(jobs.finish(self.db, work, self.outcome(work, raw)))
        return analyses.read(self.db, self.user, 'D01', run['run_id'])

    def request_body(self, action='manual', run=None):
        state = review.view(self.db, self.user, 'D01')
        return {'request_key': secrets.token_hex(16), 'expected_version': state['head_version'],
            'snapshot_id': state['snapshot_id'], 'action': action,
            'run_id': run['run_id'] if run else None,
            'analysis_revision': run['revision'] if run else None,
            'hypothesis_id': run['result']['output']['leading']['id'] if run else None,
            'diagnosis': 'Собственная вымышленная запись врача.' if action in ('manual','modify') else None,
            'diagnosis_code': 'TEST' if action in ('manual','modify') else None,
            'basis': 'Синтетическое основание врача.', 'uncertainties': 'Клиническая проверка не выполнена.',
            'reviewed': True}

    def submit(self, body, uid='doc-a', client=None, **kwargs):
        client = client or self.clients[uid]
        return client.post(self.url_review, json=body,
            headers={'X-CSRF-Token': test_access.csrf(client)}, **kwargs)

    def test_accept_exact_model_provenance_and_original_remains_unreviewed(self):
        run = self.ready();body = self.request_body('accept',run)
        original = analyses._latest(self.db,run['run_id'])
        before = test_backend_contracts.table_rows(self.db)
        response = self.submit(body);self.assertEqual(200,response.status_code,response.json)
        receipt = response.json
        self.assertEqual('physician_recorded',receipt['status'])
        self.assertEqual('physician_acceptance',receipt['diagnosis']['origin'])
        self.assertEqual(original['result']['output']['leading'],receipt['model_suggestion'])
        self.assertEqual(original['diagnosis_context'],receipt['model_context'])
        self.assertEqual(run['sources'],receipt['sources'])
        self.assertEqual('doc-a',receipt['actor_id']);self.assertEqual(body['basis'],receipt['basis'])
        self.assertEqual(original,analyses._latest(self.db,run['run_id']))
        after = test_backend_contracts.table_rows(self.db)
        for table in before:
            if table not in ('backend_diagnosis_reviews','audit_entries','sessions'):
                self.assertEqual(before[table],after[table],table)
        self.assertFalse(receipt['clinical_ready']);self.assertFalse(receipt['treatment_applied'])
        state = review.view(self.db,self.user,'D01')
        self.assertTrue(state['current']['fresh']);self.assertEqual(receipt['diagnosis'],state['current']['diagnosis'])
        self.assertEqual('stale',analyses.read(self.db,self.user,'D01',run['run_id'])['status'])

    def test_manual_modify_reject_separate_origins_and_full_version_chain(self):
        manual = review.record(self.db,self.user,'D01',self.request_body())
        self.assertEqual('manual',manual['origin']);self.assertIsNone(manual['model_suggestion'])
        run = self.ready();changed = review.record(self.db,self.user,'D01',self.request_body('modify',run))
        self.assertEqual('physician_authored',changed['diagnosis']['origin'])
        self.assertEqual('model_review',changed['origin']);self.assertEqual(manual['id'],changed['previous_id'])
        run = self.ready();rejected = review.record(self.db,self.user,'D01',self.request_body('reject',run))
        state = review.view(self.db,self.user,'D01')
        self.assertEqual([3,2,1],[r['version'] for r in state['history']])
        self.assertEqual(changed['id'],rejected['previous_id']);self.assertIsNone(state['current']['diagnosis'])
        self.assertIsNotNone(state['history'][1]['diagnosis'])
        for row in state['history']:
            frozen = self.db.execute('SELECT payload_json FROM analysis_input_snapshots WHERE id=?',(row['snapshot_id'],)).fetchone()[0]
            self.assertEqual(row['snapshot_id'],hashlib.sha256(frozen.encode()).hexdigest())

    def test_identical_retry_after_new_data_and_later_decision_is_exact_receipt(self):
        run=self.ready();body=self.request_body('accept',run)
        receipt=review.record(self.db,self.user,'D01',body)
        self.diary(summary='Новые вымышленные сведения после решения.')
        review.record(self.db,self.user,'D01',self.request_body())
        before=test_backend_contracts.table_rows(self.db)
        self.assertEqual(receipt,review.record(self.db,self.user,'D01',body))
        self.assertEqual(before,test_backend_contracts.table_rows(self.db))
        changed=deepcopy(body);changed['basis']='Другое основание.'
        with self.assertRaises(analyses.AnalysisError) as error:review.record(self.db,self.user,'D01',changed)
        self.assertEqual('idempotency_conflict',error.exception.code)

    def test_patient_foreign_doctor_disabled_ended_and_real_case_denied(self):
        body=self.request_body()
        for uid in ('pat-a','doc-b'):
            self.assertIn(self.submit(body,uid).status_code,(403,404))
            self.assertIn(self.clients[uid].get(self.url_review).status_code,(403,404))
        for variant in ('disabled','role','ended','real'):
            with self.subTest(variant=variant):
                self.db.execute('BEGIN')
                try:
                    if variant=='disabled':self.db.execute("UPDATE users SET disabled=1 WHERE id='doc-a'")
                    if variant=='role':self.db.execute("UPDATE users SET role='patient' WHERE id='doc-a'")
                    if variant=='ended':self.db.execute("UPDATE care_relationships SET ends_at='2026-01-01' WHERE doctor_id='doc-a'")
                    if variant=='real':
                        with self.assertRaises(sqlite3.IntegrityError):self.db.execute("UPDATE patients SET synthetic=0 WHERE id='D01'")
                        continue
                    with self.assertRaises(analyses.AnalysisError):review.record(self.db,self.user,'D01',body)
                finally:self.db.rollback()
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM backend_diagnosis_reviews').fetchone()[0])

    def test_stale_hypothesis_snapshot_revision_missing_and_wrong_operation(self):
        run=self.ready();valid=self.request_body('accept',run)
        for field,value in [('snapshot_id','0'*64),('analysis_revision',1),('run_id','absent'),('hypothesis_id','absent')]:
            body=deepcopy(valid);body[field]=value
            self.assertIn(self.submit(body).status_code,(404,409))
        self.diary(summary='Изменённые сведения делают прежнюю гипотезу устаревшей.')
        self.assertEqual(409,self.submit(valid).status_code)
        valid['snapshot_id']=review.view(self.db,self.user,'D01')['snapshot_id']
        self.assertEqual(409,self.submit(valid).status_code)
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM backend_diagnosis_reviews').fetchone()[0])

    def test_two_real_connections_same_version_only_one_current_and_retry(self):
        body=self.request_body();barrier=Barrier(2)
        def send(index,identical=False):
            db=connect(self.path)
            try:
                payload=deepcopy(body)
                if not identical:payload['request_key']=secrets.token_hex(16);payload['basis']+=str(index)
                barrier.wait()
                try:return ('ok',review.record(db,self.user,'D01',payload))
                except analyses.AnalysisError as exc:return ('error',exc.code)
            finally:db.close()
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(send,range(2)))
        self.assertEqual(['error','ok'],sorted(r[0] for r in results))
        self.assertEqual('revision_conflict',next(r[1] for r in results if r[0]=='error'))
        self.assertEqual(1,review.view(self.db,self.user,'D01')['head_version'])
        body=self.request_body();barrier=Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda i:send(i,True),range(2)))
        self.assertEqual(['ok','ok'],[r[0] for r in results]);self.assertEqual(results[0][1],results[1][1])
        self.assertEqual(2,review.view(self.db,self.user,'D01')['head_version'])

    def test_immutable_sql_author_sequence_and_foreign_keys(self):
        receipt=review.record(self.db,self.user,'D01',self.request_body())
        for statement in ('UPDATE backend_diagnosis_reviews SET version=99','DELETE FROM backend_diagnosis_reviews'):
            with self.assertRaises(sqlite3.IntegrityError):self.db.execute(statement)
        row=dict(self.db.execute('SELECT * FROM backend_diagnosis_reviews').fetchone())
        for variant in ('sequence','author','parent','snapshot'):
            bad=dict(row);bad['id']=secrets.token_hex(16);bad['request_key']=secrets.token_hex(16)
            bad.update(version=2,previous_id=receipt['id'])
            if variant=='sequence':bad['version']=3
            if variant=='author':bad['actor_id']='pat-a'
            if variant=='parent':bad['previous_id']=None
            if variant=='snapshot':bad['snapshot_id']='absent'
            forged=json.loads(bad['receipt_json'])
            for field in ('id','version','actor_id','previous_id','snapshot_id'):
                forged[field]=bad[field]
            bad['receipt_json']=json.dumps(forged)
            message={'sequence':'version conflict','author':'current synthetic physician',
                     'parent':'parent conflict','snapshot':'FOREIGN KEY'}[variant]
            with self.assertRaisesRegex(sqlite3.IntegrityError,message):
                self.db.execute('INSERT INTO backend_diagnosis_reviews ('+','.join(bad)+') VALUES('+','.join('?' for _ in bad)+')',list(bad.values()))
        self.assertEqual([],self.db.execute('PRAGMA foreign_key_check').fetchall())

    def test_data_and_diagnosis_invalidate_existing_manual_plan_without_applying(self):
        form={'kind':'plan_change','content':'Вымышленный проект.','basis':'Вымышленное основание.',
              'uncertainties':'Не проверено.','request_key':secrets.token_hex(16)}
        pid=decisions.draft(self.db,self.user,'D01',form)
        proposal=self.db.execute('SELECT version FROM proposals WHERE id=?',(pid,)).fetchone()
        receipt=review.record(self.db,self.user,'D01',self.request_body())
        items=decisions.history(self.db,self.user,'D01')
        self.assertIn(pid,decisions.stale_ids(self.db,self.user,'D01',items))
        with self.assertRaises(decisions.DecisionError):
            decisions.confirm(self.db,self.user,'D01',pid,{'decision':'approved','rationale':'Проверено.','reviewed':'yes','version':str(proposal[0])})
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])
        self.diary(summary='Следующие вымышленные существенные сведения.')
        state=review.view(self.db,self.user,'D01');self.assertFalse(state['current']['fresh'])
        self.assertIsNone(state['current']['diagnosis']);self.assertEqual(receipt,state['history'][0])

    def test_backend_plan_snapshot_also_invalidated_by_diagnosis(self):
        plan=analyses.create(self.db,self.user,'D01',self.body('plan'))
        review.record(self.db,self.user,'D01',self.request_body())
        self.assertEqual('stale',analyses.read(self.db,self.user,'D01',plan['run_id'])['status'])
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])

    def test_source_unavailable_keeps_history_but_cannot_authorize_new_review(self):
        receipt=review.record(self.db,self.user,'D01',self.request_body())
        body=self.request_body()
        with patch.object(analyses,'capture',side_effect=analyses.AnalysisError('Нет источника.',409,'source_unavailable')):
            state=review.view(self.db,self.user,'D01')
            self.assertEqual(receipt,state['history'][0]);self.assertIsNone(state['snapshot_id'])
            self.assertFalse(state['current']['fresh']);self.assertIsNone(state['current']['diagnosis'])
            self.assertEqual('source_unavailable',state['freshness_error'])
            with self.assertRaises(analyses.AnalysisError):review.record(self.db,self.user,'D01',body)
        self.assertEqual(1,review.view(self.db,self.user,'D01')['head_version'])

    def test_audit_failure_rolls_back_entire_manual_review_and_input(self):
        body=self.request_body();before=test_backend_contracts.table_rows(self.db)
        with patch.object(access,'audit',side_effect=sqlite3.IntegrityError('synthetic audit failure')):
            with self.assertRaises(sqlite3.IntegrityError):review.record(self.db,self.user,'D01',body)
        self.assertEqual(before,test_backend_contracts.table_rows(self.db))

    def test_age_unknown_or_child_requires_scope_resolution(self):
        for age,status in ((12,'known'),(None,'unknown')):
            self.db.execute("UPDATE patients SET age_years=?,age_status=? WHERE id='D01'",(age,status))
            body=self.request_body()
            with self.assertRaises(analyses.AnalysisError) as error:review.record(self.db,self.user,'D01',body)
            self.assertEqual('scope_unavailable',error.exception.code)

    def test_wrong_operation_and_not_ready_are_not_reviewable(self):
        for operation in ('risk','diagnosis','plan'):
            run=analyses.create(self.db,self.user,'D01',self.body(operation))
            body=self.request_body('accept')
            body.update(run_id=run['run_id'],analysis_revision=run['revision'],hypothesis_id='absent')
            with self.assertRaises(analyses.AnalysisError) as error:review.record(self.db,self.user,'D01',body)
            self.assertEqual('hypothesis_unavailable',error.exception.code)

    def test_restart_preserves_receipt_csrf_json_and_read_only_get(self):
        body=self.request_body();client=self.clients['doc-a']
        self.assertEqual(403,client.post(self.url_review,json=body).status_code)
        for bad in ([],{},dict(body,extra=True),dict(body,expected_version=True),dict(body,reviewed=False),
                    dict(body,basis=' '),dict(body,action='accept'),dict(body,action='manual',run_id='run')):
            self.assertEqual(400,self.submit(bad).status_code,str(bad))
        response=self.submit(body);self.assertEqual(200,response.status_code,response.json)
        restart=create_app(self.path).test_client()
        restart.set_cookie(access.COOKIE,client.get_cookie(access.COOKIE).value)
        self.assertEqual(response.json,self.submit(body,client=restart).json)
        before=test_backend_contracts.table_rows(self.db)
        for method in (restart.get,restart.head):
            reply=method(self.url_review);self.assertEqual(200,reply.status_code)
            self.assertEqual('no-store',reply.headers['Cache-Control'])
        after=test_backend_contracts.table_rows(self.db)
        for table in before:
            if table!='sessions':self.assertEqual(before[table],after[table],table)
        for query in ('?page=0','?page=2','?page=1&page=1','?extra=1'):
            self.assertEqual(400,restart.get(self.url_review+query).status_code)
        duplicate='{"request_key":"a","request_key":"b"}'
        self.assertEqual(400,client.post(self.url_review,data=duplicate,content_type='application/json',headers={'X-CSRF-Token':test_access.csrf(client)}).status_code)

if __name__=='__main__':unittest.main()
