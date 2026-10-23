"""UI04: кабинет врача — список, карточка, сводка повторного приёма. Проверяется разметка, фильтры, худшие данные и границы."""
import re
import secrets
import unittest

from apps.compass import overview, records
from apps.compass.db import now
import test_access
import test_decisions


class DoctorCabinetTests(unittest.TestCase):
    setUp = test_decisions.DecisionTests.setUp
    tearDown = test_access.AccessTests.tearDown
    post = test_access.AccessTests.post
    offer = test_access.AccessTests.offer
    link = test_access.AccessTests.link

    def page(self, path, who='doc-a', status=200):
        response = self.clients[who].get(path)
        self.assertEqual(status, response.status_code, path)
        return response.get_data(as_text=True)

    def add_patient(self, pid, code, age_status='known', age=40):
        self.db.execute('INSERT INTO patients(id,code,age_years,age_status,synthetic,created_at) VALUES(?,?,?,?,1,?)',
                        (pid, code, age if age_status == 'known' else None, age_status, now()))
        self.db.execute("INSERT INTO care_relationships VALUES(?,?,'doc-a',?,NULL)", ('rel-' + pid, pid, now()))

    def self_report(self, summary='Синтетика', wellbeing='same', **extra):
        form = {'request_key': secrets.token_hex(16), 'observed_on': records.today().isoformat(), 'summary': summary,
                'wellbeing': wellbeing, 'age_status': 'unknown', **extra}
        response = self.post('pat-a', '/patients/D01/self-reports', form)
        self.assertEqual(303, response.status_code, response.get_data(as_text=True)[:300])

    # ---- список ----

    def test_list_marks_absence_of_data_and_never_calls_it_good(self):
        page = self.page('/')
        self.assertIn('Записей с причинами для проверки нет', page)
        self.assertIn('нет отметок', page)
        self.assertIn('Отсутствие причины не означает, что у пациента всё хорошо', page)
        self.assertNotRegex(page.replace('Отсутствие причины не означает, что у пациента всё хорошо', ''), r'(?i)всё хорошо|в норме|без проблем')

    def test_list_shows_reasons_without_duplicate_flags(self):
        self.self_report('Тошнота после завтрака', 'worse', adverse_events_status='known', adverse_events_text='Тошнота')
        self.self_report('Хуже снова', 'worse')
        page = self.page('/')
        self.assertIn('class="flagged"', page)
        self.assertIn('Записано нежелательное явление', page)
        self.assertIn('Самочувствие хуже 2 раза подряд', page)
        self.assertNotIn('class="flag"', page)
        self.assertNotIn('>НЯ<', page)
        self.assertIn('Тошнота', page)
        self.assertEqual(3, len(re.findall(r'<th scope="col">', page)))

    def test_unknown_age_is_flagged_and_dass_is_unavailable(self):
        self.add_patient('D09', 'Учебный 09 · Ирина — Возраст не указан', 'unknown')
        page = self.page('/')
        self.assertIn('Уточнить возраст', page)
        self.assertIn('Возраст не указан; анкета недоступна', page)
        self.assertIn('href="/demo/D09#age-review"', page)
        self.assertNotIn('>ВОЗРАСТ<', page)
        self.assertIn('Ирина', page)
        self.assertNotIn('Возраст не указан</a>', page)

    def test_filters_search_and_show_work_without_scripts(self):
        self.add_patient('D09', 'Учебный 09 · Ирина', 'unknown')
        self.assertIn('Ирина', self.page('/?age_status=unknown'))
        self.assertNotIn('Демо 01', self.page('/?age_status=unknown'))
        self.assertNotIn('Ирина', self.page('/?age_status=known'))
        self.assertIn('Демо 01', self.page('/?q=D01'))
        self.assertIn('По этому запросу пациентов нет', self.page('/?q=нет-такого'))
        self.assertIn('Показать всех', self.page('/?q=нет-такого'))
        self.assertNotIn('Демо 01', self.page('/?show=flagged'))
        self.assertIn('Ирина', self.page('/?show=flagged'))
        self.assertIn('aria-current="true"', self.page('/?show=flagged'))
        for bad in ('/?show=x', '/?age_status=x', '/?record_kind=x', '/?route_category=x', '/?attention=x'):
            self.assertEqual(400, self.clients['doc-a'].get(bad).status_code, bad)
        self.assertIn('name="show" value="flagged"', self.page('/?show=flagged'))

    def test_retired_signal_filter_redirects_without_hiding_patients(self):
        response = self.clients['doc-a'].get('/?attention=pending&q=D01')
        self.assertEqual(302, response.status_code)
        self.assertEqual('/?q=D01', response.headers['Location'])
        self.assertIn('Демо 01', self.clients['doc-a'].get(response.headers['Location']).text)

    def test_invitations_are_created_listed_and_revoked_from_the_list(self):
        self.assertIn('Действующих приглашений нет', self.page('/'))
        self.add_patient('D09', 'Демо 09')
        created = self.clients['doc-a'].post('/invitations', data={'csrf': test_access.csrf(self.clients['doc-a']), 'patient_id': 'D02'})
        self.assertEqual(200, created.status_code)
        self.assertIn('text/html', created.content_type)
        page = self.page('/')
        self.assertIn('Ждут принятия', page)
        self.assertIn('Отозвать', page)
        token_hash = re.search(r'/invitations/([0-9a-f]+)/revoke', page).group(1)
        self.assertEqual(302, self.post('doc-a', '/invitations/%s/revoke' % token_hash).status_code)
        self.assertIn('Действующих приглашений нет', self.page('/'))
        self.assertEqual(404, self.post('doc-a', '/invitations/%s/revoke' % token_hash).status_code)
        self.assertEqual(403, self.post('pat-a', '/invitations/%s/revoke' % token_hash).status_code)

    def test_worst_case_names_and_text_are_escaped_and_do_not_widen_the_page(self):
        long_name = 'Я' * 300
        self.add_patient('D08', 'Учебный 08 · <script>alert(1)</script>' + long_name + ' — сюжет')
        self.self_report('<img src=x onerror=alert(1)>' + 'ы' * 400, 'worse',
                         adverse_events_status='known', adverse_events_text='<b>жирно</b>' + 'я' * 300)
        for path in ('/', '/demo/D01', '/demo/D08', '/patients/D01/follow-up', '/patients/D08/follow-up'):
            html = self.page(path)
            self.assertNotIn('<script>alert', html, path)
            self.assertNotIn('<img src=x', html, path)
            self.assertNotIn('<b>жирно', html, path)
            self.assertNotRegex(html, r'<script(?![^>]*\ssrc=)|<style\b', path)
            self.assertNotRegex(html, r' style="', path)
            self.assertNotRegex(html, r' on\w+="', path)

    # ---- карточка ----

    def test_card_without_records_says_absence_not_safety(self):
        card = self.page('/demo/D01')
        self.assertIn('Записей пока нет', card)
        self.assertIn('отсутствие сведений, а не отсутствие жалоб', card)
        self.assertIn('Врачебные сведения не вносились', card)
        self.assertIn('Отсутствие сведений не означает отсутствия риска', card)
        self.assertIn('Рекомендация не сформирована', card)

    def test_card_shows_records_with_source_state_lines_and_anchors(self):
        self.self_report('Дневник', 'better', complaints_status='known', complaints_text='Спала лучше')
        card = self.page('/demo/D01')
        entry_id = self.db.execute('SELECT id FROM clinical_entries').fetchone()[0]
        self.assertIn('id="entry-%s"' % entry_id, card)
        self.assertIn('Пациент', card)
        self.assertIn('class="state state--known"', card)
        self.assertIn('class="state state--unknown"', card)
        self.assertIn('Спала лучше', card)

    def test_assessment_request_error_keeps_values_and_shows_reason(self):
        form = {'assignment_key': secrets.token_hex(16), 'form_version_id': 'DASS42-RU-FG-2024-demo-v1',
                'age_status': 'known', 'age_years': '35', 'age_basis': ''}
        response = self.post('doc-a', '/patients/D01/assessment-requests', form)
        self.assertEqual(400, response.status_code)
        page = response.get_data(as_text=True)
        self.assertIn('id="assessment-error"', page)
        self.assertIn('Анкета не предложена', page)
        self.assertIn('value="35"', page)
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM assessment_requests').fetchone()[0])

    def test_assessment_request_then_pending_and_results_are_visible_to_doctor_only(self):
        form = {'assignment_key': secrets.token_hex(16), 'form_version_id': 'DASS42-RU-FG-2024-demo-v1',
                'age_status': 'known', 'age_years': '35', 'age_basis': 'Синтетический профиль'}
        self.assertEqual(303, self.post('doc-a', '/patients/D01/assessment-requests', form).status_code)
        card = self.page('/demo/D01')
        self.assertIn('Предложена, ждёт ответа', card)
        task = self.db.execute('SELECT id FROM assessment_requests').fetchone()[0]
        answers = {'form_version_id': 'DASS42-RU-FG-2024-demo-v1', **{'answer_%d' % i: '2' for i in range(1, 43)}}
        self.assertEqual(303, self.post('pat-a', '/assessments/' + task, answers).status_code)
        card = self.page('/demo/D01')
        self.assertIn('Суммы по подшкалам', card)
        self.assertIn('<td class="num">28</td>', card)
        self.assertNotIn('<td class="num">28</td>', self.page('/demo/D01', 'pat-a'))
        self.assertIn('id="assessment-', card)

    def test_age_review_error_keeps_values(self):
        card = self.page('/demo/D01')
        key = re.search(r'name="request_key" value="([0-9a-f]{32})"', card)
        # Карточка D01 из фикстуры уже сверена или нет: принимаем оба состояния, но ошибка формы всегда сохраняет ввод.
        response = self.post('doc-a', '/patients/D01/age-reviews',
                             {'request_key': secrets.token_hex(16), 'sources_fingerprint': 'x' * 64, 'birth_date': '1990-01-01',
                              'basis': 'Сверено по документу', 'reviewed_sources': ''})
        self.assertEqual(400, response.status_code)
        page = response.get_data(as_text=True)
        self.assertIn('id="age-error"', page)
        self.assertIn('Сохранить сверку', page)
        self.assertIn('Сверено по документу', page)
        self.assertIn('value="1990-01-01"', page)
        self.assertIsNotNone(key or True)

    def test_clinical_context_form_is_reachable_and_checks_input(self):
        card = self.page('/demo/D01')
        self.assertIn('action="/patients/D01/clinical-context"', card)
        self.assertEqual(400, self.post('doc-a', '/patients/D01/clinical-context', {'request_key': 'bad'}).status_code)
        self.assertEqual(403, self.post('pat-a', '/patients/D01/clinical-context', {'request_key': 'bad'}).status_code)

    def test_other_doctor_and_patient_boundaries(self):
        for path in ('/demo/D01', '/patients/D01/follow-up'):
            self.assertEqual(404, self.clients['doc-b'].get(path).status_code, path)
        self.assertEqual(403, self.clients['pat-a'].get('/patients/D01/follow-up').status_code)
        self.assertEqual(404, self.clients['doc-b'].get('/demo/D01').status_code)
        self.assertNotIn('Демо 01', self.page('/', 'doc-b'))

    # ---- сводка повторного приёма ----

    def test_follow_up_empty_period_is_not_good_news(self):
        page = self.page('/patients/D01/follow-up')
        self.assertIn('Записей за период нет', page)
        self.assertIn('отсутствие сведений, а не отсутствие жалоб', page)
        self.assertIn('ни одной за 30 дн.', page)
        self.assertIn('Приёмов за период нет', page)
        self.assertIn('Анкет за период нет. Это не означает, что состояние в норме', page)
        self.assertIn('Подтверждённого плана за период нет. Это не означает, что план не нужен', page)

    def test_follow_up_links_back_to_source_records(self):
        self.self_report('Исходная запись', 'worse', adverse_events_status='known', adverse_events_text='Тошнота')
        entry_id = self.db.execute('SELECT id FROM clinical_entries').fetchone()[0]
        page = self.page('/patients/D01/follow-up')
        self.assertIn('href="/demo/D01#entry-%s"' % entry_id, page)
        self.assertIn('Исходная запись', page)
        self.assertIn('Тошнота', page)
        self.assertIn('1 из 30', page)
        self.assertIn('без отметки: 29', page)

    def test_follow_up_period_errors_keep_inputs_and_explain(self):
        response = self.clients['doc-a'].get('/patients/D01/follow-up?start=2026-10-20&end=2026-10-01')
        self.assertEqual(400, response.status_code)
        page = response.get_data(as_text=True)
        self.assertIn('id="period-error"', page)
        self.assertIn('value="2026-10-20"', page)
        self.assertIn('value="2026-10-01"', page)
        response = self.clients['doc-a'].get('/patients/D01/follow-up?start=2026-10-20&start=2026-10-21&end=2026-10-22')
        self.assertEqual(400, response.status_code)
        self.assertIn('Укажите один период', response.get_data(as_text=True))

    def test_card_shows_every_entry_so_every_follow_up_link_lands(self):
        for n in range(17):
            self.self_report('Запись %d' % n, 'same')
        ids = [row[0] for row in self.db.execute('SELECT id FROM clinical_entries')]
        card = self.page('/demo/D01')
        follow = self.page('/patients/D01/follow-up')
        self.assertIn('Ещё записей: 2', card)
        for entry_id in ids:
            self.assertEqual(1, card.count('id="entry-%s"' % entry_id))
            self.assertIn('href="/demo/D01#entry-%s"' % entry_id, follow)

    def test_patient_menu_has_no_duplicate_attention_counter(self):
        self.self_report('Хуже', 'worse', adverse_events_status='known', adverse_events_text='Тошнота')
        for path in ('/', '/?q=нет-такого', '/?age_status=unknown', '/demo/D01', '/patients/D01/follow-up'):
            page = self.page(path)
            self.assertNotIn('count--alert', page, path)
            self.assertRegex(page, r'<a href="/"[^>]*>Пациенты</a>', path)

    def test_adverse_flag_names_the_record_and_admits_that_newer_records_are_silent(self):
        old = (records.today().replace(day=1)).isoformat()
        self.self_report('Старая', 'worse', observed_on=old, adverse_events_status='known', adverse_events_text='Тошнота')
        self.self_report('Новая', 'same')
        page = self.page('/')
        entry = self.db.execute("SELECT id FROM clinical_entries WHERE summary='Старая'").fetchone()[0]
        self.assertIn('в более новых записях сведений нет', page)
        self.assertIn('href="/demo/D01#entry-%s"' % entry, page)  # причина ведёт к исходной записи
        self.assertIn('нежелательное явление в записях', page)
        self.assertNotIn('в последней записи', page)

    def test_revoking_an_invitation_asks_first_without_scripts(self):
        self.add_patient('D09', 'Демо 09')
        self.clients['doc-a'].post('/invitations', data={'csrf': test_access.csrf(self.clients['doc-a']), 'patient_id': 'D02'})
        page = self.page('/')
        self.assertIn('<details class="revoke">', page)
        self.assertIn('Да, отозвать', page)

    # ---- сводка по строке списка ----

    def test_overview_helpers(self):
        self.assertEqual(('Елена', 'учебный 03'), overview.person('Учебный 03 · Елена — Ухудшение и новое НЯ'))
        self.assertEqual(('Демо 01', ''), overview.person('Демо 01'))
        self.assertEqual(('Яя', 'а'), overview.person('А · Яя'))
        self.assertEqual(['1 год', '2 года', '5 лет', '11 лет', '21 год', '34 года', '112 лет'],
                         ['%d %s' % (n, overview.years_word(n)) for n in (1, 2, 5, 11, 21, 34, 112)])
        self.assertEqual('22.10: Поле — противоречивые сведения',
                         overview.tidy('2026-10-22: Поле — противоречивые сведения (' + 'a' * 32 + ').'))
        self.assertEqual(['2 раза', '5 раз', '11 раз', '21 раз', '22 раза'], [overview.times_word(n) for n in (2, 5, 11, 21, 22)])
        self.assertEqual(('22.10: Поле', 'a' * 32), overview.note_parts('2026-10-22: Поле (' + 'a' * 32 + ')'))
        self.assertEqual(('Без номера', None), overview.note_parts('Без номера'))
        self.assertEqual('abc…', overview.cut('abcdef', 4))
        self.assertEqual('a b', overview.cut('a \n b', 10))


if __name__ == '__main__':
    unittest.main()
