"""The walkthrough must preserve manual work and never bypass clinical boundaries."""
import hashlib
from pathlib import Path
import re
import tempfile
import unittest

from tools.seed_walkthrough_demo import build, PASSWORD
from apps.compass import access, records
from apps.compass.db import connect, migrate
from apps.compass.repository import seed_demo
from apps.compass.web import create_app
from werkzeug.security import generate_password_hash


class WalkthroughTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.source = Path(self.tmp.name) / 'original.sqlite3'
        self.target = Path(self.tmp.name) / 'walkthrough.sqlite3'
        self.db = connect(self.source)
        migrate(self.db)
        seed_demo(self.db)
        create_app(self.source)
        hashed = generate_password_hash(PASSWORD, method='scrypt:32768:8:1')
        self.db.execute('INSERT INTO users VALUES(?,?,?,?,0)', ('doc-a', 'doctor', 'Existing doctor', hashed))
        self.db.execute('INSERT INTO users VALUES(?,?,?,?,0)', ('pat-a', 'patient', 'Existing patient', hashed))
        self.db.execute("UPDATE patients SET user_id='pat-a' WHERE id='D01'")
        access.accept_invite(self.db, 'pat-a', access.invite(self.db, 'doc-a', 'D01'))
        records.save(self.db, {'id': 'pat-a', 'role': 'patient'}, 'D01', 'self_report', {
            'observed_on': records.today().isoformat(), 'request_key': 'a' * 32,
            'summary': 'EXISTING MANUAL WORK MUST SURVIVE',
        })

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_histories_visibility_boundaries_and_preservation(self):
        before = hashlib.sha256(self.source.read_bytes()).hexdigest()
        original = {table: [tuple(r) for r in self.db.execute('SELECT * FROM ' + table)]
            for table in ('patients', 'users', 'clinical_entries', 'self_reports', 'care_relationships',
                          'proposals', 'source_versions', 'catalog_versions', 'assessment_form_releases', 'audit_entries')}
        report = build(self.source, self.target)
        self.assertEqual(before, hashlib.sha256(self.source.read_bytes()).hexdigest())
        self.assertEqual(5, len(report['patients']))
        db = connect(self.target)
        try:
            for table, rows in original.items():
                new = {tuple(r) for r in db.execute('SELECT * FROM ' + table)}
                self.assertTrue(set(rows).issubset(new), table)
            for item in report['patients']:
                pid = item['patient_id']
                self.assertEqual(5, db.execute("SELECT count(*) FROM clinical_entries WHERE patient_id=? AND kind='self_report'", (pid,)).fetchone()[0])
                self.assertEqual(3, db.execute('SELECT count(*) FROM first_visit_versions WHERE patient_id=?', (pid,)).fetchone()[0])
                self.assertEqual(5, db.execute('SELECT count(*) FROM adherence_tasks WHERE patient_id=?', (pid,)).fetchone()[0])
                self.assertEqual(2, db.execute('''SELECT count(*) FROM care_actions a JOIN doctor_confirmations c ON c.id=a.confirmation_id
                    JOIN proposals p ON p.id=c.proposal_id WHERE p.patient_id=?''', (pid,)).fetchone()[0])
                self.assertTrue(all('УЧЕБНЫЙ ПРИМЕР' in row[0] for row in db.execute(
                    'SELECT payload_json FROM proposals WHERE patient_id=?', (pid,))))
            self.assertEqual(0, db.execute("SELECT count(*) FROM assessment_requests WHERE patient_id='WD05'").fetchone()[0])
            incomplete = db.execute("SELECT a.answers_json FROM assessments a WHERE a.patient_id='WD04'").fetchall()
            self.assertEqual(1, sum('null' in row[0] for row in incomplete))
            self.assertEqual(0, db.execute("SELECT count(*) FROM critical_events WHERE patient_id LIKE 'WD%'").fetchone()[0])
            self.assertEqual('ok', db.execute('PRAGMA integrity_check').fetchone()[0])
            self.assertEqual([], db.execute('PRAGMA foreign_key_check').fetchall())
        finally:
            db.close()
        app = create_app(self.target)
        for login, expected in [('doc-a', '/'), ('demo-anna', '/demo/WD01'), ('demo-irina', '/demo/WD05')]:
            client = app.test_client()
            page = client.get('/login').text
            token = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
            self.assertEqual(302, client.post('/login', data={'csrf': token, 'login': login, 'password': PASSWORD}).status_code)
            self.assertEqual(200, client.get(expected).status_code)
            if login == 'doc-a':
                for item in report['patients']:
                    self.assertIn(item['name'], client.get('/').text)
                    summary = client.get(item['summary_url'])
                    self.assertEqual(200, summary.status_code)
                    self.assertIn('УЧЕБНЫЙ ПРИМЕР', summary.text)
            else:
                self.assertEqual(403, client.get('/patients/WD01/follow-up').status_code)
                self.assertEqual(404, client.get('/demo/WD02').status_code)

    def test_refuse_existing_output_and_same_source(self):
        self.target.write_text('DO NOT OVERWRITE')
        with self.assertRaises(FileExistsError):
            build(self.source, self.target)
        self.assertEqual('DO NOT OVERWRITE', self.target.read_text())
        with self.assertRaises(ValueError):
            build(self.source, self.source)

    def test_refuse_non_synthetic_missing_doctor_and_repeated_seed(self):
        with self.assertRaises(ValueError):
            build(self.source, self.target, 'missing-doctor')
        self.assertFalse(self.target.exists())
        # Adversarial legacy/corrupted fixture: the normal schema itself forbids this.
        self.db.execute('PRAGMA ignore_check_constraints=ON')
        self.db.execute("UPDATE patients SET synthetic=0 WHERE id='D01'")
        self.db.execute('PRAGMA ignore_check_constraints=OFF')
        with self.assertRaises(ValueError):
            build(self.source, self.target)
        self.assertFalse(self.target.exists())
        self.db.execute("UPDATE patients SET synthetic=1 WHERE id='D01'")
        build(self.source, self.target)
        duplicate = self.target.with_name('duplicate.sqlite3')
        with self.assertRaises(ValueError):
            build(self.target, duplicate)
        self.assertFalse(duplicate.exists())
