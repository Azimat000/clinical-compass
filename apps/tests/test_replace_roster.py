"""Replacement must separate identities, preserve sources and retain honest provenance."""
from contextlib import closing
from datetime import date, timedelta
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from apps.compass import access, records
from apps.compass.db import connect, migrate
from apps.compass.repository import seed_demo
from apps.compass.web import create_app
from tools import replace_roster as roster
from werkzeug.security import generate_password_hash


class VisibleText(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.parts = []
        self.feed(html)

    def handle_data(self, data):
        self.parts.append(data)


class ReplaceRosterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.source = Path(cls.tmp.name) / 'old.sqlite3'
        cls.target = Path(cls.tmp.name) / 'new.sqlite3'
        cls.credentials = Path(cls.tmp.name) / 'accounts.json'
        with closing(connect(cls.source)) as db:
            migrate(db)
            seed_demo(db)
            create_app(cls.source)
            hashed = generate_password_hash('old-test-password', method='scrypt:32768:8:1')
            for uid, role in [('old-doctor', 'doctor'), ('old-patient', 'patient')]:
                db.execute('INSERT INTO users VALUES(?,?,?,?,0)', (uid, role, uid, hashed))
            db.execute("UPDATE patients SET user_id='old-patient' WHERE id='D01'")
            access.accept_invite(db, 'old-patient', access.invite(db, 'old-doctor', 'D01'))
            records.save(db, {'id': 'old-patient', 'role': 'patient'}, 'D01', 'self_report', {
                'observed_on': records.today().isoformat(), 'request_key': 'a' * 32,
                'summary': 'OLD CONTENT MUST NOT APPEAR IN THE NEW DATABASE',
            })
            access.authenticate(db, 'old-doctor', 'old-test-password', '127.0.0.1')
            cls.sources_before = {t: [tuple(r) for r in db.execute('SELECT * FROM ' + t)] for t in roster.SOURCE_TABLES}
        cls.before = hashlib.sha256(cls.source.read_bytes()).hexdigest()
        cls.report = roster.build(cls.source, cls.target, cls.credentials)
        cls.accounts = {a['login']: a for a in json.loads(cls.credentials.read_text())['accounts']}
        cls.dataset = roster.load_dataset()
        cls.app = create_app(cls.target)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def login(self, uid):
        client = self.app.test_client()
        token = re.search(r'name="csrf" value="([^"]+)"', client.get('/login').text).group(1)
        result = client.post('/login', data={'csrf': token, 'login': uid, 'password': self.accounts[uid]['password']})
        self.assertEqual(302, result.status_code)
        return client

    def test_source_preserved_new_roster_and_indexes_contain_no_old_people(self):
        self.assertEqual(self.before, hashlib.sha256(self.source.read_bytes()).hexdigest())
        self.assertEqual(0o600, self.credentials.stat().st_mode & 0o777)
        self.assertEqual(11, len({a['password'] for a in self.accounts.values()}))
        with closing(connect(self.target)) as db:
            self.assertEqual(3, db.execute("SELECT count(*) FROM users WHERE role='doctor'").fetchone()[0])
            self.assertEqual(8, db.execute('SELECT count(*) FROM patients').fetchone()[0])
            self.assertEqual({p['login'] for p in self.dataset['patients']} | {d['id'] for d in self.dataset['doctors']},
                             {r[0] for r in db.execute('SELECT id FROM users')})
            for table, before in self.sources_before.items():
                self.assertEqual(before, [tuple(r) for r in db.execute('SELECT * FROM ' + table)], table)
            # Full logical dump includes FTS backing tables and audit/event payloads.
            dump = '\n'.join(db.iterdump())
            for old in ('old-doctor', 'old-patient', 'OLD CONTENT MUST NOT APPEAR', "'D01'", "'D06'"):
                self.assertNotIn(old, dump)
            self.assertEqual('ok', db.execute('PRAGMA integrity_check').fetchone()[0])
            self.assertEqual([], db.execute('PRAGMA foreign_key_check').fetchall())
            self.assertEqual(0, db.execute("SELECT count(*) FROM catalog_versions WHERE status='reviewed'").fetchone()[0])
            self.assertEqual(0, db.execute('SELECT count(*) FROM therapy_courses').fetchone()[0])
            self.assertEqual(0, db.execute('SELECT count(*) FROM clinical_rule_evaluations').fetchone()[0])

    def test_individual_histories_dates_plans_results_and_provenance(self):
        with closing(connect(self.target)) as db:
            provenance = json.loads(db.execute("SELECT metadata_json FROM audit_entries WHERE event='fictional.roster_loaded'").fetchone()[0])
            self.assertTrue(provenance['synthetic'])
            self.assertTrue(provenance['simulated_dates'])
            self.assertFalse(provenance['clinical_review'])
            self.assertFalse(provenance['real_user_trial'])
            start = date.fromisoformat(provenance['observation_start'])
            days = [(start + timedelta(days=n)).isoformat() for n in (0, 7, 14, 21, 28, 35, 41)]
            sums = []
            for p in self.dataset['patients']:
                pid = p['id']
                self.assertEqual(p['doctor'], db.execute('SELECT doctor_id FROM care_relationships WHERE patient_id=?', (pid,)).fetchone()[0])
                reports = db.execute("SELECT observed_on,payload_json FROM clinical_entries WHERE patient_id=? AND kind='self_report' ORDER BY observed_on", (pid,)).fetchall()
                self.assertEqual(days, [r[0] for r in reports])
                self.assertEqual(p['diary'], [json.loads(r[1])['summary'] for r in reports])
                self.assertEqual(p['wellbeing'], [json.loads(r[1])['wellbeing'] for r in reports])
                self.assertEqual(3, db.execute('SELECT count(*) FROM first_visit_versions WHERE patient_id=?', (pid,)).fetchone()[0])
                self.assertEqual(3, db.execute("SELECT count(*) FROM clinical_entries WHERE patient_id=? AND kind='visit'", (pid,)).fetchone()[0])
                self.assertEqual(3, db.execute('SELECT count(*) FROM assessments WHERE patient_id=?', (pid,)).fetchone()[0])
                self.assertEqual(4, db.execute('SELECT count(*) FROM assessment_requests WHERE patient_id=?', (pid,)).fetchone()[0])
                plans = db.execute('''SELECT p.payload_json FROM proposals p JOIN doctor_confirmations c ON c.proposal_id=p.id
                    JOIN care_actions a ON a.confirmation_id=c.id WHERE p.patient_id=? ORDER BY p.version''', (pid,)).fetchall()
                self.assertEqual(p['plans'], [json.loads(r[0])['content'] for r in plans])
                self.assertEqual(7, db.execute('SELECT count(*) FROM adherence_tasks WHERE patient_id=?', (pid,)).fetchone()[0])
                outcomes = db.execute('''SELECT e.outcome FROM adherence_entries e JOIN adherence_tasks t ON t.id=e.task_id
                    WHERE t.patient_id=? ORDER BY e.recorded_at''', (pid,)).fetchall()
                self.assertEqual(p['outcomes'], [r[0] for r in outcomes])
                self.assertEqual(0, db.execute('''SELECT count(*) FROM adherence_entries e JOIN adherence_tasks t ON t.id=e.task_id
                    WHERE t.patient_id=? AND e.recorded_at<t.due_at''', (pid,)).fetchone()[0])
                messages = db.execute('''SELECT m.body FROM messages m JOIN conversations c ON c.id=m.conversation_id
                    JOIN care_relationships r ON r.id=c.relationship_id WHERE r.patient_id=? ORDER BY m.sent_at''', (pid,)).fetchall()
                self.assertEqual([text for pair in zip(p['diary'], p['replies']) for text in pair], [r[0] for r in messages])
                sums.append(tuple(r[0] for r in db.execute('SELECT answers_json FROM assessments WHERE patient_id=? ORDER BY completed_at', (pid,))))
            self.assertEqual(8, len(set(sums)))
            self.assertEqual(1, db.execute("SELECT count(*) FROM assessments WHERE completeness='incomplete'").fetchone()[0])
            self.assertEqual(0, db.execute("SELECT count(*) FROM assessments WHERE completeness<>'complete' AND score IS NOT NULL").fetchone()[0])

    def test_diary_tasks_do_not_claim_absence_of_existing_reports(self):
        with closing(connect(self.target)) as db:
            for p in self.dataset['patients']:
                history = db.execute('''SELECT e.outcome,e.reason FROM adherence_entries e
                    JOIN adherence_tasks t ON t.id=e.task_id WHERE t.patient_id=? ORDER BY t.due_at''', (p['id'],)).fetchall()
                self.assertEqual(6, len(history))
                if p['id'] != 'P108':
                    self.assertTrue(all(h['outcome'] == 'taken' for h in history), p['id'])
                else:
                    self.assertEqual(['conflicting','missed','unknown','taken','unknown','conflicting'], [h['outcome'] for h in history])
                    self.assertTrue(all('Самоотчёт отправлен' in h['reason'] for h in history if h['outcome'] != 'taken'))
                self.assertTrue(all('В этот день запись не сделана.' != h['reason'] for h in history))

    def test_visible_pages_plain_language_access_and_old_login_rejected(self):
        for d in self.dataset['doctors']:
            client = self.login(d['id'])
            dashboard = client.get('/').text
            self.assertIn(d['name'], dashboard)
            for p in self.dataset['patients']:
                if p['doctor'] != d['id']:
                    self.assertNotIn(p['name'], dashboard)
                    self.assertEqual(404, client.get('/demo/' + p['id']).status_code)
                    continue
                self.assertIn(p['name'], dashboard)
                for route in ('/demo/{id}', '/patients/{id}/follow-up', '/patients/{id}/first-visits',
                              '/patients/{id}/decisions', '/patients/{id}/communication'):
                    response = client.get(route.format(id=p['id']))
                    self.assertEqual(200, response.status_code, route)
                    text = ' '.join(VisibleText(response.text).parts)
                    self.assertNotRegex(text.lower(), r'учебн|демонстрац|\bдемо\b|demo|вымышлен|смоделир|синтетич')
                    if route == '/demo/{id}':
                        self.assertNotIn('id="encounter-', response.text)
        for p in self.dataset['patients']:
            client = self.login(p['login'])
            routes = ['/demo/' + p['id'] + suffix for suffix in ('', '/diary', '/report', '/forms')]
            routes += ['/patients/' + p['id'] + suffix for suffix in ('/decisions', '/communication')]
            with closing(connect(self.target)) as db:
                routes += ['/assessments/' + r[0] for r in db.execute('SELECT id FROM assessment_requests WHERE patient_id=?', (p['id'],))]
            for route in routes:
                response = client.get(route)
                self.assertEqual(200, response.status_code)
                self.assertNotRegex(' '.join(VisibleText(response.text).parts).lower(), r'учебн|демонстрац|\bдемо\b|demo|вымышлен|смоделир|синтетич')
                self.assertIn('compass-data-origin', response.text)
            self.assertEqual(403, client.get('/patients/' + p['id'] + '/follow-up').status_code)
            other = next(x['id'] for x in self.dataset['patients'] if x['id'] != p['id'])
            self.assertEqual(404, client.get('/demo/' + other).status_code)
        client = self.app.test_client()
        token = re.search(r'name="csrf" value="([^"]+)"', client.get('/login').text).group(1)
        self.assertEqual(401, client.post('/login', data={'csrf': token, 'login': 'old-doctor', 'password': 'old-test-password'}).status_code)

    def test_refuses_overwrites_and_cleans_partial_build_without_touching_source(self):
        with self.assertRaises(FileExistsError):
            roster.build(self.source, self.target, self.credentials)
        with self.assertRaises(ValueError):
            roster.build(self.source, self.source, self.credentials)
        target = self.target.with_name('partial.sqlite3')
        credentials = self.credentials.with_name('partial.json')
        with patch.object(roster, 'seed_patient', side_effect=RuntimeError('interrupted')):
            with self.assertRaisesRegex(RuntimeError, 'interrupted'):
                roster.build(self.source, target, credentials)
        self.assertFalse(target.exists())
        self.assertFalse(credentials.exists())
        self.assertEqual(self.before, hashlib.sha256(self.source.read_bytes()).hexdigest())
