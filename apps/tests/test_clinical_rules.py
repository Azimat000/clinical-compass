"""Synthetic rule semantics and real transaction/outbox persistence."""
from datetime import timedelta
import json
from pathlib import Path
import secrets
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from werkzeug.datastructures import MultiDict
from apps.compass import ages, clinical_rules as rules, events, records
from apps.compass.db import connect, migrate, now
from apps.compass.repository import seed_demo
from test_access import setup_identities


class ClinicalRuleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = connect(Path(self.tmp.name) / 'db.sqlite3')
        migrate(self.db)
        seed_demo(self.db)
        setup_identities(self.db)
        self.doc = {'id': 'doc-a', 'role': 'doctor'}
        self.pat = {'id': 'pat-a', 'role': 'patient'}
        self.db.execute("INSERT INTO care_relationships VALUES('rel','D01','doc-a',?,NULL)", (now(),))
        self.db.execute("UPDATE patients SET age_status='known',age_years=19,birth_date=NULL,created_at=? WHERE id='D01'", (now(),))
        self.context()

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def context_form(self, **kw):
        return {'request_key': secrets.token_hex(16), 'observed_on': records.today().isoformat(),
                'gad_status': 'present', 'severity': 'nonsevere', 'suicide_risk': 'denied',
                'psychiatric_comorbidity': 'denied', 'treatment_resistance': 'denied',
                'aviandr_prescription': 'active', 'clinical_basis': 'Synthetic doctor record F41.1',
                'prescription_basis': 'Synthetic existing prescription', **kw}

    def context(self, **kw):
        return rules.save_context(self.db, self.doc, 'D01', self.context_form(**kw))

    def form(self, **kw):
        return {'request_key': secrets.token_hex(16), 'observed_on': records.today().isoformat(),
                'safety_form_version': 'aviandr-safety-v1',
                **{'safety_' + f: 'present' if f in ('taken', 'after_dose', 'current', 'rigidity') else 'denied'
                   for f in rules.SAFETY_FIELDS}, **kw}

    def save(self, **kw):
        entry = records.save(self.db, self.pat, 'D01', 'self_report', self.form(**kw))
        row = self.db.execute('SELECT * FROM clinical_rule_evaluations WHERE entry_id=?', (entry,)).fetchone()
        self.assertIsNotNone(row)
        return dict(row)

    def count(self, table):
        return self.db.execute('SELECT count(*) FROM ' + table).fetchone()[0]

    def test_each_of_four_source_reactions_creates_event_with_complete_evidence(self):
        for field in rules.SAFETY_FIELDS[3:]:
            with self.subTest(field=field):
                row = self.save(**{**{'safety_' + f: 'denied' for f in rules.SAFETY_FIELDS[3:]}, 'safety_' + field: 'present'})
                self.assertEqual('triggered', row['result'])
                evidence = json.loads(row['evidence_json'])
                self.assertEqual('synthetic_prototype', evidence['release']['mode'])
                self.assertFalse(evidence['release']['clinical_validation'])
                self.assertEqual('doc-a', evidence['context']['actor_id'])
                self.assertEqual({'id':'doc-a','role':'doctor','display_name':'doc-a'}, evidence['context']['payload']['source_author'])
                event = self.db.execute('SELECT * FROM critical_events WHERE evaluation_id=?', (row['id'],)).fetchone()
                self.assertEqual(('rel', 'doc-a', 'pending_s10'), tuple(event[k] for k in ('relationship_id', 'recipient_id', 'delivery_state')))
                outbox = self.db.execute('SELECT * FROM outbox_events WHERE id=?', (event['outbox_event_id'],)).fetchone()
                self.assertEqual(rules.TOPIC, outbox['topic'])
                self.assertEqual({'event_id': event['id'], 'patient_id': 'D01'}, json.loads(outbox['payload_json']))
        self.assertEqual(4, self.count('critical_events'))
        self.assertEqual(0, self.count('care_actions'))

    def test_three_required_facts_missing_denied_conflicting(self):
        for fact in rules.SAFETY_FIELDS[:3]:
            for value, expected in [('unknown','unknown'), ('denied','no_match'), ('conflicting','conflicting')]:
                with self.subTest(fact=fact, value=value):
                    self.assertEqual(expected, self.save(**{'safety_' + fact: value})['result'])
        self.assertEqual(0, self.count('critical_events'))

    def test_reaction_unknown_conflict_negative_and_positive_with_uncertainty(self):
        for value, expected in [('unknown','unknown'), ('denied','no_match'), ('conflicting','conflicting')]:
            self.assertEqual(expected, self.save(safety_rigidity=value)['result'])
        row = self.save(safety_trismus='conflicting')
        self.assertEqual('triggered', row['result'])
        self.assertTrue(json.loads(row['evidence_json'])['uncertainty'])
        self.save(safety_rigidity='denied')
        self.save(safety_rigidity='conflicting')
        self.assertEqual(1, self.count('critical_events'))

    def test_age_18_19_unknown_conflicting_and_all_source_intersection(self):
        for years, status, expected in [(18,'known','not_applicable'), (19,'known','triggered'),
                                         (None,'unknown','unknown'), (19,'conflicting','conflicting')]:
            self.db.execute('UPDATE patients SET age_years=?,age_status=? WHERE id=\'D01\'', (years,status))
            self.assertEqual(expected, self.save()['result'])
        self.db.execute("UPDATE patients SET age_years=19,age_status='known' WHERE id='D01'")
        self.save(age_status='known', age_years='18')
        self.assertEqual('conflicting', self.save()['result'])
        patient = self.db.execute("SELECT * FROM patients WHERE id='D01'").fetchone()
        state = ages.view(self.db, patient)
        today = records.today()
        birth = today.replace(year=today.year - 19).isoformat()
        ages.reconcile(self.db, self.doc, 'D01', {'birth_date': birth, 'basis':'Synthetic reconciliation',
            'reviewed_sources':'yes','sources_fingerprint':state['fingerprint'],'request_key':secrets.token_hex(16)})
        # New unknown age contributes no new age source: reconciliation remains current.
        self.assertEqual('triggered', self.save()['result'])
        # New explicit incompatible source invalidates the current reconciliation.
        self.assertEqual('conflicting', self.save(age_status='known', age_years='18')['result'])

    def test_age_range_crossing_boundary_does_not_choose_adult(self):
        self.db.execute("UPDATE patients SET age_years=18,created_at=? WHERE id='D01'", ((records.today()-timedelta(days=1)).isoformat(),))
        row = self.save()
        self.assertEqual('unknown', row['result'])
        age = json.loads(row['evidence_json'])['age_applicability']
        self.assertEqual((18,19), (age['min_years'],age['max_years']))

    def test_context_rx_denied_unknown_conflicting_missing_and_stale_historical_report(self):
        for rx, expected in [('denied','no_match'),('unknown','unknown'),('conflicting','conflicting')]:
            self.context(aviandr_prescription=rx)
            self.assertEqual(expected, self.save()['result'])
        self.context(observed_on=(records.today()-timedelta(days=1)).isoformat())
        self.assertEqual('unknown', self.save()['result'])
        self.assertEqual('unknown', self.save(safety_taken='denied')['result'])
        self.context()
        self.assertEqual('unknown', self.save(observed_on=(records.today()-timedelta(days=1)).isoformat())['result'])
        # A different synthetic case has no physician context, no invented prescription.
        self.db.execute("UPDATE patients SET age_status='known',age_years=19,birth_date=NULL,created_at=? WHERE id='D02'", (now(),))
        entry = records.save(self.db, {'id':'pat-b','role':'patient'}, 'D02', 'self_report', self.form())
        self.assertEqual('unknown', self.db.execute('SELECT result FROM clinical_rule_evaluations WHERE entry_id=?',(entry,)).fetchone()[0])

    def test_disabled_doctor_and_ended_relationship_preserve_events_and_context(self):
        self.db.execute("UPDATE users SET disabled=1 WHERE id='doc-a'")
        self.assertEqual('triggered', self.save()['result'])
        first = self.db.execute('SELECT * FROM critical_events').fetchone()
        self.assertEqual('doc-a', first['recipient_id'])
        self.db.execute("UPDATE care_relationships SET ends_at=? WHERE id='rel'", (now(),))
        self.assertEqual('triggered', self.save()['result'])
        last = self.db.execute('SELECT * FROM critical_events ORDER BY rowid DESC LIMIT 1').fetchone()
        self.assertEqual('unassigned', last['delivery_state'])
        self.assertIsNone(last['recipient_id'])
        self.assertIsNone(last['relationship_id'])

    def test_referral_mandatory_desirable_alternative_unknown_and_age(self):
        advice = rules.recommendation(self.db, self.doc, 'D01')
        self.assertEqual(('desirable','unknown','psychotherapist'), tuple(advice[k] for k in ('category','urgency','alternative')))
        for field, value in [('severity','severe'),('suicide_risk','present'),('psychiatric_comorbidity','present'),('treatment_resistance','present')]:
            self.context(**{field:value, **({'severity':'unknown'} if field != 'severity' else {})})
            self.assertEqual('mandatory', rules.recommendation(self.db,self.doc,'D01')['category'])
        for changes in ({'gad_status':'unknown'}, {'severity':'unknown'}, {'suicide_risk':'unknown'},
                        {'suicide_risk':'conflicting'}, {'gad_status':'denied'}, {'gad_status':'conflicting'},
                        {'observed_on':(records.today()-timedelta(days=1)).isoformat()}):
            self.context(**changes)
            self.assertEqual('unknown', rules.recommendation(self.db,self.doc,'D01')['category'])
        self.context()
        for age, expected in [(17,'unknown'),(18,'desirable')]:
            self.db.execute("UPDATE patients SET age_years=? WHERE id='D01'", (age,))
            self.assertEqual(expected, rules.recommendation(self.db,self.doc,'D01')['category'])
        self.assertEqual(0,self.count('care_actions'))
        self.assertEqual(0,self.count('proposals'))

    def test_context_idempotency_conflict_and_role_current_authorization(self):
        form = self.context_form()
        first = rules.save_context(self.db, self.doc, 'D01', form)
        self.assertEqual(first, rules.save_context(self.db, self.doc, 'D01', form))
        self.db.execute("UPDATE users SET display_name='changed name' WHERE id='doc-a'")
        self.assertEqual(first, rules.save_context(self.db, self.doc, 'D01', form))
        self.assertEqual('doc-a', rules._context(self.db,'D01')['payload']['source_author']['display_name'])
        with self.assertRaises(rules.RuleError) as caught:
            rules.save_context(self.db, self.doc, 'D01', {**form,'severity':'severe'})
        self.assertEqual(409,caught.exception.status)
        for user in (self.pat, {'id':'doc-b','role':'doctor'}, {'id':'pat-a','role':'doctor'}):
            with self.assertRaises(rules.RuleError):
                rules.save_context(self.db,user,'D01', self.context_form())
            with self.assertRaises(rules.RuleError):
                rules.panel(self.db,user,'D01')
        self.db.execute("UPDATE users SET disabled=1 WHERE id='doc-a'")
        with self.assertRaises(rules.RuleError):
            rules.save_context(self.db,self.doc,'D01',self.context_form())
        self.assertEqual('doc-a', rules._context(self.db,'D01')['actor_id'])

    def test_validation_duplicates_and_required_prescription_basis(self):
        self.assertIsNone(rules.parse_safety({}))
        parsed = rules.parse_safety({'safety_form_version':'aviandr-safety-v1'})
        self.assertTrue(all(parsed[f]=='unknown' for f in rules.SAFETY_FIELDS))
        for bad in ({'safety_form_version':'v0'}, {'safety_form_version':'aviandr-safety-v1','safety_taken':'yes'},
                    MultiDict([('safety_form_version','aviandr-safety-v1'),('safety_taken','present'),('safety_taken','denied')])):
            with self.assertRaises(rules.RuleError): rules.parse_safety(bad)
        for changes in ({'prescription_basis':''},{'clinical_basis':''},{'severity':'mild'},
                        {'observed_on':(records.today()+timedelta(days=1)).isoformat()}, {'clinical_basis':'x'*2001}):
            with self.assertRaises(rules.RuleError): self.context(**changes)

    def test_record_retry_atomic_rollback_and_critical_consumer(self):
        form = self.form()
        first = records.save(self.db,self.pat,'D01','self_report',form)
        self.assertEqual(first,records.save(self.db,self.pat,'D01','self_report',form))
        with self.assertRaises(records.RecordError):
            records.save(self.db,self.pat,'D01','self_report',{**form,'safety_taken':'denied'})
        self.assertEqual(1,self.count('critical_events'))
        tables = ('clinical_entries','clinical_rule_evaluations','critical_events','outbox_events','self_reports','observations')
        before = {t:self.count(t) for t in tables}
        with patch.object(rules.events,'enqueue',side_effect=RuntimeError('injected outbox failure')):
            with self.assertRaises(RuntimeError): self.save()
        self.assertEqual(before,{t:self.count(t) for t in tables})
        while events.process_one(self.db, {k:v for k,v in events.HANDLERS.items() if k != rules.TOPIC}):
            pass
        outbox = self.db.execute('SELECT * FROM outbox_events WHERE topic=?',(rules.TOPIC,)).fetchone()
        self.assertEqual(('pending',0), (outbox['status'],outbox['attempts']))
        self.assertEqual(1,self.count('critical_events'))
        self.assertTrue(events.process_one(self.db))
        self.assertEqual(1,self.count('critical_delivery'))
        self.assertEqual('ok',self.db.execute('PRAGMA integrity_check').fetchone()[0])
        self.assertEqual([],self.db.execute('PRAGMA foreign_key_check').fetchall())

    def test_append_only_and_transaction_requirement(self):
        self.save()
        for table in ('clinical_contexts','clinical_rule_evaluations','critical_events'):
            for statement in ('UPDATE '+table+' SET patient_id=patient_id','DELETE FROM '+table):
                with self.assertRaises(sqlite3.IntegrityError): self.db.execute(statement)
        with self.assertRaises(RuntimeError):
            rules.evaluate_safety(self.db,self.pat,'D01','missing',{'medication_safety':{}})
        self.assertIsNone(rules.evaluate_safety(self.db,self.pat,'D01','missing',{}))

    def test_source_hash_and_release_fail_closed_and_fingerprint(self):
        original = rules.release()
        self.assertEqual(['A02-v2'],original['active_rules'])
        self.assertEqual(64,len(rules.fingerprint()))
        for change in ({'clinical_validation':True}, {'mode':'clinical'}, {'active_rules':['A01']}):
            with patch.object(rules.json,'loads',return_value={**original,**change}):
                with self.assertRaises(rules.RuleError): rules.release()
        bad = json.loads(json.dumps(original))
        bad['sources']['aviandr']['sha256']='0'*64
        with patch.object(rules.json,'loads',return_value=bad):
            with self.assertRaises(rules.RuleError): rules.release()
        before = self.count('clinical_entries')
        with patch.object(rules,'release',side_effect=rules.RuleError('changed source')):
            with self.assertRaises(rules.RuleError): self.save()
        self.assertEqual(before,self.count('clinical_entries'))
        with patch.object(rules,'fingerprint',return_value='changed'):
            self.assertEqual('changed',rules.recommendation(self.db,self.doc,'D01')['release_fingerprint'])

    def test_legacy_reports_and_non_synthetic_case_never_activate_rule(self):
        before = self.count('clinical_rule_evaluations')
        records.save(self.db,self.pat,'D01','self_report',
                     {'request_key':secrets.token_hex(16),'observed_on':records.today().isoformat()})
        self.assertEqual(before,self.count('clinical_rule_evaluations'))
        # The existing schema itself forbids real patients in this prototype.
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE patients SET synthetic=0 WHERE id='D01'")
        self.assertEqual(0,self.count('critical_events'))

    def test_context_transaction_rolls_back_and_event_failure_rolls_back_entire_report(self):
        before_context = self.count('clinical_contexts')
        with patch.object(rules.access,'audit',side_effect=RuntimeError('audit failed')):
            with self.assertRaises(RuntimeError): self.context()
        self.assertEqual(before_context,self.count('clinical_contexts'))
        before = {t:self.count(t) for t in ('clinical_entries','clinical_rule_evaluations','critical_events','outbox_events')}
        self.db.execute("CREATE TEMP TRIGGER fail_event BEFORE INSERT ON critical_events BEGIN SELECT RAISE(ABORT,'test event failure'); END;")
        with self.assertRaises(sqlite3.IntegrityError): self.save()
        self.assertEqual(before,{t:self.count(t) for t in before})
