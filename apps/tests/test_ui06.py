"""UI06/S31: сообщения двух ролей, уведомления и отсутствие критического интерфейса."""
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
        self.assertNotIn('name="due_local"', doctor)
        self.assertNotIn('Запланировать пункт', doctor)

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

    def test_entry_link_resolves_and_task_context_has_no_removed_anchor(self):
        entry = records.save(self.db, {'id': 'pat-a', 'role': 'patient'}, 'D01', 'self_report',
                             {'request_key': secrets.token_hex(16), 'observed_on': records.today().isoformat(), 'wellbeing': 'worse'})
        task, _ = self.task()
        self.say(entry_id=entry, task_id=task['id'])
        doctor, patient = self.page(), self.page(who='pat-a')
        for who, page in [('doc-a', doctor), ('pat-a', patient)]:
            self.assertIn('/patients/D01/records/' + entry, page)
            response = self.clients[who].get('/patients/D01/records/' + entry)
            self.assertEqual(302, response.status_code)
            self.assertIn('id="entry-' + entry + '"', self.clients[who].get(response.location).text)
        for page in (doctor, patient):
            self.assertNotIn('href="#task-', page)
            self.assertNotIn('id="task-', page)
            self.assertIn(task['label'], page)
            self.assertIn(task['due_at'], page)

    # ---- пункты плана ----

    def test_plan_sections_removed_for_both_roles_without_deleting_history(self):
        for populated in (False, True):
            if populated:
                action = self.action()
                done, _ = self.task(action)
                self.task(action, due_at='2030-01-01T10:00:00+03:00')
                self.post('pat-a', URL + '/report', {'task_id': done['id'], 'request_key': secrets.token_hex(16),
                                                   'outcome': 'missed', 'reason': 'Причина-ПРОПУСКА'})
            for who in ('doc-a', 'pat-a'):
                for method in ('get', 'head'):
                    self.assertEqual(200, getattr(self.clients[who], method)(URL).status_code)
                page = self.page(who=who)
                for removed in ('Выполнение пунктов плана', 'Запланировать пункт', 'Доля выполненных пунктов',
                                'id="plan-items"', 'id="schedule"', '/communication/schedule', '/communication/report',
                                'name="due_local"', 'name="outcome"', 'Причина-ПРОПУСКА'):
                    self.assertNotIn(removed, page)
                self.assertIn('id="compose"', page)
                self.assertIn('Переписка', page)
        self.assertEqual(2, self.db.execute('SELECT count(*) FROM adherence_tasks').fetchone()[0])
        self.assertEqual(1, self.db.execute('SELECT count(*) FROM adherence_entries').fetchone()[0])

    def test_legacy_report_error_does_not_link_to_removed_form(self):
        task, _ = self.task()
        response = self.post('pat-a', URL + '/report', {'task_id': task['id'], 'request_key': secrets.token_hex(16), 'outcome': 'missed', 'reason': ''})
        self.assertEqual(400, response.status_code)
        page = response.get_data(as_text=True)
        self.assertIn('Отметка не сохранена', page)
        self.assertNotIn('Введённое осталось в форме', page)
        self.assertNotIn('href="#task-', page)
        self.assertNotIn('item-form', page)
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM adherence_entries').fetchone()[0])

    def test_legacy_schedule_preserves_moscow_time_and_uses_plain_error(self):
        action = self.action()
        data = {'action_id': action, 'request_key': secrets.token_hex(16), 'label': 'Синтетическое упражнение',
                'due_local': '2030-05-01T09:30', 'reviewed': 'yes'}
        self.assertEqual(303, self.post('doc-a', URL + '/schedule', data).status_code)
        self.assertEqual('2030-05-01T06:30:00.000000+00:00', self.db.execute('SELECT due_at FROM adherence_tasks').fetchone()[0])
        refused = self.post('doc-a', URL + '/schedule', {**data, 'request_key': secrets.token_hex(16), 'reviewed': '', 'label': 'ОСТАЛОСЬ-В-ФОРМЕ'})
        self.assertEqual(400, refused.status_code)
        page = refused.get_data(as_text=True)
        self.assertIn('Пункт не запланирован', page)
        self.assertNotIn('Введённое осталось в форме', page)
        self.assertNotIn('href="#schedule', page)
        self.assertEqual(1, self.db.execute('SELECT count(*) FROM adherence_tasks').fetchone()[0])
        self.assertEqual(403, self.post('pat-a', URL + '/schedule', data).status_code)

    def test_no_schedule_form_without_a_confirmed_treatment_plan(self):
        self.assertNotIn('id="schedule"', self.page())
        self.action(kind='referral')
        page = self.page()
        self.assertNotIn('id="schedule"', page)
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

    def test_removed_critical_page_redirects_without_recording_any_receipt(self):
        self.critical()
        doctor = self.clients_ready()['doc-a']
        for method in ('get', 'head'):
            response = getattr(doctor, method)('/critical')
            self.assertEqual(302, response.status_code)
            self.assertEqual('/', response.headers['Location'])
        row = self.db.execute('SELECT received_at,seen_at,acknowledged_at,reacted_at FROM critical_delivery').fetchone()
        self.assertTrue(all(v is None for v in row))

    def test_no_critical_ui_on_any_doctor_screen_even_with_a_stored_event(self):
        eid = self.critical()
        doctor = self.clients_ready()['doc-a']
        for path in ('/', '/notifications', '/demo/D01', '/patients/D01/follow-up', '/patients/D01/decisions',
                     '/patients/D01/first-visits', '/patients/D01/imports', URL):
            page = doctor.get(path).text
            for removed in ('Критические события', 'Критический сигнал', 'href="/critical',
                            'alert-band', 'receipt.js', 'name="reaction"', 'data-receipt-url', eid):
                self.assertNotIn(removed, page, path)
        self.assertEqual(1, self.db.execute('SELECT count(*) FROM critical_events').fetchone()[0])

    def test_removed_page_preserves_role_boundaries_and_has_no_script(self):
        clients = self.clients_ready()
        self.assertEqual(403, clients['pat-a'].get('/critical').status_code)
        self.assertEqual(302, clients['doc-b'].get('/critical').status_code)
        self.assertEqual(404, clients['doc-a'].get('/static/receipt.js').status_code)

    def test_legacy_server_operations_still_validate_order_length_and_do_not_change_treatment(self):
        eid = self.critical()
        doctor = self.clients_ready()['doc-a']
        csrf = test_access.csrf(doctor)
        self.assertEqual(409, doctor.post('/critical/%s/seen' % eid, data={'csrf': csrf}).status_code)
        for action, status in (('received', 204), ('seen', 303), ('acknowledged', 303)):
            self.assertEqual(status, doctor.post('/critical/%s/%s' % (eid, action), data={'csrf': csrf}).status_code)
        refused = doctor.post('/critical/%s/reacted' % eid, data={'csrf': csrf, 'reaction': 'коротко'})
        self.assertEqual(400, refused.status_code)
        self.assertIsNone(self.db.execute('SELECT reacted_at FROM critical_delivery').fetchone()[0])
        accepted = doctor.post('/critical/%s/reacted' % eid, data={'csrf': csrf, 'reaction': 'Синтетическая фактическая реакция'})
        self.assertEqual(303, accepted.status_code)
        self.assertEqual('/', accepted.headers['Location'])
        self.assertEqual('Синтетическая фактическая реакция', self.db.execute('SELECT reaction FROM critical_delivery').fetchone()[0])
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])

    def test_removed_notifications_redirect_without_delivery_and_leave_patient_records(self):
        entry = records.save(self.db, {'id': 'pat-a', 'role': 'patient'}, 'D01', 'self_report',
                             {'request_key': secrets.token_hex(16), 'observed_on': records.today().isoformat(),
                              'summary': 'Сохранённая запись пациента', 'wellbeing': 'unknown'})
        while events.process_one(self.db):
            pass
        doctor = self.clients_ready()['doc-a']
        before = dict(self.db.execute('SELECT * FROM routine_notifications WHERE id=?', (entry,)).fetchone())
        for method in ('get', 'head'):
            response = getattr(doctor, method)('/notifications')
            self.assertEqual(302, response.status_code)
            self.assertEqual('/', response.headers['Location'])
        for path in ('/', '/demo/D01', '/patients/D01/follow-up', '/patients/D01/decisions',
                     '/patients/D01/first-visits', '/patients/D01/imports', URL, '/invitations/new'):
            response = doctor.get(path)
            self.assertEqual(200, response.status_code, path)
            for removed in ('href="/notifications', 'Отметить: просмотрено', 'Отметить: принято',
                            'Просмотрено вами', 'Принято вами', 'ждут отметки'):
                self.assertNotIn(removed, response.text, path)
        self.assertIn('Сохранённая запись пациента', doctor.get('/demo/D01').text)
        self.assertIn('Нужно проверить', doctor.get('/').text)
        after = dict(self.db.execute('SELECT * FROM routine_notifications WHERE id=?', (entry,)).fetchone())
        self.assertEqual(before, after)

    def test_doctor_pages_do_not_mark_notifications_as_shown(self):
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
