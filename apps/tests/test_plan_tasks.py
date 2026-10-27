"""Recommendation marking through patient plan; synthetic data only."""
import secrets
import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from apps.compass import communication, decisions, plan_tasks, records, access, follow_up
from apps.compass.db import connect
from apps.compass.web import create_app
import test_communication


class PlanTaskTests(unittest.TestCase):
    setUp = test_communication.CommunicationTests.setUp
    tearDown = test_communication.CommunicationTests.tearDown
    post = test_communication.CommunicationTests.post
    offer = test_communication.CommunicationTests.offer
    link = test_communication.CommunicationTests.link
    values = test_communication.CommunicationTests.values
    draft = test_communication.CommunicationTests.draft
    confirm = test_communication.CommunicationTests.confirm
    action = test_communication.CommunicationTests.action
    task = test_communication.CommunicationTests.task
    url = '/patients/D01/communication'
    plan_url = '/patients/D01/decisions'
    tasks_url = '/patients/D01/plan-tasks'

    def add(self, **kw):
        action = kw.pop('action_id', None) or self.action()
        data = dict(action_id=action, request_key=secrets.token_hex(16),
                    label='Пройти вымышленное обследование', due_on=records.today().isoformat(), reviewed='yes')
        data.update(kw)
        response = self.post('doc-a', self.tasks_url, data)
        self.assertEqual(303, response.status_code, response.text)
        task = self.db.execute('SELECT * FROM adherence_tasks WHERE request_key=?', (data['request_key'],)).fetchone()
        return dict(task), data

    def mark(self, task, **kw):
        data = dict(request_key=secrets.token_hex(16), outcome='taken', revision='', reason='')
        data.update(kw)
        return self.post('pat-a', self.tasks_url+'/'+task['id']+'/report', data), data

    def test_native_end_to_end_doctor_sees_patient_and_history(self):
        t, _ = self.add()
        self.assertIn('id="task-'+t['id']+'"', self.clients['pat-a'].get(self.plan_url).text)
        self.assertEqual(303, self.mark(t, reason='Первый комментарий')[0].status_code)
        latest = self.db.execute('SELECT id FROM adherence_entries').fetchone()[0]
        self.assertEqual(303, self.mark(t, revision=latest, outcome='missed', reason='Исправление пациента')[0].status_code)
        for uid in ('pat-a', 'doc-a'):
            page = self.clients[uid].get(self.plan_url).text
            for text in (t['label'], 'Первый комментарий', 'Исправление пациента', 'Предыдущие отметки (1)'):
                self.assertIn(text, page)
            self.assertIn('Пропущено', page)
        self.assertEqual(2, self.db.execute('SELECT count(*) FROM adherence_entries').fetchone()[0])
        # Medication schedule and the physician's decision remain unchanged.
        self.assertEqual(1, self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])
        self.assertNotIn('Другие рекомендации', self.clients['doc-a'].get(self.url).text)

    def test_repeat_and_stale_tab_are_distinct(self):
        t, _ = self.add()
        response, form = self.mark(t)
        target = self.tasks_url+'/'+t['id']+'/report'
        self.assertEqual(303, response.status_code)
        self.assertEqual(303, self.post('pat-a', target, form).status_code)
        self.assertEqual(409, self.post('pat-a', target, {**form, 'reason':'different'}).status_code)
        response, _ = self.mark(t, outcome='missed', reason='Несохранённый текст')
        self.assertEqual(409, response.status_code)
        self.assertIn('Несохранённый текст', response.text)
        self.assertIn('Обновите страницу', response.text)
        self.assertEqual(1, self.db.execute('SELECT count(*) FROM adherence_entries').fetchone()[0])

    def test_correction_to_unknown_is_not_missed(self):
        t, _ = self.add()
        self.mark(t)
        latest = self.db.execute('SELECT id FROM adherence_entries').fetchone()[0]
        self.assertEqual(303, self.mark(t, revision=latest, outcome='unknown')[0].status_code)
        data = communication.view(self.db, {'id':'doc-a','role':'doctor'}, 'D01')
        self.assertEqual(0, data['counts']['missed'])
        self.assertEqual(1, data['counts']['unknown'])
        self.assertIsNone(data['counts']['percent'])

    def test_role_relationship_csrf_and_foreign_task_guards(self):
        t, data = self.add()
        target = self.tasks_url+'/'+t['id']+'/report'
        form = dict(request_key=secrets.token_hex(16), outcome='taken', revision='')
        self.assertEqual(403, self.post('doc-a', target, form).status_code)
        self.assertEqual(403, self.post('pat-a', self.tasks_url, data).status_code)
        self.assertEqual(404, self.post('pat-b', target, form).status_code)
        self.assertEqual(404, self.post('doc-b', self.tasks_url, data).status_code)
        self.assertEqual(403, self.clients['pat-a'].post(target, data=form).status_code)
        self.assertEqual(404, self.post('pat-a', self.tasks_url+'/foreign/report', form).status_code)
        self.db.execute("UPDATE care_relationships SET ends_at='2000-01-01'")
        self.assertEqual(409, self.post('pat-a', target, form).status_code)
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM adherence_entries').fetchone()[0])

    def test_future_items_accept_answer_without_claiming_completion(self):
        t, _ = self.add(due_on='2030-01-01')
        for uid in ('pat-a', 'doc-a'):
            page = self.clients[uid].get(self.plan_url).text
            self.assertIn(t['label'], page)
            self.assertIn('впереди', page)
        self.assertIn(self.tasks_url+'/'+t['id']+'/report', self.clients['pat-a'].get(self.plan_url).text)
        response, form = self.mark(t, outcome='unknown', reason='Заснул в 23:40. Вопрос к следующему приёму.')
        self.assertEqual(303, response.status_code)
        for uid in ('pat-a', 'doc-a'):
            page = self.clients[uid].get(self.plan_url).text
            self.assertIn(form['reason'], page)
            self.assertIn('Выполнение не отмечено', page)
        self.assertEqual(303, self.post('pat-a', self.tasks_url+'/'+t['id']+'/report', form).status_code)
        self.assertEqual(1, self.db.execute('SELECT count(*) FROM adherence_entries').fetchone()[0])

    def test_replaced_future_plan_blocked_with_history_retained(self):
        t, _ = self.add(due_on='2030-01-01')
        self.action(kind='plan_change')
        self.assertEqual(409, self.mark(t)[0].status_code)
        self.assertIn('предыдущего плана', self.clients['pat-a'].get(self.plan_url).text)
        self.assertIn(t['label'], self.clients['doc-a'].get(self.plan_url).text)

    def test_only_current_approved_decision_can_supply_items(self):
        draft = self.draft()
        form = dict(action_id=draft['id'], request_key=secrets.token_hex(16), label='Тест', due_on=records.today().isoformat(), reviewed='yes')
        self.assertEqual(409, self.post('doc-a', self.tasks_url, form).status_code)
        action = self.action()
        self.action(kind='plan_change')
        self.assertEqual(409, self.post('doc-a', self.tasks_url, {**form, 'action_id':action}).status_code)
        action = self.action(kind='therapy_stop')
        self.assertEqual(409, self.post('doc-a', self.tasks_url, {**form, 'action_id':action}).status_code)
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM adherence_tasks').fetchone()[0])

    def test_confirmed_referral_can_have_explicit_item(self):
        action = self.action(kind='referral')
        t, form = self.add(action_id=action)
        self.assertEqual(303, self.mark(t)[0].status_code)

    def test_input_errors_preserve_values_and_create_no_partial_rows(self):
        t, form = self.add()
        for change in ({'due_on':'2026-02-31'}, {'due_on':'1899-01-01'}, {'reviewed':''}, {'label':'x'*501}):
            response = self.post('doc-a', self.tasks_url, {**form, 'request_key':secrets.token_hex(16), **change})
            self.assertEqual(400, response.status_code)
            self.assertIn('Рекомендация не добавлена', response.text)
            self.assertIn('name="due_on"', response.text)
        for change in ({'outcome':'bad'}, {'outcome':'missed'}, {'outcome':'conflicting'}, {'reason':'x'*1001}, {'request_key':'bad'}):
            response, _ = self.mark(t, **change)
            self.assertEqual(400, response.status_code)
            self.assertIn('Отметка не сохранена', response.text)
        self.assertEqual(1, self.db.execute('SELECT count(*) FROM adherence_tasks').fetchone()[0])
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM adherence_entries').fetchone()[0])

    def test_new_observations_invalidate_open_physician_draft(self):
        t, _ = self.add()
        draft = self.draft(kind='plan_change')
        self.assertEqual(303, self.mark(t)[0].status_code)
        self.assertEqual(409, self.confirm(draft).status_code)

    def test_get_head_no_writes_and_escaping_private_basis_not_exposed(self):
        t, _ = self.add(label='<script>BAD</script>')
        self.mark(t, reason='<script>COMMENT</script>')
        before = tuple(self.db.execute('SELECT count(*) FROM audit_entries').fetchone())
        for uid in ('pat-a', 'doc-a'):
            for method in ('get', 'head'):
                self.assertEqual(200, getattr(self.clients[uid], method)(self.plan_url).status_code)
            html = self.clients[uid].get(self.plan_url).text
            self.assertIn('&lt;script&gt;BAD', html)
            self.assertNotIn('<script>BAD', html)
            self.assertNotIn('<script>COMMENT', html)
        self.assertEqual(before, tuple(self.db.execute('SELECT count(*) FROM audit_entries').fetchone()))
        self.assertNotIn('Почечная функция', self.clients['pat-a'].get(self.plan_url).text)

    def test_legacy_patient_and_doctor_marks_remain_visible(self):
        t, _ = self.task()
        communication.report(self.db, {'id':'doc-a','role':'doctor'}, 'D01', t['id'], dict(request_key=secrets.token_hex(16), outcome='taken', reason='Прежняя отметка врача'))
        data = plan_tasks.view(self.db, {'id':'pat-a','role':'patient'}, 'D01')
        self.assertEqual(t['id'], data['tasks'][0]['id'])
        self.assertEqual(1, data['tasks'][0]['version'])
        self.assertIn('Прежняя отметка врача', self.clients['pat-a'].get(self.plan_url).text)

    def test_restart_immutability_and_transaction_rollback(self):
        t, _ = self.add()
        form = dict(request_key=secrets.token_hex(16), outcome='taken', revision='', reason='')
        with patch.object(access, 'audit', side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError):
                communication.report(self.db, {'id':'pat-a','role':'patient'}, 'D01', t['id'], form, patient_only=True)
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM adherence_entries').fetchone()[0])
        self.assertEqual(303, self.mark(t)[0].status_code)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute('DELETE FROM adherence_entries')
        fresh = create_app(self.path).test_client()
        fresh.set_cookie(access.COOKIE, self.clients['pat-a'].get_cookie(access.COOKIE).value)
        self.assertIn('Выполнено', fresh.get(self.plan_url).text)
        self.assertEqual([], self.db.execute('PRAGMA foreign_key_check').fetchall())

    def test_simultaneous_corrections_reject_stale_revision(self):
        t, _ = self.add()
        def send(key):
            db = connect(self.path)
            try:
                communication.report(db, {'id':'pat-a','role':'patient'}, 'D01', t['id'], dict(request_key=key, outcome='taken', revision='', reason=''), patient_only=True)
                return 303
            except decisions.DecisionError as failure:
                return failure.status
            finally:
                db.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual([303,409], sorted(pool.map(send, [secrets.token_hex(16),secrets.token_hex(16)])))
        self.assertEqual(1, self.db.execute('SELECT count(*) FROM adherence_entries').fetchone()[0])

    def test_schedule_retry_and_changed_body(self):
        t, form = self.add()
        self.assertEqual(303, self.post('doc-a', self.tasks_url, form).status_code)
        self.assertEqual(409, self.post('doc-a', self.tasks_url, {**form, 'label':'Изменённый текст'}).status_code)
        self.assertEqual(1, self.db.execute('SELECT count(*) FROM adherence_tasks').fetchone()[0])

    def test_moscow_date_is_preserved_in_physician_projection(self):
        t, form = self.add()
        data = follow_up.view(self.db, {'id':'doc-a','role':'doctor'}, 'D01', {}, all_history=True)
        task = next(t0 for t0 in data['tasks'] if t0['id'] == t['id'])
        self.assertEqual(form['due_on'], task['due_day'])
        self.assertNotEqual(form['due_on'], task['due_at'][:10])
        page = self.clients['doc-a'].get(self.plan_url).text
        day = records.today().strftime('%d.%m')
        self.assertIn('>'+day+'</time>', page)

    def test_active_recommendations_precede_collapsed_previous_items(self):
        old, _ = self.add(due_on='2030-01-01', label='OLD-RECOMMENDATION')
        active, _ = self.add(label='CURRENT-RECOMMENDATION')
        html = self.clients['pat-a'].get(self.plan_url).text
        self.assertLess(html.index('id="task-'+active['id']), html.index('id="previous-recommendations"'))
        self.assertLess(html.index('id="previous-recommendations"'), html.index('id="task-'+old['id']))
        self.assertIn('История заданий и ответов (1)', html)

    def test_past_old_tasks_and_answers_are_read_only_history(self):
        old, _ = self.add(due_on='2020-01-01', label='PAST-OLD-ITEM')
        self.assertEqual(303, self.mark(old, reason='OLD-ANSWER')[0].status_code)
        current, _ = self.add(due_on='2030-01-01', label='CURRENT-ITEM')
        html = self.clients['pat-a'].get(self.plan_url).text
        self.assertIn('<details class="item-history" id="previous-recommendations">', html)
        self.assertLess(html.index('id="previous-recommendations"'), html.index('PAST-OLD-ITEM'))
        self.assertIn('OLD-ANSWER', html)
        self.assertNotIn(self.tasks_url+'/'+old['id']+'/report', html)
        self.assertIn(self.tasks_url+'/'+current['id']+'/report', html)
        self.assertEqual(409, self.mark(old, reason='STALE-TAB')[0].status_code)
        self.assertEqual(1, self.db.execute('SELECT count(*) FROM adherence_entries').fetchone()[0])
        # A current plan with no items must not bring back the old ones.
        self.action(kind='plan_change')
        html = self.clients['pat-a'].get(self.plan_url).text
        self.assertNotIn('class="recommendation-form"', html)
        self.assertIn('OLD-ANSWER', html)

    def test_doctor_current_plan_and_answers_precede_collapsed_history(self):
        old, _ = self.add(due_on='2020-01-01', label='OLD-DOCTOR-ITEM')
        self.mark(old, reason='OLD-DOCTOR-ANSWER')
        current, _ = self.add(label='CURRENT-DOCTOR-ITEM')
        self.mark(current, reason='CURRENT-DOCTOR-ANSWER')
        self.draft()  # An unconfirmed project must not replace the current plan.
        html = self.clients['doc-a'].get(self.plan_url).text
        history = html.index('<details class="block plan-fold" id="history">')
        self.assertLess(html.index('id="current"'), html.index('id="fu-plan"'))
        self.assertLess(html.index('CURRENT-DOCTOR-ANSWER'), html.index('id="waiting"'))
        self.assertLess(html.index('CURRENT-DOCTOR-ANSWER'), history)
        self.assertGreater(html.index('OLD-DOCTOR-ANSWER'), history)
        self.assertGreater(html.index('id="task-'+old['id']), history)
        self.assertEqual(1, html.count('id="task-'+current['id']+'"'))
        self.assertEqual(1, html.count('id="task-'+old['id']+'"'))

    def test_patient_without_relationship_gets_no_marks_or_private_context(self):
        self.db.execute("UPDATE care_relationships SET ends_at='2000-01-01'")
        page = self.clients['pat-a'].get(self.plan_url)
        self.assertEqual(200, page.status_code)
        self.assertNotIn('name="revision"', page.text)
        self.assertNotIn('Добавить рекомендацию', page.text)

    def test_obsolete_form_retains_comment_even_when_task_becomes_read_only(self):
        t, _ = self.add(due_on='2030-01-01')
        self.action(kind='plan_change')
        response, _ = self.mark(t, reason='Несохранённый комментарий <проверка>')
        self.assertEqual(409, response.status_code)
        self.assertIn('Ваш несохранённый комментарий: Несохранённый комментарий &lt;проверка&gt;', response.text)
        self.assertNotIn(self.tasks_url+'/'+t['id']+'/report', response.text)
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM adherence_entries').fetchone()[0])

    def test_obsolete_physician_form_retains_text_after_therapy_stop(self):
        t, form = self.add()
        self.action(kind='therapy_stop')
        response = self.post('doc-a', self.tasks_url, {**form, 'request_key':secrets.token_hex(16), 'label':'Несохранённая рекомендация <проверка>'})
        self.assertEqual(409, response.status_code)
        self.assertIn('Несохранённая рекомендация &lt;проверка&gt;', response.text)
        self.assertNotIn('id="add-recommendation"', response.text)
        self.assertEqual(1, self.db.execute('SELECT count(*) FROM adherence_tasks').fetchone()[0])
