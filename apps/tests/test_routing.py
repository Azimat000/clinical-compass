import json
from unittest.mock import patch
import secrets
import unittest
import test_decisions
from apps.compass import routing, decisions, records
from apps.compass.web import create_app


class RoutingTests(unittest.TestCase):
    setUp = test_decisions.DecisionTests.setUp
    tearDown = test_decisions.DecisionTests.tearDown
    post = test_decisions.DecisionTests.post
    offer = test_decisions.DecisionTests.offer
    link = test_decisions.DecisionTests.link
    values = test_decisions.DecisionTests.values
    draft = test_decisions.DecisionTests.draft
    confirm = test_decisions.DecisionTests.confirm

    def test_categories_separate_from_urgency_and_approval_only_patient(self):
        for category, label, urgency in [('mandatory','Обязательно','planned'),('desirable','Желательно','urgent')]:
            p = self.draft(kind='referral', route_category=category, route_urgency=urgency)
            page = self.clients['doc-a'].get('/patients/D01/decisions').text
            self.assertIn(label, page)
            self.assertIn('Проект — план не изменён', page)
            patient_items=self.clients['pat-a'].get('/api/patients/D01/decisions').json['decisions']
            self.assertNotIn(p['id'],[i['id'] for i in patient_items])
            self.assertEqual(303,self.confirm(p).status_code)
            item = self.clients['pat-a'].get('/api/patients/D01/decisions').json['decisions'][0]
            self.assertEqual({'target':'psychiatrist','category':category,'urgency':urgency},item['payload']['route'])
            self.assertNotIn('routing_review',item['payload'])
            page = self.clients['doc-a'].get('/patients/D01/decisions').text
            self.assertIn('Психиатр — '+label,page)
            self.assertIn('Срочность',page)
            self.assertIn('Подтверждено врачом',page)
            card = self.clients['doc-a'].get('/demo/D01').text
            self.assertIn('Психиатр — '+label,card)
            self.assertIn('срочность:',card)
            self.assertIn('подтверждено врачом',card)

    def test_missing_data_not_negative_or_planned_and_confirmation_requires_choice(self):
        p=self.draft(kind='referral',route_category='unknown',route_urgency='unknown',route_population_status='unknown')
        review=json.loads(p['payload_json'])['routing_review']
        self.assertEqual('unknown',review['severity_status'])
        self.assertEqual('unknown',review['population_status'])
        self.assertEqual('unknown',review['urgency'])
        self.assertEqual(409,self.confirm(p).status_code)
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])
        self.assertEqual(303,self.confirm(p,'rejected').status_code)
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])

    def test_validation_no_made_up_categories_sources_or_empty_rationale(self):
        for field,value in [('route_category','safe'),('route_urgency','automatic'),
                            ('route_severity_status','denied'),('route_population_status','adult'),
                            ('routing_reference','old'),('route_evidence',''),('route_population',''),
                            ('route_specialty',''),('route_unavailable',''),('route_severity',''),
                            ('route_evidence','x'*2001),('route_evidence','bad\0')]:
            with self.subTest(field=field):
                response=self.post('doc-a','/patients/D01/decisions',self.values(kind='referral',**{field:value}))
                self.assertIn(response.status_code,(400,409))
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM proposals').fetchone()[0])

    def test_source_update_obsolete_legacy_draft_and_missing_access(self):
        p=self.draft(kind='referral')
        with patch.object(routing,'fingerprint',return_value='changed'):
            self.assertEqual(409,self.confirm(p).status_code)
        # An immutable old-format proposal stays stored; approval must require a new revision.
        for uid,code in [('pat-a',403),('pat-b',403),('doc-b',404)]:
            r=self.post(uid,f'/patients/D01/decisions/{p["id"]}/confirm',
                        {'decision':'approved','version':str(p['version']),'rationale':'test','reviewed':'yes'})
            self.assertEqual(code,r.status_code)
        self.assertEqual([],routing.summaries(self.db,{'id':'doc-b','role':'doctor'},'D01'))
        with self.assertRaises(decisions.DecisionError):routing.confirmable(self.db,'D01',{'kind':'referral'})

    def test_inactive_critical_rules_never_create_alerts_or_outbox(self):
        ref=routing.reference()
        self.assertFalse(ref['active_rules'])
        self.assertEqual(5,len(ref['critical_candidates']))
        self.assertTrue(all(x['status']=='draft_inactive' for x in ref['critical_candidates']))
        before=self.db.execute('SELECT count(*) FROM outbox_events').fetchone()[0]
        for age,status in [(17,'known'),(18,'known'),(19,'known'),(None,'unknown'),(18,'conflicting')]:
            self.db.execute('UPDATE patients SET age_years=?,age_status=? WHERE id=?',(age,status,'D01'))
            self.clients['doc-a'].get('/patients/D01/decisions')
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM alerts').fetchone()[0])
        self.assertEqual(before,self.db.execute('SELECT count(*) FROM outbox_events').fetchone()[0])
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM proposals').fetchone()[0])
        bad={**ref,'active_rules':True}
        with patch('apps.compass.routing.json.loads',return_value=bad):
            with self.assertRaises(RuntimeError):routing.reference()

    def test_adult_reference_never_silently_applies_to_child_unknown_or_conflict(self):
        for age,status in [(17,'known'),(18,'known'),(19,'known'),(None,'unknown'),(18,'conflicting')]:
            self.db.execute('UPDATE patients SET age_years=?,age_status=? WHERE id=?',(age,status,'D01'))
            p=self.draft(kind='referral',route_age_years=str(age) if age is not None else '',
                         route_population_status='known' if status=='known' else status)
            expected=303 if status=='known' and age>=18 else 409
            self.assertEqual(expected,self.confirm(p).status_code)
        # A doctor's claimed age cannot overwrite an inconsistent source.
        self.db.execute("UPDATE patients SET age_years=17,age_status='known' WHERE id='D01'")
        p=self.draft(kind='referral',route_age_years='35')
        self.assertEqual(409,self.confirm(p).status_code)

    def test_retry_conflicting_change_data_and_restart(self):
        form=self.values(kind='referral',route_population_status='conflicting',route_population='<script>x</script>')
        url='/patients/D01/decisions'
        self.assertEqual(303,self.post('doc-a',url,form).status_code)
        self.assertEqual(303,self.post('doc-a',url,form).status_code)
        self.assertEqual(409,self.post('doc-a',url,{**form,'route_urgency':'planned'}).status_code)
        p=self.db.execute('SELECT * FROM proposals').fetchone()
        records.save(self.db,{'id':'pat-a','role':'patient'},'D01','self_report',
                     {'request_key':secrets.token_hex(16),'observed_on':records.today().isoformat()})
        self.assertEqual(409,self.confirm(p).status_code)
        client=create_app(self.path).test_client()
        from apps.compass import access
        client.set_cookie(access.COOKIE,self.clients['doc-a'].get_cookie(access.COOKIE).value)
        self.assertIn('&lt;script&gt;x&lt;/script&gt;',client.get(url).text)
        self.assertNotIn('<script>x</script>',client.get(url).text)
        self.assertEqual('ok',self.db.execute('PRAGMA integrity_check').fetchone()[0])
        self.assertEqual([],self.db.execute('PRAGMA foreign_key_check').fetchall())
