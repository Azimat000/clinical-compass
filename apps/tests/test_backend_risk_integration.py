"""BE08 queue/publication/HTTP on genuine SQLite; candidate fixtures are not quality metrics."""
from copy import deepcopy
import json
import secrets
import sqlite3
import unittest
from unittest.mock import patch

from apps.compass import backend_analyses as analyses, backend_jobs as jobs
from apps.compass import backend_risk_context as context, backend_risk_episodes as episodes
from apps.compass import backend_risk_rules as rules, backend_sources
from apps.compass.db import now
from apps.tests import test_access, test_backend_contracts, test_backend_snapshot, test_backend_risk_context


class RiskIntegrationTests(unittest.TestCase):
    setUp = test_backend_contracts.BackendContractTests.setUp
    tearDown = test_access.AccessTests.tearDown
    post = test_access.AccessTests.post
    offer = test_access.AccessTests.offer
    body = test_backend_contracts.BackendContractTests.body
    diary = test_backend_snapshot.BackendSnapshotTests.diary
    positive = test_backend_risk_context.RiskContextTests.positive

    def enable(self):
        self.db.execute('UPDATE backend_job_settings SET enabled=1,generation_version=?', (context.EXECUTION_VERSION,))

    def create(self):
        return analyses.create(self.db, self.user, 'D01', self.body())

    def result(self, work, error=None, empty=False):
        snapshot = work['snapshot']
        u = next(u for u in context.prepare_snapshot(snapshot) if u['code'] == 'summary')
        model = test_backend_risk_context.Model({'candidates': [] if empty else [
            test_backend_risk_context.candidate(u['unit_id'], u['text'])]}, error)
        return context.execute('risk', snapshot, model)

    def test_atomic_publication_positive_rule_and_model_projection_with_http_details(self):
        self.enable(); self.positive(); self.diary(summary='Вымышленное опасение.')
        run = self.create(); work = jobs.claim(self.db)
        self.assertTrue(jobs.finish(self.db, work, self.result(work)))
        value = analyses.read(self.db, self.user, 'D01', run['run_id'])
        self.assertEqual('ready', value['status'])
        self.assertEqual('potential_risk', value['result']['output']['assessment'])
        self.assertEqual('partial', value['risk_context']['status'])
        self.assertEqual('not_established', value['risk_context']['assessment'])
        self.assertIsNone(value['model']); self.assertEqual(1, len(value['risk_context']['candidate_ids']))
        self.assertEqual({'rule','model_candidate'}, {r['origin'] for r in episodes.read(self.db, self.user, 'D01')})
        path = self.url + '/' + run['run_id'] + '/risk-context'
        response = self.clients['doc-a'].get(path)
        self.assertEqual(200, response.status_code); self.assertEqual('no-store', response.headers['Cache-Control'])
        report = response.json['report']
        self.assertEqual('model_suspicion_unreviewed', report['model_candidates'][0]['interpretation'])
        self.assertEqual(200, self.clients['doc-a'].head(path).status_code)
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM critical_events').fetchone()[0])

    def test_real_adapter_missing_credentials_keeps_rule_and_no_safe_claim(self):
        self.enable(); self.positive(); self.diary()
        run = self.create()
        with patch.dict('os.environ', {}, clear=True):
            # Genuine default executor/adapter, no replaced transport or generator.
            self.assertTrue(jobs.process_one(self.db, lane='risk'))
        value = analyses.read(self.db, self.user, 'D01', run['run_id'])
        self.assertEqual('ready', value['status'])
        self.assertEqual('potential_risk', value['result']['output']['assessment'])
        self.assertEqual(['missing_credentials'], value['risk_context']['error_codes'])
        self.assertEqual('not_evaluated', value['risk_context']['model_evaluation'])
        self.assertFalse(value['risk_context']['clinical_ready'])

    def test_insufficient_rules_can_still_retain_unreviewed_candidates_and_missing_data(self):
        self.enable(); self.diary(); run = self.create(); work = jobs.claim(self.db)
        jobs.finish(self.db, work, self.result(work))
        value = analyses.read(self.db, self.user, 'D01', run['run_id'])
        self.assertEqual('insufficient_data', value['status']); self.assertIsNone(value['result'])
        self.assertEqual(1, len(value['risk_context']['candidate_ids']))
        self.assertEqual('partial', value['risk_context']['status'])
        self.assertTrue(value['risk_context']['missing_categories'])

    def test_adapter_initialization_failure_preserves_rule_without_provider_call(self):
        self.enable();self.positive();self.diary();run=self.create()
        with patch('apps.compass.backend_model.Budget',side_effect=OSError('SECRET')):
            self.assertTrue(jobs.process_one(self.db,lane='risk'))
        value=analyses.read(self.db,self.user,'D01',run['run_id'])
        self.assertEqual('potential_risk',value['result']['output']['assessment'])
        self.assertEqual(['model_initialization_error'],value['risk_context']['error_codes'])

    def test_model_failures_empty_or_unexpected_exception_never_suppress_positive_rule(self):
        self.enable(); self.positive(); self.diary()
        for failure in ('timeout','transport_error','budget_exceeded','context_limit','cancelled',None):
            run = self.create(); work = jobs.claim(self.db)
            jobs.finish(self.db, work, self.result(work, error=failure, empty=failure is None))
            value = analyses.read(self.db, self.user, 'D01', run['run_id'])
            self.assertEqual('potential_risk', value['result']['output']['assessment'])
            self.assertEqual('not_established', value['risk_context']['assessment'])
        run = self.create(); work = jobs.claim(self.db)
        model = test_backend_risk_context.Model()
        with patch.object(model, 'generate', side_effect=RuntimeError('SECRET')):
            outcome = context.execute('risk', work['snapshot'], model)
        jobs.finish(self.db, work, outcome)
        self.assertEqual(['model_internal_error'], analyses._latest(self.db, run['run_id'])['risk_context']['error_codes'])

    def test_snapshot_role_source_version_and_cancellation_fence_all_episode_writes(self):
        self.enable(); self.positive(); self.diary()
        for kind in ('data', 'source', 'cancel', 'lease', 'version', 'relationship'):
            if kind == 'relationship':
                # Last mutation revokes access to all prior runs.
                pass
            run = self.create(); work = jobs.claim(self.db); result = self.result(work)
            before = self.db.execute('SELECT count(*) FROM backend_risk_episode_evaluations').fetchone()[0]
            if kind == 'data': self.diary(summary='Новый факт')
            if kind == 'source':
                manager = patch.object(backend_sources, 'capture', side_effect=backend_sources.SourceError(['unavailable']))
                manager.start()
            if kind == 'cancel': jobs.cancel(self.db, self.user, 'D01', run['run_id'])
            if kind == 'lease': self.db.execute("UPDATE backend_jobs SET lease_until='2000' WHERE run_id=?", (run['run_id'],))
            if kind == 'version':
                manager = patch.object(context, 'PROMPT_SHA256', 'changed'); manager.start()
            if kind == 'relationship': self.db.execute('UPDATE care_relationships SET ends_at=?', (now(),))
            try: jobs.finish(self.db, work, result)
            finally:
                if kind in ('source','version'): manager.stop()
            self.assertEqual(before, self.db.execute('SELECT count(*) FROM backend_risk_episode_evaluations').fetchone()[0], kind)

    def test_publication_failure_rolls_back_analysis_and_episodes_together(self):
        self.enable(); self.positive(); self.diary(); run = self.create(); work = jobs.claim(self.db)
        outcome = self.result(work)
        with patch.object(analyses, 'advance_in_job', side_effect=RuntimeError('crash')):
            jobs.finish(self.db, work, outcome)
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM backend_risk_episode_evaluations').fetchone()[0])
        self.assertEqual([], episodes.read(self.db, self.user, 'D01'))
        self.assertEqual('running', analyses._latest(self.db, run['run_id'])['status'])
        self.db.execute("UPDATE backend_jobs SET available_at='2000'")
        work = jobs.claim(self.db); self.assertTrue(jobs.finish(self.db, work, outcome))
        self.assertEqual('ready', analyses._latest(self.db, run['run_id'])['status'])

    def test_episode_result_and_job_terminal_update_rollback_on_database_failure(self):
        self.enable(); self.positive(); self.diary(); run = self.create(); work = jobs.claim(self.db)
        self.db.execute("CREATE TRIGGER inject_fault BEFORE UPDATE ON backend_jobs WHEN new.state='done' BEGIN SELECT RAISE(ABORT,'fault'); END")
        with self.assertRaises(sqlite3.IntegrityError): jobs.finish(self.db, work, self.result(work))
        self.assertEqual('running', analyses._latest(self.db, run['run_id'])['status'])
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM backend_risk_episode_evaluations').fetchone()[0])

    def test_http_live_rights_and_stale_details_are_explicit(self):
        self.enable(); self.diary(); run = self.create(); work = jobs.claim(self.db)
        jobs.finish(self.db, work, self.result(work))
        path = self.url + '/' + run['run_id'] + '/risk-context'
        for uid, expected in [('pat-a',403),('pat-b',403),('doc-b',404)]:
            self.assertEqual(expected, self.clients[uid].get(path).status_code)
        self.assertEqual(401, self.app.test_client().get(path).status_code)
        self.assertEqual(400, self.clients['doc-a'].get(path+'?anything=1').status_code)
        self.diary(summary='Данные обновлены')
        self.assertEqual('stale', self.clients['doc-a'].get(path).json['analysis_status'])
        self.db.execute('UPDATE care_relationships SET ends_at=?', (now(),))
        self.assertEqual(404, self.clients['doc-a'].get(path).status_code)

    def test_after_close_new_observation_new_episode_repeats_and_denials_keep_history(self):
        self.enable(); self.diary()
        def execute(empty=False):
            run=self.create(); work=jobs.claim(self.db); jobs.finish(self.db, work, self.result(work, empty=empty)); return run
        execute(); original = episodes.read(self.db, self.user, 'D01')[0]
        episodes.close(self.db, self.user, 'D01', original['id'], 1, 'Синтетическое рассмотрение', secrets.token_hex(16))
        execute(); self.assertEqual(1, len(episodes.read(self.db, self.user, 'D01')))
        self.diary(summary='Новая вымышленная жалоба.', observed_on='2026-10-26')
        # Include all text fields; a newly recorded field really is a new basis.
        run=self.create();work=jobs.claim(self.db)
        units=[u for u in context.prepare_snapshot(work['snapshot']) if u['code']=='summary']
        model=test_backend_risk_context.Model({'candidates':[test_backend_risk_context.candidate(u['unit_id'],u['text']) for u in units]})
        jobs.finish(self.db,work,context.execute('risk',work['snapshot'],model))
        self.assertEqual(2,len(episodes.read(self.db,self.user,'D01')))
        before=episodes.read(self.db,self.user,'D01')
        self.diary(summary='Отрицаю жалобу.');execute(empty=True)
        self.assertEqual(before,episodes.read(self.db,self.user,'D01'))


if __name__=='__main__': unittest.main()
