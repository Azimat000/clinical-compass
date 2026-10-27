"""UI05: кабинет врача — план и решения, приём (документы убраны из сайта в UI11). Разметка, подтверждение только по ответу сервера, ошибки, худшие данные."""
import re
import secrets
import unittest

from apps.compass import decisions, first_visits, records
import test_access
import test_decisions

SCREENS = ('/patients/D01/decisions', '/patients/D01/first-visits')


class DoctorWorkTests(unittest.TestCase):
    setUp = test_decisions.DecisionTests.setUp
    tearDown = test_access.AccessTests.tearDown
    post = test_access.AccessTests.post
    offer = test_access.AccessTests.offer
    link = test_access.AccessTests.link
    values = test_decisions.DecisionTests.values
    draft = test_decisions.DecisionTests.draft
    confirm = test_decisions.DecisionTests.confirm

    def page(self, path, who='doc-a', status=200):
        response = self.clients[who].get(path)
        self.assertEqual(status, response.status_code, path)
        return response.get_data(as_text=True)

    # ---- общие границы ----

    def test_screens_are_doctor_only_and_patient_never_sees_them(self):
        for path in SCREENS:
            page = self.page(path)
            self.assertIn('aria-label="Разделы пациента"', page, path)
            self.assertIn('aria-current="page"', page, path)
            self.assertNotIn('<script>', page.replace('<script src', ''), path)
            self.assertNotIn(' style=', page, path)
        for path in ('/patients/D01/first-visits',):
            self.assertEqual(403, self.clients['pat-a'].get(path).status_code)
        # Страница решений открыта и пациенту по прежним правилам доступа, но вместо врачебного экрана он получает свой экран плана (UI06B).
        asked = self.clients['pat-a'].get('/patients/D01/decisions')
        self.assertEqual(200, asked.status_code)
        self.assertIn('<h1>План</h1>', asked.get_data(as_text=True))
        self.assertNotIn('Решение врача', asked.get_data(as_text=True))
        self.assertEqual(404, self.clients['doc-b'].get('/patients/D01/decisions').status_code)

    def test_patient_nav_links_lead_only_to_existing_screens(self):
        for path in ('/demo/D01', '/patients/D01/follow-up') + SCREENS:
            page = self.page(path)
            for href in re.findall(r'<nav class="jump patient-nav".*?</nav>', page, re.S)[0].split('href="')[1:]:
                target = href.split('"')[0]
                self.assertEqual(200, self.clients['doc-a'].get(target).status_code, (path, target))

    def test_no_duplicate_ids_on_screens_with_data(self):
        self.draft()
        self.draft(kind='plan_change')
        self.post('doc-a', '/patients/D01/first-visits/new', {'request_key': secrets.token_hex(16), 'base_revision': '0', 'state': 'draft',
                  'observed_on': records.today().isoformat(), 'visit_kind': 'first', 'not_collected': 'yes', 'age_source': 'patient'})
        for path in SCREENS:
            ids = re.findall(r'\sid="([^"]+)"', self.page(path))
            self.assertEqual([], sorted({i for i in ids if ids.count(i) > 1}), path)

    def test_scripts_are_local_files_that_exist(self):
        for path in SCREENS:
            for src in re.findall(r'<script src="([^"]+)"', self.page(path)):
                self.assertTrue(src.startswith('/static/'), src)
                served = self.clients['doc-a'].get(src)
                self.assertEqual(200, served.status_code, src)
                served.close()

    # ---- решения ----

    def test_empty_state_names_absence_and_unknown_is_not_admission(self):
        page = self.page('/patients/D01/decisions')
        self.assertIn('Подтверждённого плана нет. Это не означает, что план не нужен.', page)
        self.assertIn('Неизвестность не означает допуск', page)
        self.assertIn('Прежних решений и ответов пока нет.', page)

    def test_draft_waits_and_confirmation_shows_only_after_server_answer(self):
        proposal = self.draft()
        waiting = self.page('/patients/D01/decisions')
        self.assertIn('Проект — план не изменён', waiting)
        self.assertNotIn('Подтверждено врачом', waiting)
        self.assertIn('name="decision" value="approved"', waiting)
        self.assertIn('name="decision" value="rejected"', waiting)
        # Отказ сервера не оставляет на экране «Подтверждено»: страница результата без изменения плана.
        refused = self.confirm(proposal, reviewed='', rationale='Мой текст обоснования')
        self.assertIn(refused.status_code, (400, 409))
        # Отказ возвращает на экран решений с введённым обоснованием, а не на общую страницу ошибки.
        text = refused.get_data(as_text=True)
        self.assertIn('Решение не записано', text)
        self.assertIn('Мой текст обоснования', text)
        self.assertIn('id="confirm-error"', text)
        self.assertNotIn('Подтверждено врачом', self.page('/patients/D01/decisions'))
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])
        self.assertEqual(303, self.confirm(proposal).status_code)
        done = self.page('/patients/D01/decisions')
        self.assertIn('Подтверждено врачом', done)
        self.assertIn('Текущий план', done)
        self.assertNotIn('name="decision" value="approved"', done)

    def test_server_failure_on_confirm_is_a_page_with_a_code_and_changes_nothing(self):
        import sqlite3
        from unittest.mock import patch
        proposal = self.draft()
        with patch.object(decisions, 'confirm', side_effect=sqlite3.OperationalError('database is locked')):
            response = self.confirm(proposal)
        self.assertEqual(503, response.status_code)
        self.assertEqual('5', response.headers['Retry-After'])
        text = response.get_data(as_text=True)
        self.assertIn('Сервис временно недоступен', text)
        self.assertIn('результат операции неизвестен', text)
        self.assertNotIn('Подтверждено врачом', text)
        self.assertNotIn('database is locked', text)
        self.assertNotIn('Подтверждено врачом', self.page('/patients/D01/decisions'))
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])

    def test_confirmed_plan_comes_before_waiting_projects(self):
        # UI14: текущий подтверждённый план и ответы по нему первыми, проекты на подтверждении — следующим разделом.
        first = self.draft()
        self.assertEqual(303, self.confirm(first).status_code)
        self.draft(kind='plan_change')
        page = self.page('/patients/D01/decisions')
        self.assertLess(page.index('id="current"'), page.index('id="waiting"'))

    def test_repeat_click_on_confirm_is_the_same_result(self):
        proposal = self.draft()
        for _ in range(2):
            self.assertEqual(303, self.confirm(proposal).status_code)
        self.assertEqual(1, self.db.execute('SELECT count(*) FROM doctor_confirmations').fetchone()[0])
        self.assertEqual(1, self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])

    def test_rejected_project_stays_in_history_without_changing_plan(self):
        proposal = self.draft()
        self.assertEqual(303, self.confirm(proposal, 'rejected').status_code)
        page = self.page('/patients/D01/decisions')
        self.assertIn('Отклонено врачом — план не изменён', page)
        self.assertIn('Подтверждённого плана нет', page)
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])

    def test_stale_project_cannot_be_confirmed_and_offers_a_new_version(self):
        proposal = self.draft()
        records.save(self.db, {'id': 'pat-a', 'role': 'patient'}, 'D01', 'self_report',
                     {'request_key': secrets.token_hex(16), 'observed_on': records.today().isoformat(), 'wellbeing': 'worse'})
        page = self.page('/patients/D01/decisions')
        self.assertIn('Подтвердить нельзя: проект устарел', page)
        self.assertIn('?revise=' + proposal['id'], page)
        self.assertRegex(page, r'<button class="button button--primary"[^>]*value="approved"[^>]*disabled')
        self.assertEqual(409, self.confirm(proposal).status_code)
        # Отклонить устаревший проект можно.
        self.assertEqual(303, self.confirm(proposal, 'rejected').status_code)

    def test_revise_prefills_a_new_version_and_links_the_parent(self):
        proposal = self.draft(kind='referral', route_specialty='Терапевт', content='Текст исходного проекта')
        page = self.page('/patients/D01/decisions?revise=' + proposal['id'])
        self.assertIn('Текст исходного проекта', page)
        self.assertIn('name="parent_id" value="' + proposal['id'] + '"', page)
        self.assertIn('Терапевт', page)
        self.assertIn('Прежний проект остаётся в истории', page)
        self.assertEqual(404, self.clients['doc-a'].get('/patients/D01/decisions?revise=nope').status_code)
        self.assertEqual(403, self.clients['pat-a'].get('/patients/D01/decisions?revise=' + proposal['id']).status_code)

    def test_form_error_keeps_every_typed_value_and_says_nothing_was_saved(self):
        form = self.values(content='Введённое решение', basis='', route_evidence='Введённое основание направления', kind='referral')
        response = self.post('doc-a', '/patients/D01/decisions', form)
        self.assertEqual(400, response.status_code)
        page = response.get_data(as_text=True)
        self.assertIn('Проект не сохранён', page)
        self.assertIn('Введённое решение', page)
        self.assertIn('Введённое основание направления', page)
        self.assertIn('id="form-error"', page)
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM proposals').fetchone()[0])

    def test_all_review_areas_and_both_kind_groups_are_in_the_form(self):
        page = self.page('/patients/D01/decisions')
        for area in decisions.reference()['review_areas']:
            self.assertIn('name="review_%s"' % area['id'], page)
            self.assertIn('name="note_%s"' % area['id'], page)
        self.assertIn('data-for-kinds="referral"', page)
        self.assertIn('data-for-kinds="therapy_start therapy_change therapy_stop"', page)
        self.assertIn('name="therapy_reference"', page)
        self.assertIn('name="routing_reference"', page)

    def test_worst_case_text_in_decision_does_not_break_the_page(self):
        long_word = 'Ж' * 3500
        proposal = self.draft(content=long_word, basis='Ё' * 3000, uncertainties='<b>жирно</b> ' + 'x' * 3000)
        self.assertEqual(303, self.confirm(proposal).status_code)
        page = self.page('/patients/D01/decisions')
        self.assertIn(long_word, page)
        self.assertNotIn('<b>жирно</b>', page)
        self.assertIn('&lt;b&gt;жирно&lt;/b&gt;', page)

    # ---- приём ----

    def test_first_visit_form_has_text_fields_without_metadata_controls(self):
        page = self.page('/patients/D01/first-visits')
        for code in (*first_visits.CURRENT_FIELDS, *first_visits.STATIC_FIELDS):
            self.assertIn('name="%s_text"' % code, page)
            for suffix in ('status', 'source', 'on', 'basis'):
                self.assertNotIn('name="%s_%s"' % (code, suffix), page)
        self.assertIn('name="state" value="draft"', page)
        self.assertIn('name="state" value="completed"', page)
        self.assertIn('Новый приём', page)
        self.assertNotIn('name="medications_text"', page)
        self.assertNotIn('name="age_basis"', page)

    def test_completed_visit_is_a_closed_record_without_a_form(self):
        values = {'request_key': secrets.token_hex(16), 'base_revision': '0', 'state': 'completed',
                  'observed_on': records.today().isoformat(), 'visit_kind': 'first', 'not_collected': 'yes', 'age_source': 'patient'}
        response = self.post('doc-a', '/patients/D01/first-visits/new', values)
        self.assertEqual(303, response.status_code)
        page = self.page(response.location)
        self.assertIn('Запись приёма', page)
        self.assertIn('Что уточнить', page)
        self.assertIn('Завершена', page)
        self.assertNotIn('name="state"', page)
        self.assertIn('Начать новый приём', page)

    def test_finish_needs_a_second_step_and_unknown_shows_no_invented_source(self):
        page = self.page('/patients/D01/first-visits')
        self.assertIn('class="finish"', page)
        self.assertIn('Да, завершить запись', page)
        self.assertIn('name="state" value="draft"', page)
        values = {'request_key': secrets.token_hex(16), 'base_revision': '0', 'state': 'completed',
                  'observed_on': records.today().isoformat(), 'visit_kind': 'first', 'not_collected': 'yes', 'age_source': 'patient'}
        record = self.page(self.post('doc-a', '/patients/D01/first-visits/new', values).location)
        self.assertIn('источник не указан', record)
        self.assertNotIn('Со слов пациента,', record)

    def test_first_visit_error_page_names_the_unsaved_version(self):
        values = {'request_key': secrets.token_hex(16), 'base_revision': '0', 'state': 'draft',
                  'observed_on': '2099-01-01', 'visit_kind': 'first', 'complaints_text': 'Сохранить при ошибке'}
        response = self.post('doc-a', '/patients/D01/first-visits/new', values)
        self.assertEqual(400, response.status_code)
        page = response.get_data(as_text=True)
        self.assertIn('Новая версия не сохранена', page)
        self.assertIn('Сохранить при ошибке', page)

    # ---- общий отказ на слишком большой запрос ----

    def test_oversized_request_shows_a_page_not_a_blank_screen(self):
        response = self.post('doc-a', '/patients/D01/decisions', self.values(content='я' * 40000))
        self.assertEqual(413, response.status_code)
        self.assertIn('Ввод слишком большой', response.get_data(as_text=True))

if __name__ == '__main__':
    unittest.main()
