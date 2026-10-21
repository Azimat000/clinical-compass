"""S26C: кабинет пациента в «Бланке». Экран «Сегодня», шаги самоотчёта, состояния. Серверные правила и тексты шкал не менялись."""
import re
import secrets
import unittest
from datetime import datetime, timedelta, timezone
from apps.compass import records
import test_follow_up
import test_communication


class PatientWorkspaceTests(unittest.TestCase):
    setUp = test_follow_up.FollowUpTests.setUp
    tearDown = test_follow_up.FollowUpTests.tearDown
    post = test_follow_up.FollowUpTests.post
    offer = test_follow_up.FollowUpTests.offer
    link = test_follow_up.FollowUpTests.link
    values = test_follow_up.FollowUpTests.values
    draft = test_follow_up.FollowUpTests.draft
    confirm = test_follow_up.FollowUpTests.confirm
    action = test_follow_up.FollowUpTests.action
    task = test_follow_up.FollowUpTests.task
    assessment = test_follow_up.FollowUpTests.assessment
    url = '/patients/D01/communication'

    def page(self, path='/demo/D01', who='pat-a'):
        return self.clients[who].get(path).get_data(as_text=True)

    def request_assessment(self):
        from apps.compass import assessments
        f = assessments.definition()
        self.assertEqual(303, self.post('doc-a', '/patients/D01/assessment-requests', {
            'assignment_key': secrets.token_hex(16), 'form_version_id': f['id'],
            'age_status': 'known', 'age_years': '35', 'age_basis': 'Синтетический профиль'}).status_code)
        return self.db.execute('SELECT id FROM assessment_requests ORDER BY requested_at DESC LIMIT 1').fetchone()[0]

    def test_today_has_one_main_action_and_it_follows_the_priority(self):
        page = self.page()
        self.assertIn('<h2 id="today-title">Сегодня</h2>', page)
        self.assertEqual(1, page.count('class="button today-action"'))
        self.assertIn('Записать самочувствие', page)
        self.assertNotIn('Добавить самоотчёт', page)
        # план без отметки выше самоотчёта
        self.task()
        page = self.page()
        self.assertEqual(1, page.count('class="button today-action"'))
        self.assertIn('Отметить выполнение плана', page)
        self.assertIn('Пунктов плана без вашей отметки: 1.', page)
        # анкета со сроком выше плана
        rid = self.request_assessment()
        page = self.page()
        self.assertEqual(1, page.count('class="button today-action"'))
        self.assertIn('Заполнить анкету DASS-42', page)
        self.assertIn('/assessments/' + rid, page)

    def test_patient_without_a_doctor_link_is_told_to_enter_the_invitation_code(self):
        # Сначала разрываем связь: без действующего врача отправлять сведения некому.
        self.db.execute("UPDATE care_relationships SET ends_at=? WHERE patient_id='D01'", ('2000-01-01T00:00:00+00:00',))
        page = self.page()
        self.assertIn('Ввести код приглашения врача', page)
        self.assertIn('href="#connection"', page)
        self.assertIn('связь не установлена', page)
        self.assertIn('Код приглашения от врача', page)
        self.assertEqual(1, page.count('class="button today-action"'))

    def test_today_never_claims_doctor_saw_or_reacted(self):
        page = self.page()
        for text in ['Сохранено на сервере', 'Реакция врача', 'Система её не отслеживает']:
            self.assertIn(text, page)
        self.assertIn('не обеспечивает экстренную помощь', page)
        self.assertNotRegex(page, r'врач (увидел|прочитал|ответил)')

    def test_patient_navigation_is_short_and_present_on_all_patient_pages(self):
        rid = self.request_assessment()
        for path in ['/demo/D01', self.url, '/patients/D01/decisions', '/assessments/' + rid]:
            page = self.page(path)
            nav = re.search(r'<nav aria-label="Разделы кабинета".*?</nav>', page, re.S).group(0)
            for name in ['Сегодня', 'Самоотчёт', 'Динамика', 'Анкеты', 'Сообщения и план']:
                self.assertIn('>' + name + '</a>', nav, path)
            self.assertEqual(5, nav.count('<a '))
        self.assertIn('aria-current="page"', re.search(r'<nav aria-label="Разделы кабинета".*?</nav>', self.page(self.url), re.S).group(0))

    def test_self_report_is_in_two_steps_with_server_fields_unchanged(self):
        page = self.page()
        self.assertIn('data-report-form', page)
        steps = re.findall(r'data-report-step="(\d)"', page)
        self.assertEqual(['1', '2'], steps)  # S26D: заполнение и проверка
        for name in ['observed_on', 'wellbeing', 'age_status', 'age_years', 'birth_date', 'age_detail', 'summary',
                     'complaints_status', 'complaints_text', 'adverse_events_status', 'safety_taken', 'safety_form_version']:
            self.assertEqual(1, len(re.findall(r'name="%s"' % name, page)), name)
        self.assertIn('<details open>', page)
        self.assertIn('Не ждите ответа через демонстрационный кабинет', page)
        self.assertIn('/static/self_report.js', page)
        # врач получает прежний бланк визита без шагов
        doctor = self.page('/demo/D01', 'doc-a')
        self.assertNotIn('data-report-form', doctor)
        self.assertNotIn('self_report.js', doctor)

    def test_failed_submission_keeps_every_entered_value_and_saves_nothing(self):
        before = self.db.execute('SELECT count(*) FROM clinical_entries').fetchone()[0]
        form = {'request_key': secrets.token_hex(16), 'observed_on': records.today().isoformat(),
                'wellbeing': 'worse', 'age_status': 'unknown', 'complaints_status': 'known', 'complaints_text': '',
                'adverse_events_status': 'denied', 'adverse_events_text': 'Текст при отрицании: должен остаться в форме',
                'summary': 'Синтетическое резюме, которое нельзя терять'}
        response = self.post('pat-a', '/patients/D01/self-reports', form)
        self.assertEqual(400, response.status_code)
        page = response.get_data(as_text=True)
        self.assertIn('Текст при отрицании: должен остаться в форме', page)
        self.assertIn('Синтетическое резюме, которое нельзя терять', page)
        self.assertIn('data-has-error="yes"', page)
        self.assertIn('role="alert"', page)
        self.assertEqual(before, self.db.execute('SELECT count(*) FROM clinical_entries').fetchone()[0])

    def test_message_states_are_separate_words_and_not_a_doctor_reaction(self):
        self.assertEqual(303, self.post('pat-a', self.url + '/send', {
            'request_key': secrets.token_hex(16), 'body': 'Синтетическое сообщение', 'entry_id': '', 'task_id': ''}).status_code)
        page = self.page(self.url)
        self.assertIn('Сохранено на сервере', page)
        self.assertIn('Получено адресатом: не отмечено', page)
        self.assertIn('Прочитано адресатом: не отмечено', page)
        self.assertIn('Получение и прочтение не означает реакцию врача', page)
        mid = self.db.execute('SELECT id FROM messages').fetchone()[0]
        self.assertEqual(303, self.post('doc-a', self.url + '/received', {'message_id': mid}).status_code)
        page = self.page(self.url)
        self.assertNotIn('Получено адресатом: не отмечено', page)
        self.assertIn('Прочитано адресатом: не отмечено', page)

    def test_questionnaire_keeps_text_order_and_shows_receipt_states(self):
        from apps.compass import assessments
        rid = self.request_assessment()
        page = self.page('/assessments/' + rid)
        instrument = assessments.definition()
        self.assertIn('data-answer-progress', page)
        self.assertIn('/static/questionnaire.js', page)
        positions = [page.index('%d. %s' % (i + 1, item.replace('&', '&amp;'))) for i, item in enumerate(instrument['items'])
                     if ('%d. %s' % (i + 1, item.replace('&', '&amp;'))) in page]
        self.assertEqual(42, len(positions))
        self.assertEqual(sorted(positions), positions)
        self.assertEqual(42 * 5, page.count('type="radio"'))
        form = {'form_version_id': instrument['id'], **{'answer_%d' % i: '1' for i in range(1, 43)}}
        self.assertEqual(303, self.post('pat-a', '/assessments/' + rid, form).status_code)
        receipt = self.page('/assessments/' + rid)
        self.assertIn('Анкета отправлена врачу', receipt)
        self.assertIn('Сохранено на сервере', receipt)
        self.assertIn('Прочитано врачом', receipt)
        self.assertNotIn('Депрессивные симптомы', receipt)

    def test_patient_cannot_use_doctor_screens_and_doctor_card_is_not_the_patient_one(self):
        self.assertEqual(403, self.clients['pat-a'].get('/patients/D01/follow-up').status_code)
        doctor = self.page('/demo/D01', 'doc-a')
        self.assertNotIn('today-title', doctor)
        self.assertNotIn('Разделы кабинета', doctor)


if __name__ == '__main__':
    unittest.main()
