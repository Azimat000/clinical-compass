from pathlib import Path
import sqlite3
import tempfile
import unittest

from apps.compass.db import connect, health, migrate, transaction, MIGRATIONS
from apps.compass.events import enqueue, process_one
from apps.compass.repository import seed_demo, patient_list
from apps.compass.web import create_app


class FoundationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'compass.sqlite3'
        self.db = connect(self.path)
        migrate(self.db)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_seed_is_idempotent_and_survives_connection_restart(self):
        seed_demo(self.db)
        seed_demo(self.db)
        self.db.close()
        self.db = connect(self.path)
        migrate(self.db)
        self.assertEqual(6, self.db.execute('SELECT count(*) FROM patients').fetchone()[0])
        self.assertEqual(6, self.db.execute('SELECT count(*) FROM outbox_events').fetchone()[0])
        self.assertEqual('conflicting', self.db.execute("SELECT age_status FROM patients WHERE id='D06'").fetchone()[0])
        self.assertEqual('delete', health(self.db)['journal_mode'])
        self.assertEqual([], self.db.execute('PRAGMA foreign_key_check').fetchall())

    def test_atomic_data_and_event_rollback(self):
        with self.assertRaises(RuntimeError):
            with transaction(self.db):
                self.db.execute("INSERT INTO patients(id,code,age_status,synthetic,created_at) VALUES('x','x','unknown',1,'now')")
                enqueue(self.db, 'demo.patient_created.v1', 'x', {})
                raise RuntimeError('simulate interruption')
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM patients').fetchone()[0])
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM outbox_events').fetchone()[0])
        with self.assertRaises(RuntimeError):
            enqueue(self.db, 'bad', 'x', {})

    def test_event_retry_rolls_back_partial_handler_and_recovers(self):
        seed_demo(self.db)

        def fail_after_write(db, event):
            db.execute('INSERT INTO event_receipts VALUES(?,?,?)', (event['id'], 'partial', 'now'))
            raise ValueError('private payload must not be logged')

        process_one(self.db, {'demo.patient_created.v1': fail_after_write})
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM event_receipts').fetchone()[0])
        event = self.db.execute('SELECT * FROM outbox_events WHERE attempts=1').fetchone()
        self.assertEqual('ValueError', event['last_error'])
        self.db.close()
        self.db = connect(self.path)
        self.db.execute("UPDATE outbox_events SET available_at='2000-01-01' WHERE attempts=1")
        while process_one(self.db):
            pass
        self.assertEqual(6, self.db.execute('SELECT count(*) FROM event_receipts').fetchone()[0])
        self.assertFalse(process_one(self.db))
        self.assertEqual(6, self.db.execute('SELECT count(*) FROM event_receipts').fetchone()[0])

    def test_unknown_topic_goes_to_dead_queue(self):
        with transaction(self.db):
            event_id = enqueue(self.db, 'unsupported.v1', 'demo', {})
        for _ in range(5):
            self.db.execute("UPDATE outbox_events SET available_at='2000-01-01' WHERE id=?", (event_id,))
            process_one(self.db)
        row = self.db.execute('SELECT * FROM outbox_events WHERE id=?', (event_id,)).fetchone()
        self.assertEqual(('dead', 5), (row['status'], row['attempts']))

    def test_search_filter_and_index_update(self):
        seed_demo(self.db)
        self.assertEqual(['D01'], [r['id'] for r in patient_list(self.db, 'Демо 01')])
        self.assertEqual(['D06'], [r['id'] for r in patient_list(self.db, age_status='conflicting')])
        self.db.execute("UPDATE encounters SET narrative='Уникальныймаркер' WHERE id='D01-initial'")
        self.assertEqual(['D01'], [r['id'] for r in patient_list(self.db, 'Уникальныймаркер')])
        self.db.execute("DELETE FROM observations WHERE encounter_id='D01-initial'")
        self.db.execute("DELETE FROM encounters WHERE id='D01-initial'")
        self.assertEqual([], patient_list(self.db, 'Уникальныймаркер'))
        self.assertEqual([], patient_list(self.db, "' OR 1=1 --"))

    def test_immutable_migrations_and_atomic_failure(self):
        custom = Path(self.tmp.name) / 'migrations'
        custom.mkdir()
        for p in MIGRATIONS.glob('*.sql'):
            (custom / p.name).write_bytes(p.read_bytes())
        (custom / '002_broken.sql').write_text('CREATE TABLE example(id TEXT);\nBROKEN SQL;\n')
        with self.assertRaises(sqlite3.OperationalError):
            migrate(self.db, custom)
        self.assertIsNone(self.db.execute("SELECT name FROM sqlite_master WHERE name='example'").fetchone())
        (custom / '002_broken.sql').unlink()
        first = next(custom.glob('*.sql'))
        first.write_text(first.read_text() + '\n-- tampering\n')
        with self.assertRaisesRegex(RuntimeError, 'checksum'):
            migrate(self.db, custom)

    def test_model_guards_unknowns_foreign_keys_and_audit(self):
        seed_demo(self.db)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO patients(id,code,age_status,synthetic,created_at) VALUES(NULL,'invalid','unknown',1,'now')")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO encounters(id,patient_id,occurred_at,narrative,origin) VALUES('bad','missing','now','text','test')")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO observations(id,patient_id,code,value_json,data_status,observed_at,recorded_at,provenance_json) VALUES('bad','D01','allergy','false','unknown','now','now','{}')")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO care_actions(id,confirmation_id,effective_at) VALUES('bad','missing','now')")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE audit_entries SET event='changed'")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute('DELETE FROM audit_entries')

    def test_schema_extension_preserves_existing_data(self):
        seed_demo(self.db)
        custom = Path(self.tmp.name) / 'migrations'
        custom.mkdir()
        for p in MIGRATIONS.glob('*.sql'):
            (custom / p.name).write_bytes(p.read_bytes())
        (custom / '002_test_extension.sql').write_text('ALTER TABLE patients ADD COLUMN test_extension TEXT;\nCREATE INDEX test_extension_index ON patients(test_extension);\n')
        migrate(self.db, custom)
        migrate(self.db, custom)
        self.assertEqual(6, self.db.execute('SELECT count(*) FROM patients').fetchone()[0])
        self.assertEqual(6, self.db.execute('SELECT count(*) FROM outbox_events').fetchone()[0])
        self.assertEqual('002_test_extension', health(self.db)['schema_version'])
        self.assertEqual([], self.db.execute('PRAGMA foreign_key_check').fetchall())

    def test_authenticated_shell_escapes_input_and_rejects_other_hosts(self):
        seed_demo(self.db)
        from test_access import setup_identities, login
        from apps.compass.access import invite, accept_invite
        setup_identities(self.db)
        accept_invite(self.db, 'pat-a', invite(self.db, 'doc-a', 'D01'))
        app = create_app(self.path)
        client = app.test_client()
        self.assertEqual(302, login(client, 'doc-a').status_code)
        self.assertEqual('ok', client.get('/healthz').json['status'])
        page = client.get('/').get_data(as_text=True)
        self.assertIn('Демо 01', page)
        self.assertIn('width=device-width', page)
        self.assertEqual(200, client.get('/demo/D01').status_code)
        self.assertEqual(404, client.get('/demo/no-such-case').status_code)
        self.assertEqual(405, client.post('/').status_code)
        self.assertEqual(400, client.get('/', headers={'Host': 'external.example'}).status_code)
        self.assertEqual(400, client.get('/?age_status=invalid').status_code)
        self.assertNotIn('<script>alert(1)</script>', client.get('/', query_string={'q': '<script>alert(1)</script>'}).get_data(as_text=True))
        self.assertIn("frame-ancestors 'none'", client.get('/').headers['Content-Security-Policy'])

    def test_confirmation_requires_doctor_relationship_version_and_approval(self):
        seed_demo(self.db)
        for user_id, role in [('doctor', 'doctor'), ('stranger', 'doctor'), ('patient', 'patient')]:
            self.db.execute('INSERT INTO users(id,role,display_name,disabled) VALUES(?,?,?,0)', (user_id, role, user_id))
        self.db.execute("INSERT INTO care_relationships VALUES('r','D01','doctor','now',NULL)")
        for proposal_id in ['p1', 'p2']:
            self.db.execute("INSERT INTO proposals(id,patient_id,kind,version,payload_json,input_snapshot_json,created_at) VALUES(?,'D01','plan_change',1,'{}','{}','now')", (proposal_id,))
        for doctor_id, version in [('patient', 1), ('stranger', 1), ('doctor', 2)]:
            with self.assertRaises(sqlite3.IntegrityError):
                self.db.execute("INSERT INTO doctor_confirmations VALUES('bad','p1',?,?,'approved','test','now')", (doctor_id, version))
        self.db.execute("INSERT INTO doctor_confirmations VALUES('c1','p1','doctor',1,'approved','synthetic test','now')")
        self.db.execute("INSERT INTO care_actions(id,confirmation_id,effective_at) VALUES('a1','c1','now')")
        self.db.execute("INSERT INTO doctor_confirmations VALUES('c2','p2','doctor',1,'rejected','synthetic test','now')")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO care_actions(id,confirmation_id,effective_at) VALUES('a2','c2','now')")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE doctor_confirmations SET decision='approved' WHERE id='c2'")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE proposals SET payload_json='[1]' WHERE id='p1'")

    def test_catalog_extension_keeps_versions_and_blocks_incomplete_scores(self):
        seed_demo(self.db)
        self.db.execute("INSERT INTO source_versions VALUES('src','TEST','1','local:test','hash','now','{}','unknown','unknown','unverified')")
        for version in ('1', '2'):
            self.db.execute("INSERT INTO catalog_versions(id,kind,code,version,source_version_id,definition_json,blocker) VALUES(?,'scale','TEST',?,'src','{}','not clinically reviewed')", ('test-' + version, version))
        self.assertEqual(2, self.db.execute('SELECT count(*) FROM catalog_versions').fetchone()[0])
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO assessments VALUES('bad','D01','test-1',NULL,NULL,'{}',0,'incomplete','v1')")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE catalog_versions SET status='reviewed' WHERE id='test-1'")


if __name__ == '__main__':
    unittest.main()
