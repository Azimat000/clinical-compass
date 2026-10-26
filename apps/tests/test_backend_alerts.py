"""BE09 real SQLite/outbox/API channel, with adversarial authorization and retries."""
import json
import secrets
import sqlite3
import unittest
from unittest.mock import patch

from apps.compass import backend_alerts as alerts, backend_analyses as analyses
from apps.compass import backend_jobs as jobs, backend_risk_context as context, events
from apps.compass.db import connect, now, transaction
from apps.compass.web import create_app
from apps.tests import test_access, test_backend_risk_integration, test_backend_risk_context


class BackendAlertTests(unittest.TestCase):
    setUp = test_backend_risk_integration.RiskIntegrationTests.setUp
    tearDown = test_backend_risk_integration.RiskIntegrationTests.tearDown
    post = test_access.AccessTests.post
    offer = test_access.AccessTests.offer
    body = test_backend_risk_integration.RiskIntegrationTests.body
    diary = test_backend_risk_integration.RiskIntegrationTests.diary
    positive = test_backend_risk_integration.RiskIntegrationTests.positive
    enable = test_backend_risk_integration.RiskIntegrationTests.enable
    create = test_backend_risk_integration.RiskIntegrationTests.create
    result = test_backend_risk_integration.RiskIntegrationTests.result
    endpoint = '/api/v1/physician/alerts'

    def prepare(self, model=True):
        self.enable(); self.positive(); self.diary(summary='Вымышленное опасение.')
        run = self.create(); work = jobs.claim(self.db)
        self.assertTrue(jobs.finish(self.db,work,self.result(work,empty=not model)))
        self.assertEqual('ready',analyses.read(self.db,self.user,'D01',run['run_id'])['status'])
        return [dict(r) for r in self.db.execute('SELECT * FROM backend_alerts ORDER BY id')]

    def drain(self):
        self.db.execute("UPDATE outbox_events SET available_at='2999' WHERE topic<>?",(alerts.TOPIC,))
        for _ in range(30):
            if not events.process_one(self.db):
                return
        self.fail('outbox did not drain')

    def action_body(self, row, action, **changes):
        return {'action':action,'expected_revision':row['episode_revision'],
                'reason':'Рассмотрен вымышленный сигнал врачом.' if action=='processed' else '',
                'request_key':secrets.token_hex(16),**changes}

    def action(self,row,body,uid='doc-a'):
        c=self.clients[uid]
        return c.post(self.endpoint+'/'+row['id']+'/actions',json=body,headers={'X-CSRF-Token':test_access.csrf(c)})

    def test_atomic_signal_outbox_real_channel_and_separate_receipt_view_decision(self):
        rows=self.prepare(); self.assertEqual(2,len(rows))
        row=rows[0]
        self.assertEqual('queued',alerts.read(self.db,self.user,row['id'])['state'])
        self.assertEqual(409,self.action(row,self.action_body(row,'received')).status_code)
        self.drain()
        c=self.clients['doc-a']; path=self.endpoint+'/'+row['id']
        for _ in range(2):
            response=c.get(path);self.assertEqual(200,response.status_code)
            self.assertEqual('delivered',response.json['state']);self.assertEqual([],response.json['actions'])
            self.assertEqual('no-store',response.headers['Cache-Control'])
        self.assertEqual(200,c.head(path).status_code)
        self.assertEqual(409,self.action(row,self.action_body(row,'seen')).status_code)
        self.assertEqual(409,self.action(row,self.action_body(row,'processed')).status_code)
        for action in ('received','seen','processed'):
            body=self.action_body(row,action)
            response=self.action(row,body);self.assertEqual(200,response.status_code,response.text)
            self.assertEqual(action,response.json['state']);self.assertFalse(response.json['clinical_ready'])
            self.assertEqual(200,self.action(row,body).status_code)
            self.assertEqual(409 if action=='processed' else 400,self.action(row,{**body,'reason':'Другое основание.'}).status_code)
        self.assertEqual('closed',response.json['episode']['state'])
        self.assertEqual(3,self.db.execute('SELECT count(*) FROM backend_alert_actions').fetchone()[0])
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])

    def test_all_roles_paths_exports_events_and_no_anonymous_leak(self):
        row=self.prepare()[0];self.drain();detail=self.endpoint+'/'+row['id']
        self.assertEqual(401,self.app.test_client().get(self.endpoint).status_code)
        self.assertEqual(401,self.app.test_client().post(detail+'/actions',json={}).status_code)
        for uid in ('pat-a','pat-b','doc-b'):
            c=self.clients[uid]
            self.assertEqual(403 if uid.startswith('pat') else 200,c.get(self.endpoint).status_code)
            if uid=='doc-b':self.assertEqual([],c.get(self.endpoint).json['items'])
            self.assertEqual(403 if uid.startswith('pat') else 404,c.get(detail).status_code)
            self.assertEqual(403 if uid.startswith('pat') else 404,self.action(row,self.action_body(row,'received'),uid).status_code)
        for path in ('/api/patients/D01','/api/patients/D01/reports','/api/patients/D01/documents','/api/critical'):
            text=self.clients['pat-a'].get(path).text
            self.assertNotIn(row['id'],text);self.assertNotIn(row['episode_id'],text)
        payload=json.loads(self.db.execute('SELECT payload_json FROM outbox_events WHERE id=?',(row['event_id'],)).fetchone()[0])
        self.assertEqual({'alert_id':row['id']},payload)
        self.assertNotIn('Вымышленное',json.dumps(payload))
        c=self.clients['doc-a']
        self.assertEqual(403,c.post(detail+'/actions',json=self.action_body(row,'received')).status_code)

    def test_retry_rolls_back_channel_then_restart_replays_one_signal(self):
        rows=self.prepare();row=rows[0]
        def broken(db,event):
            alerts.deliver(db,event)
            raise RuntimeError('PRIVATE provider payload')
        # Force this event first and avoid unrelated events from fixture writes.
        self.db.execute("UPDATE outbox_events SET available_at='2999' WHERE id<>?",(row['event_id'],))
        self.assertTrue(events.process_one(self.db,{alerts.TOPIC:broken}))
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM deliveries WHERE event_id=?',(row['event_id'],)).fetchone()[0])
        self.assertEqual('RuntimeError',alerts.read(self.db,self.user,row['id'])['attempt_log'][0]['error'])
        self.assertNotIn('PRIVATE',json.dumps(alerts.read(self.db,self.user,row['id'])))
        self.db.close();self.db=connect(self.path)
        self.db.execute("UPDATE outbox_events SET available_at='2000' WHERE id=?",(row['event_id'],))
        self.assertTrue(events.process_one(self.db))
        value=alerts.read(self.db,self.user,row['id'])
        self.assertEqual('delivered',value['state']);self.assertEqual(['retry','processed'],[r['outcome'] for r in value['attempt_log']])
        with transaction(self.db):alerts.deliver(self.db,self.db.execute('SELECT * FROM outbox_events WHERE id=?',(row['event_id'],)).fetchone())
        self.assertEqual(1,self.db.execute('SELECT count(*) FROM deliveries WHERE event_id=?',(row['event_id'],)).fetchone()[0])
        self.assertEqual(2,self.db.execute('SELECT count(*) FROM backend_risk_episodes').fetchone()[0])
        fresh=create_app(self.path).test_client()
        from apps.compass import access
        fresh.set_cookie(access.COOKIE,self.clients['doc-a'].get_cookie(access.COOKIE).value)
        self.assertEqual('delivered',fresh.get(self.endpoint+'/'+row['id']).json['state'])

    def test_revocation_new_recipient_disabled_absent_and_exhaustion_never_leak(self):
        rows=self.prepare();row=rows[0]
        self.db.execute('UPDATE care_relationships SET ends_at=?',(now(),))
        self.db.execute('INSERT INTO care_relationships VALUES(?,?,?,?,NULL)',('replacement','D01','doc-b',now()))
        for _ in range(5):
            self.db.execute("UPDATE outbox_events SET available_at='2000' WHERE id=?",(row['event_id'],))
            self.assertTrue(events.process_one(self.db))
        status=next(s for s in alerts.status(self.db) if s['id']==row['id'])
        self.assertEqual('dead',status['status']);self.assertEqual(5,status['attempts'])
        self.assertEqual('recipient_unavailable',status['recipient_state'])
        for uid in ('doc-a','doc-b'):
            self.assertEqual(404,self.clients[uid].get(self.endpoint+'/'+row['id']).status_code)
            self.assertEqual([],self.clients[uid].get(self.endpoint).json['items'])
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM deliveries').fetchone()[0])
        self.assertEqual(5,self.db.execute('SELECT count(*) FROM outbox_attempts WHERE event_id=?',(row['event_id'],)).fetchone()[0])

    def test_disabled_doctor_before_or_after_delivery_loses_access(self):
        row=self.prepare()[0];self.db.execute("UPDATE users SET disabled=1 WHERE id='doc-a'")
        self.drain();self.assertEqual('pending',self.db.execute('SELECT status FROM outbox_events WHERE id=?',(row['event_id'],)).fetchone()[0])
        with self.assertRaises(analyses.AnalysisError):alerts.read(self.db,self.user,row['id'])
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM deliveries').fetchone()[0])
        self.db.execute("UPDATE users SET disabled=0 WHERE id='doc-a'")
        self.db.execute("UPDATE outbox_events SET available_at='2000'");self.drain()
        self.assertEqual('delivered',alerts.read(self.db,self.user,row['id'])['state'])
        self.db.execute("UPDATE users SET disabled=1 WHERE id='doc-a'")
        with self.assertRaises(analyses.AnalysisError):alerts.act(self.db,self.user,row['id'],self.action_body(row,'received'))

    def test_repeated_snapshot_new_evidence_old_alert_cannot_close_new_revision(self):
        rows=self.prepare();self.drain();row=next(r for r in rows if self.db.execute('SELECT origin FROM backend_risk_episodes WHERE id=?',(r['episode_id'],)).fetchone()[0]=='model_candidate')
        run=self.create();work=jobs.claim(self.db);jobs.finish(self.db,work,self.result(work))
        self.assertEqual(2,self.db.execute('SELECT count(*) FROM backend_alerts').fetchone()[0])
        self.diary(summary='Другое вымышленное опасение.');run=self.create();work=jobs.claim(self.db)
        units=[u for u in context.prepare_snapshot(work['snapshot']) if u['code']=='summary']
        model=test_backend_risk_context.Model({'candidates':[test_backend_risk_context.candidate(u['unit_id'],u['text']) for u in units]})
        jobs.finish(self.db,work,context.execute('risk',work['snapshot'],model))
        self.assertEqual(2,self.db.execute('SELECT count(*) FROM backend_risk_episodes').fetchone()[0])
        self.assertEqual(3,self.db.execute('SELECT count(*) FROM backend_alerts').fetchone()[0])
        for action in ('received','seen'):
            self.assertEqual(200,self.action(row,self.action_body(row,action)).status_code)
        latest=self.db.execute('SELECT max(revision) FROM backend_risk_episode_versions WHERE episode_id=?',(row['episode_id'],)).fetchone()[0]
        result=self.action(row,self.action_body(row,'processed'))
        self.assertEqual(2,latest);self.assertEqual(409,result.status_code)

    def test_publication_failure_rolls_back_episode_signal_outbox_and_analysis(self):
        self.enable();self.positive();self.diary();run=self.create();work=jobs.claim(self.db)
        original=alerts.enqueue_pending
        def fail(db):original(db);raise RuntimeError('failure')
        with patch.object(alerts,'enqueue_pending',side_effect=fail):jobs.finish(self.db,work,self.result(work))
        for table in ('backend_alerts','backend_risk_episodes','backend_risk_episode_evaluations'):
            self.assertEqual(0,self.db.execute('SELECT count(*) FROM '+table).fetchone()[0])
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM outbox_events WHERE topic=?',(alerts.TOPIC,)).fetchone()[0])
        self.assertEqual('running',analyses.read(self.db,self.user,'D01',run['run_id'])['status'])

    def test_backlog_and_custom_consumer_and_immutable_logs(self):
        self.prepare();self.db.execute("UPDATE outbox_events SET available_at='2999' WHERE topic<>?",(alerts.TOPIC,))
        self.assertFalse(events.process_one(self.db,{}))
        self.assertEqual(2,self.db.execute('SELECT count(*) FROM backend_alerts').fetchone()[0])
        for _ in range(2):
            with transaction(self.db):alerts.enqueue_pending(self.db)
        self.drain();row=dict(self.db.execute('SELECT * FROM backend_alerts LIMIT 1').fetchone())
        self.action(row,self.action_body(row,'received'))
        for sql in ('DELETE FROM backend_alerts','UPDATE backend_alerts SET recipient_id=\'doc-b\'',
                    'DELETE FROM backend_alert_actions','UPDATE backend_alert_actions SET reason=\'changed\''):
            with self.assertRaises(sqlite3.IntegrityError):self.db.execute(sql)

    def test_existing_be08_ledger_is_caught_up_without_reanalysis(self):
        with patch.object(alerts,'enqueue_pending'):
            self.assertEqual([],self.prepare())
        count=self.db.execute('SELECT count(*) FROM analysis_runs').fetchone()[0]
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM backend_alerts').fetchone()[0])
        self.drain()
        self.assertEqual(2,self.db.execute('SELECT count(*) FROM backend_alerts').fetchone()[0])
        self.assertEqual(count,self.db.execute('SELECT count(*) FROM analysis_runs').fetchone()[0])
        self.assertEqual(2,self.db.execute('SELECT count(*) FROM deliveries').fetchone()[0])

    def test_concurrent_workers_and_receipt_retries_remain_single(self):
        from concurrent.futures import ThreadPoolExecutor
        row=self.prepare(model=False)[0]
        self.db.execute("UPDATE outbox_events SET available_at='2999' WHERE id<>?",(row['event_id'],))
        def deliver_once(_):
            db=connect(self.path)
            try:return events.process_one(db)
            finally:db.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual([False,True],sorted(pool.map(deliver_once,range(2))))
        body=self.action_body(row,'received')
        def receive(_):
            db=connect(self.path)
            try:return alerts.act(db,self.user,row['id'],body)['state']
            finally:db.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(['received','received'],list(pool.map(receive,range(2))))
        self.assertEqual(1,self.db.execute('SELECT count(*) FROM deliveries').fetchone()[0])
        self.assertEqual(1,self.db.execute('SELECT count(*) FROM backend_alert_actions').fetchone()[0])
        self.assertEqual(1,self.db.execute('SELECT count(*) FROM outbox_attempts WHERE event_id=?',(row['event_id'],)).fetchone()[0])

    def test_strict_input_page_order_revision_and_idempotency(self):
        row=self.prepare()[0];self.drain();c=self.clients['doc-a'];path=self.endpoint+'/'+row['id']+'/actions'
        for query in ('page=0','page=-1','page=1&page=2','x=1','page=9999999'):
            self.assertEqual(400,c.get(self.endpoint+'?'+query).status_code)
        for bad in ({},[],{**self.action_body(row,'received'),'recipient_id':'doc-b'},self.action_body(row,'processed',reason=''),self.action_body(row,'received',expected_revision=True)):
            self.assertEqual(400,self.action(row,bad).status_code)
        self.assertEqual(409,self.action(row,self.action_body(row,'received',expected_revision=99)).status_code)
        body=self.action_body(row,'received');self.assertEqual(200,self.action(row,body).status_code)
        self.assertEqual(409,self.action(row,{**body,'action':'seen'}).status_code)
        self.assertEqual(409,self.action(row,self.action_body(row,'received')).status_code)
        self.assertEqual(400,c.post(path,data='{"action":"received","action":"seen"}',content_type='application/json',headers={'X-CSRF-Token':test_access.csrf(c)}).status_code)
        self.assertEqual(415,c.post(path,data='{}',headers={'X-CSRF-Token':test_access.csrf(c)}).status_code)


if __name__=='__main__':unittest.main()
