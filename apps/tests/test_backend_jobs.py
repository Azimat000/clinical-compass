"""BE06: transactional intents, real SQLite leases and publication boundaries."""
from copy import deepcopy
import hashlib
import json
import secrets
import sqlite3
import unittest
from unittest.mock import patch

from apps.compass import backend_analyses as analyses, backend_jobs as jobs, events, records
from apps.compass.db import connect, now, transaction
from apps.tests import test_access, test_backend_contracts, test_backend_snapshot


def insufficient(operation, snapshot):
    return {'status': 'insufficient_data', 'errors': [
        {'code': 'synthetic_fixture', 'message': 'Техническая проверка; клинической оценки нет.', 'retryable': False}]}


class BackendJobTests(unittest.TestCase):
    setUp = test_backend_contracts.BackendContractTests.setUp
    tearDown = test_access.AccessTests.tearDown
    post = test_access.AccessTests.post
    offer = test_access.AccessTests.offer
    body = test_backend_contracts.BackendContractTests.body
    diary = test_backend_snapshot.BackendSnapshotTests.diary
    visit = test_backend_snapshot.BackendSnapshotTests.visit
    questionnaire = test_backend_snapshot.BackendSnapshotTests.questionnaire

    def enable(self):
        self.db.execute('UPDATE backend_job_settings SET enabled=1')

    def create(self, operation='risk', body=None):
        return analyses.create(self.db, self.user, 'D01', body or self.body(operation))

    def latest(self, run):
        return analyses._latest(self.db, run['run_id'])

    def due(self):
        self.db.execute("UPDATE backend_jobs SET available_at='2000'")
        self.db.execute("UPDATE outbox_events SET available_at='2000'")

    def test_disabled_by_default_and_schema015_tolerated(self):
        self.create()
        self.diary()
        self.assertIsNone(jobs.fingerprint(self.db))
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0])
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM outbox_events WHERE topic=?', (jobs.TOPIC,)).fetchone()[0])
        self.assertFalse(jobs.process_one(self.db))
        self.db.execute('DROP TABLE backend_job_settings')
        self.assertIsNone(jobs.settings(self.db))

    def test_atomic_intents_rollback_and_existing_deterministic_path(self):
        self.enable()
        with patch('apps.compass.report_drafts.consumed', side_effect=RuntimeError('crash')):
            with self.assertRaises(RuntimeError):
                self.diary()
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM clinical_entries').fetchone()[0])
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM outbox_events WHERE topic=?', (jobs.TOPIC,)).fetchone()[0])
        with patch('apps.compass.clinical_rules.evaluate_safety', wraps=__import__('apps.compass.clinical_rules', fromlist=['evaluate_safety']).evaluate_safety) as safety:
            self.diary()
            self.assertEqual(1, safety.call_count)
        self.assertGreater(self.db.execute('SELECT count(*) FROM outbox_events WHERE topic=?', (jobs.TOPIC,)).fetchone()[0], 0)
        # Processing unavailable analysis must not roll back the saved record.
        while events.process_one(self.db):
            pass
        for _ in range(3):
            jobs.process_one(self.db, executor=jobs.unavailable); self.due()
        self.assertEqual(1, self.db.execute('SELECT count(*) FROM clinical_entries').fetchone()[0])
        self.assertEqual('failed', json.loads(self.db.execute('SELECT payload_json FROM analysis_result_versions ORDER BY revision DESC LIMIT 1').fetchone()[0])['status'])

    def test_four_source_changes_and_corrections_create_only_risk(self):
        self.enable()
        self.diary()
        vid, values = self.visit()
        values.update(base_revision='1', request_key=secrets.token_hex(16), history_text='Уточнение синтетического анамнеза')
        from apps.compass import first_visits
        first_visits.save(self.db, self.user, 'D01', vid, values)
        self.questionnaire()
        while events.process_one(self.db):
            pass
        runs = self.db.execute('SELECT * FROM analysis_runs').fetchall()
        self.assertEqual(1, len(runs))  # All events coalesce to one exact current snapshot.
        self.assertEqual('risk', runs[0]['operation'])
        self.assertEqual(1, self.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0])
        # Another actual correction produces a new snapshot and risk run.
        self.db.execute("UPDATE observations SET observed_at='2026-10-17' WHERE code='reported_age'")
        while events.process_one(self.db):
            pass
        self.assertEqual(2, self.db.execute('SELECT count(*) FROM analysis_runs').fetchone()[0])
        self.assertTrue(all(r[0] == 'risk' for r in self.db.execute('SELECT operation FROM analysis_runs')))

    def test_request_job_and_snapshot_rollback_together(self):
        self.enable()
        with patch.object(jobs, 'schedule', side_effect=RuntimeError()):
            with self.assertRaises(RuntimeError):
                self.create()
        for table in ('analysis_runs','analysis_input_snapshots','analysis_result_versions','backend_jobs'):
            self.assertEqual(0, self.db.execute('SELECT count(*) FROM ' + table).fetchone()[0])

    def test_idempotent_replay_and_two_connections_no_duplicate_claim(self):
        self.enable()
        body = self.body('diagnosis')
        run = self.create(body=body)
        self.assertEqual(run, self.create(body=body))
        first = jobs.claim(self.db)
        other = connect(self.path)
        try:
            self.assertIsNone(jobs.claim(other))
            self.assertTrue(jobs.finish(other, first, insufficient('diagnosis', first['snapshot'])))
            self.assertFalse(jobs.finish(self.db, first, insufficient('diagnosis', first['snapshot'])))
        finally:
            other.close()
        self.assertEqual('insufficient_data', self.latest(run)['status'])
        self.assertEqual(1, self.db.execute("SELECT count(*) FROM analysis_result_versions WHERE status='insufficient_data'").fetchone()[0])

    def test_risk_priority_and_lane_isolation(self):
        self.enable()
        generation = self.create('diagnosis')
        risk = self.create('risk')
        claim = jobs.claim(self.db)
        self.assertEqual(risk['run_id'], claim['run']['id'])
        self.assertIsNone(jobs.claim(self.db, 'risk'))
        second = jobs.claim(self.db, 'generation')
        self.assertEqual(generation['run_id'], second['run']['id'])
        self.assertFalse(self.db.in_transaction)

    def test_restart_expiry_and_fencing_prevent_late_publication(self):
        self.enable()
        run = self.create()
        first = jobs.claim(self.db)
        self.db.execute("UPDATE backend_jobs SET lease_until='2000'")
        self.assertFalse(jobs.finish(self.db, first, insufficient('risk', first['snapshot'])))
        other = connect(self.path)
        try:
            second = jobs.claim(other)
            self.assertEqual(2, second['attempt'])
            self.assertFalse(jobs.finish(other, first, insufficient('risk', first['snapshot'])))
            self.assertTrue(jobs.finish(other, second, insufficient('risk', second['snapshot'])))
        finally:
            other.close()
        self.assertEqual(['expired','done'], [r[0] for r in self.db.execute('SELECT outcome FROM backend_job_attempts ORDER BY attempt')])
        self.assertEqual('insufficient_data', self.latest(run)['status'])

    def test_three_crashes_exhaust_lease_and_fail(self):
        self.enable()
        run = self.create()
        for _ in range(3):
            self.assertIsNotNone(jobs.claim(self.db))
            self.db.execute("UPDATE backend_jobs SET lease_until='2000'")
        self.assertIsNone(jobs.claim(self.db))
        self.assertEqual('failed', self.latest(run)['status'])
        self.assertEqual('lease_expired', self.latest(run)['errors'][0]['code'])

    def test_unavailable_is_bounded_technical_failure_with_no_result(self):
        self.enable()
        run = self.create()
        for _ in range(3):
            self.assertTrue(jobs.process_one(self.db, executor=jobs.unavailable)); self.due()
        self.assertFalse(jobs.process_one(self.db))
        value = self.latest(run)
        self.assertEqual('failed', value['status'])
        self.assertIsNone(value['result'])
        self.assertEqual('operation_unavailable', value['errors'][0]['code'])
        self.assertEqual(3, self.db.execute('SELECT count(*) FROM backend_job_attempts').fetchone()[0])
        self.assertEqual('blocked', value['release']['status'])

    def test_model_exception_does_not_log_secret_or_hold_write_lock(self):
        self.enable()
        run = self.create()
        def executor(operation, snapshot):
            other = connect(self.path)
            try:
                with transaction(other):
                    other.execute("INSERT INTO relationship_checks VALUES(?,?,?,?)", ('lock-test', self.db.execute('SELECT id FROM care_relationships').fetchone()[0], 'pat-a', now()))
            finally:
                other.close()
            raise RuntimeError('SECRET clinical text')
        jobs.process_one(self.db, executor=executor)
        row = self.db.execute('SELECT * FROM backend_jobs').fetchone()
        self.assertEqual(1, self.db.execute("SELECT count(*) FROM relationship_checks WHERE id='lock-test'").fetchone()[0])
        self.assertEqual('executor_error', row['last_error'])
        self.assertNotIn('SECRET', str(dict(row)))
        self.assertEqual('running', self.latest(run)['status'])

    def test_revoke_or_replace_relationship_during_work_suppresses_result(self):
        for replace in (False, True):
            with self.subTest(replace=replace):
                if replace:
                    self.db.execute('INSERT INTO care_relationships VALUES(?,?,?,?,NULL)', ('replacement', 'D01', 'doc-a', now()))
                self.enable()
                run = self.create()
                work = jobs.claim(self.db)
                self.db.execute('UPDATE care_relationships SET ends_at=? WHERE ends_at IS NULL', (now(),))
                if replace:
                    self.db.execute('INSERT INTO care_relationships VALUES(?,?,?,?,NULL)', ('replacement2', 'D01', 'doc-b', now()))
                self.assertTrue(jobs.finish(self.db, work, insufficient('risk', work['snapshot'])))
                self.assertEqual('stale', self.latest(run)['status'])
                with self.assertRaises(analyses.AnalysisError):
                    analyses.read(self.db, self.user, 'D01', run['run_id'])

    def test_disabled_doctor_and_revoked_event_never_reassigned(self):
        self.enable()
        self.diary()
        self.db.execute("UPDATE users SET disabled=1 WHERE id='doc-a'")
        while events.process_one(self.db):
            pass
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM analysis_runs').fetchone()[0])

    def test_new_data_source_version_or_model_version_stales_result(self):
        self.enable()
        run = self.create()
        work = jobs.claim(self.db)
        self.diary()
        jobs.finish(self.db, work, insufficient('risk', work['snapshot']))
        self.assertEqual('stale', self.latest(run)['status'])
        run = self.create()
        jobs.process_one(self.db, executor=insufficient)
        self.assertEqual('insufficient_data', analyses.read(self.db, self.user, 'D01', run['run_id'])['status'])
        self.db.execute("UPDATE backend_job_settings SET generation_version='next-version'")
        self.assertEqual('stale', analyses.read(self.db, self.user, 'D01', run['run_id'])['status'])
        run = self.create()
        work = jobs.claim(self.db)
        self.db.execute("UPDATE source_versions SET checked_at='2000' WHERE id=(SELECT id FROM source_versions LIMIT 1)")
        jobs.finish(self.db, work, insufficient('risk', work['snapshot']))
        self.assertEqual('stale', self.latest(run)['status'])

    def test_cancel_is_authorized_idempotent_and_fenced(self):
        self.enable()
        run = self.create()
        work = jobs.claim(self.db)
        with self.assertRaises(analyses.AnalysisError):
            jobs.cancel(self.db, {'id':'doc-b','role':'doctor'}, 'D01', run['run_id'])
        value = jobs.cancel(self.db, self.user, 'D01', run['run_id'])
        self.assertEqual('cancelled', value['errors'][0]['code'])
        self.assertEqual(value, jobs.cancel(self.db, self.user, 'D01', run['run_id']))
        self.assertFalse(jobs.finish(self.db, work, insufficient('risk', work['snapshot'])))

    def test_invalid_generator_payload_cannot_bypass_contract(self):
        self.enable()
        run = self.create()
        for _ in range(3):
            jobs.process_one(self.db, executor=lambda *_: {'status':'ready','result':{'invented':'value'}})
            self.due()
        self.assertEqual('failed', self.latest(run)['status'])
        self.assertEqual('invalid_result', self.latest(run)['errors'][0]['code'])
        self.assertEqual(0, self.db.execute("SELECT count(*) FROM analysis_result_versions WHERE status='ready'").fetchone()[0])

    def test_disable_during_work_and_snapshot_failure_keep_safe_state(self):
        self.enable()
        run = self.create()
        work = jobs.claim(self.db)
        self.db.execute('UPDATE backend_job_settings SET enabled=0')
        jobs.finish(self.db, work, insufficient('risk', work['snapshot']))
        self.assertEqual('stale', self.latest(run)['status'])
        self.enable()
        self.diary()
        with patch.object(analyses, 'capture', side_effect=analyses.AnalysisError('blocked',409,'source_unavailable')):
            events.process_one(self.db)
        event = self.db.execute('SELECT * FROM outbox_events WHERE topic=? ORDER BY attempts DESC', (jobs.TOPIC,)).fetchone()
        self.assertEqual('pending', event['status'])
        self.assertEqual(1, event['attempts'])
        self.assertEqual('RuntimeError', event['last_error'])

    def test_critical_event_priority_over_analysis_and_other_events(self):
        self.enable()
        self.diary()
        with transaction(self.db):
            events.enqueue(self.db, 'clinical.critical.medication_safety.v1', 'D01', {})
        seen=[]
        handlers={key: lambda db,event: seen.append(event['topic']) for key in events.HANDLERS}
        events.process_one(self.db, handlers)
        self.assertEqual(['clinical.critical.medication_safety.v1'],seen)


    def test_concurrent_workers_publish_one_terminal_version(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        self.enable()
        run = self.create()
        barrier = Barrier(2)
        def worker():
            other = connect(self.path)
            try:
                barrier.wait(timeout=5)
                return jobs.process_one(other, executor=insufficient)
            finally:
                other.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = pool.submit(worker), pool.submit(worker)
            self.assertEqual(1, sum([first.result(timeout=10), second.result(timeout=10)]))
        self.assertEqual('insufficient_data', self.latest(run)['status'])
        self.assertEqual(1, self.db.execute("SELECT count(*) FROM analysis_result_versions WHERE status='insufficient_data'").fetchone()[0])
        self.assertEqual(1, self.db.execute('SELECT count(*) FROM backend_job_attempts').fetchone()[0])

    def test_crash_between_result_and_job_completion_rolls_back_both(self):
        self.enable()
        run = self.create()
        work = jobs.claim(self.db)
        self.db.execute("CREATE TRIGGER injected_finish_fault BEFORE UPDATE ON backend_jobs WHEN new.state='done' BEGIN SELECT RAISE(ABORT,'injected fault'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            jobs.finish(self.db, work, insufficient('risk', work['snapshot']))
        self.assertEqual('running', self.latest(run)['status'])
        self.assertEqual('running', self.db.execute('SELECT state FROM backend_jobs').fetchone()[0])
        self.assertEqual('running', self.db.execute('SELECT outcome FROM backend_job_attempts').fetchone()[0])
        self.db.execute('DROP TRIGGER injected_finish_fault')
        self.assertTrue(jobs.finish(self.db, work, insufficient('risk', work['snapshot'])))
        self.assertEqual('insufficient_data', self.latest(run)['status'])
        self.assertEqual(1, self.db.execute("SELECT count(*) FROM analysis_result_versions WHERE status='insufficient_data'").fetchone()[0])

    def test_disabled_doctor_during_execution_cannot_receive_output(self):
        self.enable()
        run = self.create()
        work = jobs.claim(self.db)
        self.db.execute("UPDATE users SET disabled=1 WHERE id='doc-a'")
        jobs.finish(self.db, work, insufficient('risk', work['snapshot']))
        self.assertEqual('stale', self.latest(run)['status'])
        self.assertIsNone(self.latest(run)['result'])
        with self.assertRaises(analyses.AnalysisError):
            analyses.read(self.db, self.user, 'D01', run['run_id'])


if __name__ == '__main__':
    unittest.main()
