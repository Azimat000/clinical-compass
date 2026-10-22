"""Regression cases for audit B13/B14; HTTP authorization and immutable provenance."""
from datetime import date
import json
from pathlib import Path
import secrets
import sqlite3
import unittest
from unittest.mock import patch

from apps.compass import access, ages, records, decisions
from apps.compass.db import connect, migrate, MIGRATIONS
from apps.compass.repository import seed_demo
from apps.compass.web import create_app
import test_assessments as fixtures


class AgeTests(unittest.TestCase):
    setUp = fixtures.AssessmentsTests.setUp
    tearDown = fixtures.AssessmentsTests.tearDown
    assignment = fixtures.AssessmentsTests.assignment
    post = fixtures.AssessmentsTests.post
    offer = fixtures.AssessmentsTests.offer
    answers = fixtures.AssessmentsTests.answers

    def profile(self, **updates):
        assert set(updates) <= {'age_status', 'age_years', 'birth_date', 'created_at'}
        columns = ','.join(key+'=?' for key in updates)
        self.db.execute(f'UPDATE patients SET {columns} WHERE id=?', (*updates.values(), 'D01'))

    def patient(self):
        return self.db.execute("SELECT * FROM patients WHERE id='D01'").fetchone()

    def review(self, **updates):
        return {'birth_date': '1991-01-01', 'basis': 'Сверены вымышленные даты: ошибку исходного профиля уточнили.',
                'request_key': secrets.token_hex(16), 'reviewed_sources': 'yes',
                'sources_fingerprint': ages.view(self.db, self.patient())['fingerprint'], **updates}

    def record(self, uid='pat-a', **updates):
        kind = 'self_report' if uid == 'pat-a' else 'visit'
        return records.save(self.db, {'id':uid, 'role':'patient' if kind=='self_report' else 'doctor'}, 'D01', kind,
                            {'request_key':secrets.token_hex(16), 'observed_on': records.today().isoformat(),
                             'age_status':'known', 'age_years':'35', **updates})

    def test_original_birthdate_probe_and_all_historical_sources(self):
        with patch.object(records, 'today', return_value=date(2026,10,19)):
            self.profile(age_status='known',age_years=35,birth_date='2010-01-01',created_at='2026-10-19T00:00:00+00:00')
            for age in ('16','18','35'):
                self.assertIn(self.post('doc-a','/patients/D01/assessment-requests',self.assignment(age_years=age)).status_code,(400,409))
            self.profile(age_status='unknown',age_years=None,birth_date=None)
            self.record(observed_on='2026-01-01',birth_date='2010-01-01',age_years='16')
            self.record(uid='doc-a')
            self.assertEqual(409,self.post('doc-a','/patients/D01/assessment-requests',self.assignment()).status_code)

    def test_eighteenth_birthday_and_one_day_before(self):
        self.profile(age_status='known',age_years=None,birth_date='2008-10-19',created_at='2026-10-18T00:00:00+00:00')
        with patch.object(records,'today',return_value=date(2026,10,18)):
            self.assertEqual(409,self.post('doc-a','/patients/D01/assessment-requests',self.assignment(age_years='18')).status_code)
        with patch.object(records,'today',return_value=date(2026,10,19)):
            self.assertEqual(303,self.post('doc-a','/patients/D01/assessment-requests',self.assignment(age_years='18')).status_code)
        # Feb 29 follows the same calendar comparison on both input and derived ages.
        self.assertEqual(17,ages.years_on(date(2008,2,29),date(2026,2,28)))
        self.assertEqual(18,ages.years_on(date(2008,2,29),date(2026,3,1)))

    def test_integer_age_observation_date_range(self):
        source={'observed_on':'2025-10-19','age':{'status':'known','years':17,'birth_date':None}}
        self.assertEqual({18},ages.possible_years(source,date(2026,10,19)))
        self.assertEqual({17,18},ages.possible_years(source,date(2026,10,18)))
        self.assertEqual({18,19},ages.possible_years(source,date(2026,10,20)))
        for age in ({'status':'known','years':None,'birth_date':None},
                    {'status':'known','years':35,'birth_date':'broken'},
                    {'status':'unknown','years':None,'birth_date':'2099-01-01'}):
            with self.assertRaises(ages.AgeError): ages.possible_years({**source,'age':age},date(2026,10,19))

    def test_explicit_doctor_resolution_preserves_original_conflict_and_history(self):
        self.profile(age_status='conflicting')
        self.record(age_status='conflicting',age_years='',age_detail='Не совпали даты.')
        self.record(uid='doc-a')
        self.assertEqual(409,self.post('doc-a','/patients/D01/assessment-requests',self.assignment()).status_code)
        before=ages.source_snapshot(self.db,self.patient())
        review=self.review()
        self.assertEqual(303,self.post('doc-a','/patients/D01/age-reviews',review).status_code)
        self.assertEqual('conflicting',self.patient()['age_status'])
        self.assertEqual(before,ages.source_snapshot(self.db,self.patient()))
        row=ages.history(self.db,'D01')[0]
        self.assertEqual(before,row['sources_json']);self.assertEqual('doc-a',row['actor_id'])
        self.assertEqual(303,self.post('doc-a','/patients/D01/assessment-requests',self.assignment()).status_code)
        task=self.db.execute('SELECT id FROM assessment_requests').fetchone()[0]
        self.assertEqual(303,self.post('pat-a','/assessments/'+task,self.answers()).status_code)
        fresh=create_app(self.path).test_client()
        fresh.set_cookie(access.COOKIE,self.clients['doc-a'].get_cookie(access.COOKIE).value)
        html=fresh.get('/demo/D01').get_data(as_text=True)
        self.assertIn(row['id'],html);self.assertIn(review['basis'],html);self.assertIn('Журнал сверок',html)
        for sql in ("UPDATE age_reviews SET birth_date='2000-01-01'",'DELETE FROM age_reviews'):
            with self.assertRaises(sqlite3.IntegrityError):self.db.execute(sql)

    def test_patient_cannot_clear_conflict_and_access_csrf(self):
        self.profile(age_status='conflicting')
        self.record();self.record(uid='doc-a')
        data=self.review()
        for uid,pid,code in [('pat-a','D01',403),('doc-b','D01',404),('doc-a','D02',404),('pat-b','D01',403)]:
            self.assertEqual(code,self.post(uid,f'/patients/{pid}/age-reviews',data).status_code)
        self.assertEqual(403,self.clients['doc-a'].post('/patients/D01/age-reviews',data=data).status_code)
        self.assertEqual(409,self.post('doc-a','/patients/D01/assessment-requests',self.assignment()).status_code)
        self.assertEqual([],ages.history(self.db,'D01'))
        self.db.execute("UPDATE care_relationships SET ends_at='2000-01-01'")
        with self.assertRaises(ages.AgeError):ages.reconcile(self.db,{'id':'doc-a','role':'doctor'},'D01',data)

    def test_invalid_review_and_stale_source_snapshot(self):
        data=self.review()
        for updates in ({'basis':''},{'reviewed_sources':''},{'birth_date':''},{'birth_date':'2099-01-01'}, {'request_key':'x'*32}):
            self.assertEqual(400,self.post('doc-a','/patients/D01/age-reviews',{**data,**updates}).status_code)
        self.record()
        self.assertEqual(409,self.post('doc-a','/patients/D01/age-reviews',data).status_code)
        self.assertEqual([],ages.history(self.db,'D01'))

    def test_new_patient_information_cannot_reuse_resolution_or_old_offer(self):
        self.profile(age_status='conflicting')
        self.assertEqual(303,self.post('doc-a','/patients/D01/age-reviews',self.review()).status_code)
        task=self.offer()
        self.record(age_years='16',birth_date='2010-01-01')
        self.record(uid='doc-a')
        self.assertIsNone(ages.view(self.db,self.patient())['current'])
        self.assertEqual(409,self.post('pat-a','/assessments/'+task,self.answers()).status_code)
        self.assertEqual(409,self.post('doc-a','/patients/D01/assessment-requests',self.assignment()).status_code)
        self.assertEqual(303,self.post('doc-a','/patients/D01/age-reviews',self.review()).status_code)
        self.assertEqual(409,self.post('pat-a','/assessments/'+task,self.answers()).status_code)
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM assessments').fetchone()[0])
        self.offer()

    def test_underage_review_never_grants_adulthood_and_source_changes_rechecked(self):
        self.profile(age_status='conflicting')
        self.assertEqual(303,self.post('doc-a','/patients/D01/age-reviews',self.review(birth_date='2010-01-01')).status_code)
        self.assertEqual(409,self.post('doc-a','/patients/D01/assessment-requests',self.assignment()).status_code)
        self.assertEqual(303,self.post('doc-a','/patients/D01/age-reviews',self.review()).status_code)
        task=self.offer()
        self.profile(birth_date='2010-01-01')
        self.assertEqual(409,self.post('pat-a','/assessments/'+task,self.answers()).status_code)

    def test_retries_atomic_failure_escaping_and_decision_snapshot(self):
        relationship=self.db.execute('SELECT id FROM care_relationships').fetchone()[0]
        before=decisions.snapshot(self.db,'D01',relationship)
        data=self.review(basis='<script>test</script>')
        with patch.object(access,'audit',side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError):ages.reconcile(self.db,{'id':'doc-a','role':'doctor'},'D01',data)
        self.assertEqual([],ages.history(self.db,'D01'))
        for _ in range(2):self.assertEqual(303,self.post('doc-a','/patients/D01/age-reviews',data).status_code)
        self.assertEqual(1,len(ages.history(self.db,'D01')))
        self.assertEqual(409,self.post('doc-a','/patients/D01/age-reviews',{**data,'basis':'other'}).status_code)
        html=self.clients['doc-a'].get('/demo/D01').get_data(as_text=True)
        self.assertIn('&lt;script&gt;test',html);self.assertNotIn('<script>test',html)
        self.assertNotEqual(before,decisions.snapshot(self.db,'D01',relationship))

    def test_even_compatible_new_age_information_requires_new_offer(self):
        task=self.offer()
        self.record()  # Even compatible new information requires a fresh offer.
        self.assertEqual(409,self.post('pat-a','/assessments/'+task,self.answers()).status_code)
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM assessments').fetchone()[0])
        self.offer()

    def test_age_review_blocks_previously_prepared_decision(self):
        actor={'id':'doc-a','role':'doctor'}
        proposal_id=decisions.draft(self.db,actor,'D01',{'request_key':secrets.token_hex(16),
            'kind':'plan_change','content':'Синтетический план','basis':'Вымышленный визит',
            'uncertainties':'Данные неполны'})
        version=self.db.execute('SELECT version FROM proposals WHERE id=?',(proposal_id,)).fetchone()[0]
        self.assertEqual(303,self.post('doc-a','/patients/D01/age-reviews',self.review()).status_code)
        response=self.post('doc-a',f'/patients/D01/decisions/{proposal_id}/confirm',{
            'decision':'approved','version':str(version),'rationale':'Проверено','reviewed':'yes'})
        self.assertEqual(409,response.status_code)
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])

    def test_upgrade_preserves_every_s08a_table_and_row(self):
        old=connect(Path(self.tmp.name)/'s08a.sqlite3')
        directory=Path(self.tmp.name)/'s08a-migrations';directory.mkdir()
        for p in MIGRATIONS.glob('*.sql'):
            if p.name<'006':(directory/p.name).write_bytes(p.read_bytes())
        migrate(old,directory);seed_demo(old)
        tables=[r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        before={t:[tuple(r) for r in old.execute('SELECT * FROM "'+t+'"')] for t in tables}
        migrate(old)
        for table,rows in before.items():
            after=[tuple(r) for r in old.execute('SELECT * FROM "'+table+'"')]
            self.assertEqual(rows,after[:len(rows)] if table=='schema_migrations' else after)
        self.assertEqual([],old.execute('PRAGMA foreign_key_check').fetchall())
        self.assertEqual('ok',old.execute('PRAGMA integrity_check').fetchone()[0]);old.close()
