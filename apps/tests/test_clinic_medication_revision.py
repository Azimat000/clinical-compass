"""S56: source-bound fictional re-authoring preserves IDs and clinical boundaries."""
from contextlib import closing
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import unittest
from unittest.mock import patch

from apps.compass import assessments, decisions, medications, records
from apps.compass.backup import copy_database
from apps.compass.db import connect
from apps.compass.web import create_app
from tools import revise_clinic_medications as revision
import test_clinic_roster as base


class ClinicMedicationRevisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # S56 is an exact dated revision of S55 authored on 26 October.
        # Dynamic 'today' would silently construct a different source fixture.
        with patch('apps.compass.records.today',return_value=date(2026,10,26)):
            base.ClinicRosterTests.setUpClass()
        cls.original = base.ClinicRosterTests.target
        cls.target = cls.original.with_name('revised.sqlite3')
        cls.before = hashlib.sha256(cls.original.read_bytes()).hexdigest()
        with patch('apps.compass.records.today',return_value=date(2026,10,26)):
            cls.result = revision.build(cls.original, cls.target)
        cls.app = create_app(cls.target)
        cls.accounts = base.ClinicRosterTests.accounts

    @classmethod
    def tearDownClass(cls):
        base.ClinicRosterTests.tearDownClass()

    def setUp(self):
        clock=patch('apps.compass.records.today',return_value=date(2026,10,26))
        clock.start();self.addCleanup(clock.stop)

    def login(self, uid):
        client = self.app.test_client()
        token = re.search('name="csrf" value="([^"]+)"', client.get('/login').text)[1]
        response = client.post('/login',data=dict(csrf=token,login=uid,password=self.accounts[uid]['password']))
        self.assertEqual(302,response.status_code)
        return client

    def test_source_and_ids_passwords_sources_protections_preserved(self):
        self.assertEqual(self.before,hashlib.sha256(self.original.read_bytes()).hexdigest())
        self.assertEqual(0o600,self.target.stat().st_mode&0o777)
        with closing(connect(self.target)) as db, closing(connect(self.original)) as old:
            for table in ('users','patients','care_relationships','doctor_confirmations','care_actions',
                          'source_versions','catalog_versions','assessment_form_releases','text_imports','extraction_reviews'):
                self.assertEqual([tuple(r) for r in old.execute('SELECT * FROM '+table)],
                                 [tuple(r) for r in db.execute('SELECT * FROM '+table)],table)
            for table in ('proposals','clinical_entries','self_reports','first_visit_versions','messages'):
                self.assertEqual({r[0] for r in old.execute('SELECT id FROM '+table)},
                                 {r[0] for r in db.execute('SELECT id FROM '+table)})
            triggers = 'SELECT name,sql FROM sqlite_master WHERE type=\'trigger\' ORDER BY name'
            self.assertEqual([tuple(r) for r in old.execute(triggers)],[tuple(r) for r in db.execute(triggers)])
            for table in ('clinical_entries','first_visit_versions','proposals','medication_marks','messages'):
                with self.assertRaises(sqlite3.IntegrityError):
                    field='sequence' if table=='medication_marks' else 'id'
                    db.execute(f'UPDATE {table} SET {field}={field}')
            self.assertEqual('ok',db.execute('PRAGMA integrity_check').fetchone()[0])
            self.assertEqual([],db.execute('PRAGMA foreign_key_check').fetchall())
            self.assertEqual(0,db.execute('SELECT count(*) FROM clinical_rule_evaluations').fetchone()[0])

    def test_all_medication_phases_have_exact_strength_and_no_overlap(self):
        with closing(connect(self.target)) as db:
            def dose(pid,day):
                return medications.occurrences(db,pid,date.fromisoformat(day),date.fromisoformat(day))
            for pid in ('P202','P208'):
                self.assertIn('25 мг',dose(pid,'2026-09-21')[0]['name'])
                self.assertIn('50 мг',dose(pid,'2026-09-22')[0]['name'])
            for day, strength in (('2026-10-05','50 мг'),('2026-10-06','25 мг'),('2026-10-12','25 мг'),('2026-10-13','50 мг')):
                item=dose('P204',day)
                self.assertEqual(1,len(item))
                self.assertIn('Алевал '+strength,item[0]['name'])
                self.assertEqual(4,item[0]['quarters'])
            self.assertEqual(4,dose('P207','2026-10-05')[0]['quarters'])
            for day in ('2026-10-06','2026-10-18'):
                item=dose('P207',day)[0]
                self.assertIn('Элицея 10 мг',item['name'])
                self.assertEqual(2,item['quarters'])
                self.assertEqual(2,item['actual'])
            self.assertEqual([],dose('P207','2026-10-19'))
            self.assertEqual([],medications.approved(db,'P207')[-1]['medications'])
            self.assertEqual(240,db.execute('SELECT count(*) FROM medication_marks').fetchone()[0])
            for pid in revision.load()['plans']:
                for item in medications.occurrences(db,pid,date(2026,9,15),date(2026,12,4)):
                    if 'Алевал' in item['name']:
                        self.assertEqual(4,item['quarters'])  # Separate tablet strengths, no asserted equal splitting.

    def test_reports_mirrors_feedback_marks_snapshots_and_indexes_agree(self):
        with closing(connect(self.target)) as db:
            proposals={r['id']:dict(r) for r in db.execute('SELECT * FROM proposals')}
            for row in db.execute('SELECT * FROM clinical_entries'):
                payload=json.loads(row['payload_json'])
                mirror=db.execute('SELECT payload_json FROM self_reports WHERE id=?',(row['self_report_id'],)).fetchone()[0]
                self.assertEqual(row['payload_json'],mirror)
                for feedback in payload.get('medication_feedback',[]):
                    med=json.loads(proposals[feedback['proposal_id']]['payload_json'])['medications'][feedback['med_index']]
                    self.assertEqual(med['name'],feedback['name'])
                    self.assertLessEqual(med['start'],row['observed_on'])
                    self.assertGreaterEqual(med['end'],row['observed_on'])
                search=db.execute('SELECT body FROM clinical_entry_search WHERE entry_id=?',(row['id'],)).fetchone()[0]
                self.assertEqual(row['summary']+' '+row['payload_json'],search)
            self.assertTrue(db.execute("SELECT 1 FROM clinical_entry_search WHERE clinical_entry_search MATCH 'Элицея'").fetchone())
            for row in proposals.values():
                snapshot=json.loads(row['input_snapshot_json'])
                for table in ('clinical_entries','self_reports','first_visit_versions','medication_marks','messages','observations','adverse_events'):
                    for item in snapshot.get(table,[]):
                        key='sequence' if table=='medication_marks' else 'id'
                        stored=dict(db.execute(f'SELECT * FROM {table} WHERE {key}=?',(item[key],)).fetchone())
                        self.assertEqual(item,stored,(table,row['id']))
                for item in snapshot.get('medication_marks',[]):
                    self.assertLessEqual(item['recorded_at'],row['created_at'])
            for uid,pid in (('a.mironov','P209'),('a.mironov','P210')):
                relationship=db.execute('SELECT id FROM care_relationships WHERE patient_id=?',(pid,)).fetchone()[0]
                draft=db.execute('SELECT p.input_snapshot_json FROM proposals p WHERE patient_id=? AND NOT EXISTS(SELECT 1 FROM doctor_confirmations c WHERE c.proposal_id=p.id)',(pid,)).fetchone()[0]
                self.assertEqual(decisions.snapshot(db,pid,relationship),draft)

    def test_no_placeholders_in_current_records_and_four_nonmedicated_cases_unchanged(self):
        with closing(connect(self.target)) as db,closing(connect(self.original)) as old:
            for table,field in (('proposals','payload_json'),('proposals','input_snapshot_json'),('clinical_entries','payload_json'),
                                ('first_visit_versions','payload_json'),('self_reports','payload_json'),('messages','body'),('adverse_events','description')):
                for row in db.execute('SELECT '+field+' FROM '+table):
                    self.assertNotIn('Препарат А',row[0]);self.assertNotIn('Препарат Б',row[0])
            for pid in ('P205','P206','P209','P210'):
                for table in ('clinical_entries','self_reports','first_visit_versions','proposals'):
                    self.assertEqual([tuple(r) for r in old.execute('SELECT * FROM '+table+' WHERE patient_id=?',(pid,))],
                                     [tuple(r) for r in db.execute('SELECT * FROM '+table+' WHERE patient_id=?',(pid,))],(pid,table))
            provenance=json.loads(db.execute('SELECT metadata_json FROM audit_entries WHERE event=?',(revision.EVENT,)).fetchone()[0])
            self.assertTrue(provenance['synthetic']);self.assertFalse(provenance['clinical_review'])
            self.assertFalse(provenance['medication_eligibility_established'])
            self.assertEqual(13,provenance['added_synthetic_marks'])

    def test_same_logins_pages_roles_and_pending_forms_work(self):
        for uid,pid in (('e.orlova','P203'),('a.mironov','P207')):
            client=self.login(uid)
            for route in ('/demo/'+pid,'/patients/'+pid+'/decisions','/patients/'+pid+'/communication'):
                response=client.get(route)
                self.assertEqual(200,response.status_code,route)
                self.assertNotIn('Препарат А',response.text);self.assertNotIn('Препарат Б',response.text)
        client=self.login('nikita.zuev')
        self.assertEqual(200,client.get('/demo/P204/report').status_code)
        self.assertEqual(404,client.get('/demo/P201').status_code)
        with closing(connect(self.target)) as db:
            for p in base.ClinicRosterTests.data['patients']:
                self.assertEqual(3,len(assessments.pending(db,dict(id=p['login'],role='patient'),p['id'])))

    def test_existing_output_real_data_and_post_fixture_work_are_rejected(self):
        with self.assertRaises(ValueError):revision.build(self.original,self.target)
        for mode in ('real','new_work'):
            altered=self.original.with_name(mode+'.sqlite3');out=altered.with_name(mode+'-out.sqlite3')
            copy_database(self.original,altered)
            with closing(connect(altered)) as db:
                if mode=='real':
                    # Simulate an incompatible legacy/corrupt input only in this disposable copy.
                    db.execute('PRAGMA ignore_check_constraints=ON')
                    db.execute("UPDATE patients SET synthetic=0 WHERE id='P201'")
                else:records.save(db,dict(id='anna.larina',role='patient'),'P201','self_report',dict(
                    request_key='f'*32,observed_on=records.today().isoformat(),summary='NEW USER WORK MUST SURVIVE'))
            with self.assertRaises(ValueError):revision.build(altered,out)
            self.assertFalse(out.exists())
        self.assertEqual(self.before,hashlib.sha256(self.original.read_bytes()).hexdigest())


if __name__=='__main__':unittest.main()
