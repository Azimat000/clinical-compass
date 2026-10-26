"""BE01 contracts, real SQLite transitions, HTTP boundaries and additive migration."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import secrets
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from apps.compass import access, backend_analyses as analyses, decisions, records
from apps.compass.db import MIGRATIONS, connect, migrate, now
from apps.compass.repository import seed_demo
from apps.compass.web import create_app
from apps.tests import test_access


def table_rows(db):
    return {row['name']: sorted(json.dumps(list(r), ensure_ascii=False, default=str) for r in db.execute('SELECT * FROM "' + row['name'] + '"'))
            for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}


class BackendContractTests(unittest.TestCase):
    def setUp(self):
        test_access.AccessTests.setUp(self)
        test_access.AccessTests.link(self)
        self.user = {'id': 'doc-a', 'role': 'doctor'}
        self.db.execute("UPDATE patients SET age_status='known',age_years=35,birth_date=NULL,created_at=? WHERE id='D01'", (records.today().isoformat()+'T00:00:00+03:00',))
        self.url = '/api/v1/patients/D01/analyses'

    tearDown = test_access.AccessTests.tearDown
    post = test_access.AccessTests.post
    offer = test_access.AccessTests.offer

    def body(self, operation='risk', key=None):
        return {'contract_version': '1.0', 'operation': operation, 'request_key': key or secrets.token_hex(16)}

    def request(self, uid='doc-a', body=None, **kw):
        client = self.clients[uid]
        return client.post(self.url, json=body or self.body(), headers={'X-CSRF-Token': test_access.csrf(client)}, **kw)

    def start(self, operation='risk'):
        value = analyses.create(self.db, self.user, 'D01', self.body(operation))
        return analyses.advance(self.db, self.user, 'D01', value['run_id'], value['revision'], 'running')

    def result(self, operation='risk', diagnosis=None):
        source = self.db.execute('SELECT id FROM source_versions ORDER BY id LIMIT 1').fetchone()[0]
        finding = {'id': 'finding1', 'text': 'Синтетический вывод для проверки формата.', 'fact_ids': ['fact1'], 'source_ids': [source]}
        outputs = {'risk': {'assessment': 'potential_risk', 'patterns': [finding]},
                   'diagnosis': {'leading': finding, 'alternatives': []},
                   'plan': {'diagnosis_run_id': diagnosis or 'missing-diagnosis', 'items': [finding]}}
        return {'summary': 'Только проверка структуры, не клиническая оценка.',
                'facts': [{'id': 'fact1', 'text': 'Вымышленный факт.', 'evidence_refs': ['profile:D01']}],
                'contradictions': [], 'missing_data': ['Независимая проверка не выполнена.'], 'output': outputs[operation]}

    def ready(self, operation='risk', diagnosis=None):
        run = self.start(operation)
        # BE01 structural fixture only. BE03 source gate is exercised without
        # substitution in test_backend_sources; this does not simulate medicine.
        with patch.object(analyses.backend_sources, 'check_result'):
            return analyses.advance(self.db, self.user, 'D01', run['run_id'], run['revision'], 'ready', result=self.result(operation, diagnosis))

    def test_real_http_create_read_restart_and_idempotent_replay(self):
        body = self.body()
        response = self.request(body=body)
        self.assertEqual(202, response.status_code)
        value = response.json
        analyses.validate_analysis(value)
        self.assertEqual('queued', value['status'])
        self.assertEqual('blocked', value['release']['status'])
        self.assertIsNone(value['result'])
        self.assertEqual(value, self.clients['doc-a'].get(response.headers['Location']).json)
        self.assertEqual(value, self.request(body=body).json)
        self.assertEqual(1, self.db.execute('SELECT count(*) FROM analysis_runs').fetchone()[0])
        fresh = create_app(self.path).test_client()
        fresh.set_cookie(access.COOKIE, self.clients['doc-a'].get_cookie(access.COOKIE).value)
        self.assertEqual(value, fresh.get(response.headers['Location']).json)
        self.assertEqual('no-store', response.headers['Cache-Control'])
        self.assertEqual(409, self.request(body={**body, 'operation': 'diagnosis'}).status_code)

    def test_authentication_roles_csrf_patient_run_and_relationship_isolation(self):
        response = self.request()
        url = response.headers['Location']
        for uid, code in [('pat-a', 403), ('pat-b', 403), ('doc-b', 404)]:
            self.assertEqual(code, self.clients[uid].get(url).status_code)
            self.assertEqual(code, self.request(uid).status_code)
        self.assertEqual(401, self.app.test_client().get(url).status_code)
        self.assertEqual(401, self.app.test_client().post(self.url, json=self.body()).status_code)
        self.assertEqual(403, self.clients['doc-a'].post(self.url, json=self.body()).status_code)
        self.assertEqual(404, self.clients['doc-a'].get(url.replace('/D01/', '/D02/')).status_code)
        self.assertEqual(404, self.clients['doc-a'].get(url.rsplit('/', 1)[0] + '/foreign').status_code)
        self.db.execute('UPDATE care_relationships SET ends_at=?', (now(),))
        self.assertEqual(404, self.clients['doc-a'].get(url).status_code)
        self.db.execute('INSERT INTO care_relationships VALUES(?,?,?,?,NULL)', ('new-link', 'D01', 'doc-a', now()))
        self.assertEqual(404, self.clients['doc-a'].get(url).status_code)
        self.db.execute("UPDATE users SET disabled=1 WHERE id='doc-a'")
        with self.assertRaises(analyses.AnalysisError):
            analyses.read(self.db, self.user, 'D01', response.json['run_id'])

    def test_strict_inputs_duplicate_keys_media_limits_and_safe_json_errors(self):
        for bad in [{**self.body(), 'operation': 'chat'}, {**self.body(), 'contract_version': '2.0'},
                    {**self.body(), 'release': {'status': 'active'}}, {**self.body(), 'request_key': 123},
                    {'operation': 'risk'}, [], None]:
            client = self.clients['doc-a']
            response = client.post(self.url, data=json.dumps(bad), content_type='application/json',
                                   headers={'X-CSRF-Token': test_access.csrf(client)})
            self.assertEqual(400, response.status_code, response.text)
            analyses.validate('HttpError', response.json)
        client = self.clients['doc-a']
        headers = {'X-CSRF-Token': test_access.csrf(client)}
        for raw in ['{', '{"operation":"risk","operation":"plan"}', 'NaN', '"' + 'x'*66000 + '"']:
            response = client.post(self.url, data=raw, content_type='application/json', headers=headers)
            self.assertIn(response.status_code, (400, 413))
            analyses.validate('HttpError', response.json)
        self.assertEqual(415, client.post(self.url, data='{}', headers=headers).status_code)
        for response in [self.app.test_client().get(self.url+'/x'), self.clients['pat-a'].get(self.url+'/x'), client.get(self.url+'/x')]:
            analyses.validate('HttpError', response.json)
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM analysis_runs').fetchone()[0])

    def test_every_state_and_three_operation_outputs_validate_without_care_actions(self):
        before = {t: self.db.execute('SELECT count(*) FROM '+t).fetchone()[0]
                  for t in ['proposals', 'doctor_confirmations', 'care_actions', 'therapy_courses', 'outbox_events']}
        ready_risk = self.ready()
        diagnosis = self.ready('diagnosis')
        plan = self.ready('plan', diagnosis['run_id'])
        self.assertEqual('ready', plan['status'])
        self.assertEqual('blocked', diagnosis['release']['status'])
        for state in ['insufficient_data', 'unsupported', 'failed', 'stale']:
            run = self.start()
            value = analyses.advance(self.db, self.user, 'D01', run['run_id'], run['revision'], state,
                                     errors=[] if state == 'stale' else [{'code': state, 'message': 'Вымышленная причина.', 'retryable': state == 'failed'}],
                                     stale_reason='Изменились условия.' if state == 'stale' else None)
            self.assertEqual(state, value['status'])
            analyses.validate_analysis(value)
        negative = self.result()
        negative['output'] = {'assessment': 'no_pattern_found', 'patterns': []}
        run = self.start()
        with patch.object(analyses.backend_sources, 'check_result'):
            value = analyses.advance(self.db, self.user, 'D01', run['run_id'], run['revision'], 'ready', result=negative)
        self.assertEqual('no_pattern_found', value['result']['output']['assessment'])
        self.assertEqual(before, {t: self.db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in before})
        self.assertEqual(ready_risk['revision'], analyses.read(self.db, self.user, 'D01', ready_risk['run_id'])['revision'])

    def test_transitions_concurrency_preconditions_and_immutable_history(self):
        queued = analyses.create(self.db, self.user, 'D01', self.body())
        with self.assertRaises(analyses.AnalysisError):
            analyses.advance(self.db, self.user, 'D01', queued['run_id'], 1, 'ready', result=self.result())
        running = analyses.advance(self.db, self.user, 'D01', queued['run_id'], 1, 'running')
        for revision, state in [(1, 'failed'), (True, 'failed'), (2, 'queued')]:
            with self.assertRaises(analyses.AnalysisError):
                analyses.advance(self.db, self.user, 'D01', running['run_id'], revision, state)
        done = analyses.advance(self.db, self.user, 'D01', running['run_id'], 2, 'failed',
                                errors=[{'code': 'timeout', 'message': 'Вымышленная ошибка.', 'retryable': True}])
        with self.assertRaises(analyses.AnalysisError):
            analyses.advance(self.db, self.user, 'D01', done['run_id'], 3, 'running')
        for table in ['analysis_input_snapshots', 'analysis_runs', 'analysis_result_versions']:
            with self.assertRaises(sqlite3.IntegrityError):
                self.db.execute('DELETE FROM '+table)
            column = 'revision' if table == 'analysis_result_versions' else 'id'
            with self.assertRaises(sqlite3.IntegrityError):
                self.db.execute(f'UPDATE {table} SET {column}={column}')
        bad = deepcopy(done);bad.update(status='running', revision=4)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute('INSERT INTO analysis_result_versions VALUES(?,?,?,?,?)',
                            (bad['run_id'], 4, 'running', decisions.canonical(bad), now()))
        self.assertEqual(3, self.db.execute('SELECT count(*) FROM analysis_result_versions').fetchone()[0])

    def test_output_validation_rejects_wrong_operation_forged_links_and_empty_success(self):
        run = self.start()
        result = self.result()
        variants = [None, {**result, 'output': {'leading': result['output']['patterns'][0], 'alternatives': []}},
                    {**result, 'output': {'assessment': 'potential_risk', 'patterns': []}}]
        for path, bad_value in [('evidence_refs', ['invented:row']), ('id', 'fact1')]:
            value = deepcopy(result)
            if path == 'id':value['facts'].append(deepcopy(value['facts'][0]))
            else:value['facts'][0][path] = bad_value
            variants.append(value)
        value = deepcopy(result);value['output']['patterns'][0]['source_ids'] = ['invented-source'];variants.append(value)
        value = deepcopy(result);value['output']['patterns'][0]['fact_ids'] = ['invented-fact'];variants.append(value)
        value = deepcopy(result);value['summary'] = 'x'*601;variants.append(value)
        for value in variants:
            with self.assertRaises(analyses.AnalysisError):
                analyses.advance(self.db, self.user, 'D01', run['run_id'], 2, 'ready', result=value)
        self.assertEqual(2, analyses._latest(self.db, run['run_id'])['revision'])
        bad = deepcopy(run);bad['release']['status'] = 'active'
        with self.assertRaises(analyses.AnalysisError):analyses.validate_analysis(bad)
        with self.assertRaises(analyses.AnalysisError):
            analyses.advance(self.db, self.user, 'D01', run['run_id'], 2, 'failed', errors={})

    def test_plan_requires_matching_current_diagnosis_and_cannot_apply_itself(self):
        run = self.start('plan')
        with self.assertRaises(analyses.AnalysisError):
            analyses.advance(self.db, self.user, 'D01', run['run_id'], 2, 'ready', result=self.result('plan'))
        risk = self.ready()
        with self.assertRaises(analyses.AnalysisError):
            analyses.advance(self.db, self.user, 'D01', run['run_id'], 2, 'ready', result=self.result('plan', risk['run_id']))
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])

    def test_changed_inputs_or_sources_make_pure_read_stale_and_block_write(self):
        ready = self.ready()
        original = analyses._latest(self.db, ready['run_id'])
        self.db.execute("UPDATE source_versions SET status='superseded'")
        stale = analyses.read(self.db, self.user, 'D01', ready['run_id'])
        self.assertEqual('stale', stale['status'])
        self.assertEqual(original, analyses._latest(self.db, ready['run_id']))
        with self.assertRaises(analyses.AnalysisError):
            analyses.advance(self.db, self.user, 'D01', ready['run_id'], ready['revision'], 'stale', stale_reason='changed')
        run = analyses.create(self.db, self.user, 'D01', self.body())
        self.db.execute("UPDATE patients SET age_status='unknown',age_years=NULL WHERE id='D01'")
        self.assertEqual('stale', analyses.read(self.db, self.user, 'D01', run['run_id'])['status'])

    def test_scope_version_change_invalidates_existing_snapshot(self):
        run = self.ready()
        replacement = Path(self.tmp.name)/'changed-scope.json'
        replacement.write_bytes(analyses.SCOPE_PATH.read_bytes()+b' ')
        with patch.object(analyses, 'SCOPE_PATH', replacement):
            self.assertEqual('stale', analyses.read(self.db, self.user, 'D01', run['run_id'])['status'])
        self.assertEqual('ready', analyses._latest(self.db, run['run_id'])['status'])
        self.assertFalse(self.db.in_transaction)

    def test_age_unknown_conflicting_minor_and_adult_do_not_become_no_risk(self):
        for years, status, expected in [(None, 'unknown', 'insufficient_data'), (35, 'conflicting', 'insufficient_data'),
                                        (17, 'known', 'unsupported'), (18, 'known', 'queued'), (90, 'known', 'queued')]:
            self.db.execute('UPDATE patients SET age_years=?,age_status=? WHERE id=?', (years, status, 'D01'))
            value = self.request().json
            self.assertEqual(expected, value['status'])
            self.assertIsNone(value['result'])
            self.assertEqual('blocked', value['release']['status'])

    def test_prior_day_integer_age_still_requires_clarification_at_adult_boundary(self):
        from datetime import timedelta
        observed=(records.today()-timedelta(days=1)).isoformat()
        self.db.execute("UPDATE patients SET age_years=17,created_at=? WHERE id='D01'",(observed+'T00:00:00+03:00',))
        value=self.request().json
        self.assertEqual('insufficient_data',value['status'])
        self.assertIsNone(value['result'])

    def test_concurrent_retries_create_one_run_and_one_request_audit(self):
        body = self.body()
        def create_once(_):
            db = connect(self.path)
            try:return analyses.create(db, self.user, 'D01', body)['run_id']
            finally:db.close()
        with ThreadPoolExecutor(max_workers=4) as pool:
            ids = list(pool.map(create_once, range(8)))
        self.assertEqual(1, len(set(ids)))
        self.assertEqual(1, self.db.execute('SELECT count(*) FROM analysis_runs').fetchone()[0])
        self.assertEqual(1, self.db.execute("SELECT count(*) FROM audit_entries WHERE event='analysis.requested'").fetchone()[0])

    def test_actual_sql_failure_rolls_back_and_redacts_private_details(self):
        self.db.execute("CREATE TRIGGER synthetic_failure BEFORE INSERT ON analysis_runs BEGIN SELECT RAISE(ABORT,'private-clinical-text-do-not-expose'); END")
        response = self.request()
        self.assertEqual(503, response.status_code)
        self.assertEqual('5', response.headers['Retry-After'])
        self.assertNotIn('private-clinical-text-do-not-expose', response.text)
        analyses.validate('HttpError', response.json)
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM analysis_runs').fetchone()[0])
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM analysis_input_snapshots').fetchone()[0])

    def test_snapshot_and_output_byte_budgets_rollback_atomically(self):
        run = self.start()
        result = self.result()
        result['facts'] = [{'id': 'f'+str(i), 'text': 'я'*2000, 'evidence_refs': ['profile:D01']} for i in range(100)]
        result['output'] = {'assessment': 'no_pattern_found', 'patterns': []}
        with self.assertRaises(analyses.AnalysisError):
            analyses.advance(self.db, self.user, 'D01', run['run_id'], 2, 'ready', result=result)
        self.assertEqual(2, analyses._latest(self.db, run['run_id'])['revision'])
        self.db.execute("UPDATE encounters SET narrative=? WHERE id=(SELECT id FROM encounters WHERE patient_id='D01' LIMIT 1)", ('я'*2200000,))
        before = self.db.execute('SELECT count(*) FROM analysis_runs').fetchone()[0]
        with self.assertRaises(analyses.AnalysisError) as exc:
            analyses.create(self.db, self.user, 'D01', self.body())
        self.assertEqual('snapshot_too_large', exc.exception.code)
        self.assertEqual(before, self.db.execute('SELECT count(*) FROM analysis_runs').fetchone()[0])


class BackendSpecificationTests(unittest.TestCase):
    def test_all_documented_examples_and_matrix(self):
        root = analyses.ROOT
        examples = json.loads((root/'docs/architecture/backend-api-examples.json').read_text())
        analyses.validate('CreateAnalysis', examples['create'])
        for value in examples['responses'].values():analyses.validate_analysis(value)
        self.assertEqual(set(analyses.TRANSITIONS), {v['status'] for v in examples['responses'].values()})
        scope = json.loads(analyses.SCOPE_PATH.read_text())
        self.assertEqual(['risk', 'diagnosis', 'plan'], scope['operations'])
        self.assertEqual('blocked', scope['clinical_release'])
        self.assertEqual(3, len(scope['instruments']))
        with self.assertRaises(RuntimeError):analyses.validate_schema('x', {'unknown_keyword': True})

    def test_migration_preserves_existing_rows_schema_triggers_and_is_repeatable(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = Path(tmp)/'migrations';old.mkdir()
            for path in MIGRATIONS.glob('*.sql'):
                if path.name < '016':(old/path.name).write_bytes(path.read_bytes())
            db = connect(Path(tmp)/'copy.sqlite3')
            try:
                migrate(db, old);seed_demo(db);test_access.setup_identities(db)
                before = table_rows(db)
                previous_versions = {r[0] for r in db.execute('SELECT version FROM schema_migrations')}
                schema = dict(db.execute("SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL"))
                migrate(db)
                after = table_rows(db)
                for table, rows in before.items():
                    actual = after[table]
                    if table == 'schema_migrations':
                        actual = [r for r in actual if json.loads(r)[0] in previous_versions]
                    self.assertEqual(rows, actual, table)
                self.assertEqual({p.stem for p in MIGRATIONS.glob('*.sql')},
                                 {r[0] for r in db.execute('SELECT version FROM schema_migrations')})
                current_schema = dict(db.execute("SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL"))
                self.assertTrue(all(current_schema[k] == v for k,v in schema.items()))
                migrated = table_rows(db);migrate(db)
                self.assertEqual(migrated, table_rows(db))
                self.assertEqual('ok', db.execute('PRAGMA integrity_check').fetchone()[0])
                self.assertEqual([], db.execute('PRAGMA foreign_key_check').fetchall())
            finally:db.close()
