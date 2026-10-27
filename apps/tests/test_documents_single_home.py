"""S49 → UI11: document notes are no longer a site feature, but notes saved earlier stay intact."""
import secrets
import unittest
from test_access import csrf
import test_first_visits as base


class DocumentsSingleHomeTests(unittest.TestCase):
    def setUp(self):
        self.case = base.FirstVisitTests('test_sources_dates_unknown_denial_conflict_and_summary_sections')
        self.case.setUp()
        self.addCleanup(self.case.tearDown)
        self.db = self.case.db
        self.client = self.case.clients['doc-a']

    def rows(self):
        return self.case.rows()

    def seed(self):
        values = self.case.values(documented_facts='Исходная запись <em>врача</em>', document_basis='Документ А, автор А, 01.10.2026',
                                  action_draft='Уникальное действие', complaints_status='known', complaints_text='Исходная жалоба', complaints_basis='Беседа')
        self.assertEqual(303, self.case.post(values).status_code)
        return self.rows()[0]

    def test_ordinary_visit_saves_and_retries_keep_earlier_document_notes(self):
        old = self.seed()
        ordinary = self.case.values(base_revision='1', action_draft='Новое действие')
        self.assertEqual(303, self.case.post(ordinary, old['visit_id']).status_code)
        self.assertEqual(303, self.case.post(ordinary, old['visit_id']).status_code)
        self.assertEqual(2, len(self.rows()))
        self.assertEqual(303, self.case.post(self.case.values(base_revision='2', state='completed'), old['visit_id']).status_code)
        for row in self.rows():
            self.assertEqual('Исходная запись <em>врача</em>', row['payload']['documented_facts'])
            self.assertEqual('Документ А, автор А, 01.10.2026', row['payload']['document_basis'])

    def test_document_notes_are_not_offered_or_editable_on_any_screen(self):
        old = self.seed()
        for path in ('/patients/FV01/first-visits', '/patients/FV01/first-visits/' + old['visit_id'], '/demo/FV01'):
            page = self.client.get(path, follow_redirects=True).text
            self.assertNotIn('name="documented_facts"', page)
            self.assertNotIn('name="document_basis"', page)
            self.assertNotIn('/imports', page)
            self.assertNotIn('<em>врача</em>', page)
        before = [tuple(r) for r in self.db.execute('SELECT * FROM first_visit_versions')]
        refused = self.client.post(f'/patients/FV01/first-visits/{old["visit_id"]}/documents',
                                   data={'csrf': csrf(self.client), 'request_key': secrets.token_hex(16), 'base_revision': '1',
                                         'documented_facts': 'Подмена', 'document_basis': 'Подмена'})
        self.assertEqual(404, refused.status_code)
        self.assertEqual(before, [tuple(r) for r in self.db.execute('SELECT * FROM first_visit_versions')])
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])


if __name__ == '__main__':
    unittest.main()
