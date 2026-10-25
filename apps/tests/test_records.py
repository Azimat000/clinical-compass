"""S06 acceptance: two roles, provenance, unknowns, atomicity and durable history."""
import json
from pathlib import Path
import secrets
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from apps.compass import access, records
from apps.compass.db import connect, migrate
from apps.compass.repository import seed_demo
from apps.compass.web import create_app
from test_access import setup_identities, login, csrf


class RecordsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'records.sqlite3'
        self.db = connect(self.path)
        migrate(self.db)
        seed_demo(self.db)
        setup_identities(self.db)
        access.accept_invite(self.db, 'pat-a', access.invite(self.db, 'doc-a', 'D01'))
        self.app = create_app(self.path)
        self.clients = {u: self.app.test_client() for u in ('doc-a', 'doc-b', 'pat-a', 'pat-b')}
        for uid, client in self.clients.items():
            self.assertEqual(302, login(client, uid).status_code)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def values(self, **kwargs):
        return {'request_key': secrets.token_hex(16), 'observed_on': '2026-10-18',
                'summary': 'Синтетическое резюме', 'wellbeing': 'unknown', **kwargs}

    def submit(self, uid='pat-a', pid='D01', data=None, kind='self-reports'):
        c = self.clients[uid]
        return c.post(f'/patients/{pid}/{kind}', data={'csrf': csrf(c), **(data or self.values())})

    def test_pair_same_report_provenance_and_separate_adverse_event(self):
        data = self.values(complaints_status='known', complaints_text='Стало труднее спать',
                           risk_factors_status='denied', concomitant_medications_status='unknown',
                           adverse_events_status='known', adverse_events_text='Синтетическая тошнота',
                           wellbeing='worse', age_status='known', age_years='34')
        self.assertEqual(303, self.submit(data=data).status_code)
        entry = self.db.execute('SELECT * FROM clinical_entries').fetchone()
        self.assertEqual('pat-a', entry['actor_id'])
        for uid, path in (('doc-a', '/demo/D01'), ('pat-a', '/demo/D01/diary')):
            page = self.clients[uid].get(path).get_data(as_text=True)
            self.assertIn('id="entry-%s"' % entry['id'], page)
            self.assertIn('Синтетическая тошнота', page)
            api = self.clients[uid].get('/api/patients/D01/history').json
            self.assertEqual('pat-a', api['entries'][0]['actor_id'])
            self.assertNotIn('request_key', api['entries'][0])
        report = self.db.execute('SELECT * FROM self_reports').fetchone()
        self.assertEqual(entry['id'], report['id'])
        self.assertEqual(2, report['schema_version'])
        self.assertEqual('2026-10-18', report['reported_at'])
        self.assertNotEqual(report['reported_at'], report['received_at'])
        observations = self.db.execute("SELECT * FROM observations WHERE code!='synthetic_profile_snapshot'").fetchall()
        self.assertEqual(5, len(observations))
        for obs in observations:
            self.assertEqual(entry['id'], json.loads(obs['provenance_json'])['entry_id'])
            self.assertEqual('pat-a', json.loads(obs['provenance_json'])['actor_id'])
        event = self.db.execute('SELECT * FROM adverse_events').fetchone()
        self.assertEqual('unreviewed', event['review_status'])
        self.assertIsNone(event['therapy_id'])
        self.assertEqual(entry['id'], event['source_entry_id'])
        for table in ('care_actions', 'proposals', 'risk_evaluations', 'assessments', 'alerts'):
            self.assertEqual(0, self.db.execute('SELECT count(*) FROM ' + table).fetchone()[0])

    def test_unknown_denied_conflicting_and_age_mismatch(self):
        self.assertEqual(303, self.submit(data=self.values()).status_code)
        first = self.db.execute('SELECT payload_json FROM clinical_entries').fetchone()[0]
        self.assertEqual('unknown', json.loads(first)['age']['status'])
        self.assertEqual('unknown', json.loads(first)['fields']['risk_factors']['status'])
        data = self.values(age_status='known', age_years='18', birth_date='2000-01-01',
                           complaints_status='conflicting', complaints_text='Пациент отрицает, в выписке указаны жалобы',
                           adverse_events_status='denied')
        self.assertEqual(303, self.submit(data=data).status_code)
        entries = records.history(self.db, 'D01')
        self.assertEqual('conflicting', entries[0]['payload']['age']['status'])
        page = self.clients['doc-a'].get('/demo/D01').get_data(as_text=True)
        self.assertIn('Возраст не соответствует дате рождения', page)
        self.assertIn('Сверить противоречивые сведения', page)
        self.assertIn('Явно отрицает', page)
        self.assertIn('Неизвестно', page)
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM adverse_events').fetchone()[0])
        self.assertEqual(35, self.db.execute("SELECT age_years FROM patients WHERE id='D01'").fetchone()[0])

    def test_unknown_initial_age_is_never_adult(self):
        self.db.execute("UPDATE patients SET age_status='unknown',age_years=NULL WHERE id='D01'")
        self.submit(data=self.values())
        page = self.clients['pat-a'].get('/demo/D01/diary').get_data(as_text=True)
        self.assertIn('Взрослая применимость не установлена', page)
        self.assertRegex(page, r'<dt>Возраст</dt>\s*<dd><span class="state state--unknown">Неизвестно</span>')

    def test_visit_and_report_disagreements_same_day_preserved_not_merged(self):
        self.submit(data=self.values(risk_factors_status='denied', wellbeing='better'))
        self.assertEqual(303, self.submit('doc-a', kind='visits', data=self.values(
            risk_factors_status='known', risk_factors_text='Указано в синтетической выписке', wellbeing='worse')).status_code)
        entries = records.history(self.db, 'D01')
        self.assertEqual(2, len(entries))
        self.assertEqual('visit', entries[0]['kind'])
        self.assertEqual('doc-a', entries[0]['actor_id'])
        self.assertTrue(any('различаются сведения' in w for w in records.warnings(self.db.execute("SELECT * FROM patients WHERE id='D01'").fetchone(), entries)))
        self.assertEqual(2, self.db.execute("SELECT count(*) FROM encounters WHERE patient_id='D01'").fetchone()[0])
        self.assertEqual(1, self.db.execute('SELECT count(*) FROM self_reports').fetchone()[0])
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE clinical_entries SET summary='overwrite'")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute('DELETE FROM clinical_entries')

    def test_doctor_record_redirects_to_history_and_is_not_duplicated_as_archive(self):
        response = self.submit('doc-a', kind='visits', data=self.values(summary='Новая запись врача'))
        self.assertEqual(303, response.status_code)
        self.assertTrue(response.location.startswith('/demo/D01#entry-'))
        page = self.clients['doc-a'].get(response.location)
        self.assertEqual(200, page.status_code)
        entry = self.db.execute('SELECT id FROM clinical_entries').fetchone()[0]
        self.assertIn('id="entry-%s"' % entry, page.text)
        self.assertNotIn('id="encounter-%s"' % entry, page.text)

    def test_retry_idempotency_changed_body_and_distinct_observation_dates(self):
        data = self.values(wellbeing='better')
        self.assertEqual(303, self.submit(data=data).status_code)
        self.assertEqual(303, self.submit(data=data).status_code)
        self.assertEqual(409, self.submit(data={**data, 'wellbeing': 'worse'}).status_code)
        self.assertEqual(1, self.db.execute('SELECT count(*) FROM clinical_entries').fetchone()[0])
        self.submit(data=self.values(observed_on='2026-10-17', wellbeing='worse'))
        entries = records.history(self.db, 'D01')
        self.assertEqual(['2026-10-18', '2026-10-17'], [e['observed_on'] for e in entries])
        fresh = create_app(self.path).test_client()
        fresh.set_cookie(access.COOKIE, self.clients['doc-a'].get_cookie(access.COOKIE).value)
        self.assertEqual(2, len(fresh.get('/api/patients/D01/history').json['entries']))

    def test_server_validation_and_failed_form_keeps_input_without_partial_rows(self):
        invalid = [dict(observed_on='tomorrow'), dict(observed_on='2099-01-01'), dict(observed_on='1899-01-01'),
                   dict(age_status='unknown', age_years='18'), dict(age_status='known', age_years='-1'),
                   dict(age_status='known', birth_date='2026-10-19'), dict(age_status='known', age_years='121'),
                   dict(age_status='known'), dict(age_status='denied'), dict(age_status='conflicting'),
                   dict(complaints_status='known'), dict(risk_factors_status='unsafe'),
                   dict(adverse_events_status='unknown', adverse_events_text='данные'),
                   dict(adverse_events_status='denied', adverse_events_text='данные'),
                   dict(summary='x'*4001), dict(summary='bad\x00text'), dict(wellbeing='score_10'), dict(request_key='bad')]
        for values in invalid:
            with self.subTest(values=str(values)[:80]):
                response = self.submit(data=self.values(summary='Сохранённый ввод', **({k:v for k,v in values.items() if k!='summary'})) if 'summary' not in values else self.values(**values))
                self.assertEqual(400, response.status_code)
                self.assertIn('Запись не сохранена', response.get_data(as_text=True))
                self.assertEqual(0, self.db.execute('SELECT count(*) FROM clinical_entries').fetchone()[0])
                self.assertEqual(0, self.db.execute('SELECT count(*) FROM self_reports').fetchone()[0])
        page = self.submit(data=self.values(summary='Сохранённый ввод', complaints_status='known')).get_data(as_text=True)
        self.assertIn('Сохранённый ввод', page)

    def test_atomic_failure_rolls_back_report_observations_event_audit(self):
        original = access.audit
        with patch.object(access, 'audit', side_effect=RuntimeError('synthetic injected failure')):
            with self.assertRaises(RuntimeError):
                records.save(self.db, {'id': 'pat-a', 'role': 'patient'}, 'D01', 'self_report',
                             self.values(adverse_events_status='known', adverse_events_text='test'))
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM self_reports').fetchone()[0])
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM clinical_entries').fetchone()[0])
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM adverse_events').fetchone()[0])
        self.assertEqual(6, self.db.execute('SELECT count(*) FROM observations').fetchone()[0])
        self.assertIs(access.audit, original)

    def test_authorization_csrf_ended_relationship_and_xss(self):
        for uid, pid, kind, status in [('doc-a','D01','self-reports',403), ('pat-a','D01','visits',403),
                                      ('pat-a','D02','self-reports',404), ('doc-b','D01','visits',404)]:
            self.assertEqual(status, self.submit(uid,pid,self.values(),kind).status_code)
        anon = self.app.test_client()
        self.assertEqual(302, anon.post('/patients/D01/self-reports', data=self.values()).status_code)
        self.assertEqual(401, anon.get('/api/patients/D01/history').status_code)
        self.assertEqual(404, self.clients['doc-b'].get('/api/patients/D01/history').status_code)
        self.assertEqual(404, self.clients['pat-b'].get('/api/patients/D01/history').status_code)
        self.assertEqual(403, self.clients['pat-a'].post('/patients/D01/self-reports', data=self.values()).status_code)
        self.submit(data=self.values(summary='<script>alert(1)</script>', complaints_status='known', complaints_text='<img src=x onerror=alert(1)>'))
        page = self.clients['doc-a'].get('/demo/D01').get_data(as_text=True)
        self.assertNotIn('<script>alert(1)', page)
        self.assertIn('&lt;script&gt;', page)
        self.assertIn('&lt;img', page)
        audit = str([tuple(r) for r in self.db.execute("SELECT * FROM audit_entries WHERE event LIKE 'record.%'")])
        self.assertNotIn('<script>', audit)
        self.db.execute("UPDATE care_relationships SET ends_at='2026-10-18'")
        self.assertEqual(404, self.clients['doc-a'].get('/api/patients/D01/history').status_code)
        self.assertEqual(404, self.submit('doc-a',kind='visits').status_code)
        self.assertEqual(409, self.submit().status_code)
        self.assertEqual(1, self.db.execute('SELECT count(*) FROM clinical_entries').fetchone()[0])

    def test_migration_preserves_s05_and_prior_migrations_are_unchanged(self):
        oldpath = Path(self.tmp.name) / 's05.sqlite3'
        old = connect(oldpath)
        directory = Path(self.tmp.name) / 's05-migrations'
        directory.mkdir()
        from apps.compass.db import MIGRATIONS
        for name in ('001_initial.sql', '002_access.sql'):
            (directory / name).write_bytes((MIGRATIONS / name).read_bytes())
        migrate(old, directory)
        seed_demo(old)
        setup_identities(old)
        before = {t: [tuple(r) for r in old.execute('SELECT * FROM ' + t)] for t in ('patients','encounters','observations','users','outbox_events')}
        migrate(old)
        for table, rows in before.items():
            self.assertEqual(rows, [tuple(r) for r in old.execute('SELECT * FROM ' + table)])
        self.assertEqual([], old.execute('PRAGMA foreign_key_check').fetchall())
        old.close()
