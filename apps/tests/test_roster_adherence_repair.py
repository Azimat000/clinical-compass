"""S32: fixture correction is bounded, append-only, repeatable and never a clinical inference."""
from contextlib import closing
from copy import deepcopy
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import secrets
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from apps.compass import communication, follow_up, records
from apps.compass.db import connect
from tools import repair_roster_adherence as repair
import test_replace_roster


class RosterAdherenceRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        legacy = deepcopy(repair.replace_roster.load_dataset())
        legacy['version'] = 'clinic-roster-20261023-v1'
        for profile in legacy['patients']:
            profile['outcome_notes'] = {str(i): 'Запись за этот день сделана.' for i in range(6)}
            for index, outcome in repair.LEGACY.get(profile['id'], {}).items():
                profile['outcomes'][index] = outcome
                profile['outcome_notes'][str(index)] = repair.OLD_REASONS[outcome]
        with patch.object(records, 'today', return_value=date(2026, 10, 23)), \
                patch.object(repair.replace_roster, 'load_dataset', return_value=legacy):
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

    def tearDown(self):
        self.db.close(); self.case.cleanup()

    def apply(self):
        return repair.repair(self.path, apply=True, backup_path=self.snapshot)

    def mark(self):
        return self.db.execute("SELECT t.id FROM adherence_tasks t WHERE patient_id='P103' AND due_at LIKE '2026-09-25%'").fetchone()[0]

    def test_dry_run_is_read_only_and_identifies_six_false_results_and_five_explanations(self):
        digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
        result = repair.repair(self.path)
        self.assertFalse(result['applied'])
        self.assertEqual(11, len(result['changes']))
        self.assertEqual(6, sum(x['outcome'] != x['old_outcome'] for x in result['changes']))
        self.assertEqual(digest, hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertFalse(self.snapshot.exists())

    def test_apply_preserves_original_rows_sources_records_and_confirmations(self):
        tables = ('clinical_entries', 'source_versions', 'catalog_versions', 'assessment_form_releases',
                  'adherence_tasks', 'care_actions', 'doctor_confirmations', 'proposals', 'users')
        unchanged = {t: [tuple(r) for r in self.db.execute('SELECT * FROM ' + t)] for t in tables}
        original = {r['id']: tuple(r) for r in self.db.execute('SELECT * FROM adherence_entries')}
        result = self.apply()
        self.assertEqual(11, len(result['changes']))
        self.assertEqual(0o600, self.snapshot.stat().st_mode & 0o777)
        for table, rows in unchanged.items():
            self.assertEqual(rows, [tuple(r) for r in self.db.execute('SELECT * FROM ' + table)], table)
        for rid, row in original.items():
            self.assertEqual(row, tuple(self.db.execute('SELECT * FROM adherence_entries WHERE id=?', (rid,)).fetchone()))
        self.assertEqual(len(original) + 11, self.db.execute('SELECT count(*) FROM adherence_entries').fetchone()[0])
        data = follow_up.view(self.db, {'id': 'm.sokolova', 'role': 'doctor'}, 'P103', {'start': '2026-09-11', 'end': '2026-10-23'})
        item = next(t for t in data['tasks'] if t['due_at'].startswith('2026-09-25'))
        self.assertEqual('taken', item['outcome'])
        self.assertEqual(['missed', 'taken'], [h['outcome'] for h in item['history']])
        self.assertEqual(1, len(item['diary_entries']))
        provenance = json.loads(self.db.execute("SELECT metadata_json FROM audit_entries WHERE event='fictional.adherence_corrected'").fetchone()[0])
        self.assertTrue(provenance['fictional_fixture_correction']); self.assertFalse(provenance['clinical_review'])

    def test_repeat_with_same_backup_is_safe_and_does_not_duplicate_corrections(self):
        self.apply()
        rows = self.db.execute('SELECT count(*) FROM adherence_entries').fetchone()[0]
        again = self.apply()
        self.assertEqual([], again['changes'])
        self.assertEqual(rows, self.db.execute('SELECT count(*) FROM adherence_entries').fetchone()[0])
        self.assertEqual(1, self.db.execute("SELECT count(*) FROM audit_entries WHERE event='fictional.adherence_corrected'").fetchone()[0])

    def test_later_user_clarification_is_never_replaced(self):
        communication.report(self.db, {'id': 'olga.vorontsova', 'role': 'patient'}, 'P103', self.mark(),
                             {'request_key': secrets.token_hex(16), 'outcome': 'missed', 'reason': 'Уточнение пользователя: подробный дневник не заполнен'})
        result = self.apply()
        self.assertEqual(10, len(result['changes']))
        self.assertTrue(any(s['patient_id'] == 'P103' and s['day'] == '2026-09-25' and s['reason'] == 'later_user_mark_preserved' for s in result['skipped']))
        self.assertEqual(2, self.db.execute('SELECT count(*) FROM adherence_entries WHERE task_id=?', (self.mark(),)).fetchone()[0])

    def test_missing_original_report_refuses_before_any_backup_or_write(self):
        changed = deepcopy(repair.replace_roster.load_dataset())
        next(p for p in changed['patients'] if p['id'] == 'P103')['diary'][2] = 'Исходная запись отличается'
        count = self.db.execute('SELECT count(*) FROM adherence_entries').fetchone()[0]
        with patch.object(repair.replace_roster, 'load_dataset', return_value=changed), self.assertRaises(ValueError):
            self.apply()
        self.assertFalse(self.snapshot.exists())
        self.assertEqual(count, self.db.execute('SELECT count(*) FROM adherence_entries').fetchone()[0])

    def test_nonfictional_identity_and_unrecognized_origin_are_rejected(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE patients SET synthetic=0 WHERE id='P103'")
        self.db.execute("UPDATE patients SET user_id=NULL WHERE id='P103'")
        with self.assertRaises(ValueError): self.apply()
        self.assertFalse(self.snapshot.exists())
        self.db.execute("UPDATE patients SET user_id='olga.vorontsova' WHERE id='P103'")
        self.db.execute("INSERT INTO audit_entries(event,entity_id,occurred_at,metadata_json) VALUES('fictional.roster_loaded','extra','2026-10-23','{}')")
        with self.assertRaises(ValueError): self.apply()

    def test_mid_batch_error_rolls_back_every_new_mark_and_retains_backup(self):
        count = self.db.execute('SELECT count(*) FROM adherence_entries').fetchone()[0]
        self.db.execute("CREATE TRIGGER refuse_repair BEFORE INSERT ON adherence_entries WHEN NEW.actor_id='olga.vorontsova' BEGIN SELECT RAISE(ABORT,'test refusal'); END")
        with self.assertRaises(sqlite3.IntegrityError): self.apply()
        self.assertTrue(self.snapshot.exists())
        self.assertEqual(count, self.db.execute('SELECT count(*) FROM adherence_entries').fetchone()[0])
        self.assertEqual(0, self.db.execute("SELECT count(*) FROM audit_entries WHERE event='fictional.adherence_corrected'").fetchone()[0])

    def test_ordinary_self_report_never_automatically_confirms_plan_completion(self):
        records.save(self.db, {'id': 'olga.vorontsova', 'role': 'patient'}, 'P103', 'self_report',
                     {'request_key': secrets.token_hex(16), 'observed_on': '2026-09-25', 'summary': 'Есть сообщение, но о выполнении плана ничего не сказано'})
        item = next(t for t in follow_up.view(self.db, {'id': 'm.sokolova', 'role': 'doctor'}, 'P103', {'start': '2026-09-11', 'end': '2026-10-23'})['tasks'] if t['id'] == self.mark())
        self.assertEqual('missed', item['outcome'])
        self.assertEqual(2, len(item['diary_entries']))


if __name__ == '__main__':
    unittest.main()
