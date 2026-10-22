"""UI03: кабинет пациента в «Листе результатов». Сегодня, дневник, самоотчёт, анкета, приглашение. Серверные правила и тексты шкал не менялись."""
import html
import re
import secrets
import unittest
from datetime import datetime, timedelta, timezone
from apps.compass import records
import test_access
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

    def actions(self, page):
        """Главные кнопки действия на экране: у пациента она одна."""
        return re.findall(r'class="button button--primary button--action"', page)

    def test_today_has_one_main_action_and_it_follows_the_priority(self):
        page = self.page()
        self.assertEqual(1, len(self.actions(page)))
        self.assertIn('Отметить самочувствие', page)
        self.assertIn('href="/demo/D01/report"', page)
        self.assertIn('<h1>', page)
        self.assertIn('сведения на', page)
        self.assertIn('Учебные данные', page)
        # начатый и сохранённый черновик выше обычной отметки
        self.assertEqual(200, self.clients['pat-a'].post('/patients/D01/self-report-draft', data={
            'csrf': test_access.csrf(self.clients['pat-a']), 'request_key': secrets.token_hex(16),
            'draft_revision': '0', 'draft_action': 'save', 'summary': 'начало'}, headers={'Accept': 'application/json'}).status_code)
        page = self.page()
        self.assertEqual(1, len(self.actions(page)))
        self.assertIn('Продолжить черновик', page)
        # анкета со сроком выше черновика
        rid = self.request_assessment()
        page = self.page()
        self.assertEqual(1, len(self.actions(page)))
        self.assertIn('Заполнить анкету DASS\u201142', page)
        self.assertIn('/assessments/' + rid, page)
        self.assertNotIn('Продолжить черновик', page)

    def test_patient_without_a_doctor_link_enters_the_invitation_code_on_today(self):
        # Без действующего врача отправлять сведения некому: главное действие — привязка по приглашению.
        self.db.execute("UPDATE care_relationships SET ends_at=? WHERE patient_id='D01'", ('2000-01-01T00:00:00+00:00',))
        page = self.page()
        self.assertEqual(1, len(self.actions(page)))
        self.assertIn('Привязать врача', page)
        self.assertIn('name="invitation"', page)
        self.assertIn('Код приглашения от врача', page)
        self.assertIn('action="/link"', page)
        self.assertIn('Врач с кабинетом не связан', page)
        self.assertNotIn('Отправить проверку связи', page)

    def test_invitation_screen_for_doctor_and_binding_for_patient(self):
        self.db.execute("UPDATE care_relationships SET ends_at=? WHERE patient_id='D01'", ('2000-01-01T00:00:00+00:00',))
        doctor = self.clients['doc-a']
        response = self.post('doc-a', '/invitations', {'patient_id': 'D01'})
        self.assertEqual(200, response.status_code)
        screen = response.get_data(as_text=True)
        self.assertIn('Приглашение готово', screen)
        self.assertIn('readonly', screen)
        token = re.search(r'id="invitation-code" value="([^"]+)"', screen).group(1)
        self.assertIn('Код показывается один раз', screen)
        # техническим клиентам по-прежнему отдаётся JSON
        again = doctor.post('/invitations', data={'csrf': test_access.csrf(doctor), 'patient_id': 'D01'},
                            headers={'Accept': 'application/json'})
        self.assertEqual({'invitation'}, set(again.json))
        # чужой код и повтор не привязывают; верный привязывает и главное действие меняется
        wrong = self.post('pat-a', '/link', {'invitation': 'wrong-code'})
        self.assertEqual(409, wrong.status_code)
        self.assertIn('Приглашение недоступно', wrong.get_data(as_text=True))
        self.assertEqual(302, self.post('pat-a', '/link', {'invitation': token}).status_code)
        page = self.page()
        self.assertIn('Отметить самочувствие', page)
        self.assertIn('Отправить проверку связи', page)
        self.assertEqual(409, self.post('pat-a', '/link', {'invitation': token}).status_code)

    def test_connection_check_is_a_form_with_csrf_and_lands_back_on_today(self):
        page = self.page()
        self.assertIn('action="/patients/D01/connection-check"', page)
        self.assertEqual(302, self.post('pat-a', '/patients/D01/connection-check').status_code)
        self.assertIn('Последняя проверка связи получена', self.page())

    def test_today_never_claims_doctor_saw_or_reacted(self):
        page = self.page()
        for text in ['Сохранено на сервере не значит', 'Ответа здесь может не быть', 'не обеспечивает экстренную помощь']:
            self.assertIn(text, page)
        self.assertNotRegex(page, r'врач (увидел|прочитал|ответил)')
        self.assertNotIn('Прочитано врачом: да', page)

    def test_patient_navigation_is_short_and_marks_the_current_section(self):
        rid = self.request_assessment()
        expected = {'/demo/D01': 'Сегодня', '/demo/D01/diary': 'Дневник', '/demo/D01/report': 'Дневник',
                    '/demo/D01/forms': 'Анкеты', '/assessments/' + rid: 'Анкеты'}
        for path, current in expected.items():
            page = self.page(path)
            nav = re.search(r'<nav class="p-tabs" aria-label="Разделы кабинета">.*?</nav>', page, re.S).group(0)
            self.assertEqual(3, nav.count('<a '), path)
            for name in ['Сегодня', 'Дневник', 'Анкеты']:
                self.assertRegex(nav, r'<a href="[^"]+"[^>]*>%s</a>' % name, path)
            self.assertEqual(1, nav.count('aria-current="page"'), path)
            self.assertRegex(nav, r'<a href="[^"]+" aria-current="page">%s</a>' % current, path)
            # раздел «Сообщения» собирается в UI06: до тех пор его нет в навигации совсем
            self.assertNotIn('Сообщения', nav)
            self.assertNotIn('aria-disabled', nav)

    def test_self_report_form_keeps_server_fields_and_drops_the_two_steps(self):
        page = self.page('/demo/D01/report')
        self.assertIn('data-report-form', page)
        self.assertNotIn('data-report-step', page)
        for name in ['observed_on', 'wellbeing', 'age_status', 'age_years', 'birth_date', 'age_detail', 'summary',
                     'complaints_status', 'complaints_text', 'risk_factors_status', 'concomitant_medications_status',
                     'adverse_events_status', 'safety_taken', 'safety_hemoglobin', 'safety_form_version',
                     'csrf', 'request_key', 'draft_revision']:
            self.assertTrue(re.search(r'name="%s"' % name, page), name)
        self.assertEqual(4, len(re.findall(r'name="wellbeing"', page)))
        self.assertIn('Не ждите ответа через демонстрационный кабинет', page)
        self.assertIn('/static/report_draft.js', page)
        self.assertIn('/static/self_report.js', page)
        self.assertIn('action="/patients/D01/self-report-draft"', page)
        self.assertNotIn('localStorage', page)
        # без JS работает обычная форма: она сама отправляет данные на сервер
        self.assertIn('method="post" action="/patients/D01/self-reports"', page)
        self.assertIn('Сохранить черновик', page)
        self.assertIn('Удалить черновик', page)

    def test_patient_screens_are_closed_to_doctors_and_foreign_patients(self):
        for path in ['/demo/D01/diary', '/demo/D01/report', '/demo/D01/forms']:
            self.assertEqual(403, self.clients['doc-a'].get(path).status_code, path)
            self.assertEqual(404, self.clients['pat-b'].get(path).status_code, path)
        self.assertEqual(404, self.clients['pat-b'].get('/demo/D01').status_code)
        doctor = self.clients['doc-a'].get('/demo/D01')
        self.assertEqual(200, doctor.status_code)  # врач получает свою карточку, а не кабинет пациента
        self.assertIn('Разделы карточки', doctor.get_data(as_text=True))
        self.assertNotIn('Разделы кабинета', doctor.get_data(as_text=True))

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
        self.assertRegex(page, r'<input type="radio" name="wellbeing" value="worse" checked>')
        self.assertIn('data-has-error="yes"', page)
        self.assertIn('id="record-error"', page)
        self.assertIn('role="alert"', page)
        self.assertIn('Добавьте описание сведений.', page)
        self.assertIn('Удалите описание или выберите состояние', page)
        self.assertRegex(page, r'<details class="more" data-more open>')  # поля с ошибкой раскрыты
        self.assertEqual(before, self.db.execute('SELECT count(*) FROM clinical_entries').fetchone()[0])

    def test_diary_shows_saved_entry_with_escaped_text_and_no_scores(self):
        form = {'request_key': secrets.token_hex(16), 'observed_on': records.today().isoformat(), 'wellbeing': 'better',
                'summary': '<script>window.BAD=true</script>', 'complaints_status': 'known', 'complaints_text': 'Ночью просыпалась'}
        response = self.post('pat-a', '/patients/D01/self-reports', form)
        self.assertEqual(303, response.status_code)
        self.assertRegex(response.location, r'/demo/D01/diary#entry-[0-9a-f]{32}$')
        diary = self.page('/demo/D01/diary')
        entry = response.location.split('#')[1]
        self.assertIn('id="%s"' % entry, diary)
        self.assertIn('&lt;script&gt;window.BAD=true&lt;/script&gt;', diary)
        self.assertNotIn('<script>window.BAD', diary)
        self.assertIn('Ночью просыпалась', diary)
        self.assertIn('Сохранено на сервере', diary)
        self.assertNotRegex(diary, r'Депрессивные симптомы|Тревожные симптомы|из 42')
        today = self.page()
        self.assertIn('Ваши отметки', today)
        self.assertIn('Лучше', today)

    def test_empty_states_say_what_is_missing(self):
        self.assertIn('Отметок пока нет', self.page())
        self.assertIn('Записей пока нет', self.page('/demo/D01/diary'))
        forms = self.page('/demo/D01/forms')
        self.assertIn('Новых анкет от врача нет', forms)
        self.assertIn('Отправленных анкет пока нет', forms)

    def test_forms_screen_lists_pending_task_and_receipts_without_scores(self):
        rid = self.request_assessment()
        forms = self.page('/demo/D01/forms')
        self.assertIn('href="/assessments/%s"' % rid, forms)
        self.assertIn('42&nbsp;вопроса', forms)
        self.assertRegex(forms, r'отправить до <time datetime="[^"]+">\d\d\.\d\d\.\d{4} \d\d:\d\d МСК</time>')
        instrument = assessments_definition()
        self.assertEqual(303, self.post('pat-a', '/assessments/' + rid,
                                        {'form_version_id': instrument['id'], **{'answer_%d' % i: '1' for i in range(1, 43)}}).status_code)
        forms = self.page('/demo/D01/forms')
        self.assertIn('Отправлены врачу', forms)
        self.assertIn('Квитанция', forms)
        self.assertIn('Новых анкет от врача нет', forms)
        self.assertNotRegex(forms, r'Депрессивные|Тревожные|Стресс')

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
        rid = self.request_assessment()
        page = self.page('/assessments/' + rid)
        instrument = assessments_definition()
        self.assertIn('data-answer-progress', page)
        self.assertIn('data-skip-notice', page)
        self.assertIn('/static/questionnaire.js', page)
        self.assertIn(html.escape(instrument['instruction']), page)
        legends = re.findall(r'<legend>(\d+)\. (.*?)</legend>', page)
        self.assertEqual([(str(i + 1), html.escape(item)) for i, item in enumerate(instrument['items'])], legends)
        for number in (1, 42):
            for code, option in enumerate(instrument['options']):
                self.assertIn('<span class="visually-hidden">%d. </span>%s' % (code, html.escape(option)), page)
        self.assertEqual(42 * 5, page.count('type="radio"'))
        self.assertEqual(42, page.count('value="" checked'))  # пропуск выбран, пока пациент не ответил
        # пациенту не показываются суммы и расшифровка до, во время и после отправки
        self.assertNotRegex(page, r'Депрессивные|Тревожные|Стресс|баллов:')
        form = {'form_version_id': instrument['id'], **{'answer_%d' % i: '1' for i in range(1, 43)}}
        self.assertEqual(303, self.post('pat-a', '/assessments/' + rid, form).status_code)
        receipt = self.page('/assessments/' + rid)
        self.assertIn('Анкета отправлена врачу', receipt)
        for state in ['Сохранено на сервере', 'Прочитано врачом', 'Реакция врача']:
            self.assertIn(state, receipt)
        self.assertIn('Здесь не показывается', receipt)
        self.assertNotRegex(receipt, r'Депрессивные|Тревожные|Стресс|из 42')
        self.assertIn('href="/demo/D01/diary"', receipt)

    def test_questionnaire_error_keeps_answers_and_shows_a_reason(self):
        rid = self.request_assessment()
        instrument = assessments_definition()
        form = {'form_version_id': instrument['id'], **{'answer_%d' % i: '2' for i in range(1, 43)}, 'answer_7': '9'}
        before = self.db.execute('SELECT count(*) FROM assessments').fetchone()[0]
        response = self.post('pat-a', '/assessments/' + rid, form)
        self.assertEqual(400, response.status_code)
        page = response.get_data(as_text=True)
        self.assertIn('id="q-error"', page)
        self.assertIn('Анкета не отправлена', page)
        self.assertEqual(41, len(re.findall(r'value="2" checked', page)))
        self.assertEqual(before, self.db.execute('SELECT count(*) FROM assessments').fetchone()[0])

    def test_patient_cannot_use_doctor_screens_and_doctor_card_is_not_the_patient_one(self):
        self.assertEqual(403, self.clients['pat-a'].get('/patients/D01/follow-up').status_code)
        doctor = self.page('/demo/D01', 'doc-a')
        self.assertIn('Разделы карточки', doctor)
        self.assertNotIn('Разделы кабинета', doctor)
        self.assertNotIn('h-today', doctor)


def assessments_definition():
    from apps.compass import assessments
    return assessments.definition()


if __name__ == '__main__':
    unittest.main()
