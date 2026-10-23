"""S36 fixture integrity and plan UI; no clinical assertions."""
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
import unittest
from unittest.mock import patch
from apps.compass import medications, records, decisions
from apps.compass.db import connect
from apps.compass.web import create_app
from tools import seed_roster_medications as seed
import test_replace_roster


class RosterMedicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.object(records,'today',return_value=date(2026,10,23)):
            test_replace_roster.ReplaceRosterTests.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.case=tempfile.TemporaryDirectory();self.path=Path(self.case.name)/'case.sqlite3'
        self.snapshot=Path(self.case.name)/'before.sqlite3'
        shutil.copy2(self.target,self.path);self.db=connect(self.path)
        self.before={r[0]:set(tuple(x) for x in self.db.execute('SELECT * FROM "'+r[0]+'"'))
                     for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}

    def tearDown(self):
        self.db.close();self.case.cleanup()

    def apply(self):
        return seed.seed(self.path,apply=True,backup_path=self.snapshot)

    def test_preview_backup_append_only_and_idempotence(self):
        digest=hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.assertEqual(250,seed.seed(self.path)['additions']['medication_marks'])
        self.assertEqual(digest,hashlib.sha256(self.path.read_bytes()).hexdigest())
        with self.assertRaises(ValueError):seed.seed(self.path,apply=True)
        result=self.apply();self.assertEqual(0o600,self.snapshot.stat().st_mode&0o777)
        additions={**result['additions'],'audit_entries':1}
        for table,rows in self.before.items():
            after=set(tuple(x) for x in self.db.execute('SELECT * FROM "'+table+'"'))
            self.assertTrue(rows<=after,table);self.assertEqual(len(rows)+additions.get(table,0),len(after),table)
        digest=hashlib.sha256(self.path.read_bytes()).hexdigest()
        again=seed.seed(self.path,apply=True)
        self.assertTrue(again['already_imported']);self.assertEqual({},again['additions'])
        self.assertEqual(digest,hashlib.sha256(self.path.read_bytes()).hexdigest())
        audit=json.loads(self.db.execute('SELECT metadata_json FROM audit_entries WHERE event=?',(seed.EVENT,)).fetchone()[0])
        self.assertTrue(audit['synthetic']);self.assertFalse(audit['clinical_review']);self.assertTrue(audit['fictional_medication_names'])
        self.assertIn('actual_imported_at',audit)

    def test_all_doctors_exact_miss_unknown_and_prior_contradictions_preserved(self):
        self.apply();data,roster=seed.load_dataset();missed=[]
        for p in roster['patients']:
            doses=medications.occurrences(self.db,p['id'],date(2026,9,11),date(2026,10,23))
            self.assertTrue(doses,p['id'])
            missed += [(p['id'],d['day']) for d in doses if d['state']=='missed']
            if p['id']=='P108':
                self.assertEqual(data['patients']['P108']['unmarked'],[d['day'] for d in doses if d['state']=='unknown'])
            if p['id'] in ('P104','P106'):
                self.assertEqual(['2026-10-23'],[d['day'] for d in doses])
            head=decisions.history(self.db,{'id':p['doctor'],'role':'doctor'},p['id'])[0]
            self.assertEqual(p['plans'][-1],head['payload']['content'])
            self.assertEqual(p['doctor'],head['doctor_id'])
        self.assertEqual([('P103','2026-10-22')],missed)
        self.assertEqual('ok',self.db.execute('PRAGMA integrity_check').fetchone()[0])
        self.assertEqual([],self.db.execute('PRAGMA foreign_key_check').fetchall())

    def test_timeline_excludes_future_and_links_to_actual_gap(self):
        self.apply()
        with patch.object(records,'today',return_value=date(2026,10,23)),patch.object(medications,'now',return_value='2026-10-23T09:00:00+03:00'):
            cal=medications.calendar(self.db,'P103','2026-10-22')
            self.assertEqual(6,len(cal['periods']));last=cal['periods'][-1]
            self.assertEqual(4,last['total']);self.assertEqual(1,last['missed']);self.assertEqual('2026-10-22',last['open_day'])
            cal=medications.calendar(self.db,'P108','2026-10-16')
            self.assertEqual(3,sum(p['unknown'] for p in cal['periods']))
            self.assertEqual('unknown',cal['doses'][0]['state'])

    def test_rollback_and_existing_identity_work_refused(self):
        with patch.object(seed.backup,'checked',side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError):self.apply()
        for table,rows in self.before.items():
            self.assertEqual(rows,set(tuple(x) for x in self.db.execute('SELECT * FROM "'+table+'"')),table)
        self.db.execute("UPDATE patients SET code='Changed identity' WHERE id='P101'")
        with self.assertRaises(ValueError):seed.seed(self.path)

    def test_missing_or_changed_imported_row_is_not_silently_repaired(self):
        self.apply()
        # Provenance and all imported rows are immutable. A forged second provenance is rejected.
        self.db.execute('INSERT INTO audit_entries(event,entity_id,occurred_at,metadata_json) VALUES(?,?,?,?)',
            (seed.EVENT,seed.load_dataset()[0]['version'],'2026-10-23','{}'))
        with self.assertRaises(ValueError):seed.seed(self.path,apply=True)

    def test_structure_compose_nojs_errors_and_stable_anchors(self):
        self.apply();app=create_app(self.path)
        from apps.compass import access
        client=app.test_client()
        session,error=access.authenticate(self.db,'m.sokolova',self.accounts['m.sokolova']['password'],'127.0.0.1')
        self.assertIsNone(error);client.set_cookie(access.COOKIE,session)
        csrf=self.db.execute('SELECT csrf_token FROM sessions WHERE token_hash=?',(access.digest(session),)).fetchone()[0]
        base='/patients/P103/decisions'
        html=client.get(base).text
        self.assertEqual(200,client.get(base).status_code)
        self.assertIn('<h2 id="h-current">Текущий план</h2>',html)
        self.assertLess(html.index('id="current"'),html.index('id="medications"'))
        self.assertNotIn('id="waiting"',html)
        self.assertNotIn('id="new-decision" open',html)
        ids=re.findall(r'\sid="([^"]+)"',html);self.assertEqual(len(ids),len(set(ids)))
        opened=client.get(base+'?compose=1&med_edit=1#new-decision').text
        self.assertIn('id="new-decision" open',opened)
        self.assertIn('value="replace" selected',opened)
        response=client.post(base,data={'csrf':csrf,'request_key':'d'*32,'kind':'plan_change','content':'Сохрани мой текст'})
        self.assertEqual(400,response.status_code);self.assertIn('id="new-decision" open',response.text)
        self.assertIn('Сохрани мой текст',response.text)
