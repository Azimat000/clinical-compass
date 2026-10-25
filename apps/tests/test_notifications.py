"""S10A: ordinary reports, durable delivery and explicit human acknowledgement."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import secrets
import tempfile
from threading import Barrier
import unittest
from unittest.mock import patch

from apps.compass import access, events, notifications, records
from apps.compass.db import MIGRATIONS, connect, migrate, now
from apps.compass.repository import seed_demo
from apps.compass.web import create_app
from test_access import setup_identities, login, csrf


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'delivery.sqlite3'
        self.db = connect(self.path)
        migrate(self.db)
        seed_demo(self.db)
        setup_identities(self.db)
        access.accept_invite(self.db, 'pat-a', access.invite(self.db, 'doc-a', 'D01'))
        while events.process_one(self.db):
            pass
        self.app = create_app(self.path)
        self.clients = {u: self.app.test_client() for u in ('doc-a', 'doc-b', 'pat-a', 'pat-b')}
        for uid, client in self.clients.items():
            self.assertEqual(302, login(client, uid).status_code)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def values(self):
        return {'request_key': secrets.token_hex(16), 'observed_on': '2026-10-18',
                'summary': 'Synthetic ordinary report', 'wellbeing': 'unknown'}

    def save(self, values=None):
        return records.save(self.db, {'id': 'pat-a', 'role': 'patient'}, 'D01', 'self_report', values or self.values())

    def row(self, entry):
        return self.db.execute('SELECT * FROM routine_notifications WHERE id=?', (entry,)).fetchone()

    def post(self, uid, entry, action, token=True):
        client = self.clients[uid]
        return client.post(f'/notifications/{entry}/{action}', data={'csrf': csrf(client)} if token else {})

    def test_atomic_enqueue_failure_and_request_and_processing_duplicates(self):
        untouched = {table: [tuple(r) for r in self.db.execute('SELECT * FROM ' + table)]
                     for table in ('observations', 'audit_entries', 'outbox_events', 'adverse_events')}
        original = notifications.enqueue_report
        def fail(*args):
            original(*args)
            raise RuntimeError('synthetic private marker')
        with patch.object(notifications, 'enqueue_report', side_effect=fail):
            with self.assertRaises(RuntimeError):
                self.save()
        for table in ('clinical_entries', 'self_reports', 'routine_notifications'):
            self.assertEqual(0, self.db.execute('SELECT count(*) FROM ' + table).fetchone()[0])
        self.assertEqual(0, self.db.execute("SELECT count(*) FROM outbox_events WHERE topic='routine.self_report.v1'").fetchone()[0])
        for table, rows in untouched.items():
            self.assertEqual(rows, [tuple(r) for r in self.db.execute('SELECT * FROM ' + table)], table)
        values = self.values()
        entry = self.save(values)
        self.assertEqual(entry, self.save(values))
        with self.assertRaises(records.RecordError):
            self.save({**values, 'wellbeing': 'worse'})
        row = self.row(entry)
        event = self.db.execute('SELECT * FROM outbox_events WHERE id=?', (row['event_id'],)).fetchone()
        self.assertEqual({'entry_id': entry}, json.loads(event['payload_json']))
        self.assertIsNone(row['ready_at'])
        self.assertTrue(events.process_one(self.db))
        ready = self.row(entry)['ready_at']
        notifications.ready_report(self.db, event)
        self.assertEqual(ready, self.row(entry)['ready_at'])
        self.assertFalse(events.process_one(self.db))
        self.assertEqual(1, self.db.execute('SELECT count(*) FROM routine_notifications').fetchone()[0])

    def test_transient_failure_recovers_without_duplicate_and_summary_is_escaped(self):
        entry = self.save({**self.values(), 'summary': '<script>syntheticMarker()</script>'})
        event_id = self.row(entry)['event_id']
        def transient(db, event):
            notifications.ready_report(db, event)
            raise RuntimeError('private synthetic failure')
        self.assertTrue(events.process_one(self.db, {'routine.self_report.v1': transient}))
        self.assertIsNone(self.row(entry)['ready_at'])
        self.assertIsNone(self.row(entry)['delivered_at'])
        self.db.execute("UPDATE outbox_events SET available_at='2000-01-01' WHERE id=?", (event_id,))
        self.assertTrue(events.process_one(self.db))
        self.assertFalse(events.process_one(self.db))
        self.assertIsNotNone(self.row(entry)['ready_at'])
        self.assertIsNone(self.row(entry)['delivered_at'])
        attempts = self.db.execute('SELECT attempt,outcome,error FROM outbox_attempts WHERE event_id=? ORDER BY attempt', (event_id,)).fetchall()
        self.assertEqual([(1, 'retry', 'RuntimeError'), (2, 'processed', None)], [tuple(r) for r in attempts])
        page = self.clients['doc-a'].get('/demo/D01').get_data(as_text=True)
        self.assertIn('&lt;script&gt;syntheticMarker()&lt;/script&gt;', page)
        self.assertNotIn('<script>syntheticMarker()', page)
        self.assertIsNone(self.row(entry)['delivered_at'])
        self.assertEqual(1, self.db.execute('SELECT count(*) FROM routine_notifications').fetchone()[0])

    def test_concurrent_same_request_serializes_to_one_report_event_notification(self):
        values = self.values()
        barrier = Barrier(2)
        def submit():
            db = connect(self.path)
            try:
                barrier.wait(timeout=5)
                return records.save(db, {'id': 'pat-a', 'role': 'patient'}, 'D01', 'self_report', values)
            finally:
                db.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(submit) for _ in range(2)]
            entries = [future.result(timeout=15) for future in futures]
        self.assertEqual(entries[0], entries[1])
        for table in ('clinical_entries', 'self_reports', 'routine_notifications'):
            self.assertEqual(1, self.db.execute('SELECT count(*) FROM ' + table).fetchone()[0], table)
        self.assertEqual(1, self.db.execute("SELECT count(*) FROM outbox_events WHERE topic='routine.self_report.v1'").fetchone()[0])
        self.assertTrue(events.process_one(self.db))
        self.assertFalse(events.process_one(self.db))
        self.assertIsNotNone(self.row(entries[0])['ready_at'])

    def test_failed_handler_rolls_back_then_retry_dead_journal_survives_reopen(self):
        entry = self.save()
        event_id = self.row(entry)['event_id']
        def fail(db, event):
            db.execute('UPDATE routine_notifications SET ready_at=? WHERE id=?', (now(), entry))
            raise RuntimeError('private clinical error must not be persisted')
        for attempt in range(1, 6):
            self.db.execute("UPDATE outbox_events SET available_at='2000-01-01' WHERE id=?", (event_id,))
            self.assertTrue(events.process_one(self.db, {'routine.self_report.v1': fail}))
            self.assertIsNone(self.row(entry)['ready_at'])
            event = self.db.execute('SELECT * FROM outbox_events WHERE id=?', (event_id,)).fetchone()
            self.assertEqual(attempt, event['attempts'])
        self.assertEqual('dead', event['status'])
        self.db.close()
        self.db = connect(self.path)
        attempts = self.db.execute('SELECT * FROM outbox_attempts WHERE event_id=? ORDER BY attempt', (event_id,)).fetchall()
        self.assertEqual([1, 2, 3, 4, 5], [r['attempt'] for r in attempts])
        self.assertEqual(['retry'] * 4 + ['dead'], [r['outcome'] for r in attempts])
        self.assertNotIn('private clinical', str([tuple(r) for r in attempts]))
        self.assertIn(entry, [n['id'] for n in notifications.inbox(self.db, {'id':'doc-a','role':'doctor'}, prepare=False)])
        self.assertIsNone(self.row(entry)['delivered_at'])

    def test_delivery_seen_ack_order_idempotency_and_no_clinical_actions(self):
        catalog_before = [tuple(r) for r in self.db.execute('SELECT * FROM catalog_versions')]
        entry = self.save()
        self.assertEqual(409, self.post('doc-a', entry, 'seen').status_code)
        self.assertEqual(409, self.post('doc-a', entry, 'acknowledged').status_code)
        events.process_one(self.db)
        self.assertIsNone(self.row(entry)['delivered_at'])
        self.assertEqual(302, self.clients['doc-a'].head('/notifications').status_code)
        self.assertIsNone(self.row(entry)['delivered_at'])
        self.assertEqual(409, self.post('doc-a', entry, 'seen').status_code)
        # Historical backend receipts remain testable without a user-facing inbox.
        items = notifications.inbox(self.db, {'id':'doc-a','role':'doctor'})
        self.assertIn(entry, [n['id'] for n in items])
        self.assertEqual(409, self.post('doc-a', entry, 'acknowledged').status_code)
        self.assertIn(self.post('doc-a', entry, 'seen').status_code, (302, 303))
        self.assertIn(self.post('doc-a', entry, 'acknowledged').status_code, (302, 303))
        before = dict(self.row(entry))
        self.clients['doc-a'].get('/notifications')
        self.post('doc-a', entry, 'seen')
        self.post('doc-a', entry, 'acknowledged')
        self.assertEqual(before, dict(self.row(entry)))
        stamps = [before[k] for k in ('created_at', 'ready_at', 'delivered_at', 'seen_at', 'acknowledged_at')]
        self.assertEqual(sorted(stamps), stamps)
        self.db.close()
        self.db = connect(self.path)
        migrate(self.db)
        self.assertEqual(before, dict(self.row(entry)))
        payload = json.loads(self.db.execute('SELECT payload_json FROM clinical_entries WHERE id=?', (entry,)).fetchone()[0])
        self.assertEqual('unknown', payload['fields']['risk_factors']['status'])
        for table in ('care_actions', 'proposals', 'alerts', 'risk_evaluations', 'assessments'):
            self.assertEqual(0, self.db.execute('SELECT count(*) FROM ' + table).fetchone()[0])
        self.assertEqual(catalog_before, [tuple(r) for r in self.db.execute('SELECT * FROM catalog_versions')])
        self.assertEqual([], self.db.execute('PRAGMA foreign_key_check').fetchall())

    def test_role_csrf_foreign_and_ended_or_replaced_relationship(self):
        entry = self.save()
        events.process_one(self.db)
        self.clients['doc-a'].get('/notifications')
        anon = self.app.test_client()
        self.assertEqual(302, anon.get('/notifications').status_code)
        self.assertEqual(403, self.clients['pat-a'].get('/notifications').status_code)
        for action in ('seen', 'acknowledged'):
            self.assertEqual(302, anon.post(f'/notifications/{entry}/{action}').status_code)
            self.assertEqual(404, self.post('doc-a', 'missing', action).status_code)
            self.assertEqual(403, self.post('doc-a', entry, action, token=False).status_code)
            self.assertEqual(404, self.post('doc-b', entry, action).status_code)
            self.assertEqual(403, self.post('pat-a', entry, action).status_code)
            client = self.clients['doc-a']
            self.assertEqual(403, client.post(f'/notifications/{entry}/{action}', data={'csrf': csrf(self.clients['doc-b'])}).status_code)
        self.assertNotIn(entry, self.clients['doc-b'].get('/notifications').get_data(as_text=True))
        self.db.execute('UPDATE care_relationships SET ends_at=?', (now(),))
        access.accept_invite(self.db, 'pat-a', access.invite(self.db, 'doc-b', 'D01'))
        for uid in ('doc-a', 'doc-b'):
            self.assertNotIn(entry, self.clients[uid].get('/notifications').get_data(as_text=True))
            self.assertEqual(404, self.post(uid, entry, 'seen').status_code)
        self.assertIsNone(self.row(entry)['seen_at'])
        self.db.execute('UPDATE care_relationships SET ends_at=? WHERE ends_at IS NULL', (now(),))
        access.accept_invite(self.db, 'pat-a', access.invite(self.db, 'doc-a', 'D01'))
        self.assertNotIn(entry, self.clients['doc-a'].get('/notifications').get_data(as_text=True))
        self.assertEqual(404, self.post('doc-a', entry, 'seen').status_code)

    def test_pending_old_or_future_link_and_disabled_doctor_cannot_deliver(self):
        for change in ('ended', 'future', 'disabled'):
            with self.subTest(change=change):
                entry = self.save()
                rel = self.db.execute("SELECT * FROM care_relationships WHERE ends_at IS NULL").fetchone()
                if change == 'ended':
                    self.db.execute('UPDATE care_relationships SET ends_at=? WHERE id=?', (now(), rel['id']))
                elif change == 'future':
                    self.db.execute('UPDATE care_relationships SET starts_at=? WHERE id=?', (access.future(days=1), rel['id']))
                else:
                    self.db.execute("UPDATE users SET disabled=1 WHERE id='doc-a'")
                self.assertTrue(events.process_one(self.db))
                self.assertIsNone(self.row(entry)['ready_at'])
                self.assertIsNone(self.row(entry)['delivered_at'])
                if change == 'disabled':
                    for operation in (lambda: notifications.inbox(self.db, {'id': 'doc-a', 'role': 'doctor'}),
                                      lambda: notifications.mark(self.db, {'id': 'doc-a', 'role': 'doctor'}, entry, 'seen')):
                        with self.assertRaises(notifications.NotificationError) as denied:
                            operation()
                        self.assertEqual(403, denied.exception.status)
                self.db.execute('UPDATE care_relationships SET ends_at=NULL,starts_at=? WHERE id=?', ('2000-01-01', rel['id']))
                self.db.execute("UPDATE users SET disabled=0 WHERE id='doc-a'")
                self.db.execute("UPDATE outbox_events SET status='dead' WHERE id=?", (self.row(entry)['event_id'],))
        self.db.execute('UPDATE care_relationships SET ends_at=?', (now(),))
        with self.assertRaises(records.RecordError):
            self.save()

    def test_upgrade_s09_database_preserves_every_existing_table_row(self):
        old = connect(Path(self.tmp.name) / 'old.sqlite3')
        directory = Path(self.tmp.name) / 'old-migrations'
        directory.mkdir()
        for file in MIGRATIONS.glob('*.sql'):
            if file.name[:3] <= '006':
                (directory / file.name).write_bytes(file.read_bytes())
        migrate(old, directory)
        seed_demo(old)
        setup_identities(old)
        tables = [r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type='table' AND name!='schema_migrations'")]
        before = {t: [tuple(r) for r in old.execute('SELECT * FROM "' + t + '"')] for t in tables}
        migrate(old)
        for table, rows in before.items():
            self.assertEqual(rows, [tuple(r) for r in old.execute('SELECT * FROM "' + table + '"')], table)
        self.assertEqual(0, old.execute('SELECT count(*) FROM routine_notifications').fetchone()[0])
        self.assertEqual([], old.execute('PRAGMA foreign_key_check').fetchall())
        self.assertEqual('ok', old.execute('PRAGMA integrity_check').fetchone()[0])
        old.close()
