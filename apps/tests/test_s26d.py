"""S26D: negotiated receipts and retries use the existing authenticated transaction."""
import secrets
import unittest
import re
from concurrent.futures import ThreadPoolExecutor
from apps.compass import records
from apps.compass.db import connect
import test_s26c
import test_access


class PatientSendTests(unittest.TestCase):
    setUp = test_s26c.PatientWorkspaceTests.setUp
    tearDown = test_s26c.PatientWorkspaceTests.tearDown
    link = test_s26c.PatientWorkspaceTests.link
    offer = test_s26c.PatientWorkspaceTests.offer
    post = test_s26c.PatientWorkspaceTests.post
    endpoint = '/patients/D01/self-reports'

    def values(self, **kw):
        return {'request_key': secrets.token_hex(16), 'observed_on': records.today().isoformat(),
                'summary': 'Синтетика S26D', **kw}

    def send(self, values, uid='pat-a'):
        client = self.clients[uid]
        return client.post(self.endpoint, data={'csrf': test_access.csrf(client), **values},
                           headers={'Accept': 'application/json'})

    def counts(self):
        return {table: self.db.execute('SELECT count(*) FROM '+table).fetchone()[0]
                for table in ('clinical_entries','self_reports','observations','adverse_events',
                              'routine_notifications','outbox_events','audit_entries')}

    def test_lost_receipt_retry_has_same_location_and_no_side_effects(self):
        values = self.values(adverse_events_status='known', adverse_events_text='Синтетическая реакция')
        first = self.send(values)
        self.assertEqual(200, first.status_code)
        self.assertRegex(first.json['location'], r'^/demo/D01/diary#entry-[0-9a-f]{32}$')
        state = self.counts()
        for _ in range(3):
            retry = self.send(values)
            self.assertEqual(first.json, retry.json)
            self.assertEqual(state, self.counts())
        receipt = self.clients['pat-a'].get(first.json['location'].split('#')[0]).text
        self.assertIn('Сохранено на сервере', receipt)

    def test_concurrent_repeat_commits_exactly_one_entry_and_notification(self):
        values = self.values()
        def save():
            db = connect(self.path)
            try: return records.save(db, {'id':'pat-a','role':'patient'}, 'D01', 'self_report', values)
            finally: db.close()
        before = self.counts()
        with ThreadPoolExecutor(max_workers=2) as pool: ids = list(pool.map(lambda _: save(), range(2)))
        self.assertEqual(ids[0], ids[1])
        after = self.counts()
        for table in ('clinical_entries','self_reports','routine_notifications','outbox_events','audit_entries'):
            self.assertEqual(1, after[table]-before[table], table)

    def test_changed_retry_returns_conflict_and_preserves_original(self):
        values = self.values()
        first = self.send(values); state = self.counts()
        changed = self.send({**values, 'summary':'Другой текст'})
        self.assertEqual(409, changed.status_code)
        self.assertIn('другим содержимым', changed.json['error'])
        self.assertEqual(state, self.counts())
        self.assertEqual(first.json, self.send(values).json)

    def test_validation_failure_is_json_and_nothing_is_written(self):
        before = self.counts()
        response = self.send(self.values(adverse_events_status='denied', adverse_events_text='Конфликт'))
        self.assertEqual(400, response.status_code)
        self.assertIn('error', response.json)
        self.assertEqual(before, self.counts())

    def test_csrf_and_roles_still_reject_json_sends(self):
        before = self.counts()
        r = self.clients['pat-a'].post(self.endpoint, data=self.values(), headers={'Accept':'application/json'})
        self.assertEqual(403, r.status_code)
        self.assertEqual(403, self.send(self.values(), 'doc-a').status_code)
        self.assertEqual(404, self.send(self.values(), 'pat-b').status_code)
        self.assertEqual(before, self.counts())

    def test_native_form_post_keeps_redirect_and_error_values(self):
        values = self.values()
        response = self.post('pat-a', self.endpoint, values)
        self.assertEqual(303, response.status_code)
        self.assertRegex(response.location, r'#entry-[0-9a-f]{32}$')
        error = self.post('pat-a', self.endpoint, self.values(complaints_status='known', complaints_text=''))
        self.assertEqual(400, error.status_code)
        self.assertIn('Синтетика S26D', error.text)
        page = self.clients['pat-a'].get('/demo/D01').text
        self.assertEqual(1, len(re.findall(r'button button--primary button--action', page)))
        self.assertLess(page.index('button--action'), page.index('class="p-foot"'))
        self.assertIn('data-report-form', self.clients['pat-a'].get('/demo/D01/report').text)
