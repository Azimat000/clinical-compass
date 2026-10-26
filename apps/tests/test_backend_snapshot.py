"""BE02: real source adapters, frozen evidence, permissions and completeness."""
from copy import deepcopy
import json
import secrets
import sqlite3
import unittest

from apps.compass import access, assessments, backend_analyses as analyses, backend_snapshot as snapshots
from apps.compass import decisions, first_visits, medications, records
from apps.compass.db import now
from apps.compass.web import create_app
from apps.tests import test_access, test_backend_contracts


def pointer(row, path):
    value = row
    for part in path.lstrip('/').split('/'):
        if isinstance(value, str):
            value = json.loads(value)
        value = value[part.replace('~1', '/').replace('~0', '~')]
        if part.endswith('_json') and value is not None:
            value = json.loads(value)
    return value


class BackendSnapshotTests(unittest.TestCase):
    setUp = test_backend_contracts.BackendContractTests.setUp
    tearDown = test_access.AccessTests.tearDown
    post = test_access.AccessTests.post
    offer = test_access.AccessTests.offer
    body = test_backend_contracts.BackendContractTests.body

    def run_analysis(self):
        return analyses.create(self.db, self.user, 'D01', self.body())

    def frozen(self, run=None):
        run = run or self.run_analysis()
        row = self.db.execute('SELECT payload_json FROM analysis_input_snapshots WHERE id=?',
                              (run['snapshot_id'],)).fetchone()
        return json.loads(row[0])

    def visit(self, **updates):
        values = {'request_key': secrets.token_hex(16), 'base_revision': '0', 'state': 'draft',
                  'observed_on': '2026-10-18', 'visit_kind': 'first', 'not_collected': 'yes',
                  'age_source': 'patient', 'history_status': 'known', 'history_text': 'Прежний эпизод: синтетика.',
                  'history_basis': 'Беседа', 'history_on': '2020-01-01',
                  'safety_status': 'denied', 'safety_basis': 'Явное отрицание', **updates}
        vid = first_visits.save(self.db, self.user, 'D01', 'new', values)
        return vid, values

    def diary(self, **updates):
        values = {'request_key': secrets.token_hex(16), 'observed_on': '2026-10-18',
                  'summary': 'Вымышленная поздняя запись', 'wellbeing': 'worse', **updates}
        rid = records.save(self.db, {'id': 'pat-a', 'role': 'patient'}, 'D01', 'self_report', values)
        return rid, values

    def questionnaire(self, missing=False):
        form = assessments.definition()
        task = assessments.assign(self.db, self.user, 'D01', {
            'assignment_key': secrets.token_hex(16), 'form_version_id': form['id'],
            'age_status': 'known', 'age_years': '35', 'age_basis': 'Синтетический профиль'})
        values = {'form_version_id': form['id'], **{f'answer_{i}': '1' for i in range(1, 43)}}
        if missing:
            values['answer_2'] = ''
        return assessments.submit(self.db, {'id': 'pat-a', 'role': 'patient'}, task, values)

    def plan(self, **updates):
        values = {'kind': 'plan_change', 'request_key': secrets.token_hex(16),
                  'content': 'Вымышленный план', 'basis': 'Синтетический приём',
                  'uncertainties': 'Только проверка механизма', **updates}
        return decisions.draft(self.db, self.user, 'D01', values)

    def approve(self, proposal):
        row = self.db.execute('SELECT * FROM proposals WHERE id=?', (proposal,)).fetchone()
        return decisions.confirm(self.db, self.user, 'D01', proposal, {
            'decision': 'approved', 'version': str(row['version']), 'reviewed': 'yes',
            'rationale': 'Синтетическая проверка механизма'})

    def test_four_sources_exact_rows_fragments_authors_versions_and_no_other_patient(self):
        self.visit()
        self.diary()
        self.questionnaire()
        run = self.run_analysis()
        frozen = self.frozen(run)
        history = frozen['patient_history']
        self.assertTrue(all(history['counts'][c] > 0 for c in snapshots.CATEGORIES[:4]))
        self.assertEqual([], history['missing_categories'])
        self.assertTrue(history['complete']); self.assertFalse(history['truncated'])
        for ref, meta in history['sources'].items():
            resolved = snapshots.resolve(frozen, ref)
            table = 'care_actions' if meta['table'] == 'actions' else meta['table']
            actual = dict(self.db.execute(f'SELECT * FROM {table} WHERE {meta["key"]}=?', (meta['id'],)).fetchone())
            if table == 'care_actions':
                actual['proposal_id'] = resolved['row']['proposal_id']
            self.assertEqual(actual, resolved['row'], ref)
            self.assertEqual(snapshots.digest(actual), meta['sha256'])
            if 'patient_id' in actual:
                self.assertEqual('D01', actual['patient_id'])
        for entry in history['entries']:
            for field in entry['fields']:
                row = snapshots.resolve(frozen, field['source_ref'])['row']
                self.assertEqual(field['value'], pointer(row, field['path']), field)
        questionnaire = next(e for e in history['entries'] if e['category'] == 'questionnaires' and e['author_id'])
        self.assertEqual('pat-a', questionnaire['author_id'])
        scores = next(f for f in questionnaire['fields'] if f['code'] == 'scores')
        self.assertEqual({'anxiety': 14, 'depression': 14, 'stress': 14}, scores['value'])
        self.assertEqual('historical', next(e for e in history['entries'] if e['category'] == 'wellbeing')['temporal_scope'])

    def test_version_correction_is_immutable_and_history_fields_remain_distinct(self):
        vid, values = self.visit(complaints_status='known', complaints_text='Исходные жалобы', complaints_basis='Беседа')
        old = self.run_analysis()
        before = self.frozen(old)
        values.update(base_revision='1', request_key=secrets.token_hex(16), state='completed', complaints_text='Уточнённые жалобы')
        first_visits.save(self.db, self.user, 'D01', vid, values)
        self.assertEqual('stale', analyses.read(self.db, self.user, 'D01', old['run_id'])['status'])
        self.assertEqual(before, self.frozen(old))
        entries = [e for e in self.frozen()['patient_history']['entries'] if e['category'] == 'visits' and e['author_id'] == 'doc-a']
        self.assertEqual(2, len(entries))
        original, corrected = sorted(entries, key=lambda e: e['version'])
        self.assertFalse(original['current_revision']); self.assertTrue(corrected['current_revision'])
        self.assertEqual(original['ref'], corrected['supersedes_ref'])
        history = next(f for f in corrected['fields'] if f['code'] == 'history')
        complaints = next(f for f in corrected['fields'] if f['code'] == 'complaints')
        self.assertEqual('cumulative_history', history['context'])
        self.assertEqual('2020-01-01', history['event_at'])
        self.assertEqual('current', complaints['context'])
        for statement in ('DELETE FROM first_visit_versions', 'UPDATE first_visit_versions SET state=state'):
            with self.assertRaises(sqlite3.IntegrityError): self.db.execute(statement)

    def test_late_entry_duplicate_retry_unknown_empty_and_explicit_conflict(self):
        old = self.run_analysis()
        rid, form = self.diary(complaints_status='conflicting', complaints_text='Противоречивые сведения')
        records.save(self.db, {'id': 'pat-a', 'role': 'patient'}, 'D01', 'self_report', form)
        frozen = self.frozen()
        entries = frozen['patient_history']['entries']
        diaries = [e for e in entries if e['category'] == 'wellbeing']
        self.assertEqual(1, len(diaries))
        entry = diaries[0]
        self.assertEqual('2026-10-18', entry['event_at'])
        self.assertGreater(entry['recorded_at'][:10], entry['event_at'])
        self.assertIn('explicit_conflict:complaints', entry['issues'])
        self.assertTrue(any(f['status'] == 'unknown' and f['value'] is None for f in entry['fields']))
        self.assertEqual('stale', analyses.read(self.db, self.user, 'D01', old['run_id'])['status'])
        with self.assertRaises(sqlite3.IntegrityError): self.db.execute('DELETE FROM clinical_entries WHERE id=?', (rid,))

    def test_denial_and_disagreement_not_treated_as_absent_data_or_different_day_conflict(self):
        self.visit(complaints_status='known', complaints_text='Есть жалобы', complaints_basis='Беседа')
        self.diary(complaints_status='denied')
        history = self.frozen()['patient_history']
        relevant = [e for e in history['entries'] if e['category'] in ('visits', 'wellbeing')]
        self.assertEqual(2, sum('same_day_disagreement:complaints' in e['issues'] for e in relevant))
        safety = next(f for e in relevant for f in e['fields'] if f['code'] == 'safety')
        self.assertEqual('denied', safety['status']); self.assertEqual('', safety['value'])
        self.diary(observed_on='2026-10-17', complaints_status='known', complaints_text='Другой день')
        other = next(e for e in self.frozen()['patient_history']['entries'] if e['category'] == 'wellbeing' and e['event_at'] == '2026-10-17')
        self.assertNotIn('same_day_disagreement:complaints', other['issues'])

    def test_unknown_age_and_missing_answers_are_explicit_not_zero(self):
        aid = self.questionnaire(missing=True)
        self.db.execute("UPDATE patients SET age_status='unknown', age_years=NULL, birth_date=NULL WHERE id='D01'")
        run = self.run_analysis()
        self.assertEqual('insufficient_data', run['status'])
        history = self.frozen(run)['patient_history']
        entry = next(e for e in history['entries'] if e['category'] == 'questionnaires' and e['state'] == 'incomplete')
        self.assertIsNone(next(f for f in entry['fields'] if f['code'] == 'scores')['value'])
        answers = next(f for f in entry['fields'] if f['code'] == 'answers')['value']
        self.assertIsNone(answers[1])
        self.assertIsNone(self.db.execute('SELECT score FROM assessments WHERE id=?', (aid,)).fetchone()[0])

    def test_fingerprint_stable_new_clinical_fact_changes_it_unrelated_audit_does_not(self):
        one = self.run_analysis(); two = self.run_analysis()
        self.assertEqual(one['snapshot_id'], two['snapshot_id'])
        access.audit(self.db, 'doc-a', 'test.unrelated', 'none')
        self.assertEqual(one['snapshot_id'], self.run_analysis()['snapshot_id'])
        self.db.execute("INSERT INTO encounters(id,patient_id,occurred_at,narrative,origin) VALUES('foreign','D02','2026-10-18','FOREIGN_SECRET','synthetic')")
        self.assertEqual(one['snapshot_id'], self.run_analysis()['snapshot_id'])
        self.assertNotIn('FOREIGN_SECRET', decisions.canonical(self.frozen(one)))
        self.diary()
        self.assertNotEqual(one['snapshot_id'], self.run_analysis()['snapshot_id'])

    def test_allowed_legacy_deletion_and_source_withdrawal_invalidate_but_old_evidence_opens(self):
        self.db.execute("INSERT INTO encounters(id,patient_id,occurred_at,narrative,origin) VALUES('deletable','D01','2026-10-18','Архив без связанных строк','synthetic')")
        row = self.db.execute("SELECT * FROM encounters WHERE id='deletable'").fetchone()
        old = self.run_analysis(); frozen = self.frozen(old)
        ref = next(ref for ref, meta in frozen['patient_history']['sources'].items() if meta['table'] == 'encounters' and meta['id'] == row['id'])
        # An unlinked legacy archive is deletable under the existing schema.
        self.db.execute('DELETE FROM encounters WHERE id=?', (row['id'],))
        self.assertEqual('stale', analyses.read(self.db, self.user, 'D01', old['run_id'])['status'])
        self.assertEqual(dict(row), analyses.inputs(self.db, self.user, 'D01', old['run_id'], reference=ref)['source']['row'])
        fresh = self.run_analysis()
        self.db.execute("UPDATE source_versions SET status='superseded' WHERE id=(SELECT id FROM source_versions LIMIT 1)")
        self.assertEqual('stale', analyses.read(self.db, self.user, 'D01', fresh['run_id'])['status'])

    def test_medication_prescription_and_reported_intake_corrections_separate(self):
        day = records.today().isoformat()
        pid = self.plan(med_change='replace', med_reviewed='yes', med_base='',
                        med_0_name='Вымышленная таблетка', med_0_start=day, med_0_days='2',
                        med_0_0_time='08:00', med_0_0_qty='4')
        self.approve(pid)
        for amount in (2, None, 0):
            self.db.execute('''INSERT INTO medication_marks(patient_id,proposal_id,med_index,slot_index,dose_on,
                actor_id,actual_quarters,recorded_at,request_key) VALUES('D01',?,0,0,?,'pat-a',?,?,?)''',
                (pid, day, amount, now(), secrets.token_hex(16)))
        p2 = self.plan()  # An unapproved draft must not replace the applied plan.
        h = self.frozen()['patient_history']
        prescribed = next(e for e in h['entries'] if e['ref'] == h['active_medication_plan_ref'])
        self.assertEqual('applied', prescribed['state'])
        self.assertEqual('prescribed_only', prescribed['fields'][0]['context'])
        self.assertEqual(prescribed['ref'], h['active_plan_ref'])
        actual = [e for e in h['entries'] if e['category'] == 'medication_actual']
        self.assertEqual([2, None, 0], [e['fields'][0]['value'] for e in actual])
        self.assertEqual([False, False, True], [e['current_revision'] for e in actual])
        self.assertEqual('unknown', actual[1]['fields'][0]['status'])
        self.assertEqual(actual[1]['ref'], actual[2]['supersedes_ref'])
        self.assertNotEqual(pid, p2)

    def test_http_evidence_is_frozen_after_correction_restart_and_access_closed(self):
        self.visit()
        run = self.run_analysis()
        base = f'/api/v1/patients/D01/analyses/{run["run_id"]}/inputs'
        client = self.clients['doc-a']
        response = client.get(base)
        self.assertEqual(200, response.status_code)
        analyses.validate('HistoryPage', response.json)
        self.assertEqual('no-store', response.headers['Cache-Control'])
        ref = response.json['entries'][0]['ref']
        url = base + '/' + ref
        old = client.get(url).json
        analyses.validate('HistorySource', old)
        self.diary()
        fresh = create_app(self.path).test_client()
        fresh.set_cookie(access.COOKIE, client.get_cookie(access.COOKIE).value)
        self.assertEqual(old, fresh.get(url).json)
        self.assertEqual(200, client.head(url).status_code)
        for uid, code in [('pat-a', 403), ('pat-b', 403), ('doc-b', 404)]:
            self.assertEqual(code, self.clients[uid].get(url).status_code)
            self.assertEqual(code, self.clients[uid].get(base).status_code)
        self.assertEqual(401, self.app.test_client().get(url).status_code)
        self.assertEqual(404, client.get(url.replace('/D01/', '/D02/')).status_code)
        self.assertEqual(404, client.get(base+'/s2_'+'0'*64).status_code)
        for suffix in ('?page=0', '?page=-1', '?page=abc', '?page=1&page=1', '?offset=1', '?page=9999999999', '?page=99'):
            self.assertEqual(400, client.get(base+suffix).status_code)
        self.db.execute('UPDATE care_relationships SET ends_at=?', (now(),))
        self.db.execute("INSERT INTO care_relationships VALUES('replacement','D01','doc-a',?,NULL)", (now(),))
        self.assertEqual(404, client.get(url).status_code)

    def test_long_history_pagination_no_silent_truncation_and_oversize_atomic_failure(self):
        self.db.executemany('INSERT INTO encounters(id,patient_id,occurred_at,narrative,origin) VALUES(?,\'D01\',\'2026-10-18\',?,\'synthetic\')',
                            [('long'+str(i), 'Синтетический длинный текст '+str(i)+'я'*1000) for i in range(151)])
        run = self.run_analysis()
        first = analyses.inputs(self.db, self.user, 'D01', run['run_id'])
        pages = [analyses.inputs(self.db, self.user, 'D01', run['run_id'], page=p) for p in range(1, first['page_count']+1)]
        combined = [e for page in pages for e in page['entries']]
        self.assertEqual(first['entry_count'], len(combined))
        self.assertEqual(151, sum(any(f['code'] == 'narrative' and f['value'].startswith('Синтетический длинный текст') for f in e['fields']) for e in combined))
        self.assertEqual(len(combined), len({(e['ref'], e['category']) for e in combined}))
        before = self.db.execute('SELECT count(*) FROM analysis_runs').fetchone()[0]
        self.db.execute("INSERT INTO encounters(id,patient_id,occurred_at,narrative,origin) VALUES('oversize','D01','2026-10-18',?,'synthetic')", ('я'*2200000,))
        with self.assertRaises(analyses.AnalysisError) as caught: self.run_analysis()
        self.assertEqual('snapshot_too_large', caught.exception.code)
        self.assertEqual(before, self.db.execute('SELECT count(*) FROM analysis_runs').fetchone()[0])
        self.assertEqual(first, analyses.inputs(self.db, self.user, 'D01', run['run_id']))
        self.assertEqual('stale', analyses.read(self.db, self.user, 'D01', run['run_id'])['status'])

    def test_different_questionnaire_forms_are_not_structural_conflicts(self):
        self.questionnaire()
        # Another immutable legacy form result on the same day is not a
        # disagreement: different forms/versions are not interchangeable.
        row = dict(self.db.execute("SELECT * FROM assessments WHERE patient_id='D01' LIMIT 1").fetchone())
        row.update(id='different-form-vector', completed_at=records.today().isoformat(), answers_json='[0,0]',
                   scoring_version='different-version', completeness='unknown', score=None)
        self.db.execute('INSERT INTO assessments VALUES(?,?,?,?,?,?,?,?,?)', tuple(row.values()))
        for entry in self.frozen()['patient_history']['entries']:
            if entry['category'] == 'questionnaires':
                self.assertFalse(any(issue.startswith('same_day_disagreement:') for issue in entry['issues']))

    def test_legacy_snapshot_not_rewritten_and_integrity_checked(self):
        # Exercise the reader for an authentic BE01-shaped frozen payload by
        # inserting a new immutable snapshot/run, never disabling protections.
        raw = json.loads(decisions.snapshot(self.db, 'D01', self.db.execute('SELECT id FROM care_relationships').fetchone()[0]))
        sid = snapshots.digest(raw)
        self.db.execute('INSERT INTO analysis_input_snapshots VALUES(?,?,?,?)', (sid, 'D01', decisions.canonical(raw), now()))
        relationship = self.db.execute('SELECT id FROM care_relationships').fetchone()[0]
        self.db.execute('INSERT INTO analysis_runs VALUES(?,?,?,?,?,?,?,?)', ('legacy-run', 'D01', sid, 'doc-a', relationship, 'risk', secrets.token_hex(16), now()))
        with self.assertRaises(analyses.AnalysisError) as caught: analyses.inputs(self.db, self.user, 'D01', 'legacy-run')
        self.assertEqual('snapshot_version_unavailable', caught.exception.code)
        frozen = self.frozen()
        ref = next(ref for ref, meta in frozen['patient_history']['sources'].items() if meta['table'] == 'patients')
        altered = deepcopy(frozen)
        altered['patients'][0]['age_years'] = 99
        with self.assertRaises(ValueError): snapshots.resolve(altered, ref)

    def test_new_exact_refs_accepted_and_forged_refs_rejected_by_analysis_boundary(self):
        run = self.run_analysis()
        running = analyses.advance(self.db, self.user, 'D01', run['run_id'], 1, 'running')
        result = test_backend_contracts.BackendContractTests.result(self)
        result['facts'][0]['evidence_refs'] = [next(iter(self.frozen(run)['patient_history']['sources']))]
        bad = deepcopy(result);bad['facts'][0]['evidence_refs'] = ['s2_'+'0'*64]
        with self.assertRaises(analyses.AnalysisError):
            analyses.advance(self.db, self.user, 'D01', run['run_id'], running['revision'], 'ready', result=bad)
        self.assertEqual('ready', analyses.advance(self.db, self.user, 'D01', run['run_id'], running['revision'], 'ready', result=result)['status'])
