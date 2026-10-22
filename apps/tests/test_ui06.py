"""UI06: сообщения (обе роли), уведомления и критические события врача. Разметка, три состояния, безопасный повтор, ошибки без потери введённого."""
import re
import secrets
import unittest

from apps.compass import critical_delivery as delivery, events, records
from apps.compass.db import now
import test_access
import test_clinical_rules
import test_communication
import test_decisions

URL = '/patients/D01/communication'


class MessagesTests(unittest.TestCase):
    setUp = test_decisions.DecisionTests.setUp
    tearDown = test_access.AccessTests.tearDown
    post = test_access.AccessTests.post
    offer = test_access.AccessTests.offer
    link = test_access.AccessTests.link
    values = test_decisions.DecisionTests.values
    draft = test_decisions.DecisionTests.draft
    confirm = test_decisions.DecisionTests.confirm
    action = test_communication.CommunicationTests.action
    task = test_communication.CommunicationTests.task
    url = URL

    def page(self, path=URL, who='doc-a', status=200):
        response = self.clients[who].get(path)
        self.assertEqual(status, response.status_code, path)
        return response.get_data(as_text=True)

    def say(self, who='pat-a', body='Синтетическое сообщение', **extra):
        data = {'request_key': secrets.token_hex(16), 'body': body, **extra}
        return self.post(who, URL + '/send', data), data

    # ---- обе роли, один экран ----

    def test_both_roles_get_their_own_shell_and_navigation(self):
        doctor, patient = self.page(), self.page(who='pat-a')
        self.assertIn('aria-label="Разделы пациента"', doctor)
        self.assertRegex(doctor, r'<a href="/patients/D01/communication" aria-current="page">Сообщения</a>')
        self.assertNotIn('p-tabs', doctor)
        nav = re.search(r'<nav class="p-tabs".*?</nav>', patient, re.S).group(0)
        self.assertRegex(nav, r'<a href="/patients/D01/communication" aria-current="page">Сообщения</a>')
        self.assertNotIn('aria-label="Разделы пациента"', patient)
        for page in (doctor, patient):
            self.assertEqual(1, page.count('<h1>Сообщения</h1>'))
            self.assertNotIn(' style=', page)
            self.assertNotIn('<script>', page.replace('<script src', ''))
        ids = re.findall(r'\sid="([^"]+)"', doctor)
        self.assertEqual(len(ids), len(set(ids)), 'повторяющиеся id')

    def test_patient_never_gets_doctor_only_controls_or_plan_text(self):
        action = self.action()
        self.task(action)
        patient = self.page(who='pat-a')
        self.assertNotIn('Запланировать', patient)
        self.assertNotIn('name="due_local"', patient)
        self.assertNotIn(self.db.execute('SELECT payload_json FROM proposals').fetchone()[0][:30], patient)
        doctor = self.page()
        self.assertIn('name="due_local"', doctor)
        self.assertIn('Запланировать пункт', doctor)

    def test_messages_are_isolated_between_cabinets(self):
        self.say(body='ЛИЧНОЕ-ОДНО')
        for who in ('pat-b', 'doc-b'):
            self.assertEqual(404, self.clients[who].get(URL).status_code)
        self.assertEqual(302, self.app.test_client().get(URL).status_code)

    # ---- три состояния сообщения ----

    def test_three_states_are_three_separate_lines_and_receipts_are_recipient_only(self):
        self.say()
        mid = self.db.execute('SELECT id FROM messages').fetchone()[0]
        sender, recipient = self.page(who='pat-a'), self.page()
        # автору состояние описывает адресата, адресату — его собственные отметки
        for page, got, read in ((sender, 'Получено адресатом', 'Прочитано адресатом'), (recipient, 'Получено вами', 'Прочитано вами')):
            self.assertEqual(1, page.count('<span class="state state--known">Сохранено на сервере</span>'))
            self.assertIn(got + ': не отмечено', page)
            self.assertIn(read + ': не отмечено', page)
            self.assertIn('Получение и прочтение не означает реакцию врача', page)
        # кнопки отметок есть у адресата и нет у автора
        self.assertIn('/communication/received', recipient)
        self.assertIn('/communication/read', recipient)
        self.assertNotIn('/communication/received', sender)
        self.assertNotIn('/communication/read', sender)
        self.assertIn('aria-label="Отметить прочитанным сообщение от ', recipient)  # у каждой кнопки названо, какое сообщение
        # получено: время вместо «не отмечено», кнопка «получено» исчезает, «прочитано» остаётся
        response = self.post('doc-a', URL + '/received', {'message_id': mid})
        self.assertEqual(303, response.status_code)
        self.assertTrue(response.headers['Location'].endswith(URL + '#message-' + mid))
        recipient = self.page()
        self.assertNotIn('Получено вами: не отмечено', recipient)
        self.assertRegex(recipient, r'Получено вами: <time class="num" datetime="[^"]+">\d\d\.\d\d\.\d{4}')
        self.assertIn('Прочитано вами: не отмечено', recipient)
        self.assertNotIn('/communication/received', recipient)
        self.assertIn('/communication/read', recipient)
        self.assertRegex(self.page(who='pat-a'), r'Получено адресатом: <time')
        self.post('doc-a', URL + '/read', {'message_id': mid})
        recipient = self.page()
        self.assertNotIn('не отмечено', re.search(r'<ul class="msg-states".*?</ul>', recipient, re.S).group(0))
        self.assertNotIn('/communication/read', recipient)
        self.assertRegex(self.page(who='pat-a'), r'Прочитано адресатом: <time')

    def test_opening_the_screen_never_marks_anything(self):
        self.say()
        for method in ('get', 'head'):
            getattr(self.clients['doc-a'], method)(URL)
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM message_receipts').fetchone()[0])

    def test_newest_first_and_authors_named_by_words_not_only_by_look(self):
        self.say(body='ПЕРВОЕ')
        self.say('doc-a', body='ВТОРОЕ')
        page = self.page()
        self.assertLess(page.index('ВТОРОЕ'), page.index('ПЕРВОЕ'))
        self.assertIn('<b translate="no">Вы</b>', page)
        self.assertIn('Пациент ', page)
        self.assertIn('Врач ', self.page(who='pat-a'))

    # ---- отправка и повтор ----

    def test_retry_with_the_same_key_never_duplicates_and_different_text_is_refused_visibly(self):
        response, data = self.say()
        self.assertEqual(303, response.status_code)
        self.assertEqual(303, self.post('pat-a', URL + '/send', data).status_code)
        self.assertEqual(1, self.db.execute('SELECT count(*) FROM messages').fetchone()[0])
        refused = self.post('pat-a', URL + '/send', {**data, 'body': 'Другой текст'})
        self.assertEqual(409, refused.status_code)
        page = refused.get_data(as_text=True)
        self.assertIn('Сообщение не отправлено', page)
        self.assertIn('Ключ уже использован с другим содержимым', page)
        self.assertIn('Другой текст', page)  # введённое осталось в поле
        key = re.search(r'name="request_key" value="([0-9a-f]{32})"', page.split('id="compose"')[1]).group(1)
        self.assertNotEqual(data['request_key'], key)  # после отказа форма получает новый ключ
        self.assertEqual(303, self.post('pat-a', URL + '/send', {'request_key': key, 'body': 'Другой текст'}).status_code)
        self.assertEqual(2, self.db.execute('SELECT count(*) FROM messages').fetchone()[0])

    def test_empty_message_returns_to_the_screen_with_a_reason(self):
        response = self.post('pat-a', URL + '/send', {'request_key': secrets.token_hex(16), 'body': '   '})
        self.assertGreaterEqual(response.status_code, 400)
        self.assertLess(response.status_code, 500)
        page = response.get_data(as_text=True)
        self.assertIn('Сообщение не отправлено', page)
        self.assertIn('id="compose"', page)
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM messages').fetchone()[0])

    def test_text_is_escaped_and_long_unbroken_text_keeps_the_page_whole(self):
        self.say(body='<script>x()</script>' + 'Ж' * 3000)
        page = self.page()
        self.assertIn('&lt;script&gt;x()&lt;/script&gt;', page)
        self.assertNotIn('<script>x()', page)
        self.assertIn('class="msg-body keep"', page)

    def test_links_to_entry_and_task_resolve_on_the_screen(self):
        entry = records.save(self.db, {'id': 'pat-a', 'role': 'patient'}, 'D01', 'self_report',
                             {'request_key': secrets.token_hex(16), 'observed_on': records.today().isoformat(), 'wellbeing': 'worse'})
        task, _ = self.task()
        self.say(entry_id=entry, task_id=task['id'])
        doctor, patient = self.page(), self.page(who='pat-a')
        self.assertIn('/demo/D01#entry-' + entry, doctor)
        self.assertIn('/demo/D01/diary#entry-' + entry, patient)
        for page in (doctor, patient):
            self.assertIn('href="#task-' + task['id'] + '"', page)
            self.assertIn('id="task-' + task['id'] + '"', page)

    # ---- пункты плана ----

    def test_plan_items_show_denominator_states_history_and_correction(self):
        page = self.page()
        self.assertIn('Пунктов плана пока нет', page)
        action = self.action()
        done, _ = self.task(action)
        self.task(action, due_at='2030-01-01T10:00:00+03:00')
        page = self.page()
        self.assertIn('не рассчитывается: знаменатель 0', page)
        self.assertIn('Срок не наступил', page)
        self.assertIn('Отметить результат можно после срока', page)
        self.assertEqual(303, self.post('pat-a', URL + '/report', {'task_id': done['id'], 'request_key': secrets.token_hex(16),
                                                                   'outcome': 'missed', 'reason': 'Причина-ПРОПУСКА'}).status_code)
        page = self.page(who='pat-a')
        self.assertIn('0.0% (0 / 1)', page)
        self.assertIn('Причина-ПРОПУСКА', page)
        self.assertIn('История отметок (1)', page)
        self.assertEqual(303, self.post('doc-a', URL + '/report', {'task_id': done['id'], 'request_key': secrets.token_hex(16),
                                                                   'outcome': 'taken', 'reason': 'Уточнено с пациентом'}).status_code)
        page = self.page()
        self.assertIn('100.0% (1 / 1)', page)
        self.assertIn('История отметок (2)', page)

    def test_report_without_reason_returns_to_the_item_with_what_was_typed(self):
        task, _ = self.task()
        response = self.post('pat-a', URL + '/report', {'task_id': task['id'], 'request_key': secrets.token_hex(16), 'outcome': 'missed', 'reason': ''})
        self.assertEqual(400, response.status_code)
        page = response.get_data(as_text=True)
        self.assertIn('Отметка не сохранена', page)
        self.assertRegex(page, r'<details class="fold item-form" open>')
        self.assertRegex(page, r'value="missed" checked')
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM adherence_entries').fetchone()[0])

    def test_schedule_accepts_a_browser_time_as_moscow_and_keeps_input_on_refusal(self):
        action = self.action()
        data = {'action_id': action, 'request_key': secrets.token_hex(16), 'label': 'Синтетическое упражнение',
                'due_local': '2030-05-01T09:30', 'reviewed': 'yes'}
        self.assertEqual(303, self.post('doc-a', URL + '/schedule', data).status_code)
        self.assertEqual('2030-05-01T06:30:00.000000+00:00', self.db.execute('SELECT due_at FROM adherence_tasks').fetchone()[0])
        refused = self.post('doc-a', URL + '/schedule', {**data, 'request_key': secrets.token_hex(16), 'reviewed': '', 'label': 'ОСТАЛОСЬ-В-ФОРМЕ'})
        self.assertEqual(400, refused.status_code)
        page = refused.get_data(as_text=True)
        self.assertIn('Пункт не запланирован', page)
        self.assertIn('ОСТАЛОСЬ-В-ФОРМЕ', page)
        self.assertEqual(1, self.db.execute('SELECT count(*) FROM adherence_tasks').fetchone()[0])
        self.assertEqual(403, self.post('pat-a', URL + '/schedule', data).status_code)

    def test_no_schedule_form_without_a_confirmed_treatment_plan(self):
        self.assertIn('Подтверждённого плана нет, пункты не задать', self.page())
        self.action(kind='referral')
        page = self.page()
        self.assertIn('Пункт запланировать нельзя', page)
        self.assertNotIn('name="due_local"', page)

    def test_relationship_ended_gives_the_plain_result_page(self):
        self.db.execute("UPDATE care_relationships SET ends_at='2000-01-01'")
        self.assertEqual(404, self.clients['doc-a'].get(URL).status_code)  # врач больше не видит карточку
        gone = self.clients['pat-a'].get(URL)  # пациент видит свою карточку, но связи нет
        self.assertEqual(409, gone.status_code)
        self.assertIn('Нужна действующая связь двух кабинетов', gone.get_data(as_text=True))


