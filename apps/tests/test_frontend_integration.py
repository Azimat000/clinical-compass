"""FE02: authenticated history discovery must not hide failures or create work."""
import json
import unittest
from apps.compass import access, backend_analyses as analyses
from apps.compass.db import now
from apps.tests import test_backend_contracts as base
from apps.tests.test_backend_contracts import table_rows


class FrontendIntegrationTests(unittest.TestCase):
    setUp = base.BackendContractTests.setUp
    tearDown = base.BackendContractTests.tearDown
    post = base.BackendContractTests.post
    offer = base.BackendContractTests.offer
    body = base.BackendContractTests.body
    request = base.BackendContractTests.request

    def get(self, suffix='', uid='doc-a'):
        return self.clients[uid].get(self.url + suffix)

    def test_empty_disabled_is_not_a_negative_assessment(self):
        value = self.get().json
        self.assertEqual([], value['items'])
        self.assertEqual(0, value['total'])
        self.assertEqual({'enabled': False, 'generation_version': None}, value['backend'])
        self.assertNotIn('result', value)
        self.assertEqual('no-store', self.get().headers['Cache-Control'])

    def test_history_newest_failure_filters_pagination_and_stale_projection(self):
        runs = [self.request(body=self.body('risk')).json for _ in range(12)]
        diagnosis = self.request(body=self.body('diagnosis')).json
        analyses.advance(self.db, self.user, 'D01', runs[-1]['run_id'], 1, 'failed',
                         errors=[{'code': 'executor_error', 'message': 'Synthetic failure.', 'retryable': False}])
        first = self.get('?operation=risk').json
        self.assertEqual(runs[-1]['run_id'], first['items'][0]['run_id'])
        self.assertEqual('failed', first['items'][0]['status'])
        self.assertIsNone(first['items'][0]['result'])
        self.assertEqual(12, first['total'])
        self.assertEqual(10, len(first['items']))
        second = self.get('?operation=risk&page=2').json
        self.assertEqual(2, len(second['items']))
        self.assertEqual(12, len({x['run_id'] for x in first['items'] + second['items']}))
        self.assertEqual(diagnosis['run_id'], self.get('?operation=diagnosis').json['items'][0]['run_id'])
        # New demographic evidence changes the snapshot; no DB revision is appended by reading.
        self.db.execute("UPDATE patients SET age_years=36 WHERE id='D01'")
        before = table_rows(self.db)
        self.assertTrue(all(x['status'] == 'stale' for x in self.get().json['items']))
        after = table_rows(self.db)
        for table in before:
            if table != 'sessions': self.assertEqual(before[table], after[table], table)

    def test_get_head_polling_never_schedules_or_writes_clinical_state(self):
        self.db.execute("UPDATE backend_job_settings SET enabled=1,generation_version='be10-diagnosis-v1'")
        self.request()
        before = table_rows(self.db)
        for _ in range(3):
            value = self.get().json
            self.assertTrue(value['backend']['enabled'])
            response = self.clients['doc-a'].head(self.url)
            self.assertEqual(200, response.status_code)
            self.assertEqual(b'', response.data)
        after = table_rows(self.db)
        for table in before:
            if table != 'sessions': self.assertEqual(before[table], after[table], table)

    def test_roles_expired_session_and_relinked_relationship(self):
        self.request()
        for uid, expected in [('pat-a', 403), ('pat-b', 403), ('doc-b', 404)]:
            self.assertEqual(expected, self.get(uid=uid).status_code)
        self.assertEqual(401, self.app.test_client().get(self.url).status_code)
        token = self.clients['doc-a'].get_cookie(access.COOKIE).value
        self.db.execute("UPDATE sessions SET expires_at='2000' WHERE token_hash=?", (access.digest(token),))
        self.assertEqual(401, self.get().status_code)
        # Restore the local test session only; replacing a relationship must hide old runs.
        self.db.execute('UPDATE sessions SET expires_at=? WHERE token_hash=?', (access.future(hours=1), access.digest(token)))
        self.db.execute('UPDATE care_relationships SET ends_at=?', (now(),))
        self.db.execute('INSERT INTO care_relationships VALUES(?,?,?,?,NULL)', ('fe02-relink', 'D01', 'doc-a', now()))
        self.assertEqual([], self.get().json['items'])

    def test_reject_ambiguous_or_unbounded_queries(self):
        for query in ['?page=0', '?page=-1', '?page=10000000', '?page=2', '?page=1&page=1',
                      '?operation=', '?operation=chat', '?operation=risk&operation=plan', '?actor_id=doc-b']:
            self.assertEqual(400, self.get(query).status_code, query)


if __name__ == '__main__': unittest.main()
