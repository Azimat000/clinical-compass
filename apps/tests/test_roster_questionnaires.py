"""S35: fixture-only, append-only history import, never clinical inference."""
from contextlib import closing
from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from apps.compass import assessments, records
from apps.compass.db import connect, transaction
from tools import seed_roster_questionnaires as seed
import test_replace_roster


class RosterQuestionnaireTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.object(records, 'today', return_value=date(2026, 10, 23)):
            test_replace_roster.ReplaceRosterTests.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.case = tempfile.TemporaryDirectory()
        self.path = Path(self.case.name) / 'case.sqlite3'
        self.snapshot = Path(self.case.name) / 'before.sqlite3'
        shutil.copy2(self.target, self.path)
        self.db = connect(self.path)
        self.before = {r[0]: [tuple(x) for x in self.db.execute('SELECT * FROM "'+r[0]+'"')]
                       for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}

    def tearDown(self):
        self.db.close(); self.case.cleanup()

    def apply(self):
        return seed.seed(self.path, apply=True, backup_path=self.snapshot)

    def test_dry_run_identifies_48_and_does_not_write(self):
        digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
        result = seed.seed(self.path)
        self.assertFalse(result['applied']); self.assertEqual(48, len(result['changes']))
        self.assertEqual(2, sum(x['incomplete'] for x in result['changes']))
        self.assertEqual(digest, hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertFalse(self.snapshot.exists())

    def test_apply_preserves_all_prior_rows_and_only_appends_expected_tables(self):
        result = self.apply()
        self.assertEqual(48, len(result['changes']))
        self.assertEqual(0o600, self.snapshot.stat().st_mode & 0o777)
        additions = {'assessment_requests': 48, 'assessments': 48, 'assessment_results': 48, 'audit_entries': 1}
        for table, rows in self.before.items():
            after = [tuple(x) for x in self.db.execute('SELECT * FROM "'+table+'"')]
            self.assertEqual(len(rows)+additions.get(table, 0), len(after), table)
            self.assertTrue(set(rows) <= set(after), table)
        provenance = json.loads(self.db.execute('SELECT metadata_json FROM audit_entries WHERE event=?', (seed.EVENT,)).fetchone()[0])
        self.assertTrue(provenance['synthetic']); self.assertTrue(provenance['simulated_dates'])
        self.assertFalse(provenance['clinical_review']); self.assertFalse(provenance['real_user_trial'])
        self.assertFalse(provenance['derived_from_dass'])
        self.assertEqual(48, len(provenance['entries']))
        self.assertGreater(provenance['actual_imported_at'], '2026-10-22T23:59:59+00:00')
        self.assertEqual([], self.db.execute('PRAGMA foreign_key_check').fetchall())

    def test_authored_reference_courses_and_incomplete_gap(self):
        self.apply()
        expected = {'P101': [[11,6,3],[13,6,3]], 'P102': [[9,12,9],[13,11,8]],
            'P103': [[17,16,17],[14,13,14]], 'P104': [[9,15,16],[7,9,12]],
            'P105': [[21,19,9],[12,10,6]], 'P106': [[18,15,12],[9,7,6]],
            'P107': [[8,7,5],[13,11,6]], 'P108': [[12,None,12],[9,None,9]]}
        for pid, columns in expected.items():
            doctor = 'm.sokolova' if pid < 'P105' else 'd.krylov' if pid < 'P107' else 'y.lebedeva'
            rows = assessments.history(self.db, {'id':doctor,'role':'doctor'}, pid)
            for index, code in enumerate(('PHQ-9','GAD-7')):
                form_rows = sorted([r for r in rows if r['form']['code']==code], key=lambda r:r['observed_on'])
                self.assertEqual(3, len(form_rows))
                authored = seed.load_dataset()[0]['patients'][pid]
                self.assertEqual(authored['phq' if code=='PHQ-9' else 'gad'], [r['answers'] for r in form_rows])
                scores = [next(iter(r['scores'].values())) if r['scores'] is not None else None for r in form_rows]
                self.assertEqual(columns[index], scores, (pid, code))
                trend = assessments.trends(form_rows)[0]
                self.assertEqual(2 if pid=='P108' else 3, len(trend['series'][0]['points']))
                if pid=='P108':
                    self.assertEqual([1,1], [len(s) for s in trend['series'][0]['segments']])
                    self.assertEqual(0, trend['series'][0]['delta'])
                    self.assertEqual('incomplete', form_rows[1]['completeness'])
                    self.assertIn(None, form_rows[1]['answers'])

    def test_repeat_is_noop_and_does_not_require_a_new_backup(self):
        self.apply()
        before = self.db.total_changes
        result = self.apply()
        self.assertEqual([], result['changes']); self.assertEqual(48, len(result['skipped']))
        self.assertIsNone(result['backup']); self.assertEqual(before, self.db.total_changes)
        self.assertEqual(1, self.db.execute('SELECT count(*) FROM audit_entries WHERE event=?', (seed.EVENT,)).fetchone()[0])

    def test_missing_backup_and_unrecognized_identity_fail_before_writes(self):
        with self.assertRaisesRegex(ValueError, 'backup'):
            seed.seed(self.path, apply=True)
        self.db.execute("UPDATE patients SET code='Другой пациент' WHERE id='P101'")
        with self.assertRaisesRegex(ValueError, 'identity'):
            self.apply()
        self.assertFalse(self.snapshot.exists())
        self.assertEqual(len(self.before['assessments']), self.db.execute('SELECT count(*) FROM assessments').fetchone()[0])

    def test_withdrawn_source_rejects_before_backup(self):
        self.db.execute("UPDATE source_versions SET rights_status='unknown' WHERE id='PHQ9-RU-Z-2023-demo-v1-source'")
        with self.assertRaises(assessments.AssessmentError): self.apply()
        self.assertFalse(self.snapshot.exists())

    def test_audit_failure_rolls_back_all_144_new_rows(self):
        with patch.object(seed.database, 'now', side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError): self.apply()
        for table in ('assessment_requests','assessments','assessment_results','audit_entries'):
            self.assertEqual(len(self.before[table]), self.db.execute('SELECT count(*) FROM '+table).fetchone()[0])
        self.assertTrue(self.snapshot.exists())

    def test_existing_unrelated_same_date_response_is_preserved(self):
        item = seed.plan(self.db)['changes'][0]
        q,a,r = map(list, (item['request'],item['assessment'],item['result']))
        q[0]='a'*32; q[11]='b'*64; a[0]='c'*32; r[0]=a[0];r[1]=q[0]
        with transaction(self.db):
            self.db.execute('INSERT INTO assessment_requests VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)', q)
            self.db.execute('INSERT INTO assessments VALUES(?,?,?,?,?,?,?,?,?)', a)
            self.db.execute('INSERT INTO assessment_results VALUES(?,?,?,?,?,?)', r)
        result = self.apply()
        self.assertEqual(47, len(result['changes']))
        self.assertEqual('existing_other_response_preserved', result['skipped'][0]['reason'])
        self.assertEqual(tuple(a), tuple(self.db.execute('SELECT * FROM assessments WHERE id=?', (a[0],)).fetchone()))

    def test_changed_original_safety_response_anchor_requires_explicit_reauthoring(self):
        data, roster = seed.load_dataset()
        data['patients']['P101']['prior_dass_item21'][0] = 3
        with patch.object(seed, 'load_dataset', return_value=(data, roster)):
            with self.assertRaisesRegex(ValueError, 'safety-related response differs'):
                self.apply()
        self.assertFalse(self.snapshot.exists())

    def test_changed_import_resource_and_partial_collision_are_not_silently_repaired(self):
        item = seed.plan(self.db)['changes'][0]
        self.db.execute('INSERT INTO assessment_requests VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)', item['request'])
        with self.assertRaisesRegex(ValueError, 'refusing overwrite'): self.apply()
        self.assertFalse(self.snapshot.exists())


if __name__ == '__main__': unittest.main()
