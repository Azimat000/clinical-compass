"""S17C: diagnosis-free notes, durable versions and conservative integration."""
import json
from pathlib import Path
import re
import secrets
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from apps.compass import access, ages, assessments, decisions, first_visits, records
from apps.compass.db import connect, migrate, now, MIGRATIONS
from apps.compass.repository import seed_demo
from apps.compass.web import create_app
from test_access import setup_identities, login, csrf, PASSWORD_HASH


def fixture(db):
    seed_demo(db)
    setup_identities(db)
    db.execute("INSERT INTO users VALUES('pat-fv','patient','Синтетический первый визит',?,0)", (PASSWORD_HASH,))
    db.execute("INSERT INTO patients VALUES('FV01','pat-fv','Первое обращение',NULL,NULL,'unknown',1,?)", (now(),))
    access.accept_invite(db, 'pat-fv', access.invite(db, 'doc-a', 'FV01'))


class FirstVisitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'fv.sqlite3'
        self.db = connect(self.path)
        migrate(self.db)
        fixture(self.db)
        self.app = create_app(self.path)
        self.clients = {uid: self.app.test_client() for uid in ('doc-a','doc-b','pat-fv','pat-b')}
        for uid, client in self.clients.items():
            self.assertEqual(302, login(client, uid).status_code)
        self.doctor = {'id': 'doc-a', 'role': 'doctor'}

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def values(self, **overrides):
        return {'request_key': secrets.token_hex(16), 'base_revision': '0', 'state': 'draft',
                'observed_on': records.today().isoformat(), 'visit_kind': 'first', 'not_collected': 'yes',
                'age_source': 'patient', **overrides}

    def post(self, values, visit='new', uid='doc-a', pid='FV01'):
        client = self.clients[uid]
        return client.post(f'/patients/{pid}/first-visits/{visit}', data={'csrf': csrf(client), **values})

    def rows(self):
        return first_visits.history(self.db, self.doctor, 'FV01')

    def test_no_diagnosis_draft_retry_restart_revision_complete_without_action(self):
        preserved = {table: [tuple(r) for r in self.db.execute('SELECT * FROM '+table)] for table in
                     ('encounters','observations','clinical_entries','therapy_courses','care_actions','proposals','assessments')}
        values = self.values(complaints_status='known', complaints_text='Не хватает сил', complaints_basis='Беседа сегодня')
        response = self.post(values)
        self.assertEqual(303, response.status_code)
        self.assertEqual(303, self.post(values).status_code)
        self.assertEqual(409, self.post({**values,'complaints_text':'другой текст'}).status_code)
        self.assertEqual(1,len(self.rows()))
        first = self.rows()[0]
        fresh = create_app(self.path).test_client()
        fresh.set_cookie(access.COOKIE,self.clients['doc-a'].get_cookie(access.COOKIE).value)
        page = fresh.get(response.location).get_data(as_text=True)
        self.assertIn('Не хватает сил',page)
        self.assertIn('Черновик',page)
        self.assertIn('<span class="num">1</span>',page)
        v2 = {**values,'base_revision':'1','request_key':secrets.token_hex(16),'state':'completed',
              'complaints_text':'Сведения уточнены','action_draft':'Обсудить после уточнения'}
        self.assertEqual(303,self.post(v2,first['visit_id']).status_code)
        self.assertEqual(303,self.post(v2,first['visit_id']).status_code)
        self.assertEqual(409,self.post({**v2,'request_key':secrets.token_hex(16),'base_revision':'2'},first['visit_id']).status_code)
        self.assertEqual(2,len(self.rows()))
        self.assertEqual('Не хватает сил',self.rows()[1]['payload']['fields']['complaints']['text'])
        for table, old in preserved.items():
            self.assertEqual(old,[tuple(r) for r in self.db.execute('SELECT * FROM '+table)],table)
        self.assertEqual([],self.db.execute('PRAGMA foreign_key_check').fetchall())

    def test_sources_dates_unknown_denial_conflict_and_summary_sections(self):
        v = self.values(complaints_status='conflicting',complaints_text='Пациент отрицает; в документе жалобы',
            complaints_basis='Беседа и выписка',complaints_source='document',complaints_on='2026-10-18',
            safety_status='denied',safety_basis='Явное отрицание в беседе',
            documented_facts='Диагноз только из синтетического документа',document_basis='Врач N, 18.10.2026',
            action_draft='Уточнить сведения',state='completed')
        r=self.post(v)
        self.assertEqual(303,r.status_code)
        p=self.rows()[0]['payload']
        self.assertEqual('unknown',p['fields']['acute']['status'])
        self.assertEqual('denied',p['fields']['safety']['status'])
        self.assertEqual('2026-10-18',p['fields']['complaints']['observed_on'])
        page=self.clients['doc-a'].get(r.location).get_data(as_text=True)
        for label in ('Жалобы и сведения с источниками','Документированные врачебные факты','Что уточнить',
                      'Результат инструмента отдельно','Проект действия','Подтверждённый план','Короткая оценка пока недоступна'):
            self.assertIn(label,page)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE first_visit_versions SET state='completed'")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute('DELETE FROM first_visit_versions')

    def test_concurrent_stale_save_and_transaction_rollback(self):
        self.post(self.values())
        item=self.rows()[0]
        v=self.values(base_revision='1',complaints_status='known',complaints_text='Один',complaints_basis='Беседа')
        self.assertEqual(303,self.post(v,item['visit_id']).status_code)
        v['request_key']=secrets.token_hex(16)
        v['complaints_text']='Два'
        r=self.post(v,item['visit_id'])
        self.assertEqual(409,r.status_code)
        self.assertIn('Два',r.get_data(as_text=True))
        with patch.object(access,'audit',side_effect=RuntimeError('injected failure')):
            with self.assertRaises(RuntimeError):
                first_visits.save(self.db,self.doctor,'FV01','new',self.values())
        self.assertEqual(2,len(self.rows()))

    def test_roles_csrf_other_patient_revocation_and_xss(self):
        self.assertEqual(403,self.post(self.values(),uid='pat-fv').status_code)
        self.assertEqual(404,self.post(self.values(),uid='doc-b').status_code)
        self.assertEqual(404,self.post(self.values(),pid='D02').status_code)
        for uid in ('pat-fv','pat-b'):
            self.assertEqual(403,self.clients[uid].get('/patients/FV01/first-visits').status_code)
        self.assertEqual(302,self.app.test_client().get('/patients/FV01/first-visits').status_code)
        self.assertEqual(403,self.clients['doc-a'].post('/patients/FV01/first-visits/new',data=self.values()).status_code)
        r=self.post(self.values(action_draft='<script>alert(1)</script>'))
        page=self.clients['doc-a'].get(r.location).get_data(as_text=True)
        self.assertNotIn('<script>alert(1)',page)
        self.assertIn('&lt;script&gt;',page)
        audit=str([tuple(r) for r in self.db.execute("SELECT * FROM audit_entries WHERE event LIKE 'first_visit.%'")])
        self.assertNotIn('alert(1)',audit)
        self.db.execute("UPDATE care_relationships SET ends_at=?",(now(),))
        self.assertEqual(404,self.post(self.values()).status_code)
        self.assertEqual(404,self.clients['doc-a'].get(r.location).status_code)

    def test_validation_and_post_error_retains_values(self):
        invalid=[{'observed_on':'2099-01-01'},{'visit_kind':'diagnosis'}, {'base_revision':'bad'},
            {'request_key':'bad'}, {'not_collected':''}, {'age_status':'known','age_years':'18'},
            {'age_status':'unknown','age_years':'18'}, {'safety_status':'known'},
            {'safety_status':'denied','safety_text':'text'}, {'acute_source':'invalid'},
            {'course_on':'2099-01-01'},{'impact_status':'known','impact_text':'X'},
            {'documented_facts':'X'}, {'action_draft':'X'*4001}, {'state':'approved'}]
        for override in invalid:
            with self.subTest(override=override):
                r=self.post(self.values(**override))
                self.assertEqual(400,r.status_code)
                self.assertIn('Новая версия не сохранена',r.get_data(as_text=True))
        self.assertEqual([],self.rows())

    def test_new_age_sources_still_block_inapplicable_dass(self):
        patient=self.db.execute("SELECT * FROM patients WHERE id='FV01'").fetchone()
        before=ages.view(self.db,patient)['fingerprint']
        self.post(self.values(age_status='known',age_years='17',age_basis='Со слов пациента'))
        self.assertNotEqual(before,ages.view(self.db,patient)['fingerprint'])
        with self.assertRaises(ages.AgeError):
            ages.verify(self.db,patient,35)
        with self.assertRaises(assessments.AssessmentError):
            assessments.assign(self.db,self.doctor,'FV01',{'assignment_key':secrets.token_hex(16),
                'form_version_id':assessments.definition()['id'],'age_status':'known','age_years':'17','age_basis':'Беседа'})
        self.post(self.values(age_status='conflicting',age_detail='17 со слов, 35 в документе',age_basis='Два источника'))
        with self.assertRaises(ages.AgeError):
            ages.verify(self.db,patient,35)
        # Unknown age still cannot assign without an explicit verified adult input.
        with self.assertRaises(assessments.AssessmentError):
            assessments.assign(self.db,self.doctor,'FV01',{'assignment_key':secrets.token_hex(16),
                'form_version_id':assessments.definition()['id'],'age_status':'unknown','age_basis':'Беседа'})

    def test_new_visit_invalidates_existing_plan_confirmation(self):
        proposal=decisions.draft(self.db,self.doctor,'FV01',{'request_key':secrets.token_hex(16),'kind':'plan_change',
            'content':'Синтетический план','basis':'Ручной проект','uncertainties':'Неизвестно'})
        self.post(self.values())
        with self.assertRaises(decisions.DecisionError) as error:
            decisions.confirm(self.db,self.doctor,'FV01',proposal,{'decision':'approved','version':'1','reviewed':'yes','rationale':'Проверено'})
        self.assertEqual(409,error.exception.status)
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])

    def test_new_visit_invalidates_outstanding_dass_without_reconciliation(self):
        request_id=assessments.assign(self.db,self.doctor,'FV01',{'assignment_key':secrets.token_hex(16),
            'form_version_id':assessments.definition()['id'],'age_status':'known','age_years':'35',
            'age_basis':'Синтетический профиль'})
        self.post(self.values(age_status='conflicting',age_detail='Разные даты рождения',age_basis='Новый документ'))
        with self.assertRaises(assessments.AssessmentError):
            assessments.submit(self.db,{'id':'pat-fv','role':'patient'},request_id,
                {'form_version_id':assessments.definition()['id'],**{f'answer_{n}':'0' for n in range(1,43)}})
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM assessments').fetchone()[0])

    def test_upgrade_preserves_previous_rows_and_checksums(self):
        path=Path(self.tmp.name)/'old.sqlite3'
        old=connect(path)
        directory=Path(self.tmp.name)/'migrations';directory.mkdir()
        for source in sorted(MIGRATIONS.glob('*.sql')):
            if source.name<'013':
                (directory/source.name).write_bytes(source.read_bytes())
        migrate(old,directory)
        seed_demo(old)
        before={t:[tuple(r) for r in old.execute('SELECT * FROM '+t)] for t in
                ('patients','encounters','observations','schema_migrations')}
        migrate(old)
        for table, rows in before.items():
            after=[tuple(r) for r in old.execute('SELECT * FROM '+table)]
            self.assertEqual(rows,after[:len(rows)],table)
        self.assertEqual('ok',old.execute('PRAGMA integrity_check').fetchone()[0])
        old.close()

    def test_repeat_visit_and_exact_dass_results_remain_separate(self):
        r=self.post(self.values(visit_kind='repeat',age_status='known',age_years='35',age_basis='Беседа',
            followup_status='known',followup_text='Предыдущие жалобы сохраняются',followup_basis='Повторная беседа'))
        self.assertEqual(303,r.status_code)
        definition=assessments.definition()
        task=assessments.assign(self.db,self.doctor,'FV01',{'assignment_key':secrets.token_hex(16),
            'form_version_id':definition['id'],'age_status':'known','age_years':'35','age_basis':'Беседа'})
        assessments.submit(self.db,{'id':'pat-fv','role':'patient'},task,
            {'form_version_id':definition['id'],**{f'answer_{n}':'1' for n in range(1,43)}})
        page=self.clients['doc-a'].get(r.location).get_data(as_text=True)
        self.assertIn('Повторный приём',page)
        self.assertIn(definition['title'],page)
        self.assertIn(definition['id'],page)
        for subscale in definition['subscales'].values():
            self.assertIn(subscale['label'] + ': <b class="num">14</b>',page)
        self.assertEqual(1,len(self.rows()))
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])
