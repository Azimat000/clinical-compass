"""S40: reconciliation removed; age applicability and historical data remain protected."""
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

    def test_removed_endpoint_cannot_write_for_any_role(self):
        before = [tuple(r) for r in self.db.execute('SELECT * FROM age_reviews')]
        audit = [tuple(r) for r in self.db.execute('SELECT * FROM audit_entries')]
        form = {'birth_date': '1991-01-01', 'basis': 'No longer supported',
                'request_key': secrets.token_hex(16), 'reviewed_sources': 'yes',
                'sources_fingerprint': ages.view(self.db, self.patient())['fingerprint']}
        self.assertFalse(any('age-reviews' in str(rule) for rule in self.app.url_map.iter_rules()))
        self.assertFalse(hasattr(ages, 'reconcile'))
        for uid in self.clients:
            for method in ('get', 'post'):
                response = getattr(self.clients[uid], method)('/patients/D01/age-reviews',
                    **({'data': {'csrf': fixtures.csrf(self.clients[uid]), **form}} if method == 'post' else {}))
                self.assertEqual(404, response.status_code)
        self.assertEqual(before, [tuple(r) for r in self.db.execute('SELECT * FROM age_reviews')])
        self.assertEqual(audit, [tuple(r) for r in self.db.execute('SELECT * FROM audit_entries')])

    def test_historical_review_is_immutable_hidden_and_not_an_age_override(self):
        patient = self.patient()
        snapshot = ages.source_snapshot(self.db, patient)
        relationship = self.db.execute('SELECT id FROM care_relationships').fetchone()[0]
        self.db.execute('INSERT INTO age_reviews VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            ('historical-review', 'D01', 'doc-a', relationship, patient['created_at'], '1991-01-01',
             'Historical basis', snapshot, ages.digest(snapshot), 'historical-key', '{}'))
        before = tuple(self.db.execute('SELECT * FROM age_reviews').fetchone())
        page = self.clients['doc-a'].get('/demo/D01').text
        for retired in ('age-review', 'Сверка возраста', 'Журнал сверок', 'Historical basis'):
            self.assertNotIn(retired, page)
        self.assertEqual(before, tuple(self.db.execute('SELECT * FROM age_reviews').fetchone()))
        for sql in ("UPDATE age_reviews SET birth_date='2000-01-01'", 'DELETE FROM age_reviews'):
            with self.assertRaises(sqlite3.IntegrityError):
                self.db.execute(sql)
        self.profile(age_status='conflicting')
        with self.assertRaises(ages.AgeError):
            ages.verify(self.db, self.patient(), 35)

    def test_source_changes_and_underage_still_block_existing_offer(self):
        task = self.offer()
        self.record(age_years='16', birth_date='2010-01-01', observed_on='2026-01-01')
        self.assertEqual(409, self.post('pat-a', '/assessments/' + task, self.answers()).status_code)
        self.assertEqual(409, self.post('doc-a', '/patients/D01/assessment-requests', self.assignment()).status_code)
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM assessments').fetchone()[0])

    def test_even_compatible_new_age_information_requires_new_offer(self):
        task=self.offer()
        self.record()  # Even compatible new information requires a fresh offer.
        self.assertEqual(409,self.post('pat-a','/assessments/'+task,self.answers()).status_code)
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM assessments').fetchone()[0])
        self.offer()

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
