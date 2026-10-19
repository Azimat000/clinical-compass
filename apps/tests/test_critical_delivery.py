"""S10 transport, role boundaries, crash lease and distinct human actions."""
import json
from unittest.mock import patch
import unittest
from apps.compass import critical_delivery as delivery, events
from apps.compass.db import now
from apps.compass.web import create_app
import test_clinical_rules
from test_access import login, csrf


class CriticalDeliveryTests(unittest.TestCase):
    setUp = test_clinical_rules.ClinicalRuleTests.setUp
    tearDown = test_clinical_rules.ClinicalRuleTests.tearDown
    context = test_clinical_rules.ClinicalRuleTests.context
    context_form = test_clinical_rules.ClinicalRuleTests.context_form
    form = test_clinical_rules.ClinicalRuleTests.form
    save = test_clinical_rules.ClinicalRuleTests.save

    def prepare(self):
        self.save()
        while events.process_one(self.db): pass
        return self.db.execute('SELECT * FROM critical_events ORDER BY created_at DESC LIMIT 1').fetchone()['id']

    def test_receipt_read_accept_reaction_are_ordered_idempotent_no_medical_mutation(self):
        eid = self.prepare()
        for action in ('seen','acknowledged','reacted'):
            with self.assertRaises(delivery.NotificationError):
                delivery.mark(self.db,self.doc,eid,action,'Synthetic actual physician response')
        for action in ('received','seen','acknowledged','reacted'):
            delivery.mark(self.db,self.doc,eid,action,'Synthetic actual physician response')
            delivery.mark(self.db,self.doc,eid,action,'Synthetic actual physician response')
        row = self.db.execute('SELECT * FROM critical_delivery').fetchone()
        self.assertTrue(row['reacted_at'])
        self.assertEqual(5,self.db.execute('SELECT count(*) FROM critical_delivery_log').fetchone()[0])
        with self.assertRaises(delivery.NotificationError):
            delivery.mark(self.db,self.doc,eid,'reacted','Different replacement response')
        for table in ('care_actions','doctor_confirmations','proposals','therapy_courses'):
            self.assertEqual(0,self.db.execute('SELECT count(*) FROM '+table).fetchone()[0])

    def test_http_auth_csrf_receipt_not_get_and_no_cross_patient_data(self):
        eid = self.prepare()
        app = create_app(self.tmp.name+'/db.sqlite3')
        clients={u:app.test_client() for u in ('doc-a','doc-b','pat-a')}
        for uid,c in clients.items(): login(c,uid)
        c=clients['doc-a']
        self.assertIn(eid,c.get('/critical').text)
        self.assertEqual(200,c.head('/critical').status_code)
        self.assertIsNone(self.db.execute('SELECT received_at FROM critical_delivery').fetchone()[0])
        self.assertEqual([{'id':eid,'received':False}],c.get('/api/critical').json)
        self.assertEqual([],clients['doc-b'].get('/api/critical').json)
        self.assertNotIn(eid,clients['doc-b'].get('/critical').text)
        self.assertEqual(403,clients['pat-a'].get('/api/critical').status_code)
        self.assertEqual(401,app.test_client().get('/api/critical').status_code)
        self.assertEqual(403,c.post('/critical/'+eid+'/received').status_code)
        for uid,status in [('doc-b',404),('pat-a',403),('doc-a',204)]:
            response=clients[uid].post('/critical/'+eid+'/received',data={'csrf':csrf(clients[uid])})
            self.assertEqual(status,response.status_code)
        self.db.execute("UPDATE care_relationships SET ends_at=? WHERE id='rel'",(now(),))
        self.assertEqual([],c.get('/api/critical').json)
        self.assertEqual(404,c.post('/critical/'+eid+'/seen',data={'csrf':csrf(c)}).status_code)

    def test_reserve_timeout_retry_lease_recovery_and_no_duplicate_effect(self):
        eid=self.prepare()
        with patch.object(delivery,'native_dialog',side_effect=TimeoutError('secret medical message')):
            self.assertTrue(delivery.reserve_one(self.db,'doc-a'))
        row=self.db.execute('SELECT * FROM critical_delivery').fetchone()
        self.assertEqual(('pending',1),(row['reserve_state'],row['reserve_attempts']))
        self.assertNotIn('secret',json.dumps([dict(r) for r in self.db.execute('SELECT * FROM critical_delivery_log')]))
        self.assertFalse(delivery.reserve_one(self.db,'doc-a',sender=lambda: self.fail('too early')))
        self.db.execute("UPDATE critical_delivery SET reserve_after='2000',reserve_state='leased',reserve_token='crashed' WHERE event_id=?",(eid,))
        calls=[]
        self.assertTrue(delivery.reserve_one(self.db,'doc-a',sender=lambda:calls.append(eid)))
        self.assertFalse(delivery.reserve_one(self.db,'doc-a',sender=lambda:calls.append(eid)))
        self.assertEqual([eid],calls)
        row=self.db.execute('SELECT * FROM critical_delivery').fetchone()
        self.assertEqual('operator_received',row['reserve_state'])
        self.assertTrue(all(row[k] is None for k in ('received_at','seen_at','acknowledged_at','reacted_at')))

    def test_reserve_five_failures_retained_and_log_immutable(self):
        self.prepare()
        for i in range(5):
            self.db.execute("UPDATE critical_delivery SET reserve_after='2000'")
            def failure(): raise OSError('unavailable')
            self.assertTrue(delivery.reserve_one(self.db,'doc-a',sender=failure))
        self.assertEqual('dead',self.db.execute('SELECT reserve_state FROM critical_delivery').fetchone()[0])
        self.assertFalse(delivery.reserve_one(self.db,'doc-a',sender=lambda:self.fail('dead')))
        import sqlite3
        for sql in ('DELETE FROM critical_delivery_log','UPDATE critical_delivery_log SET action=action'):
            with self.assertRaises(sqlite3.IntegrityError):self.db.execute(sql)

    def test_disabled_unassigned_and_ended_relationship_no_reserve_retargeting(self):
        self.prepare()
        self.db.execute("UPDATE users SET disabled=1 WHERE id='doc-a'")
        with self.assertRaises(delivery.NotificationError):delivery.reserve_one(self.db,'doc-a')
        self.db.execute("UPDATE users SET disabled=0 WHERE id='doc-a'")
        self.db.execute("UPDATE care_relationships SET ends_at=? WHERE id='rel'",(now(),))
        self.save()
        while events.process_one(self.db):pass
        self.assertEqual(2,self.db.execute('SELECT count(*) FROM critical_delivery').fetchone()[0])
        self.assertFalse(delivery.reserve_one(self.db,'doc-a',sender=lambda:self.fail('ended')))
        self.assertFalse(delivery.reserve_one(self.db,'doc-b',sender=lambda:self.fail('retargeted')))

    def test_handler_failure_rollback_and_retry(self):
        self.save()
        with patch.object(delivery,'log',side_effect=RuntimeError('injected')):
            while events.process_one(self.db):pass
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM critical_delivery').fetchone()[0])
        self.db.execute("UPDATE outbox_events SET available_at='2000'")
        while events.process_one(self.db):pass
        self.assertEqual(1,self.db.execute('SELECT count(*) FROM critical_delivery').fetchone()[0])
        self.assertEqual(['retry','processed'],[r[0] for r in self.db.execute('SELECT outcome FROM outbox_attempts WHERE event_id=(SELECT outbox_event_id FROM critical_events) ORDER BY attempt')])

    def test_native_dialog_receipt_requires_exact_button_and_no_timeout(self):
        from types import SimpleNamespace
        with patch.object(delivery.sys,'platform','darwin'):
            for output,success in [('button returned:Сигнал замечен, gave up:false',True),
                                   ('button returned:Сигнал замечен, gave up:true',False),
                                   ('',False),('button returned:wrong, gave up:false',False)]:
                with patch.object(delivery.subprocess,'run',return_value=SimpleNamespace(stdout=output)):
                    if success:delivery.native_dialog()
                    else:
                        with self.assertRaises(TimeoutError):delivery.native_dialog()

    def test_console_refuses_redirected_output(self):
        with patch.object(delivery.sys.stdin,'isatty',return_value=False):
            with self.assertRaises(RuntimeError):delivery.console_signal()