class InboxTests(unittest.TestCase):
    """Уведомления и критические события врача."""
    setUp = test_clinical_rules.ClinicalRuleTests.setUp
    tearDown = test_clinical_rules.ClinicalRuleTests.tearDown
    context = test_clinical_rules.ClinicalRuleTests.context
    context_form = test_clinical_rules.ClinicalRuleTests.context_form
    form = test_clinical_rules.ClinicalRuleTests.form
    save = test_clinical_rules.ClinicalRuleTests.save

    def clients_ready(self):
        from apps.compass.web import create_app
        app = create_app(self.tmp.name + '/db.sqlite3')
        clients = {u: app.test_client() for u in ('doc-a', 'doc-b', 'pat-a')}
        for uid, client in clients.items():
            test_access.login(client, uid)
        return clients

    def critical(self):
        self.save()
        while events.process_one(self.db):
            pass
        return self.db.execute('SELECT id FROM critical_events ORDER BY created_at DESC LIMIT 1').fetchone()[0]

    def test_critical_steps_are_ordered_each_with_its_own_server_button(self):
        eid = self.critical()
        doctor = self.clients_ready()['doc-a']
        page = doctor.get('/critical').get_data(as_text=True)
        self.assertIn('Ждёт подтверждения', page)
        self.assertIn('Получено на экране врача: ещё нет', page)
        self.assertIn('data-receipt-url="/critical/%s/received"' % eid, page)
        self.assertIn('name="back"', page)  # форма без скрипта возвращает на страницу
        self.assertNotIn('/critical/%s/seen' % eid, page)  # следующий шаг не раньше предыдущего
        self.assertIn('receipt.js', page)
        csrf = test_access.csrf(doctor)
        self.assertEqual(204, doctor.post('/critical/%s/received' % eid, data={'csrf': csrf}).status_code)
        back = doctor.post('/critical/%s/received' % eid, data={'csrf': csrf, 'back': '1'})
        self.assertEqual(303, back.status_code)
        self.assertTrue(back.headers['Location'].endswith('/critical#event-' + eid))
        page = doctor.get('/critical').get_data(as_text=True)
        self.assertNotIn('data-receipt-url', page)
        self.assertIn('/critical/%s/seen' % eid, page)
        self.assertNotIn('/critical/%s/acknowledged' % eid, page)
        for action, hint in (('seen', 'acknowledged'), ('acknowledged', 'reacted')):
            self.assertEqual(303, doctor.post('/critical/%s/%s' % (eid, action), data={'csrf': csrf}).status_code)
            page = doctor.get('/critical').get_data(as_text=True)
            self.assertIn('/critical/%s/%s' % (eid, hint), page)
        self.assertIn('Реакция не записана', page)
        self.assertIn('name="reaction"', page)

    def test_reaction_too_short_comes_back_on_the_screen_with_the_text(self):
        eid = self.critical()
        doctor = self.clients_ready()['doc-a']
        csrf = test_access.csrf(doctor)
        for action in ('received', 'seen', 'acknowledged'):
            doctor.post('/critical/%s/%s' % (eid, action), data={'csrf': csrf})
        refused = doctor.post('/critical/%s/reacted' % eid, data={'csrf': csrf, 'reaction': 'коротко'})
        self.assertEqual(400, refused.status_code)
        page = refused.get_data(as_text=True)
        self.assertIn('Реакция не записана', page)
        self.assertIn('коротко', page)
        self.assertIsNone(self.db.execute('SELECT reacted_at FROM critical_delivery').fetchone()[0])
        self.assertEqual(303, doctor.post('/critical/%s/reacted' % eid, data={'csrf': csrf, 'reaction': 'Синтетическая фактическая реакция'}).status_code)
        page = doctor.get('/critical').get_data(as_text=True)
        self.assertIn('Закрыто записью реакции', page)
        self.assertIn('Синтетическая фактическая реакция', page)

    def test_banner_and_menu_counter_follow_unacknowledged_events_on_every_doctor_screen(self):
        eid = self.critical()
        doctor = self.clients_ready()['doc-a']
        for path in ('/', '/notifications', '/demo/D01', '/patients/D01/decisions', URL):
            page = doctor.get(path).get_data(as_text=True)
            self.assertIn('class="alert-band" role="region" aria-label="Критические события"', page, path)
            self.assertRegex(page, r'<a href="/critical">Критические события <span class="count count--alert num">1</span>', path)
        self.assertNotIn('alert-band', doctor.get('/critical').get_data(as_text=True))  # на своём экране полосы нет
        csrf = test_access.csrf(doctor)
        for action in ('received', 'seen', 'acknowledged'):
            doctor.post('/critical/%s/%s' % (eid, action), data={'csrf': csrf})
        self.assertNotIn('alert-band', doctor.get('/').get_data(as_text=True))
        self.assertNotRegex(doctor.get('/').get_data(as_text=True), r'Критические события <span class="count')

    def test_other_doctor_and_patient_see_no_critical_event_or_banner(self):
        eid = self.critical()
        clients = self.clients_ready()
        other = clients['doc-b'].get('/critical').get_data(as_text=True)
        self.assertNotIn(eid, other)
        self.assertNotIn('alert-band', clients['doc-b'].get('/').get_data(as_text=True))
        self.assertEqual(403, clients['pat-a'].get('/critical').status_code)
        self.assertNotIn('alert-band', clients['pat-a'].get('/demo/D01').get_data(as_text=True))

    def test_open_events_come_before_the_reference_text_and_buttons_name_their_event(self):
        eid = self.critical()
        doctor = self.clients_ready()['doc-a']
        csrf = test_access.csrf(doctor)
        doctor.post('/critical/%s/received' % eid, data={'csrf': csrf})
        page = doctor.get('/critical').get_data(as_text=True)
        self.assertLess(page.index('id="event-%s"' % eid), page.index('Справка и числа'))
        self.assertRegex(page, r'aria-label="Отметить: просмотрено: [^"]+, событие от ')
        self.assertNotIn('Страница сама отправит', page)
        self.assertIn('data-receipt-status hidden', page)
        self.assertRegex(page, r'<section class="block" data-receipt-status hidden>\s*<div class="notice notice--error" role="alert">')
        doctor.post('/critical/%s/seen' % eid, data={'csrf': csrf})
        page = doctor.get('/critical').get_data(as_text=True)
        self.assertIn('Подтвердить событие', page)
        self.assertNotIn('событие принято', page)

    def test_reaction_field_asks_the_browser_for_the_length_the_server_requires(self):
        eid = self.critical()
        doctor = self.clients_ready()['doc-a']
        csrf = test_access.csrf(doctor)
        for action in ('received', 'seen', 'acknowledged'):
            doctor.post('/critical/%s/%s' % (eid, action), data={'csrf': csrf})
        self.assertRegex(doctor.get('/critical').get_data(as_text=True), r'<textarea[^>]*maxlength="2000"[^>]*minlength="10"')

    def test_empty_critical_screen_does_not_say_all_is_well(self):
        page = self.clients_ready()['doc-a'].get('/critical').get_data(as_text=True)
        self.assertIn('Это не означает отсутствия риска', page)
        self.assertIn('Учебная демонстрация, не служба 24/7', page)

    def test_journal_and_reserve_state_are_readable_words(self):
        self.critical()
        delivery.reserve_one(self.db, 'doc-a', sender=lambda: None)
        page = self.clients_ready()['doc-a'].get('/critical').get_data(as_text=True)
        self.assertIn('Готово к показу', page)
        self.assertIn('Резервный сигнал: оператор отметил получение', page)
        self.assertIn('оператор на этом компьютере отметил получение; это не реакция врача', page)

    def test_notifications_list_chain_buttons_and_counters(self):
        from apps.compass import access
        access.accept_invite  # связь уже есть в наборе ClinicalRuleTests
        entry = records.save(self.db, {'id': 'pat-a', 'role': 'patient'}, 'D01', 'self_report',
                             {'request_key': secrets.token_hex(16), 'observed_on': records.today().isoformat(),
                              'summary': '<b>Текст-отметки</b>', 'wellbeing': 'unknown'})
        doctor = self.clients_ready()['doc-a']
        page = doctor.get('/notifications').get_data(as_text=True)
        self.assertIn('Ещё готовятся', page)  # воркер ещё не обработал событие
        self.assertNotIn('/notifications/%s/seen' % entry, page)
        while events.process_one(self.db):
            pass
        self.assertRegex(doctor.get('/').get_data(as_text=True), r'<a href="/notifications">Уведомления <span class="count num">1</span>')
        page = doctor.get('/notifications').get_data(as_text=True)
        self.assertIn('&lt;b&gt;Текст-отметки&lt;/b&gt;', page)
        self.assertIn('Выдано на страницу: <time', page)
        self.assertIn('Просмотрено вами: не отмечено', page)
        self.assertIn('/notifications/%s/seen' % entry, page)
        self.assertNotIn('/notifications/%s/acknowledged' % entry, page)
        csrf = test_access.csrf(doctor)
        seen = doctor.post('/notifications/%s/seen' % entry, data={'csrf': csrf})
        self.assertEqual(303, seen.status_code)
        self.assertTrue(seen.headers['Location'].endswith('/notifications#notification-' + entry))
        page = doctor.get('/notifications').get_data(as_text=True)
        self.assertIn('/notifications/%s/acknowledged' % entry, page)
        doctor.post('/notifications/%s/acknowledged' % entry, data={'csrf': csrf})
        page = doctor.get('/notifications').get_data(as_text=True)
        self.assertIn('Показать принятые (1)', page)
        self.assertNotRegex(doctor.get('/').get_data(as_text=True), r'<a href="/notifications">Уведомления <span class="count')

    def test_menu_counter_does_not_mark_notifications_as_shown(self):
        entry = records.save(self.db, {'id': 'pat-a', 'role': 'patient'}, 'D01', 'self_report',
                             {'request_key': secrets.token_hex(16), 'observed_on': records.today().isoformat(), 'wellbeing': 'unknown'})
        while events.process_one(self.db):
            pass
        doctor = self.clients_ready()['doc-a']
        for path in ('/', '/demo/D01'):
            doctor.get(path)
        self.assertIsNone(self.db.execute('SELECT delivered_at FROM routine_notifications WHERE id=?', (entry,)).fetchone()[0])

    def test_notifications_and_critical_are_for_the_doctor_role_only_and_stay_json_technical(self):
        clients = self.clients_ready()
        for path in ('/notifications', '/critical'):
            self.assertEqual(403, clients['pat-a'].get(path).status_code, path)
            technical = clients['doc-a'].get(path, headers={'Accept': 'application/json'})
            self.assertEqual(503, technical.status_code, path)
            self.assertEqual('interface_removed', technical.json['status'])
        self.assertEqual([], clients['doc-a'].get('/api/critical').json)


if __name__ == '__main__':
    unittest.main()
