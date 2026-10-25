import secrets
import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
from apps.compass import communication as comm, access, records
from apps.compass.db import connect
from apps.compass.web import create_app
import test_decisions


class CommunicationTests(unittest.TestCase):
    setUp = test_decisions.DecisionTests.setUp
    tearDown = test_decisions.DecisionTests.tearDown
    post = test_decisions.DecisionTests.post
    offer = test_decisions.DecisionTests.offer
    link = test_decisions.DecisionTests.link
    values = test_decisions.DecisionTests.values
    draft = test_decisions.DecisionTests.draft
    confirm = test_decisions.DecisionTests.confirm
    url='/patients/D01/communication'

    def send(self, uid='pat-a', **kw):
        data={'request_key':secrets.token_hex(16),'body':'Синтетическое сообщение',**kw}
        return self.post(uid,self.url+'/send',data),data

    def action(self, **kw):
        p=self.draft(**kw)
        self.assertEqual(303,self.confirm(p).status_code)
        return self.db.execute('SELECT id FROM care_actions WHERE confirmation_id=(SELECT id FROM doctor_confirmations WHERE proposal_id=?)',(p['id'],)).fetchone()[0]

    def task(self, action=None, **kw):
        action=action or self.action()
        data={'action_id':action,'request_key':secrets.token_hex(16),'label':'Синтетическое упражнение',
              'due_at':(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat(),'reviewed':'yes',**kw}
        response=self.post('doc-a',self.url+'/schedule',data)
        self.assertEqual(303,response.status_code,response.get_data(as_text=True))
        return self.db.execute('SELECT * FROM adherence_tasks WHERE request_key=?',(data['request_key'],)).fetchone(),data

    def test_bidirectional_receipts_retry_restart_and_escaping(self):
        response,form=self.send(body='<script>bad()</script>')
        self.assertEqual(303,response.status_code)
        self.assertEqual(303,self.post('pat-a',self.url+'/send',form).status_code)
        self.assertEqual(409,self.post('pat-a',self.url+'/send',{**form,'body':'different'}).status_code)
        mid=self.db.execute('SELECT id FROM messages').fetchone()[0]
        for method in ('get','head'):
            self.assertEqual(200,getattr(self.clients['doc-a'],method)(self.url).status_code)
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM message_receipts').fetchone()[0])
        self.assertEqual(404,self.post('pat-a',self.url+'/read',{'message_id':mid}).status_code)
        for _ in range(2): self.assertEqual(303,self.post('doc-a',self.url+'/read',{'message_id':mid}).status_code)
        self.assertEqual(2,self.db.execute('SELECT count(*) FROM message_receipts').fetchone()[0])
        self.assertEqual(303,self.send('doc-a',body='Ответ врача')[0].status_code)
        fresh=create_app(self.path).test_client()
        fresh.set_cookie(access.COOKIE,self.clients['pat-a'].get_cookie(access.COOKIE).value)
        page=fresh.get(self.url).get_data(as_text=True)
        self.assertIn('Ответ врача',page);self.assertIn('&lt;script&gt;',page)
        self.assertNotIn('<script>bad()',page)
        self.assertEqual(2,self.db.execute('SELECT count(*) FROM messages').fetchone()[0])
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])

    def test_isolation_csrf_link_expiry_and_context(self):
        _,form=self.send();mid=self.db.execute('SELECT id FROM messages').fetchone()[0]
        for uid in ('pat-b','doc-b'):
            for op in ('send','read','report','schedule'):
                self.assertEqual(404,self.post(uid,self.url+'/'+op,{**form,'message_id':mid}).status_code)
            self.assertEqual(404,self.clients[uid].get(self.url).status_code)
        self.assertEqual(403,self.clients['pat-a'].post(self.url+'/send',data=form).status_code)
        self.assertEqual(403,self.post('pat-a',self.url+'/schedule',form).status_code)
        self.assertEqual(404,self.send(entry_id='foreign')[0].status_code)
        self.assertEqual(404,self.send(task_id='foreign')[0].status_code)
        self.db.execute("UPDATE care_relationships SET ends_at='2000-01-01'")
        self.assertEqual(404,self.clients['doc-a'].get(self.url).status_code)
        self.assertEqual(409,self.send()[0].status_code)

    def test_denominator_unknown_conflicts_corrections_and_future(self):
        action=self.action()
        tasks=[self.task(action)[0] for _ in range(4)]
        future,_=self.task(action,due_at=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat())
        for t,outcome in zip(tasks,('taken','missed','conflicting','unknown')):
            form={'request_key':secrets.token_hex(16),'outcome':outcome,'reason':'Синтетическая причина'}
            for _ in range(2): self.assertEqual(303,self.post('pat-a',self.url+'/report',{**form,'task_id':t['id']}).status_code)
        c=comm.view(self.db,{'id':'doc-a','role':'doctor'},'D01')['counts']
        self.assertEqual((4,2,50.0,1,1,1),(c['due'],c['known'],c['percent'],c['unknown'],c['conflicting'],c['future']))
        self.assertEqual(409,self.post('pat-a',self.url+'/report',{'task_id':future['id'],'request_key':secrets.token_hex(16),'outcome':'taken'}).status_code)
        self.assertEqual(303,self.post('doc-a',self.url+'/report',{'task_id':tasks[1]['id'],'request_key':secrets.token_hex(16),'outcome':'taken','reason':'Уточнено с пациентом'}).status_code)
        v=comm.view(self.db,{'id':'pat-a','role':'patient'},'D01')
        self.assertEqual(100.0,v['counts']['percent'])
        self.assertEqual(5,self.db.execute('SELECT count(*) FROM adherence_entries').fetchone()[0])
        self.assertIn('Уточнено',self.clients['pat-a'].get(self.url).get_data(as_text=True))

    def test_plan_confirmation_change_and_schedule_idempotency(self):
        form={'request_key':secrets.token_hex(16),'action_id':'draft','label':'test','due_at':'2026-10-01T09:00:00+03:00','reviewed':'yes'}
        self.assertEqual(409,self.post('doc-a',self.url+'/schedule',form).status_code)
        task,data=self.task()
        self.assertEqual(303,self.post('doc-a',self.url+'/schedule',data).status_code)
        self.assertEqual(409,self.post('doc-a',self.url+'/schedule',{**data,'label':'different'}).status_code)
        self.assertEqual(400,self.post('doc-a',self.url+'/schedule',{**data,'due_at':'2026-10-01T09:00:00'}).status_code)
        future,_=self.task(task['action_id'],due_at=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat())
        new=self.action(kind='therapy_stop')
        self.assertEqual(409,self.post('doc-a',self.url+'/schedule',{**data,'request_key':secrets.token_hex(16),'action_id':new}).status_code)
        v=comm.view(self.db,{'id':'doc-a','role':'doctor'},'D01')
        self.assertEqual(1,v['counts']['superseded']);self.assertEqual(1,v['counts']['due'])
        self.assertEqual(409,self.post('pat-a',self.url+'/report',{'task_id':future['id'],'request_key':secrets.token_hex(16),'outcome':'taken'}).status_code)

    def test_atomic_rollback_concurrency_immutability(self):
        with patch.object(access,'audit',side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError):
                comm.send(self.db,{'id':'pat-a','role':'patient'},'D01',{'request_key':secrets.token_hex(16),'body':'rollback'})
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM messages').fetchone()[0])
        form={'request_key':secrets.token_hex(16),'body':'concurrent'}
        def run(_):
            db=connect(self.path)
            try: return comm.send(db,{'id':'pat-a','role':'patient'},'D01',form)
            finally: db.close()
        with ThreadPoolExecutor(max_workers=2) as pool: ids=list(pool.map(run,range(2)))
        self.assertEqual(ids[0],ids[1])
        for sql in ("UPDATE messages SET body='changed'",'DELETE FROM messages'):
            with self.assertRaises(sqlite3.IntegrityError):self.db.execute(sql)
        self.assertEqual([],self.db.execute('PRAGMA foreign_key_check').fetchall())
        self.assertEqual('ok',self.db.execute('PRAGMA integrity_check').fetchone()[0])

    def test_context_links_never_suppress_adverse_event(self):
        entry=records.save(self.db,{'id':'pat-a','role':'patient'},'D01','self_report',
            {'request_key':secrets.token_hex(16),'observed_on':records.today().isoformat(),
             'adverse_events_status':'known','adverse_events_text':'Вымышленное НЯ'})
        task,_=self.task()
        self.assertEqual(303,self.send(entry_id=entry,task_id=task['id'])[0].status_code)
        self.assertEqual(1,self.db.execute('SELECT count(*) FROM adverse_events').fetchone()[0])
        page=self.clients['doc-a'].get(self.url).get_data(as_text=True)
        self.assertIn('/patients/D01/records/'+entry,page);self.assertIn('#task-'+task['id'],page)

    def test_all_eight_functions_connected_two_cabinets(self):
        from apps.compass import assessments
        from test_clinical_workflow import ClinicalWorkflowTests
        # F01: doctor requests the verified form, patient submits, doctor sees scores.
        form=assessments.definition()
        self.assertEqual(303,self.post('doc-a','/patients/D01/assessment-requests',{
            'assignment_key':secrets.token_hex(16),'form_version_id':form['id'],
            'age_status':'known','age_years':'35','age_basis':'Синтетический профиль'}).status_code)
        request_id=self.db.execute('SELECT id FROM assessment_requests').fetchone()[0]
        self.assertEqual(303,self.post('pat-a','/assessments/'+request_id,{
            'form_version_id':form['id'],**{f'answer_{i}':'0' for i in range(1,43)}}).status_code)
        result=self.clients['doc-a'].get('/api/patients/D01/assessments').json['assessments'][0]
        self.assertEqual({'depression':0,'anxiety':0,'stress':0},result['scores'])
        # F05/F03/F04: patient reports wellbeing and an AE; both cabinets have durable history/trend.
        self.assertEqual(303,self.post('pat-a','/patients/D01/self-reports',{
            'request_key':secrets.token_hex(16),'observed_on':records.today().isoformat(),
            'wellbeing':'worse','adverse_events_status':'known','adverse_events_text':'Вымышленное НЯ'}).status_code)
        entry=self.db.execute('SELECT id FROM clinical_entries').fetchone()[0]
        self.assertEqual(1,self.db.execute('SELECT count(*) FROM adverse_events').fetchone()[0])
        for uid,path in (('doc-a','/demo/D01'),('pat-a','/demo/D01/diary')):
            html=self.clients[uid].get(path).text
            self.assertIn('Вымышленное НЯ',html);self.assertIn('Хуже',html);self.assertIn('class="wb',html)
        # F02: therapy reference and separate physician approval create the plan anchor.
        html=self.clients['doc-a'].get('/patients/D01/decisions').text
        self.assertIn('Авиандр',html)
        action=self.action(kind='plan_change')
        self.assertEqual(1,len(self.clients['pat-a'].get('/api/patients/D01/decisions').json['decisions']))
        # F06: both directions, each linked to the same AE/wellbeing entry.
        self.assertEqual(303,self.send(entry_id=entry)[0].status_code)
        self.assertEqual(303,self.send('doc-a',entry_id=entry,body='Вымышленный ответ')[0].status_code)
        # F07: physician-specified confirmed task, patient outcome, visible descriptive calculation.
        task,_=self.task(action)
        self.assertEqual(303,self.post('pat-a',self.url+'/report',{'task_id':task['id'],
            'request_key':secrets.token_hex(16),'outcome':'missed','reason':'Вымышленная причина'}).status_code)
        self.assertIn('0.0% (0 / 1)',self.clients['doc-a'].get(self.url).text)
        # F08: source-bound advice for two categories, then physician-confirmed route.
        for severity,category in (('nonsevere','desirable'),('severe','mandatory')):
            self.assertEqual(303,self.post('doc-a','/patients/D01/clinical-context',
                ClinicalWorkflowTests.context(self,severity=severity)).status_code)
            html=self.clients['doc-a'].get('/demo/D01').text
            self.assertIn('Желательно' if category=='desirable' else 'Обязательно',html)
            proposal=self.draft(kind='referral',route_category=category,route_urgency='planned')
            self.assertEqual(303,self.confirm(proposal).status_code)
        self.assertEqual(2,self.db.execute('SELECT count(*) FROM messages').fetchone()[0])
        self.assertEqual(1,self.db.execute('SELECT count(*) FROM adherence_entries').fetchone()[0])
        self.assertEqual([],self.db.execute('PRAGMA foreign_key_check').fetchall())

    def test_new_accompaniment_information_invalidates_pending_decision(self):
        action=self.action()
        for kind in ('message','task','outcome'):
            p=self.draft(kind='plan_change')
            if kind=='message': self.send()
            elif kind=='task': task,_=self.task(action)
            else:
                self.assertEqual(303,self.post('pat-a',self.url+'/report',{'task_id':task['id'],
                    'request_key':secrets.token_hex(16),'outcome':'taken'}).status_code)
            self.assertEqual(409,self.confirm(p).status_code)
        self.assertEqual(1,self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])

    def test_missing_report_never_becomes_missed_or_zero_percent(self):
        for state in ('empty','one_due'):
            if state=='one_due': self.task()
            v=comm.view(self.db,{'id':'doc-a','role':'doctor'},'D01')['counts']
            self.assertEqual(0,v['known']);self.assertEqual(0,v['missed']);self.assertIsNone(v['percent'])
            self.assertEqual(0 if state=='empty' else 1,v['unknown'])
        self.assertIn('не рассчитывается: знаменатель 0',self.clients['doc-a'].get(self.url).text)

    def test_intermediate_plan_stop_stays_excluded_after_another_change(self):
        from apps.compass import decisions
        task,data=self.task(due_at='2030-01-01T10:00:00+03:00')
        self.action(kind='therapy_stop')
        self.action(kind='plan_change')
        v=comm.view(self.db,{'id':'doc-a','role':'doctor'},'D01')
        self.assertEqual(1,v['counts']['superseded'])
        for table,sql in (
            ('adherence_tasks',"UPDATE adherence_tasks SET label='changed'"),
            ('adherence_tasks','DELETE FROM adherence_tasks'),
        ):
            with self.assertRaises(sqlite3.IntegrityError):self.db.execute(sql)
