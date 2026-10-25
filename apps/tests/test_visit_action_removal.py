"""S50: retiring a form field must not erase earlier physician notes."""
import secrets
import unittest
from apps.compass import first_visits
import test_first_visits as base


class VisitActionRemovalTests(unittest.TestCase):
    def setUp(self):
        self.case = base.FirstVisitTests('test_no_diagnosis_draft_retry_restart_revision_complete_without_action')
        self.case.setUp()
        self.addCleanup(self.case.tearDown)
        self.client = self.case.clients['doc-a']
        self.db = self.case.db

    def assert_no_action(self, html):
        for text in ('name="action_draft"', 'Проект действия', 'href="#v-action"', 'id="h-action"', '<section class="block" id="v-action"'):
            self.assertNotIn(text, html)
        for text in ('value="draft"', 'value="completed"', 'Да, завершить запись', 'Короткая оценка пока недоступна'):
            self.assertIn(text, html)

    def test_new_draft_error_and_empty_history_have_no_action_block(self):
        self.assert_no_action(self.client.get('/patients/FV01/first-visits').text)
        result = self.case.post(self.case.values())
        self.assertEqual(303, result.status_code)
        self.assert_no_action(self.client.get(result.location).text)
        failed = self.case.post(self.case.values(complaints_status='known', complaints_text='Сохранить жалобу'))
        self.assertEqual(400, failed.status_code)
        self.assert_no_action(failed.text)
        self.assertIn('Сохранить жалобу', failed.text)
        self.assertNotIn('Проект действия', self.client.get('/demo/FV01').text)
        self.assertEqual('', self.case.rows()[0]['payload']['action_draft'])

    def test_old_note_survives_visit_and_document_saves_retries_and_completion(self):
        self.assertEqual(303, self.case.post(self.case.values(action_draft='Прежняя заметка <b>врача</b>',
            documented_facts='Сведения из документа', document_basis='Источник А')).status_code)
        old = self.case.rows()[0]
        ordinary = self.case.values(base_revision='1')
        self.assertEqual(303, self.case.post(ordinary, old['visit_id']).status_code)
        first_visits.save_documents(self.db, self.case.doctor, 'FV01', old['visit_id'], {
            'request_key': secrets.token_hex(16), 'base_revision': '2',
            'documented_facts': 'Уточнённый документ', 'document_basis': 'Источник Б'})
        self.assertEqual(303, self.case.post(ordinary, old['visit_id']).status_code)
        self.assertEqual(3, len(self.case.rows()))
        complete = self.case.values(base_revision='3', state='completed')
        result = self.case.post(complete, old['visit_id'])
        self.assertEqual(303, result.status_code)
        self.assertEqual(303, self.case.post(complete, old['visit_id']).status_code)
        rows = self.case.rows()
        self.assertEqual(4, len(rows))
        self.assertTrue(all(v['payload']['action_draft']=='Прежняя заметка <b>врача</b>' for v in rows))
        self.assertEqual(old['payload'], rows[-1]['payload'])
        self.assertEqual('Уточнённый документ', rows[0]['payload']['documented_facts'])
        self.assert_no_action(self.client.get('/patients/FV01/first-visits').text)
        card = self.client.get('/demo/FV01').text
        self.assertIn('Прежняя заметка &lt;b&gt;врача&lt;/b&gt;', card)
        self.assertNotIn('Прежняя заметка <b>врача</b>', card)
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])
        self.assertEqual([], self.db.execute('PRAGMA foreign_key_check').fetchall())
