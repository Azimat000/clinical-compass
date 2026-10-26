"""BE07: source-gated structured rules on real SQLite/HTTP, isolated synthetic data."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import secrets
import sqlite3
import unittest
from unittest.mock import patch

from apps.compass import backend_analyses as analyses, backend_jobs as jobs
from apps.compass import backend_risk_rules as rules, backend_snapshot, backend_sources as sources
from apps.compass import events, records
from apps.compass.db import now
from apps.tests import test_access, test_backend_contracts, test_backend_snapshot


class RiskRuleTests(unittest.TestCase):
    setUp = test_backend_contracts.BackendContractTests.setUp
    tearDown = test_access.AccessTests.tearDown
    post = test_access.AccessTests.post
    offer = test_access.AccessTests.offer
    body = test_backend_contracts.BackendContractTests.body
    diary = test_backend_snapshot.BackendSnapshotTests.diary
    visit = test_backend_snapshot.BackendSnapshotTests.visit
    questionnaire = test_backend_snapshot.BackendSnapshotTests.questionnaire

    def context(self, condition='F41.1', **kw):
        return {'condition': condition, 'severity': 'nonsevere', 'basis': 'Вымышленное врачебное наблюдение.',
                'supersedes_id': None, **{k: 'denied' for k in rules.FLAGS}, **kw}

    def store(self, payload=None, **kw):
        return rules.record_context(self.db, self.user, 'D01', kw.pop('observed_on', records.today().isoformat()),
                                    payload or self.context(), kw.pop('request_key', secrets.token_hex(16)))

    def snapshot(self):
        relationship = analyses.authorize(self.db, self.user, 'D01')
        return json.loads(analyses.capture(self.db, 'D01', relationship))

    def report(self, snapshot=None):
        return rules.evaluate(snapshot or self.snapshot())

    def states(self, value):
        self.assertEqual('ready', value['status'], value)
        return {r['rule_id']: r['state'] for r in value['result']['output']['rule_evaluations']}

    def setup_case(self, context, adverse=None):
        cid = self.store(context)
        if adverse:
            self.diary(observed_on=records.today().isoformat(), adverse_events_status=adverse,
                       adverse_events_text='Вымышленное НЯ' if adverse in ('known', 'conflicting') else '')
        return cid

    def test_all_rules_positive_negative_and_boundary_with_exact_sources(self):
        cases = [
            ('DEP-SUICIDE-FACT', self.context('F32'), self.context('F32', suicidal_ideation='present')),
            ('GAD-PSY-REVIEW', self.context(), self.context(severity='severe')),
            ('GAD-ADVERSE-REVIEW', self.context(psychopharmacotherapy='present'),
                self.context(psychopharmacotherapy='present')),
            ('GAD-INITIAL-ANXIETY', self.context(), self.context(psychopharmacotherapy='present',
                initial_antidepressant_phase='present', worsening_anxiety='present'))]
        previous = None
        for rid, negative, positive in cases:
            with self.subTest(rule=rid):
                negative['supersedes_id'] = previous
                previous = self.store(negative)
                if rid == 'GAD-ADVERSE-REVIEW':
                    self.diary(observed_on=records.today().isoformat(), adverse_events_status='denied')
                self.assertEqual('no_match', self.states(self.report())[rid])
                positive['supersedes_id'] = previous
                previous = self.store(positive)
                if rid == 'GAD-ADVERSE-REVIEW':
                    self.diary(observed_on=records.today().isoformat(), adverse_events_status='known',
                               adverse_events_text='Вымышленное НЯ')
                value = self.report(); self.assertEqual('triggered', self.states(value)[rid])
                pattern = next(p for p in value['result']['output']['patterns'] if p['id'] == rid)
                self.assertEqual(['be07-' + rid], pattern['source_ids'])
                ev = next(e for e in value['result']['output']['rule_evaluations'] if e['rule_id'] == rid)
                self.assertGreater(ev['pdf_page'], 0); self.assertTrue(ev['section'])
                for fact in value['result']['facts']:
                    for ref in fact['evidence_refs']:
                        self.assertIsNotNone(backend_snapshot.resolve(self.snapshot(), ref))

    def test_each_rule_missing_conflicting_and_false_boundaries(self):
        cases = [
            ('F32', {'suicidal_ideation': 'unknown'}),
            ('F33', {'suicidal_plan': 'conflicting'}),
            ('F41.1', {'suicide_risk': 'unknown'}),
            ('F41.1', {'severity': 'conflicting'}),
            ('F41.1', {'psychopharmacotherapy': 'present'}),
            ('F41.1', {'psychopharmacotherapy': 'unknown', 'initial_antidepressant_phase': 'present', 'worsening_anxiety': 'present'}),
            ('F41.1', {'psychopharmacotherapy': 'present', 'initial_antidepressant_phase': 'conflicting', 'worsening_anxiety': 'present'})]
        previous = None
        for condition, updates in cases:
            with self.subTest(updates=updates):
                previous = self.store(self.context(condition, supersedes_id=previous, **updates))
                self.assertEqual('insufficient_data', self.report()['status'])
        previous = self.store(self.context(supersedes_id=previous, psychopharmacotherapy='present'))
        self.diary(observed_on=records.today().isoformat(), adverse_events_status='denied')
        value = self.report()
        self.assertEqual('no_match', self.states(value)['GAD-ADVERSE-REVIEW'])
        self.assertEqual('no_pattern_found', value['result']['output']['assessment'])
        self.assertIn('не означает', value['result']['missing_data'][0])

    def test_positive_not_cleared_by_unknown_or_conflicting_other_factor(self):
        self.store(self.context('F32', suicidal_plan='present', suicidal_intent='conflicting', suicidal_ideation='unknown'))
        value = self.report()
        self.assertEqual('triggered', self.states(value)['DEP-SUICIDE-FACT'])
        self.assertTrue(value['result']['contradictions'])
        self.assertTrue(any('часть факторов' in s for s in value['result']['missing_data']))

    def test_legacy_physician_risk_is_not_erased_by_four_denied_factors(self):
        self.store(self.context('F33', suicide_risk='present'))
        value = self.report()
        self.assertEqual('triggered', self.states(value)['DEP-SUICIDE-FACT'])
        self.assertIn('legacy_clinician_recorded_suicide_risk',
                      value['result']['output']['rule_evaluations'][0]['reasons'])

    def test_therapy_phase_conflict_not_cleared_by_denied_anxiety(self):
        self.store(self.context(initial_antidepressant_phase='present', worsening_anxiety='denied',
                                psychopharmacotherapy='denied'))
        self.assertEqual('insufficient_data', self.report()['status'])

    def test_each_rule_age_and_source_boundaries(self):
        cases = [('F32', {'suicidal_plan':'present'}), ('F41.1', {'severity':'severe'}),
                 ('F41.1', {'psychopharmacotherapy':'present'}),
                 ('F41.1', {'psychopharmacotherapy':'present','initial_antidepressant_phase':'present','worsening_anxiety':'present'})]
        previous = None
        self.diary(observed_on=records.today().isoformat(), adverse_events_status='known', adverse_events_text='Вымышленное НЯ')
        for index, (condition, updates) in enumerate(cases):
            with self.subTest(rule=index):
                previous = self.store(self.context(condition, supersedes_id=previous, **updates))
                self.assertEqual('triggered', self.states(self.report())[rules.release()['rules'][index]['id']])
                for age, status, expected in [(None,'unknown','insufficient_data'),(17,'known','unsupported'),
                                              (18,'known','ready'),(120,'known','ready')]:
                    # All recorded age sources also use unknown for this fixture;
                    # the profile is the only known numeric age.
                    self.db.execute("UPDATE patients SET age_status=?,age_years=? WHERE id='D01'", (status,age))
                    self.assertEqual(expected, self.report()['status'])
                self.db.execute("UPDATE patients SET age_status='known',age_years=35 WHERE id='D01'")
                snapshot = self.snapshot()
                for source in snapshot['backend_sources']['claims'].values():
                    source['reasons'] = ['source_withdrawn']
                self.assertEqual('insufficient_data', self.report(snapshot)['status'])

    def test_same_day_independent_contexts_conflict_and_explicit_correction_restores(self):
        first = self.store(self.context('F32', suicidal_plan='present'))
        second = self.store(self.context('F32'))
        self.assertEqual('risk_context_unavailable', self.report()['errors'][0]['code'])
        # Superseding one leaf still leaves two independent contexts: no silent latest wins.
        self.store(self.context('F32', supersedes_id=second))
        self.assertEqual('insufficient_data', self.report()['status'])
        self.assertEqual(3, self.db.execute('SELECT count(*) FROM clinical_contexts').fetchone()[0])

    def test_context_authorization_replay_conflict_append_only_and_transaction(self):
        payload, key = self.context(), secrets.token_hex(16)
        cid = self.store(payload, request_key=key)
        self.assertEqual(cid, self.store(payload, request_key=key))
        with self.assertRaises(ValueError): self.store(self.context('F32'), request_key=key)
        for user in ({'id':'pat-a','role':'patient'}, {'id':'doc-b','role':'doctor'}):
            with self.assertRaises(analyses.decisions.DecisionError):
                rules.record_context(self.db,user,'D01',records.today().isoformat(),payload,secrets.token_hex(16))
        with self.assertRaises(sqlite3.IntegrityError): self.db.execute('UPDATE clinical_contexts SET observed_on=? WHERE id=?', ('2000',cid))
        with self.assertRaises(sqlite3.IntegrityError): self.db.execute('DELETE FROM clinical_contexts WHERE id=?',(cid,))
        self.db.execute('UPDATE backend_job_settings SET enabled=1')
        with patch.object(events,'enqueue',side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError): self.store()
        self.assertEqual(1,self.db.execute('SELECT count(*) FROM clinical_contexts').fetchone()[0])

    def test_source_expiry_revocation_wrong_population_blocks_each_rule(self):
        self.store(self.context('F32', suicidal_plan='present'))
        baseline = self.snapshot()
        for change in ('expired','revoked','age','condition'):
            snapshot = deepcopy(baseline)
            if change in ('expired','revoked'):
                snapshot['backend_sources']['claims']['be03-KR301_3-F02']['reasons']=[change]
            elif change=='age': snapshot['patients'][0]['age_years']=17
            else: snapshot['clinical_contexts'][0]['payload_json']=json.dumps({**json.loads(snapshot['clinical_contexts'][0]['payload_json']),'condition':'unknown'})
            self.assertNotEqual('ready',self.report(snapshot)['status'])
        with patch.object(sources,'clock',return_value=datetime(2026,10,29,tzinfo=timezone.utc)):
            self.assertEqual('insufficient_data',self.report()['status'])

    def test_age_unknown_conflicting_child_adult_boundary_all_rules(self):
        self.store(self.context('F32', suicidal_plan='present'))
        for age,status,expected in [(None,'unknown','insufficient_data'),(17,'known','unsupported'),
                                    (18,'conflicting','insufficient_data'),(18,'known','ready'),(120,'known','ready')]:
            with self.subTest(age=age,status=status):
                self.db.execute("UPDATE patients SET age_status=?,age_years=? WHERE id='D01'", (status,age))
                self.assertEqual(expected,self.report()['status'])

    def test_text_scores_general_wellbeing_and_phq_answer_never_become_rule(self):
        self.store(self.context('F32'))
        self.diary(observed_on=records.today().isoformat(),wellbeing='worse',summary='Придуманная суицидальная фраза; это только текст.')
        self.questionnaire()
        from apps.compass import assessments
        form = assessments.definition('PHQ9-RU-Z-2023-demo-v1')
        task = assessments.assign(self.db, self.user, 'D01', {
            'assignment_key': secrets.token_hex(16), 'form_version_id': form['id'],
            'age_status': 'known', 'age_years': '35', 'age_basis': 'Вымышленный профиль'})
        assessments.submit(self.db, {'id':'pat-a','role':'patient'}, task,
                           {'form_version_id':form['id'], **{f'answer_{i}': '3' for i in range(1,10)}})
        value = self.report()
        self.assertEqual('no_pattern_found',value['result']['output']['assessment'])
        self.assertIn('Анкеты',value['result']['missing_data'][0])

    def test_adverse_positive_and_denial_preserve_flag_and_conflict(self):
        self.store(self.context(psychopharmacotherapy='present'))
        self.diary(observed_on=records.today().isoformat(),adverse_events_status='known',adverse_events_text='Вымышленное НЯ')
        self.diary(observed_on=records.today().isoformat(),adverse_events_status='denied')
        value=self.report()
        self.assertEqual('triggered',self.states(value)['GAD-ADVERSE-REVIEW'])
        self.assertTrue(value['result']['contradictions'])

    def test_full_queue_http_ready_and_forgery_rejected_without_model(self):
        self.db.execute('UPDATE backend_job_settings SET enabled=1')
        self.store(self.context('F32',suicidal_plan='present'))
        while events.process_one(self.db): pass
        run=dict(self.db.execute('SELECT * FROM analysis_runs').fetchone())
        with patch('apps.compass.backend_model.strict_json',side_effect=AssertionError('no model')):
            self.assertTrue(jobs.process_one(self.db,'risk'))
        value=analyses.read(self.db,self.user,'D01',run['id'])
        self.assertEqual('ready',value['status'],value)
        self.assertEqual('potential_risk',value['result']['output']['assessment'])
        self.assertEqual('blocked',value['release']['status']); self.assertIsNone(value['model'])
        client=self.clients['doc-a']; url=self.url+'/'+run['id']
        self.assertEqual(value,client.get(url).json)
        for ref in value['result']['facts'][0]['evidence_refs']:
            self.assertEqual(200,client.get(url+'/inputs/'+ref).status_code)
        self.assertEqual(403,self.clients['pat-a'].get(url).status_code)
        self.assertEqual(404,self.clients['doc-b'].get(url).status_code)
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])
        for mutation in ('clear','invent','fact','attention','model','insufficient','unsupported'):
            fresh=analyses.create(self.db,self.user,'D01',self.body())
            work=jobs.claim(self.db,'risk'); self.assertEqual(fresh['run_id'],work['run']['id'])
            outcome=rules.evaluate(work['snapshot'])
            if mutation=='clear': outcome['result']['output'].update(assessment='no_pattern_found',patterns=[])
            if mutation=='invent': outcome['result']['output']['patterns'][0]['text']='Выдуманный диагноз'
            if mutation=='fact': outcome['result']['facts'][0]['text']='Выдуманный факт'
            if mutation=='attention': outcome['result']['output']['rule_evaluations'][0]['attention']='undetermined'
            if mutation=='model': outcome['model']={'provider':'invented'}
            if mutation in ('insufficient','unsupported'):
                outcome={'status':'insufficient_data' if mutation=='insufficient' else 'unsupported',
                         'errors':[{'code':'model_veto','message':'Нет риска','retryable':False}]}
            jobs.finish(self.db,work,outcome)
            self.assertEqual('invalid_result',self.db.execute('SELECT last_error FROM backend_jobs WHERE run_id=?',(fresh['run_id'],)).fetchone()[0])
            jobs.cancel(self.db,self.user,'D01',fresh['run_id'])

    def test_missing_context_default_executor_insufficient_not_failure_or_negative(self):
        self.db.execute('UPDATE backend_job_settings SET enabled=1')
        run=analyses.create(self.db,self.user,'D01',self.body())
        self.assertTrue(jobs.process_one(self.db,'risk'))
        value=analyses.read(self.db,self.user,'D01',run['run_id'])
        self.assertEqual('insufficient_data',value['status']); self.assertIsNone(value['result'])
        self.assertEqual(1,self.db.execute('SELECT count(*) FROM backend_job_attempts').fetchone()[0])
        self.assertEqual('blocked',value['release']['status'])

    def test_rule_change_stales_without_rewriting_result_or_sources(self):
        self.db.execute('UPDATE backend_job_settings SET enabled=1')
        self.store(self.context('F32',suicidal_plan='present'))
        run=analyses.create(self.db,self.user,'D01',self.body()); jobs.process_one(self.db)
        saved=analyses._latest(self.db,run['run_id'])
        changed=rules.release(); changed['engine_sha256']='0'*64
        with patch.object(rules,'release',return_value=changed):
            self.assertEqual('stale',analyses.read(self.db,self.user,'D01',run['run_id'])['status'])
        self.assertEqual(saved,analyses._latest(self.db,run['run_id']))

    def test_old_or_wrong_relationship_context_and_non_synthetic_refused(self):
        self.store(observed_on='2026-10-18')
        self.assertEqual('insufficient_data',self.report()['status'])
        s=self.snapshot();s['patients'][0]['synthetic']=0
        self.assertEqual('unsupported',self.report(s)['status'])
        s=self.snapshot();s['relationship']='foreign'
        self.assertEqual('insufficient_data',self.report(s)['status'])

    def test_limits_are_explicit_not_truncated(self):
        self.store(self.context('F32',suicidal_plan='present'))
        snapshot=self.snapshot()
        # Exact duplicate age rows are numerous, never silently discarded.
        self.diary(observed_on=records.today().isoformat())
        snapshot=self.snapshot(); snapshot['clinical_entries'] *= 51
        self.assertEqual('risk_evidence_limit',self.report(snapshot)['errors'][0]['code'])


if __name__=='__main__': unittest.main()
