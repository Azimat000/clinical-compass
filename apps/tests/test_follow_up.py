"""Synthetic acceptance of a read-only, physician-only follow-up projection."""
from datetime import timedelta, datetime, timezone
import json
import secrets
import unittest
from unittest.mock import patch
from apps.compass import follow_up, records, assessments, access, decisions, first_visits
from apps.compass.web import create_app
import test_decisions
import test_communication


class FollowUpTests(unittest.TestCase):
    setUp = test_decisions.DecisionTests.setUp
    tearDown = test_decisions.DecisionTests.tearDown
    post = test_decisions.DecisionTests.post
    offer = test_decisions.DecisionTests.offer
    link = test_decisions.DecisionTests.link
    values = test_decisions.DecisionTests.values
    draft = test_decisions.DecisionTests.draft
    confirm = test_decisions.DecisionTests.confirm
    action = test_communication.CommunicationTests.action
    task = test_communication.CommunicationTests.task
    url = '/patients/D01/communication'
    summary = '/patients/D01/follow-up'

    def view(self, start=None, end=None):
        return follow_up.view(self.db, {'id':'doc-a','role':'doctor'}, 'D01',
                              {} if start is None else {'start':start,'end':end or start})

    def entry(self, day=None, uid='pat-a', **kw):
        return records.save(self.db, {'id':uid,'role':'patient' if uid=='pat-a' else 'doctor'},
            'D01', 'self_report' if uid=='pat-a' else 'visit',
            {'observed_on':day or records.today().isoformat(),'request_key':secrets.token_hex(16),**kw})

    def assessment(self, incomplete=False):
        f=assessments.definition()
        self.assertEqual(303,self.post('doc-a','/patients/D01/assessment-requests',{
            'assignment_key':secrets.token_hex(16),'form_version_id':f['id'],
            'age_status':'known','age_years':'35','age_basis':'Синтетический профиль'}).status_code)
        rid=self.db.execute('SELECT id FROM assessment_requests ORDER BY requested_at DESC LIMIT 1').fetchone()[0]
        self.assertEqual(303,self.post('pat-a','/assessments/'+rid,{'form_version_id':f['id'],
            **{f'answer_{i}':('' if incomplete and i==1 else '2') for i in range(1,43)}}).status_code)

    def clinical_state(self):
        # Authentication renews sessions; every clinical/source/delivery table must stay byte-for-byte.
        return {r[0]:[tuple(x) for x in self.db.execute('SELECT * FROM "'+r[0]+'" ORDER BY rowid')]
            for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE '%search%' AND name NOT IN ('sessions','login_challenges','login_limits')")}

    def test_latest_mark_is_separate_from_previous_marks_and_links_to_the_diary(self):
        from apps.compass import communication
        import re
        action = self.action()
        task, _ = self.task(action)
        report = self.entry(follow_up.local_day(task['due_at']), summary='Самоотчёт есть; это не автоматическое выполнение плана')
        for outcome, reason in [('missed', 'ПРЕЖНЯЯ-ОТМЕТКА'), ('taken', 'ДЕЙСТВУЮЩАЯ-ОТМЕТКА')]:
            communication.report(self.db, {'id': 'pat-a', 'role': 'patient'}, 'D01', task['id'],
                                 {'request_key': secrets.token_hex(16), 'outcome': outcome, 'reason': reason})
        page = self.clients['doc-a'].get('/patients/D01/decisions').text
        self.assertIn('href="/demo/D01#entry-%s"' % report, page)
        self.assertIn('Предыдущие отметки (1)', page)
        visible = re.sub(r'<details\b.*?</details>', '', page, flags=re.S)
        self.assertIn('ДЕЙСТВУЮЩАЯ-ОТМЕТКА', visible)
        self.assertNotIn('ПРЕЖНЯЯ-ОТМЕТКА', visible)
        self.assertIn('ПРЕЖНЯЯ-ОТМЕТКА', page)

    def test_periods_incomplete_and_conflicting_records_with_attribution(self):
        day=records.today().isoformat();old=(records.today()-timedelta(days=2)).isoformat()
        a=self.entry(day,adverse_events_status='known',adverse_events_text='Вымышленное НЯ <script>bad()</script>')
        b=self.entry(day,'doc-a',adverse_events_status='denied')
        outside=self.entry(old,summary='OUTSIDE-INTERVAL')
        data=self.view(day)
        self.assertEqual({a},{e['id'] for e in data['entries']})
        self.assertEqual({b},{e['id'] for e in data['doctor_entries']})
        self.assertTrue(any('различаются сведения' in w for w in data['warnings']))
        self.assertEqual(0,data['missing_diary_days'])
        html=self.clients['doc-a'].get(self.summary,query_string={'start':day,'end':day}).text
        for value in ['doc-a','pat-a','Получено:',a,b,'Неизвестно','Явно отрицает','&lt;script&gt;']:
            self.assertIn(value,html)
        self.assertNotIn('<script>bad()',html);self.assertNotIn('OUTSIDE-INTERVAL',html)
        self.assertNotIn(outside,[e['id'] for e in data['entries']])
        self.assertEqual(1,len(self.view(old)['entries']))
        # Distinct days are not treated as conflicting observations.
        self.assertFalse(any('различаются сведения' in w for w in self.view(old)['warnings']))
        self.assertEqual(1,self.view((records.today()-timedelta(days=1)).isoformat())['missing_diary_days'])

    def test_dass_exact_period_complete_and_missing_without_zero_fill(self):
        self.assessment();self.assessment(incomplete=True)
        data=self.view();self.assertEqual(2,len(data['measured']))
        self.assertEqual(1,sum(a['scores'] is None for a in data['measured']))
        full=next(a for a in data['measured'] if a['scores'] is not None)
        self.assertEqual({'depression':28,'anxiety':28,'stress':28},full['scores'])
        html=self.clients['doc-a'].get(self.summary).text
        for a in data['measured']:
            self.assertIn(a['form']['period'],html);self.assertIn('id="assessment-'+a['id']+'"',html)
            self.assertIn(a['scoring_version'],html)
        self.assertIn('Есть пропуски. Ни одна сумма не рассчитана',html)
        self.assertIn('Возраст участников русского исследования не указан',html)
        patient=self.clients['pat-a'].get('/demo/D01').text
        self.assertNotIn('Депрессивные симптомы:',patient)
        self.assertNotIn('28 / 42',patient)

    def test_plan_anchor_changes_tasks_all_authors_and_late_corrections(self):
        today=records.today();start=today-timedelta(days=2)
        self.db.execute("UPDATE care_relationships SET starts_at='2020-01-01T00:00:00+00:00'")
        stamp=lambda day:day.isoformat()+'T09:00:00.000000+00:00'
        with patch.object(decisions,'now',return_value=stamp(today-timedelta(days=4))):
            anchor=self.action(kind='plan_change')
        task,_=self.task(anchor,due_at=stamp(start),label='Синтетический пункт')
        future,_=self.task(anchor,due_at=stamp(today+timedelta(days=2)))
        for uid,outcome in [('pat-a','missed'),('doc-a','conflicting')]:
            self.assertEqual(303,self.post(uid,self.url+'/report',{'task_id':task['id'],
                'request_key':secrets.token_hex(16),'outcome':outcome,'reason':'Синтетическое уточнение'}).status_code)
        head=self.action(kind='plan_change')
        self.draft(kind='plan_change',content='UNCONFIRMED-PROJECT')
        data=self.view(start.isoformat(),today.isoformat())
        self.assertEqual([anchor,head],[a['id'] for a in data['plans']]);self.assertTrue(data['plans'][0]['carried'])
        self.assertEqual([task['id']],[t['id'] for t in data['tasks']])
        self.assertEqual(['missed','conflicting'],[h['outcome'] for h in data['tasks'][0]['history']])
        self.assertEqual('conflicting',data['tasks'][0]['outcome'])
        self.assertTrue(any('последняя отметка — противоречие' in w for w in data['warnings']))
        html=self.clients['doc-a'].get('/patients/D01/decisions').text
        self.assertIn('Противоречие',html);self.assertIn('Пропущено',html)
        self.assertIn('doc-a',html);self.assertIn('pat-a',html)
        self.assertNotIn('UNCONFIRMED-PROJECT',self.clients['doc-a'].get(self.summary).text)
        # Superseded old tasks are retained, explicitly excluded, with their plan link.
        with patch.object(records,'today',return_value=today+timedelta(days=3)):
            data=self.view(today.isoformat(),(today+timedelta(days=3)).isoformat())
        self.assertTrue(next(t for t in data['tasks'] if t['id']==future['id'])['superseded'])

    def test_no_outcome_not_missed_no_plan_not_draft(self):
        draft=self.draft(kind='plan_change',content='ONLY-DRAFT')
        self.assertEqual([],self.view()['plans'])
        task,_=self.task()
        self.assertEqual('unknown',self.view()['tasks'][0]['outcome'])
        self.assertEqual([],self.view()['tasks'][0]['history'])
        html=self.clients['doc-a'].get('/patients/D01/decisions').text
        # UI12: no answer yet and no completion mark are shown as such, never as done.
        self.assertIn('Пациент пока не ответил.',html)
        self.assertIn('Выполнение не отмечено',html)
        self.assertNotIn('ONLY-DRAFT',self.clients['doc-a'].get(self.summary).text)

    def test_assessments_on_distinct_days_keep_their_own_period(self):
        past=records.today()-timedelta(days=7)
        self.db.execute("UPDATE patients SET created_at=? WHERE id='D01'",(past.isoformat()+'T00:00:00+00:00',))
        with patch.object(records,'today',return_value=past):
            self.assessment()
        self.assessment(incomplete=True)
        old=self.view(past.isoformat())['measured']
        new=self.view(records.today().isoformat())['measured']
        self.assertEqual(1,len(old));self.assertEqual(1,len(new))
        self.assertNotEqual(old[0]['id'],new[0]['id'])
        self.assertEqual('На прошлой неделе',old[0]['form']['period'])
        self.assertEqual('На прошлой неделе',new[0]['form']['period'])
        # A record received now can describe an earlier observation date.
        self.assertEqual(past.isoformat(),old[0]['observed_on'])
        self.assertNotEqual(old[0]['observed_on'],old[0]['recorded_at'][:10])

    def test_invalid_periods_and_moscow_day_boundaries(self):
        for values in [{'start':'2026-10-30','end':'2026-10-01'}, {'start':'invalid','end':'invalid'},
                       {'start':'2026-10-01'}, {'end':'2026-10-01'}, {'start':'1899-01-01','end':'1900-01-01'},
                       {'start':'20261001','end':'20261002'}, {'start':'9999-01-01','end':'9999-01-02'},
                       [('start','2026-10-01'),('start','2026-10-02'),('end','2026-10-03')]]:
            response=self.clients['doc-a'].get(self.summary,query_string=values)
            self.assertEqual(400,response.status_code,response.text)
            self.assertIn('role="alert"',response.text)
            self.assertNotIn('id="follow-records"',response.text)
        self.assertEqual('2026-10-02',follow_up.local_day('2026-10-01T21:00:00+00:00'))
        self.assertEqual('2026-10-01',follow_up.local_day('2026-10-01T20:59:59+00:00'))
        self.assertIsNone(follow_up.local_day('2026-10-01T21:00:00'))
        day=records.today();a=self.action(kind='plan_change')
        stamp=(day-timedelta(days=1)).isoformat()+'T21:00:00+00:00'
        t,_=self.task(a,due_at=stamp)
        self.assertIn(t['id'],[r['id'] for r in self.view(day.isoformat())['tasks']])
        self.assertNotIn(t['id'],[r['id'] for r in self.view((day-timedelta(days=1)).isoformat())['tasks']])

    def test_access_roles_revocation_methods_and_read_only_restart(self):
        self.entry();self.assessment();self.task()
        before=self.clinical_state()
        for _ in range(2):
            self.assertEqual(200,self.clients['doc-a'].get(self.summary).status_code)
            self.assertEqual(200,self.clients['doc-a'].head(self.summary).status_code)
        self.assertEqual(before,self.clinical_state())
        for uid,status in [('pat-a',403),('pat-b',403),('doc-b',404)]:
            response=self.clients[uid].get(self.summary)
            self.assertEqual(status,response.status_code)
            self.assertNotIn('DASS-42',response.text)
            with self.assertRaises(decisions.DecisionError):
                follow_up.view(self.db,{'id':uid,'role':'patient' if uid.startswith('pat') else 'doctor'},'D01',{})
        self.assertEqual(302,self.app.test_client().get(self.summary).status_code)
        self.assertEqual(405,self.post('doc-a',self.summary,{}).status_code)
        self.assertEqual('no-store',self.clients['doc-a'].get(self.summary).headers['Cache-Control'])
        fresh=create_app(self.path).test_client()
        fresh.set_cookie(access.COOKIE,self.clients['doc-a'].get_cookie(access.COOKIE).value)
        self.assertEqual(200,fresh.get(self.summary).status_code)
        self.assertEqual(before,self.clinical_state())
        self.db.execute('UPDATE care_relationships SET ends_at=?',(datetime.now(timezone.utc).isoformat(),))
        self.assertEqual(404,self.clients['doc-a'].get(self.summary).status_code)

    def test_legacy_sources_and_first_visit_versions_are_not_duplicated(self):
        self.entry(uid='doc-a')
        values={'request_key':secrets.token_hex(16),'observed_on':records.today().isoformat(),
                'visit_kind':'repeat','age_source':'patient','not_collected':'yes','base_revision':'0',
                'safety_status':'conflicting','safety_text':'Синтетические источники расходятся',
                'safety_basis':'Синтетическая беседа','state':'draft'}
        vid=first_visits.save(self.db,{'id':'doc-a','role':'doctor'},'D01','new',values)
        first_visits.save(self.db,{'id':'doc-a','role':'doctor'},'D01',vid,
            {**values,'request_key':secrets.token_hex(16),'base_revision':'1'})
        data=self.view();self.assertEqual(1,len(data['visits']))
        self.assertTrue(any('Сведения о безопасности' in w for w in data['warnings']))
        self.assertEqual(2,data['visits'][0]['revision'])
        self.assertTrue(all(not e['origin'].startswith('doctor_visit / ') for e in data['encounters']))
        html=self.clients['doc-a'].get(self.summary).text
        self.assertIn('Противоречивые сведения',html);self.assertIn('Синтетические источники расходятся',html)
        for e in data['encounters']:self.assertIn('#encounter-'+e['id'],html)
        # Ссылка на экран приёма появится вместе с ним в UI05; пока страница показывает сами сведения приёма.
        self.assertIn('Что уточнить',html)
        self.assertNotIn('Сводка повторного приёма',self.clients['pat-a'].get('/demo/D01').text)
