"""S49: unique document notes move intact, with durable draft/retry boundaries."""
from html import escape
import json
import re
import secrets
import unittest
from apps.compass import extraction, first_visits, records, decisions
from test_access import csrf
import test_first_visits as base


class DocumentsSingleHomeTests(unittest.TestCase):
    def setUp(self):
        self.case = base.FirstVisitTests('test_sources_dates_unknown_denial_conflict_and_summary_sections')
        self.case.setUp()
        self.addCleanup(self.case.tearDown)
        self.db = self.case.db
        self.client = self.case.clients['doc-a']
        self.doctor = self.case.doctor

    def rows(self):
        return self.case.rows()

    def docs(self):
        return self.client.get('/patients/FV01/imports').text

    def post_docs(self, visit, values, uid='doc-a', pid='FV01', with_csrf=True):
        client = self.case.clients[uid]
        return client.post(f'/patients/{pid}/first-visits/{visit}/documents',
                           data={**({'csrf': csrf(client)} if with_csrf else {}), **values})

    def seed(self):
        values = self.case.values(documented_facts='Исходная запись <em>врача</em>', document_basis='Документ А, автор А, 01.10.2026',
                                  action_draft='Уникальное действие', complaints_status='known', complaints_text='Исходная жалоба', complaints_basis='Беседа')
        self.assertEqual(303, self.case.post(values).status_code)
        return self.rows()[0]

    def test_every_version_source_author_date_and_only_documents_home(self):
        old = self.seed()
        form = {'request_key': secrets.token_hex(16), 'base_revision': '1',
                'documented_facts': 'Уточнение из документа Б', 'document_basis': 'Автор Б, 02.10.2026'}
        response = self.post_docs(old['visit_id'], form)
        self.assertEqual(303, response.status_code)
        new = self.rows()[0]
        page = self.docs()
        for row in (old, new):
            self.assertEqual(1, page.count('id="visit-document-'+row['id']+'"'))
            self.assertIn(row['recorded_at'], page)
            for name in ('documented_facts', 'document_basis'):
                self.assertIn(escape(row['payload'][name]), page)
        self.assertIn('doc-a', page)
        self.assertNotIn('<em>врача</em>', page)
        ids = re.findall(r'\bid="([^"]+)"', page)
        self.assertEqual(len(ids), len(set(ids)))
        for path in ('/patients/FV01/first-visits', '/patients/FV01/first-visits/'+old['visit_id'], '/demo/FV01'):
            editor = self.client.get(path).text
            self.assertNotIn('name="documented_facts"', editor)
            self.assertNotIn('name="document_basis"', editor)
            self.assertNotIn('Исходная запись', editor)
            self.assertNotIn('Уточнение из документа Б', editor)
            self.assertIn('/patients/FV01/imports', editor)
        self.assertIn('#visit-document-'+old['id'], self.client.get('/demo/FV01').text)
        self.assertIn('#visit-document-'+new['id'], self.client.get('/demo/FV01').text)

    def test_document_edit_with_known_numeric_age_preserves_age_and_fields(self):
        values = self.case.values(age_status='known', age_years='34', age_basis='Со слов пациента',
                                  complaints_status='known', complaints_text='Трудности сна', complaints_basis='Беседа')
        self.assertEqual(303, self.case.post(values).status_code)
        old = self.rows()[0]
        change = {'request_key': secrets.token_hex(16), 'base_revision': '1',
                  'documented_facts': 'Сведения из записи', 'document_basis': 'Представленная запись'}
        self.assertEqual(303, self.post_docs(old['visit_id'], change).status_code)
        new = self.rows()[0]
        self.assertEqual(old['payload']['age'], new['payload']['age'])
        self.assertEqual(old['payload']['fields'], new['payload']['fields'])
        self.assertEqual('Сведения из записи', new['payload']['documented_facts'])
        self.assertEqual(303, self.post_docs(old['visit_id'], change).status_code)
        self.assertEqual(2, len(self.rows()))

    def test_visit_save_and_retries_never_erase_documents_and_stale_edits_do_not_overwrite(self):
        old = self.seed()
        change = {'request_key': secrets.token_hex(16), 'base_revision': '1',
                  'documented_facts': 'Новые сведения', 'document_basis': 'Источник Б'}
        self.assertEqual(303, self.post_docs(old['visit_id'], change).status_code)
        ordinary = self.case.values(base_revision='2', action_draft='Новое действие')
        result = self.case.post(ordinary, old['visit_id'])
        self.assertEqual(303, result.status_code)
        self.assertEqual('Новые сведения', self.rows()[0]['payload']['documented_facts'])
        self.assertEqual('Источник Б', self.rows()[0]['payload']['document_basis'])
        self.assertEqual(303, self.case.post(ordinary, old['visit_id']).status_code)
        retry = self.post_docs(old['visit_id'], change)
        self.assertEqual(303, retry.status_code)
        self.assertIn(self.rows()[1]['id'], retry.location)
        self.assertEqual(3, len(self.rows()))
        stale = self.post_docs(old['visit_id'], {**change, 'request_key': secrets.token_hex(16), 'documented_facts': 'Текст старой вкладки'})
        self.assertEqual(409, stale.status_code)
        self.assertIn('Текст старой вкладки', stale.text)
        self.assertIn('Сведения из документа не сохранены', stale.text)
        self.assertEqual(3, len(self.rows()))
        before = [tuple(r) for r in self.db.execute('SELECT * FROM first_visit_versions')]
        invalid = self.post_docs(old['visit_id'], {**change, 'base_revision': '3', 'request_key': secrets.token_hex(16), 'document_basis': ''})
        self.assertEqual(400, invalid.status_code)
        self.assertIn('Новые сведения', invalid.text)
        self.assertEqual(before, [tuple(r) for r in self.db.execute('SELECT * FROM first_visit_versions')])
        self.assertEqual(303, self.case.post(self.case.values(base_revision='3', state='completed'), old['visit_id']).status_code)
        self.assertEqual('Новые сведения', self.rows()[0]['payload']['documented_facts'])
        count = len(self.rows())
        refused = self.post_docs(old['visit_id'], {**change, 'base_revision': str(count), 'request_key': secrets.token_hex(16)})
        self.assertEqual(409, refused.status_code)
        self.assertIn('Новые сведения', refused.text)
        self.assertEqual(count, len(self.rows()))
        self.assertEqual(old['payload'], self.rows()[-1]['payload'])

    def test_only_document_fields_change_explicit_clear_is_versioned_and_access_is_protected(self):
        old = self.seed()
        values = {'base_revision': '1', 'request_key': secrets.token_hex(16), 'documented_facts': '', 'document_basis': '',
                  'complaints_text': 'Запрещённая подмена', 'age_years': '99', 'state': 'completed'}
        for uid in ('doc-b', 'pat-fv', 'pat-b'):
            self.assertIn(self.post_docs(old['visit_id'], values, uid=uid).status_code, (403,404))
            self.assertIn(self.case.clients[uid].get('/patients/FV01/imports').status_code, (403,404))
        self.assertEqual(403, self.post_docs(old['visit_id'], values, with_csrf=False).status_code)
        self.assertEqual(404, self.post_docs('missing', values).status_code)
        self.assertEqual(400, self.post_docs(old['visit_id'], {**values, 'base_revision': 'wrong'}).status_code)
        self.assertEqual(303, self.post_docs(old['visit_id'], values).status_code)
        new = self.rows()[0]
        self.assertEqual('draft', new['state'])
        for key, value in old['payload'].items():
            if key not in ('documented_facts', 'document_basis'):
                self.assertEqual(value, new['payload'][key], key)
        self.assertEqual('', new['payload']['documented_facts'])
        self.assertIn(escape(old['payload']['documented_facts']), self.docs())
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])

    def test_import_review_and_visit_documents_remain_distinct_without_clinical_actions(self):
        old = self.seed()
        source = '35 лет. F41.1. Источник <script>не исполнять</script>'
        item = extraction.save_import(self.db, self.doctor, 'FV01', source, secrets.token_hex(16))
        imported = extraction.history(self.db, 'FV01')[0]
        c = imported['result']['candidates'][0]
        extraction.review(self.db, self.doctor, 'FV01', item, {'request_key': secrets.token_hex(16),
            'candidate_id': c['id'], 'field': c['field'], 'assertion': c['assertion'], 'value': extraction.canonical(c['value']),
            'quote': c['quote'], 'reason': 'Сверено с вымышленным источником', 'disposition': 'accept'})
        before = {table: [tuple(r) for r in self.db.execute('SELECT * FROM '+table)]
                  for table in ('text_imports', 'extraction_reviews', 'assessments', 'care_actions', 'proposals')}
        self.assertEqual(303, self.post_docs(old['visit_id'], {'base_revision': '1', 'request_key': secrets.token_hex(16),
                         'documented_facts': 'Только запись врача', 'document_basis': 'Основание врача'}).status_code)
        page = self.docs()
        for text in ('Найденное — кандидаты, а не факты', 'Только запись врача', 'Основание врача',
                     'Журнал сверки', 'Сверено с вымышленным источником', escape(source)):
            self.assertIn(text, page)
        for table, values in before.items():
            self.assertEqual(values, [tuple(r) for r in self.db.execute('SELECT * FROM '+table)], table)
        self.assertEqual([], self.db.execute('PRAGMA foreign_key_check').fetchall())

    def test_document_edit_requires_fresh_review_of_pending_plan(self):
        old = self.seed()
        proposal = decisions.draft(self.db, self.doctor, 'FV01', {
            'request_key': secrets.token_hex(16), 'kind': 'plan_change',
            'content': 'Синтетический план', 'basis': 'Ручной проект', 'uncertainties': 'Неизвестно'})
        self.assertEqual(303, self.post_docs(old['visit_id'], {'request_key': secrets.token_hex(16),
            'base_revision': '1', 'documented_facts': 'Новые сведения', 'document_basis': 'Новый источник'}).status_code)
        with self.assertRaises(decisions.DecisionError) as failure:
            decisions.confirm(self.db, self.doctor, 'FV01', proposal, {
                'decision': 'approved', 'version': '1', 'reviewed': 'yes', 'rationale': 'Проверено'})
        self.assertEqual(409, failure.exception.status)
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])
