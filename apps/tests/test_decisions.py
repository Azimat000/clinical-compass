import json
import secrets
import sqlite3
from unittest.mock import patch
import unittest
import test_access
from concurrent.futures import ThreadPoolExecutor
from apps.compass.db import connect
from apps.compass import decisions, records, access
from apps.compass.web import create_app


class DecisionTests(unittest.TestCase):
    tearDown = test_access.AccessTests.tearDown
    post = test_access.AccessTests.post
    offer = test_access.AccessTests.offer
    link = test_access.AccessTests.link
    def setUp(self):
        test_access.AccessTests.setUp(self)
        self.link()

    def values(self, **kw):
        return {'request_key': secrets.token_hex(16), 'kind': 'therapy_start',
                'content': 'Синтетическое решение, не для лечения', 'basis': 'Вымышленный визит',
                'uncertainties': 'Почечная функция неизвестна; требует проверки',
                'routing_reference': 'routing-reference-v1', 'route_specialty': 'Терапевт',
                'route_category': 'mandatory', 'route_urgency': 'urgent',
                'route_population_status': 'known', 'route_age_years': '35',
                'route_severity': 'Синтетическая оценка врача', 'route_population': 'Требует оценки врача',
                'route_evidence': 'Синтетическое основание, не клиническая рекомендация',
                'route_unavailable': 'Синтетический резервный порядок',
                'therapy_reference': decisions.reference()['version'],
                'aviandr_conclusion': 'insufficient_data', 'aviandr_basis': 'Синтетика: нет данных для выбора',
                **{'note_'+a['id']: 'Синтетические сведения отсутствуют' for a in decisions.reference()['review_areas']}, **kw}

    def draft(self, **kw):
        response = self.post('doc-a','/patients/D01/decisions',self.values(**kw))
        self.assertEqual(303, response.status_code, response.get_data(as_text=True))
        return self.db.execute('SELECT * FROM proposals ORDER BY version DESC LIMIT 1').fetchone()

    def confirm(self, p, decision='approved', **kw):
        return self.post('doc-a',f'/patients/D01/decisions/{p["id"]}/confirm',
                         {'decision':decision,'version':str(p['version']),'rationale':'Просмотрено для синтетического демо', 'reviewed':'yes',**kw})

    def test_five_actions_draft_separate_review_and_patient_projection(self):
        for kind in decisions.KINDS:
            p = self.draft(kind=kind)
            patient = self.clients['pat-a'].get('/api/patients/D01/decisions').json['decisions']
            self.assertEqual(p['version']-1, len(patient))
            self.assertEqual(303, self.confirm(p).status_code)
            self.assertEqual(303, self.confirm(p).status_code)
            self.assertEqual(409, self.confirm(p,rationale='changed').status_code)
        actions = self.db.execute('SELECT * FROM care_actions').fetchall()
        self.assertEqual(5,len(actions))
        self.assertEqual(5, self.db.execute('SELECT count(*) FROM doctor_confirmations').fetchone()[0])
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM therapy_courses').fetchone()[0])
        data = self.clients['pat-a'].get('/api/patients/D01/decisions').json['decisions']
        self.assertEqual(5,len(data))
        self.assertNotIn('reference',data[0]);self.assertNotIn('input_snapshot',data[0])
        self.assertEqual(4,sum(a['supersedes_id'] is not None for a in actions))
        for a in actions:
            self.assertTrue(self.db.execute("SELECT 1 FROM doctor_confirmations WHERE id=? AND decision='approved'",(a['confirmation_id'],)).fetchone())
        self.assertIn('Подтверждено врачом',self.clients['doc-a'].get('/patients/D01/decisions').get_data(as_text=True))
        # The patient's page address shows the plan screen with confirmed decisions only, never the doctor's page.
        asked = self.clients['pat-a'].get('/patients/D01/decisions')
        self.assertEqual(200, asked.status_code)
        page = asked.get_data(as_text=True)
        self.assertEqual(5, page.count('class="plan-entry'))
        self.assertNotIn('Решение врача', page)
        self.assertNotIn('Проект', page)

    def test_reject_never_applies_and_is_hidden_from_patient(self):
        p=self.draft();self.assertEqual(303,self.confirm(p,'rejected').status_code)
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])
        self.assertEqual([],self.clients['pat-a'].get('/api/patients/D01/decisions').json['decisions'])
        self.assertEqual(409,self.confirm(p).status_code)

    def test_new_report_including_backdated_unknown_blocks_old_then_new_revision_works(self):
        p=self.draft()
        records.save(self.db,{'id':'pat-a','role':'patient'},'D01','self_report',
                     {'request_key':secrets.token_hex(16),'observed_on':'2026-10-01','adverse_events_status':'known','adverse_events_text':'Вымышленное НЯ'})
        self.assertEqual(409,self.confirm(p).status_code)
        revision=self.draft(parent_id=p['id'])
        self.assertEqual(303,self.confirm(revision).status_code)
        metadata=self.db.execute('SELECT * FROM decision_drafts WHERE proposal_id=?',(revision['id'],)).fetchone()
        self.assertEqual(p['id'],metadata['parent_proposal_id'])
        snapshot=json.loads(revision['input_snapshot_json'])
        self.assertEqual('unknown',json.loads(snapshot['clinical_entries'][0]['payload_json'])['age']['status'])
        self.assertEqual(1,len(snapshot['adverse_events']))

    def test_other_plan_changes_invalidate_parallel_project(self):
        a=self.draft();b=self.draft(kind='plan_change')
        self.assertEqual(303,self.confirm(b).status_code)
        self.assertEqual(409,self.confirm(a).status_code)
        self.assertEqual(1,self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])

    def test_source_age_date_and_catalog_change_block_confirmation(self):
        for mutation in ('age','source','day','catalog','reference'):
            with self.subTest(mutation=mutation):
                p=self.draft()
                if mutation=='age': self.db.execute("UPDATE patients SET age_status='conflicting' WHERE id='D01'")
                elif mutation=='source': self.db.execute("UPDATE source_versions SET status='superseded'")
                elif mutation=='catalog': self.db.execute("UPDATE catalog_versions SET blocker='changed'")
                if mutation=='day':
                    from datetime import date, timedelta
                    snap_day=date.fromisoformat(json.loads(p['input_snapshot_json'])['day'])
                    with patch.object(records,'today',return_value=snap_day+timedelta(days=1)):
                        self.assertEqual(409,self.confirm(p).status_code)
                elif mutation=='reference':
                    ref=decisions.reference();ref['version']='new-source-version'
                    with patch.object(decisions,'reference',return_value=ref):
                        self.assertEqual(409,self.confirm(p).status_code)
                else:self.assertEqual(409,self.confirm(p).status_code)
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])

    def test_age_boundaries_unknown_and_negative_indication_never_generate_medical_proposal(self):
        for age,status in ((17,'known'),(18,'known'),(19,'known'),(None,'unknown'),(18,'conflicting')):
            self.db.execute('UPDATE patients SET age_years=?,age_status=? WHERE id=?',(age,status,'D01'))
            page=self.clients['doc-a'].get('/patients/D01/decisions')
            self.assertEqual(200,page.status_code)
            self.assertIn('Неизвестность не означает допуск',page.get_data(as_text=True))
            self.assertEqual(0,self.db.execute('SELECT count(*) FROM proposals').fetchone()[0])
        self.assertFalse(decisions.reference()['active_rules'])
        self.assertEqual(0,self.db.execute("SELECT count(*) FROM catalog_versions WHERE kind IN ('drug','rule') AND status='reviewed'").fetchone()[0])

    def test_retry_validation_wrong_version_and_required_review(self):
        form=self.values();url='/patients/D01/decisions'
        self.assertEqual(303,self.post('doc-a',url,form).status_code)
        self.assertEqual(303,self.post('doc-a',url,form).status_code)
        self.assertEqual(409,self.post('doc-a',url,{**form,'content':'changed'}).status_code)
        p=self.db.execute('SELECT * FROM proposals').fetchone()
        for kw in ({'reviewed':''},{'version':'-1'},{'decision':'bypass'},{'rationale':''},{'version':'text'}):
            self.assertIn(self.confirm(p,**kw).status_code,(400,409))
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM doctor_confirmations').fetchone()[0])
        for kw in ({'kind':'auto'},{'content':''},{'basis':''},{'uncertainties':''},{'request_key':'bad'},{'content':'x'*4001},{'content':'bad\0value'},{'parent_id':'foreign'}):
            self.assertIn(self.post('doc-a',url,self.values(**kw)).status_code,(400,404))
        self.assertEqual(1,self.db.execute('SELECT count(*) FROM proposals').fetchone()[0])

    def test_decision_auth_csrf_other_patient_and_expired_link(self):
        p=self.draft();url=f'/patients/D01/decisions/{p["id"]}/confirm'
        form={'decision':'approved','version':str(p['version']),'rationale':'test','reviewed':'yes'}
        for uid,code in (('pat-a',403),('pat-b',403),('doc-b',404)):
            self.assertEqual(code,self.post(uid,url,form).status_code)
        self.assertEqual(403,self.clients['doc-a'].post(url,data=form).status_code)
        self.assertEqual(401,self.app.test_client().get('/api/patients/D01/decisions').status_code)
        self.assertEqual(404,self.clients['doc-b'].get('/api/patients/D01/decisions').status_code)
        self.assertEqual(404,self.clients['pat-b'].get('/patients/D01/decisions').status_code)
        self.assertEqual(404,self.post('doc-a',f'/patients/D02/decisions/{p["id"]}/confirm',form).status_code)
        self.assertEqual(403,self.post('pat-a','/patients/D01/decisions',self.values()).status_code)
        self.db.execute("UPDATE care_relationships SET ends_at=?",(records.today().isoformat(),))
        self.assertEqual(404,self.confirm(p).status_code)
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])

    def test_disabled_doctor_rechecked_inside_transaction(self):
        p=self.draft();self.db.execute("UPDATE users SET disabled=1 WHERE id='doc-a'")
        with self.assertRaises(decisions.DecisionError):
            decisions.confirm(self.db,{'id':'doc-a','role':'doctor'},'D01',p['id'],
                              {'decision':'approved','version':str(p['version']),'rationale':'test','reviewed':'yes'})

    def test_rollbacks_immutability_restart_and_html_escaping(self):
        with patch.object(access,'audit',side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError):
                decisions.draft(self.db,{'id':'doc-a','role':'doctor'},'D01',self.values())
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM proposals').fetchone()[0])
        p=self.draft(content='<script>test()</script>')
        with patch.object(access,'audit',side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError):
                decisions.confirm(self.db,{'id':'doc-a','role':'doctor'},'D01',p['id'],
                                  {'decision':'approved','version':str(p['version']),'rationale':'test','reviewed':'yes'})
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM doctor_confirmations').fetchone()[0])
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])
        self.assertEqual(303,self.confirm(p).status_code)
        for sql in ("UPDATE proposals SET payload_json='{}'",'DELETE FROM proposals',"UPDATE decision_drafts SET reference_json='{}'",'DELETE FROM decision_drafts',"UPDATE care_actions SET effective_at='bad'",'DELETE FROM care_actions',"UPDATE doctor_confirmations SET rationale='bad'"):
            with self.assertRaises(sqlite3.IntegrityError):self.db.execute(sql)
        fresh=create_app(self.path).test_client()
        fresh.set_cookie(access.COOKIE,self.clients['doc-a'].get_cookie(access.COOKIE).value)
        page=fresh.get('/patients/D01/decisions').get_data(as_text=True)
        self.assertIn('&lt;script&gt;',page);self.assertNotIn('<script>test()',page)
        self.assertIn(p['id'],page)
        self.assertEqual([],self.db.execute('PRAGMA foreign_key_check').fetchall())
        self.assertEqual('ok',self.db.execute('PRAGMA integrity_check').fetchone()[0])

    def test_concurrent_approvals_cannot_overwrite_new_plan(self):
        proposals = [dict(self.draft()), dict(self.draft(kind='plan_change'))]
        def attempt(p):
            db = connect(self.path)
            try:
                decisions.confirm(db, {'id':'doc-a','role':'doctor'}, 'D01', p['id'],
                                  {'decision':'approved','version':str(p['version']),'rationale':'concurrent','reviewed':'yes'})
                return 303
            except decisions.DecisionError as error:
                return error.status
            finally:
                db.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes=list(pool.map(attempt, proposals))
        self.assertEqual([303,409],sorted(outcomes))
        self.assertEqual(1,self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])
