"""S55: replacement, chronology, real operations, isolation and cleanup invariants."""
from contextlib import closing
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import re
import tempfile
import unittest

from werkzeug.security import generate_password_hash
from apps.compass import access, assessments, first_visits, medications, plan_tasks, records
from apps.compass.db import connect, migrate
from apps.compass.repository import seed_demo
from apps.compass.web import create_app
from tools import seed_clinic_roster as roster


class ClinicRosterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.source = Path(cls.tmp.name) / 'old.sqlite3'
        cls.target = Path(cls.tmp.name) / 'new.sqlite3'
        cls.credentials = Path(cls.tmp.name) / 'accounts.json'
        with closing(connect(cls.source)) as db:
            migrate(db)
            seed_demo(db)
            assessments.install_form(db)
            hashed = generate_password_hash('old-password')
            for uid, role in (('old-doctor', 'doctor'), ('old-patient', 'patient')):
                db.execute('INSERT INTO users VALUES(?,?,?,?,0)', (uid, role, uid, hashed))
            db.execute("UPDATE patients SET user_id='old-patient' WHERE id='D01'")
            access.accept_invite(db, 'old-patient', access.invite(db, 'old-doctor', 'D01'))
            records.save(db, dict(id='old-patient', role='patient'), 'D01', 'self_report',
                         dict(request_key=roster.key(), observed_on=records.today().isoformat(), summary='OLD PRIVATE CONTENT'))
            access.authenticate(db, 'old-doctor', 'old-password', '127.0.0.1')
            cls.sources = {t: [tuple(r) for r in db.execute('SELECT * FROM ' + t)] for t in roster.SOURCE_TABLES}
        cls.before = hashlib.sha256(cls.source.read_bytes()).hexdigest()
        cls.report = roster.build(cls.source, cls.target, cls.credentials)
        cls.data = roster.dataset()
        cls.accounts = {a['login']: a for a in json.loads(cls.credentials.read_text())['accounts']}
        cls.app = create_app(cls.target)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def login(self, uid):
        client = self.app.test_client()
        token = re.search(r'name="csrf" value="([^"]+)"', client.get('/login').text).group(1)
        response = client.post('/login', data=dict(csrf=token, login=uid, password=self.accounts[uid]['password']))
        self.assertEqual(302, response.status_code)
        return client

    def test_clean_replacement_exact_sources_and_private_access(self):
        self.assertEqual(self.before, hashlib.sha256(self.source.read_bytes()).hexdigest())
        self.assertEqual(0o600, self.target.stat().st_mode & 0o777)
        self.assertEqual(0o600, self.credentials.stat().st_mode & 0o777)
        self.assertEqual(12, len({a['password'] for a in self.accounts.values()}))
        with closing(connect(self.target)) as db:
            self.assertEqual(2, db.execute("SELECT count(*) FROM users WHERE role='doctor'").fetchone()[0])
            self.assertEqual(10, db.execute('SELECT count(*) FROM patients').fetchone()[0])
            self.assertEqual(12, db.execute('SELECT count(*) FROM users').fetchone()[0])
            self.assertEqual('ok', db.execute('PRAGMA integrity_check').fetchone()[0])
            self.assertEqual([], db.execute('PRAGMA foreign_key_check').fetchall())
            for table, rows in self.sources.items():
                self.assertEqual(rows, [tuple(r) for r in db.execute('SELECT * FROM ' + table)])
            dump = '\n'.join(db.iterdump())
            for old in ('old-doctor', 'old-patient', 'OLD PRIVATE CONTENT', "'D01'", "'D06'"):
                self.assertNotIn(old, dump)
            origin = json.loads(db.execute("SELECT metadata_json FROM audit_entries WHERE event='fictional.roster_loaded'").fetchone()[0])
            self.assertTrue(origin['synthetic'])
            self.assertTrue(origin['simulated_dates'])
            self.assertFalse(origin['clinical_review'])
            self.assertFalse(origin['real_user_trial'])
            self.assertFalse(origin['medication_eligibility_established'])

    def test_every_history_has_dates_sources_versions_and_distinct_course(self):
        start = date.fromisoformat(self.report['observation_start'])
        with closing(connect(self.target)) as db:
            for p in self.data['patients']:
                pid = p['id']
                doctor = dict(id=p['doctor'], role='doctor')
                reports = db.execute("SELECT * FROM clinical_entries WHERE patient_id=? ORDER BY observed_on", (pid,)).fetchall()
                self.assertEqual(7, len(reports))
                self.assertEqual(p['diary'], [json.loads(r['payload_json'])['summary'] for r in reports])
                self.assertEqual([(start + timedelta(days=n)).isoformat() for n in roster.OFFSETS], [r['observed_on'] for r in reports])
                self.assertTrue(all(r['actor_id'] == p['login'] and r['kind'] == 'self_report' for r in reports))
                versions = first_visits.history(db, doctor, pid)
                completed = [v for v in versions if v['state'] == 'completed']
                self.assertEqual(3, len(completed))
                self.assertEqual(list(reversed(p['visits'])), [v['payload']['fields']['conclusion']['text'] for v in completed])
                for v in completed:
                    self.assertEqual(3, v['revision'])
                    self.assertTrue(v['payload']['documented_facts'])
                    for code in first_visits.CURRENT_FIELDS + first_visits.STATIC_FIELDS:
                        self.assertTrue(v['payload']['fields'][code]['text'], (pid, code))
                    if v['payload']['visit_kind'] == 'repeat':
                        self.assertTrue(v['payload']['fields']['history']['carried_from'])
                tasks = plan_tasks.view(db, doctor, pid)['tasks']
                self.assertTrue(any(t['future'] and not t['superseded'] for t in tasks))
                self.assertTrue(any(t['superseded'] for t in tasks))
                self.assertTrue(any(t['history'] and not t['superseded'] for t in tasks))
            self.assertEqual(70, db.execute('SELECT count(*) FROM self_reports').fetchone()[0])
            self.assertEqual(140, db.execute('SELECT count(*) FROM messages').fetchone()[0])
            self.assertEqual(280, db.execute('SELECT count(*) FROM message_receipts').fetchone()[0])
            self.assertEqual(10, db.execute('SELECT count(*) FROM text_imports').fetchone()[0])
            self.assertEqual(21, db.execute('SELECT count(*) FROM extraction_reviews').fetchone()[0])
            self.assertEqual(0, db.execute('SELECT count(*) FROM clinical_entries WHERE observed_on>?', (records.today().isoformat(),)).fetchone()[0])
            self.assertEqual(0, db.execute('''SELECT count(*) FROM adherence_entries e JOIN adherence_tasks t ON t.id=e.task_id
                                             WHERE e.recorded_at<t.due_at''').fetchone()[0])

    def test_questionnaire_completeness_pending_and_patient_scores_hidden(self):
        with closing(connect(self.target)) as db:
            self.assertEqual(90, db.execute('SELECT count(*) FROM assessments').fetchone()[0])
            self.assertEqual(1, db.execute("SELECT count(*) FROM assessments WHERE completeness='incomplete'").fetchone()[0])
            self.assertEqual(0, db.execute("SELECT count(*) FROM assessments WHERE completeness<>'complete' AND score IS NOT NULL").fetchone()[0])
            self.assertEqual(30, db.execute('''SELECT count(*) FROM assessment_requests r WHERE NOT EXISTS
                (SELECT 1 FROM assessment_results a WHERE a.request_id=r.id)''').fetchone()[0])
            for p in self.data['patients']:
                user = dict(id=p['login'], role='patient')
                self.assertEqual(3, len(assessments.pending(db, user, p['id'])))
                result = assessments.history(db, user, p['id'])
                self.assertEqual(9, len(result))
                self.assertTrue(all(not ({'score', 'scores_json', 'answers_json'} & set(r)) for r in result))

    def test_medication_changes_stop_missing_partial_and_corrections(self):
        with closing(connect(self.target)) as db:
            self.assertTrue(medications.approved(db, 'P204')[0]['medications'])
            self.assertNotEqual(medications.approved(db, 'P204')[0]['medications'][0]['name'],
                                medications.approved(db, 'P204')[-1]['medications'][0]['name'])
            self.assertEqual([], medications.approved(db, 'P207')[-1]['medications'])
            for pid in ('P205', 'P206', 'P209', 'P210'):
                self.assertEqual([], medications.approved(db, pid))
            self.assertTrue(db.execute("SELECT 1 FROM medication_marks WHERE patient_id='P203' AND actual_quarters=0").fetchone())
            self.assertTrue(db.execute("SELECT 1 FROM medication_marks WHERE patient_id='P203' AND actual_quarters=2").fetchone())
            self.assertTrue(db.execute('''SELECT 1 FROM medication_marks WHERE patient_id='P203'
                GROUP BY dose_on,proposal_id HAVING count(*)=3''').fetchone())
            for pid in ('P204', 'P207'):
                self.assertTrue(db.execute('SELECT 1 FROM adverse_events WHERE patient_id=?', (pid,)).fetchone())
            self.assertEqual(1, db.execute("SELECT count(*) FROM doctor_confirmations WHERE decision='rejected'").fetchone()[0])
            self.assertEqual(2, db.execute('''SELECT count(*) FROM proposals p WHERE NOT EXISTS
                (SELECT 1 FROM doctor_confirmations c WHERE c.proposal_id=p.id)''').fetchone()[0])
            self.assertEqual(1, db.execute("SELECT count(*) FROM proposals WHERE kind='referral'").fetchone()[0])
            self.assertEqual(1, db.execute('SELECT count(*) FROM self_report_drafts WHERE active=1').fetchone()[0])
            self.assertEqual(1, db.execute("SELECT count(*) FROM first_visit_versions WHERE state='draft' AND revision=1 AND json_extract(payload_json,'$.observed_on')=?",
                                         (records.today().isoformat(),)).fetchone()[0])

    def test_all_cabinets_render_and_cannot_access_another_doctor_or_patient(self):
        for d in self.data['doctors']:
            client = self.login(d['id'])
            page = client.get('/').text
            for p in self.data['patients']:
                if p['doctor'] != d['id']:
                    self.assertNotIn(p['name'], page)
                    self.assertEqual(404, client.get('/demo/' + p['id']).status_code)
                    continue
                self.assertIn(p['name'], page)
                for route in ('/demo/{id}', '/patients/{id}/first-visits', '/patients/{id}/decisions',
                              '/patients/{id}/communication'):
                    response = client.get(route.format(id=p['id']))
                    self.assertEqual(200, response.status_code, (p['id'], route))
                    self.assertIn('synthetic; dates=simulated', response.text)
        for p in self.data['patients']:
            client = self.login(p['login'])
            for suffix in ('', '/diary', '/report', '/forms'):
                self.assertEqual(200, client.get('/demo/' + p['id'] + suffix).status_code)
            for suffix in ('/decisions', '/communication'):
                self.assertEqual(200, client.get('/patients/' + p['id'] + suffix).status_code)
            other = 'P202' if p['id'] == 'P201' else 'P201'
            self.assertEqual(404, client.get('/demo/' + other).status_code)
            self.assertEqual(404, client.get('/patients/' + p['id'] + '/imports').status_code)

    def test_existing_output_never_overwritten(self):
        before = self.target.read_bytes()
        with self.assertRaises(FileExistsError):
            roster.build(self.source, self.target, self.credentials)
        self.assertEqual(before, self.target.read_bytes())
        self.assertEqual(self.before, hashlib.sha256(self.source.read_bytes()).hexdigest())


if __name__ == '__main__':
    unittest.main()
