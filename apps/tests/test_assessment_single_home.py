"""S47: questionnaire evidence stays in the card when the editor copy is removed."""
from html import unescape
import re
import secrets
import unittest
from apps.compass import assessments
import test_first_visits as base


class AssessmentSingleHomeTests(unittest.TestCase):
    def setUp(self):
        self.case = base.FirstVisitTests('test_repeat_visit_and_exact_dass_results_remain_separate')
        self.case.setUp()
        self.addCleanup(self.case.tearDown)
        self.db = self.case.db
        self.client = self.case.clients['doc-a']
        self.doctor = self.case.doctor
        self.patient = {'id': 'pat-fv', 'role': 'patient'}
        response = self.case.post(self.case.values(age_status='known', age_years='35', age_basis='Беседа'))
        self.assertEqual(303, response.status_code)
        self.draft_url = response.location

    def snapshot(self):
        # Read screens may create authentication bookkeeping, never clinical writes.
        tables = [r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return {t: sorted(repr(tuple(r)) for r in self.db.execute('SELECT * FROM "'+t+'"'))
                for t in tables if t not in {'sessions', 'audit_entries', 'login_challenges', 'login_limits'}}

    def fill(self, form, incomplete=False):
        task = assessments.assign(self.db, self.doctor, 'FV01', {
            'assignment_key': secrets.token_hex(16), 'form_version_id': form['id']})
        values = {'form_version_id': form['id'], **{f'answer_{i}': str(i % 4)
                  for i in range(1, len(form['items']) + 1)}}
        if incomplete:
            values['answer_1'] = ''
        assessments.submit(self.db, self.patient, task, values)
        return task

    def assert_editor(self, html):
        self.assertIn('id="v-tool" href="/demo/FV01#assessments">Анкеты в карточке', html)
        for removed in ('Результат инструмента отдельно', 'assessment-series', 'assessment-plot',
                        'Исходные ответы (', 'Заполненные анкеты, сначала новые', 'data-form-version='):
            self.assertNotIn(removed, html)
        for kept in ('name="complaints_text"', 'value="draft"', 'value="completed"', 'План и решения'):
            self.assertIn(kept, html)

    def test_every_full_partial_answer_score_version_and_source_stays_in_card(self):
        forms = assessments.definitions()
        for form in forms:
            for incomplete in (False, True):
                self.fill(form, incomplete)
        rows = assessments.history(self.db, self.doctor, 'FV01')
        self.assertEqual(6, len(rows))
        before = self.snapshot()
        html = unescape(self.client.get('/demo/FV01').text)
        for form in forms:
            self.assertEqual(1, html.count('id="chart-'+form['id']+'"'))
            for text in (form['title'], form['attribution'], form['period'], form['version'],
                         form['source']['url'], form['validation_url'], form['rights_url']):
                self.assertIn(text, html)
        for row in rows:
            raw = re.search(r'<details class="fold" id="answers-'+row['id']+'">(.*?)</details>', html, re.S).group(1)
            self.assertIn(row['display_name'], raw)
            self.assertIn(row['age_basis'], raw)
            self.assertIn('Возраст: 35.', raw)
            self.assertEqual(len(row['answers']), raw.count('<li>'))
            for question, value in zip(row['form']['items'], row['answers']):
                self.assertIn('<span>'+question+'</span> <b class="num">'+str(value if value is not None else 'без ответа')+'</b>', raw)
            result = re.search(r'<tr id="assessment-'+row['id']+'">(.*?)</tr>', html, re.S).group(1)
            self.assertIn(row['observed_on'], result)
            if row['scores'] is None:
                self.assertIn('неполное', result)
                self.assertEqual(len(row['form']['subscales']), result.count('не рассчитано'))
                self.assertNotIn('href="#assessment-'+row['id']+'"', html)  # No fake zero point.
            else:
                self.assertIn('полное', result)
                for value in row['scores'].values():
                    self.assertIn('<td class="num">'+str(value)+'</td>', result)
                self.assertIn('href="#assessment-'+row['id']+'"', html)
            self.assertIn(row['scoring_version'], html)
        for url in ('/patients/FV01/first-visits', '/patients/FV01/first-visits/new', self.draft_url):
            self.assert_editor(self.client.get(url).text)
        self.assertEqual(before, self.snapshot())

    def test_empty_error_and_period_reset_keep_the_same_home(self):
        self.assert_editor(self.client.get('/patients/FV01/first-visits').text)
        error = self.case.post(self.case.values(complaints_status='known', complaints_text='Сохранить этот текст'))
        self.assertEqual(400, error.status_code)
        self.assert_editor(error.text)
        self.assertIn('Сохранить этот текст', error.text)
        self.assertIn('Новая версия не сохранена', error.text)
        self.fill(assessments.definition())
        before = self.snapshot()
        empty_period = self.client.get('/demo/FV01?start=1900-01-01&end=1900-01-02').text
        self.assertIn('Анкет за период нет', empty_period)
        restored = self.client.get('/demo/FV01').text
        self.assertIn('Исходные ответы (42 пункта)', restored)
        self.assertEqual(before, self.snapshot())

    def test_offer_patient_form_receipt_and_access_still_work(self):
        form = next(f for f in assessments.definitions() if f['code'] == 'GAD-7')
        task = assessments.assign(self.db, self.doctor, 'FV01', {
            'assignment_key': secrets.token_hex(16), 'form_version_id': form['id']})
        card = self.client.get('/demo/FV01').text
        self.assertIn('Предложить выбранную анкету', card)
        self.assertIn(form['code'], card)
        self.assertEqual([task], [r['id'] for r in assessments.pending(self.db, self.patient, 'FV01')])
        patient = self.case.clients['pat-fv']
        self.assertEqual(len(form['items']), patient.get('/assessments/'+task).text.count('<fieldset class="q"'))
        self.assertEqual(404, self.case.clients['pat-b'].get('/assessments/'+task).status_code)
        assessments.submit(self.db, self.patient, task, {'form_version_id': form['id'],
                           **{f'answer_{i}': '2' for i in range(1,8)}})
        receipt = patient.get('/assessments/'+task)
        self.assertEqual(200, receipt.status_code)
        self.assertNotIn('assessment-plot', receipt.text)
        self.assertNotIn('Исходные ответы (', receipt.text)
        for url in ('/demo/FV01', '/patients/FV01/first-visits'):
            self.assertIn(self.case.clients['doc-b'].get(url).status_code, (403,404))
        self.assertEqual(403, patient.get('/patients/FV01/first-visits').status_code)
        own = patient.get('/demo/FV01')
        self.assertEqual(200, own.status_code)
        self.assertNotIn('assessment-plot', own.text)
        self.assertNotIn('Исходные ответы (', own.text)
