"""Internal BE08B01 persistence on real SQLite; model fixtures are not quality data."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import secrets
import sqlite3
import unittest
from unittest.mock import patch

from apps.compass import backend_analyses as analyses, backend_risk_episodes as episodes
from apps.compass import backend_risk_context as context, backend_risk_rules as rules, records
from apps.compass.db import connect, migrate, now, transaction
from apps.tests import test_access, test_backend_contracts, test_backend_snapshot, test_backend_risk_context


class RiskEpisodeTests(unittest.TestCase):
    setUp = test_backend_contracts.BackendContractTests.setUp
    tearDown = test_access.AccessTests.tearDown
    post = test_access.AccessTests.post
    offer = test_access.AccessTests.offer
    body = test_backend_contracts.BackendContractTests.body
    diary = test_backend_snapshot.BackendSnapshotTests.diary
    visit = test_backend_snapshot.BackendSnapshotTests.visit
    questionnaire = test_backend_snapshot.BackendSnapshotTests.questionnaire
    positive = test_backend_risk_context.RiskContextTests.positive

    def prepare(self, topics=('safety_concern',), error=None, operation='risk'):
        run = analyses.create(self.db, self.user, 'D01', self.body(operation))
        run = analyses.advance(self.db, self.user, 'D01', run['run_id'], run['revision'], 'running')
        raw = self.db.execute('SELECT payload_json FROM analysis_input_snapshots WHERE id=?', (run['snapshot_id'],)).fetchone()[0]
        snapshot = json.loads(raw)
        units = context.prepare_snapshot(snapshot)
        proposals = [test_backend_risk_context.candidate(u['unit_id'], u['text'], topic)
                     for topic in topics for u in units if u['code'] == 'summary' and u['text'].startswith('Сигнал')]
        report = context.analyze_snapshot(snapshot, test_backend_risk_context.Model({'candidates': proposals}, error), synthetic=True)
        return run, report

    def observe(self, topics=('safety_concern',), error=None):
        run, report = self.prepare(topics, error)
        return run, report, episodes.observe(self.db, self.user, 'D01', run['run_id'], report)

    def all(self):
        return episodes.read(self.db, self.user, 'D01')

    def close(self, episode, reason='Рассмотрено врачом в синтетическом примере.', key=None):
        return episodes.close(self.db, self.user, 'D01', episode['id'], episode['revision'], reason, key or secrets.token_hex(16))

    def test_separate_rule_model_and_exact_four_source_evidence(self):
        self.visit(); self.questionnaire(missing=True); self.diary(summary='Сигнал: вымышленная жалоба.')
        self.positive()
        before = test_backend_contracts.table_rows(self.db)
        run, report, value = self.observe()
        rows = self.all()
        self.assertEqual({'rule', 'model_candidate'}, {r['origin'] for r in rows})
        self.assertEqual(2, len(rows)); self.assertFalse(value['clinical_ready'])
        self.assertEqual('not_established', value['assessment'])
        self.assertEqual([], value['missing_categories'])
        model = next(r for r in rows if r['origin'] == 'model_candidate')
        self.assertEqual(report['model_candidates'][0], model['history'][0]['payload']['finding'])
        quote = model['history'][0]['payload']['finding']['evidence'][0]
        self.assertEqual(quote['quote'], quote['text'][quote['start']:quote['end']])
        self.assertEqual(run['snapshot_id'], model['history'][0]['payload']['snapshot_id'])
        after = test_backend_contracts.table_rows(self.db)
        permitted = {'analysis_runs','analysis_input_snapshots','analysis_result_versions','audit_entries',
                     'backend_risk_episodes','backend_risk_episode_versions','backend_risk_episode_evidence','backend_risk_episode_evaluations'}
        for table in before:
            if table not in permitted:
                self.assertEqual(before[table], after[table], table)
        self.assertEqual('running', analyses.read(self.db, self.user, 'D01', run['run_id'])['status'])
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])

    def test_same_run_replay_and_new_run_with_same_evidence_do_not_duplicate(self):
        self.diary(summary='Сигнал: повтор.')
        run, report, value = self.observe()
        self.assertEqual(value, episodes.observe(self.db, self.user, 'D01', run['run_id'], report))
        _, _, repeated = self.observe()
        self.assertEqual([], repeated['changed_episodes'])
        self.assertEqual(1, len(self.all())); self.assertEqual(1, self.all()[0]['revision'])
        bad = deepcopy(report); bad['model_candidates'] = []
        with self.assertRaisesRegex(analyses.AnalysisError, 'другим ответом'):
            episodes.observe(self.db, self.user, 'D01', run['run_id'], bad)

    def test_new_evidence_updates_open_episode_and_retains_older_observation(self):
        self.diary(summary='Сигнал: сначала плохо.', observed_on='2026-10-20')
        self.observe(('reported_change',)); first = self.all()[0]
        self.diary(summary='Сигнал: стало ещё хуже.', observed_on='2026-10-22')
        self.observe(('reported_change',)); updated = self.all()[0]
        self.assertEqual(first['id'], updated['id']); self.assertEqual(2, updated['revision'])
        self.assertEqual(first['history'][0], updated['history'][0])
        self.assertEqual('new_evidence', updated['history'][1]['reason'])
        self.assertEqual(2, self.db.execute('SELECT count(*) FROM backend_risk_episode_evidence').fetchone()[0])

    def test_denial_empty_success_failure_and_missing_observations_do_not_close(self):
        self.diary(summary='Сигнал: вымышленное опасение.'); self.positive(); self.observe()
        original = self.all()
        self.diary(summary='Сегодня явно отрицаю вымышленное опасение.', observed_on='2026-10-25')
        for error in (None, 'timeout', 'budget_exceeded', 'context_limit', 'authentication_failed', 'cancelled'):
            _, report, saved = self.observe((), error)
            self.assertEqual('partial', saved['status'])
            self.assertEqual('potential_risk', saved['structured']['result']['output']['assessment'])
            self.assertEqual('not_established', saved['assessment'])
            self.assertEqual(original, self.all())
        # Six additional evaluations retain missing-source/error information.
        self.assertEqual(7, self.db.execute('SELECT count(*) FROM backend_risk_episode_evaluations').fetchone()[0])

    def test_close_requires_reason_version_and_exact_replay(self):
        self.diary(summary='Сигнал: закрытие.'); self.observe(); row = self.all()[0]
        key = secrets.token_hex(16)
        for rev, reason, badkey in [(True, 'Причина', key), (1, ' ', key), (1, 'Причина', 'short')]:
            with self.assertRaises(analyses.AnalysisError): episodes.close(self.db, self.user, 'D01', row['id'], rev, reason, badkey)
        closed = self.close(row, key=key)
        self.assertEqual('closed', closed['state']); self.assertEqual(2, closed['revision'])
        self.assertEqual(closed, self.close(row, key=key))
        with self.assertRaises(analyses.AnalysisError): self.close(row, reason='Другая причина', key=key)
        with self.assertRaises(analyses.AnalysisError): self.close(row)
        self.assertFalse(closed['clinical_ready']); self.assertEqual('not_established', closed['assessment'])

    def test_after_close_old_evidence_cannot_reopen_new_evidence_starts_new_episode(self):
        self.diary(summary='Сигнал: прежний.'); self.observe(); original = self.all()[0]
        closed = self.close(original)
        self.observe(); self.assertEqual([closed], self.all())
        # Unrelated new record changes snapshot but not the signal evidence.
        self.diary(summary='Обычная запись без нового опасения.', observed_on='2026-10-25')
        self.observe(); self.assertEqual([closed], self.all())
        self.diary(summary='Сигнал: новый после закрытия.', observed_on='2026-10-26')
        self.observe(); rows = self.all()
        self.assertEqual(2, len(rows))
        self.assertEqual(closed, next(r for r in rows if r['id'] == original['id']))
        fresh = next(r for r in rows if r['id'] != original['id'])
        self.assertEqual('open', fresh['state']); self.assertEqual(1, fresh['revision'])
        count = self.db.execute('SELECT count(*) FROM backend_risk_episode_evidence WHERE episode_id=?', (fresh['id'],)).fetchone()[0]
        self.assertEqual(1, count)

    def test_stale_close_after_new_observation_is_rejected(self):
        self.diary(summary='Сигнал: исходный.'); self.observe(); old = self.all()[0]
        self.diary(summary='Сигнал: новый.'); self.observe()
        with self.assertRaises(analyses.AnalysisError): self.close(old)
        self.assertEqual('open', self.all()[0]['state'])

    def test_changed_quote_same_field_and_multiple_spans_never_reopen(self):
        self.diary(summary='Сигнал: вымышленное опасение. Дополнение в том же поле.')
        self.observe(); closed = self.close(self.all()[0])
        run, report = self.prepare()
        snapshot = json.loads(self.db.execute('SELECT payload_json FROM analysis_input_snapshots WHERE id=?',
                                              (run['snapshot_id'],)).fetchone()[0])
        units = context.prepare_snapshot(snapshot)
        unit = next(u for u in units if u['code'] == 'summary')
        report['model_candidates'] = context.verify({'candidates': [{'topic':'safety_concern', 'evidence':[
            {'unit_id':unit['unit_id'],'quote':'вымышленное опасение'},
            {'unit_id':unit['unit_id'],'quote':'Дополнение в том же поле.'}]}]}, units, context.snapshots.digest(snapshot))
        saved = episodes.observe(self.db, self.user, 'D01', run['run_id'], report)
        self.assertEqual([], saved['changed_episodes']); self.assertEqual([closed], self.all())
        self.assertEqual(2, len(saved['model_candidates'][0]['evidence']))
        # Two spans on a new field create just one evidence identity atomically.
        self.diary(summary='Сигнал: новое основание. Дополнение в новом поле.')
        run, report = self.prepare()
        snapshot = json.loads(self.db.execute('SELECT payload_json FROM analysis_input_snapshots WHERE id=?',
                                              (run['snapshot_id'],)).fetchone()[0])
        units = context.prepare_snapshot(snapshot)
        unit = next(u for u in units if 'новое основание' in u['text'])
        report['model_candidates'] = context.verify({'candidates':[{'topic':'safety_concern','evidence':[
            {'unit_id':unit['unit_id'],'quote':'новое основание'},
            {'unit_id':unit['unit_id'],'quote':'Дополнение в новом поле.'}]}]}, units, context.snapshots.digest(snapshot))
        saved = episodes.observe(self.db, self.user, 'D01', run['run_id'], report)
        self.assertEqual(1, len(saved['changed_episodes'])); self.assertEqual(2, len(self.all()))

    def test_rule_denial_does_not_close_and_unrelated_snapshot_change_does_not_reopen(self):
        self.positive(); self.observe(())
        original = self.all()[0]; closed = self.close(original)
        self.diary(summary='Новая запись без изменения структурированного фактора.')
        self.observe(()); self.assertEqual([closed], self.all())
        old_context = self.db.execute('SELECT id,payload_json FROM clinical_contexts').fetchone()
        stored = json.loads(old_context['payload_json'])
        payload = {k: stored[k] for k in ('condition', 'severity', 'basis', 'supersedes_id', *rules.FLAGS)}
        payload.update(supersedes_id=old_context['id'], suicidal_plan='denied')
        rules.record_context(self.db, self.user, 'D01', records.today().isoformat(), payload, secrets.token_hex(16))
        self.observe(()); self.assertEqual([closed], self.all())
        new_context = self.db.execute('SELECT id FROM clinical_contexts WHERE id!=?', (old_context['id'],)).fetchone()[0]
        payload.update(supersedes_id=new_context, suicidal_plan='present')
        rules.record_context(self.db, self.user, 'D01', records.today().isoformat(), payload, secrets.token_hex(16))
        self.observe(()); self.assertEqual(2, len(self.all()))
        active = next(r for r in self.all() if r['state'] == 'open')
        # Explicit denial in a later clinician revision also cannot auto-close.
        latest_context = self.db.execute('SELECT id FROM clinical_contexts WHERE id NOT IN (?,?)',
                                          (old_context['id'], new_context)).fetchone()[0]
        payload.update(supersedes_id=latest_context, suicidal_plan='denied')
        rules.record_context(self.db, self.user, 'D01', records.today().isoformat(), payload, secrets.token_hex(16))
        self.observe(())
        self.assertEqual(active, episodes.read(self.db, self.user, 'D01', active['id']))

    def test_persistence_after_connection_restart_and_sql_scope_guards(self):
        self.diary(summary='Сигнал: перезапуск.'); self.observe(); row = self.all()[0]
        new_db = connect(self.path)
        try:
            self.assertEqual(row, episodes.read(new_db, self.user, 'D01', row['id']))
        finally:
            new_db.close()
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute('INSERT INTO backend_risk_episodes VALUES(?,?,?,?,?,?)',
                            ('duplicate', 'D01', row['relationship_id'], row['origin'], row['topic'], now()))
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute('INSERT INTO backend_risk_episode_versions VALUES(?,?,?,?,?,?,?,?,?)',
                            (row['id'], 2, 'closed', 'Подмена врача', 'doc-b', None, '{}', secrets.token_hex(16), now()))
        self.close(row)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute('INSERT INTO backend_risk_episode_versions VALUES(?,?,?,?,?,?,?,?,?)',
                            (row['id'], 3, 'open', 'Повтор', self.user['id'], row['history'][0]['run_id'], '{}', None, now()))

    def test_forged_report_or_other_operation_is_atomic_rejection(self):
        self.diary(summary='Сигнал: основание.'); self.positive()
        run, report = self.prepare()
        baseline = test_backend_contracts.table_rows(self.db)
        for kind in ('quote','span','metadata_type','rule','snapshot','ready','denial','missing','version','error'):
            bad = deepcopy(report)
            if kind == 'quote': bad['model_candidates'][0]['evidence'][0]['quote'] = 'Выдумка'
            if kind == 'span': bad['model_candidates'][0]['evidence'][0]['start'] += 1
            if kind == 'metadata_type': bad['model_candidates'][0]['evidence'][0]['metadata']['current_revision'] = 1
            if kind == 'rule': bad['structured']['result']['output']['patterns'] = []
            if kind == 'snapshot': bad['snapshot_sha256'] = 'fake'
            if kind == 'ready': bad['status'] = 'ready'
            if kind == 'denial': bad['assessment'] = 'no_risk'
            if kind == 'missing': bad['missing_categories'] = []
            if kind == 'version': bad['prompt_sha256'] = 'old'
            if kind == 'error': bad['errors'] = [{'code': 'api key secret'}]
            with self.assertRaises(analyses.AnalysisError, msg=kind): episodes.observe(self.db, self.user, 'D01', run['run_id'], bad)
            self.assertEqual(baseline, test_backend_contracts.table_rows(self.db))
        wrong, wrong_report = self.prepare(operation='diagnosis')
        with self.assertRaises(analyses.AnalysisError): episodes.observe(self.db, self.user, 'D01', wrong['run_id'], wrong_report)

    def test_freshness_before_writing_and_no_network_or_executor_connection(self):
        self.diary(summary='Сигнал: исходный.'); run, report = self.prepare()
        self.diary(summary='Изменившаяся история.')
        with self.assertRaises(analyses.AnalysisError): episodes.observe(self.db, self.user, 'D01', run['run_id'], report)
        self.assertEqual([], self.all())
        from apps.compass import backend_jobs
        with patch.object(episodes, 'observe', side_effect=AssertionError('not integrated')):
            snapshot = json.loads(analyses.capture(self.db, 'D01', analyses.authorize(self.db, self.user, 'D01')))
            self.assertEqual(rules.evaluate(snapshot), backend_jobs.execute('risk', snapshot))

    def test_live_access_relationship_replacement_disabled_user_and_synthetic_gate(self):
        self.diary(summary='Сигнал: доступ.'); run, report, _ = self.observe(); row = self.all()[0]
        for user in ({'id':'pat-a','role':'patient'}, {'id':'doc-b','role':'doctor'}):
            for method in ('read','close','observe'):
                with self.assertRaises(analyses.AnalysisError):
                    if method == 'read': episodes.read(self.db, user, 'D01', row['id'])
                    if method == 'close': episodes.close(self.db, user, 'D01', row['id'], 1, 'Причина', secrets.token_hex(16))
                    if method == 'observe': episodes.observe(self.db, user, 'D01', run['run_id'], report)
        self.db.execute("UPDATE users SET disabled=1 WHERE id='doc-a'")
        with self.assertRaises(analyses.AnalysisError): self.all()
        self.db.execute("UPDATE users SET disabled=0 WHERE id='doc-a'")
        # Existing schema already disallows real patients. Simulate a future or
        # malformed database solely to exercise the additional application gate.
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE patients SET synthetic=0 WHERE id='D01'")
        self.db.execute('PRAGMA ignore_check_constraints=ON')
        self.db.execute("UPDATE patients SET synthetic=0 WHERE id='D01'")
        with self.assertRaises(analyses.AnalysisError): self.all()
        with self.assertRaises(analyses.AnalysisError): episodes.observe(self.db, self.user, 'D01', run['run_id'], report)
        self.db.execute("UPDATE patients SET synthetic=1 WHERE id='D01'")
        self.db.execute('PRAGMA ignore_check_constraints=OFF')
        self.db.execute('UPDATE care_relationships SET ends_at=?', (now(),))
        self.db.execute('INSERT INTO care_relationships VALUES(?,?,?,?,NULL)', ('replacement', 'D01', 'doc-a', now()))
        self.assertEqual([], self.all())
        with self.assertRaises(analyses.AnalysisError): episodes.read(self.db, self.user, 'D01', row['id'])
        with self.assertRaises(analyses.AnalysisError): episodes.observe(self.db, self.user, 'D01', run['run_id'], report)

    def test_concurrent_observation_and_close_have_single_winner(self):
        self.diary(summary='Сигнал: параллельно.'); run, report = self.prepare()
        def save(_):
            db = connect(self.path)
            try: return episodes.observe(db, self.user, 'D01', run['run_id'], report)
            finally: db.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            outputs = list(pool.map(save, range(2)))
        self.assertEqual(outputs[0], outputs[1]); self.assertEqual(1, len(self.all()))
        row = self.all()[0]
        def close(_):
            db = connect(self.path)
            try:
                episodes.close(db, self.user, 'D01', row['id'], 1, 'Синтетическая причина', secrets.token_hex(16))
                return 'closed'
            except analyses.AnalysisError: return 'conflict'
            finally: db.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(['closed','conflict'], sorted(pool.map(close, range(2))))
        self.assertEqual(2, self.all()[0]['revision'])

    def test_savepoint_failure_rolls_back_even_when_outer_caller_catches(self):
        self.diary(summary='Сигнал: атомарность.'); self.positive(); run, report = self.prepare()
        before = test_backend_contracts.table_rows(self.db)
        with transaction(self.db):
            with patch.object(episodes.access, 'audit', side_effect=RuntimeError('crash')):
                with self.assertRaises(RuntimeError): episodes.observe(self.db, self.user, 'D01', run['run_id'], report)
            self.assertEqual(before, test_backend_contracts.table_rows(self.db))
        self.assertEqual(before, test_backend_contracts.table_rows(self.db))

    def test_migration_additive_idempotent_and_episode_tables_immutable(self):
        self.diary(summary='Сигнал: миграция.'); self.observe(); self.close(self.all()[0])
        before = test_backend_contracts.table_rows(self.db); migrate(self.db)
        self.assertEqual(before, test_backend_contracts.table_rows(self.db))
        for table in ('backend_risk_episodes','backend_risk_episode_versions','backend_risk_episode_evidence','backend_risk_episode_evaluations'):
            for command in ('UPDATE '+table+' SET '+{'backend_risk_episodes':'topic=topic',
                        'backend_risk_episode_versions':'reason=reason','backend_risk_episode_evidence':'topic=topic',
                        'backend_risk_episode_evaluations':'report_sha256=report_sha256'}[table], 'DELETE FROM '+table):
                with self.assertRaises(sqlite3.IntegrityError): self.db.execute(command)
        self.assertEqual(before, test_backend_contracts.table_rows(self.db))
        self.assertEqual('ok', self.db.execute('PRAGMA integrity_check').fetchone()[0])
        self.assertEqual([], self.db.execute('PRAGMA foreign_key_check').fetchall())


if __name__ == '__main__':
    unittest.main()
