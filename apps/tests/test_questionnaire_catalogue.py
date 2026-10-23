"""S34: exact-version forms, honest intervals, protected scoring and real-time axes."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import json
import secrets
import unittest
from unittest.mock import patch
from werkzeug.datastructures import MultiDict
import test_assessments as base
from apps.compass import assessments, records
from apps.compass.db import connect


class QuestionnaireCatalogueTests(unittest.TestCase):
    def setUp(self):
        self.case = base.AssessmentsTests('test_manual_reference_vectors_and_every_missing_position')
        self.case.setUp()
        self.addCleanup(self.case.tearDown)
        self.db = self.case.db
        self.doctor = {'id': 'doc-a', 'role': 'doctor'}
        self.patient = {'id': 'pat-a', 'role': 'patient'}
        self.forms = assessments.definitions()

    def assignment(self, form):
        return self.case.assignment(form_version_id=form['id'])

    def answers(self, form, value='1'):
        return {'form_version_id': form['id'], **{f'answer_{i}': value for i in range(1, len(form['items']) + 1)}}

    def test_catalogue_exact_forms_full_and_partial_arithmetic_and_access(self):
        self.assertEqual({'DASS-42', 'GAD-7', 'PHQ-9'}, {f['code'] for f in self.forms})
        for form in self.forms:
            request = assessments.assign(self.db, self.doctor, 'D01', self.assignment(form))
            page = self.case.clients['pat-a'].get('/assessments/' + request).get_data(as_text=True)
            self.assertEqual(len(form['items']), page.count('<fieldset class="q"'))
            self.assertIn(form['instruction'], page)
            self.assertIn(form['code'], page)
            self.assertEqual(404, self.case.clients['pat-b'].get('/assessments/' + request).status_code)
            maximum = len(form['options']) - 1
            expected = {k: len(g['items']) * maximum for k, g in form['subscales'].items()}
            self.assertEqual(expected, assessments.score_answers([maximum] * len(form['items']), form))
            for pos in range(len(form['items'])):
                values = [maximum] * len(form['items']); values[pos] = None
                self.assertIsNone(assessments.score_answers(values, form))
            assessments.submit(self.db, self.patient, request, self.answers(form, str(maximum)))
            receipt = self.case.clients['pat-a'].get('/assessments/' + request).get_data(as_text=True)
            self.assertIn(form['code'], receipt)
            self.assertNotIn('assessment-plot', receipt)
            self.assertNotIn(form['items'][0], receipt)
        doctor_page = self.case.clients['doc-a'].get('/demo/D01').get_data(as_text=True)
        self.assertEqual(5, doctor_page.count('<figure class="assessment-plot">'))
        for form in self.forms:
            self.assertIn('chart-' + form['id'], doctor_page)
        for entry in self.case.clients['pat-a'].get('/api/patients/D01/assessments').json['assessments']:
            self.assertEqual({'request_id', 'requested_at', 'recorded_at', 'form_version_id'}, set(entry))
        for table in ('care_actions', 'risk_evaluations', 'alerts', 'doctor_confirmations'):
            self.assertEqual(0, self.db.execute('SELECT count(*) FROM ' + table).fetchone()[0])

    def test_independently_specified_nonuniform_scoring_vectors(self):
        gad = next(f for f in self.forms if f['code'] == 'GAD-7')
        phq = next(f for f in self.forms if f['code'] == 'PHQ-9')
        self.assertEqual({'anxiety': 9}, assessments.score_answers([0,1,2,3,0,1,2], gad))
        self.assertEqual({'depression': 12}, assessments.score_answers([0,1,2,3,0,1,2,3,0], phq))

    def test_no_obligatory_interval_means_immediate_repeat_allowed_even_incomplete(self):
        for form in self.forms:
            self.assertIsNone(assessments.policy(form)['mandatory_min_interval_days'])
            for incomplete in (False, True):
                request = assessments.assign(self.db, self.doctor, 'D01', self.assignment(form))
                values = self.answers(form)
                if incomplete: values['answer_1'] = ''
                assessments.submit(self.db, self.patient, request, values)
                state = assessments.repeat_state(self.db, 'D01', form)
                self.assertTrue(state['allowed']); self.assertIsNone(state['next_at'])
                self.assertIsNotNone(state['last_at'])
        self.assertEqual(6, self.db.execute('SELECT count(*) FROM assessment_results').fetchone()[0])

    def test_pending_duplicate_and_idempotence_are_not_retest_restrictions(self):
        form = self.forms[1]
        assignment = self.assignment(form)
        task = assessments.assign(self.db, self.doctor, 'D01', assignment)
        self.assertEqual(task, assessments.assign(self.db, self.doctor, 'D01', assignment))
        with self.assertRaisesRegex(assessments.AssessmentError, 'уже предложена'):
            assessments.assign(self.db, self.doctor, 'D01', self.assignment(form))
        data = self.answers(form)
        result = assessments.submit(self.db, self.patient, task, data)
        self.assertEqual(result, assessments.submit(self.db, self.patient, task, data))
        with self.assertRaisesRegex(assessments.AssessmentError, 'другими ответами'):
            assessments.submit(self.db, self.patient, task, self.answers(form, '2'))
        self.assertNotEqual(task, assessments.assign(self.db, self.doctor, 'D01', self.assignment(form)))

    def test_expired_unanswered_does_not_start_interval(self):
        form = self.forms[1]
        old = assessments.assign(self.db, self.doctor, 'D01', self.assignment(form))
        tomorrow = records.today() + timedelta(days=1)
        with patch.object(records, 'today', return_value=tomorrow):
            new = assessments.assign(self.db, self.doctor, 'D01', self.assignment(form))
        self.assertNotEqual(old, new)

    def test_instrument_specific_age_cap_and_no_missing_form_fallback(self):
        self.db.execute("UPDATE patients SET age_years=95 WHERE id='D01'")
        for form in self.forms:
            if form['code'] != 'DASS-42':
                with self.assertRaisesRegex(assessments.AssessmentError, 'до 90'):
                    assessments.assign(self.db, self.doctor, 'D01', self.case.assignment(form_version_id=form['id'], age_years='95'))
        for unknown in ('', None, 'bad'):
            with self.assertRaises(assessments.AssessmentError): assessments.available_form(self.db, unknown)

    def test_wrong_answer_error_reuses_selected_form_not_dass(self):
        for form in self.forms[1:]:
            task = assessments.assign(self.db, self.doctor, 'D01', self.assignment(form))
            data = {**self.answers(form), 'answer_1': '99'}
            response = self.case.post('pat-a', '/assessments/' + task, data)
            self.assertEqual(400, response.status_code)
            html = response.get_data(as_text=True)
            self.assertEqual(len(form['items']), html.count('<fieldset class="q"'))
            self.assertIn(form['items'][0], html)
            self.assertNotIn(assessments.definition()['items'][0], html)
            for invalid in ({'answer_99': '0'}, {'answer_1': '1.5'}, {'answer_1': '-1'}):
                with self.assertRaises(assessments.AssessmentError): assessments.parse_answers({**self.answers(form), **invalid}, form)
            duplicate = MultiDict(self.answers(form)); duplicate.add('answer_1', '0')
            with self.assertRaises(assessments.AssessmentError): assessments.parse_answers(duplicate, form)

    def test_stale_age_invitation_is_hidden_and_does_not_block_fresh_offer(self):
        form = self.forms[1]
        old = assessments.assign(self.db, self.doctor, 'D01', self.assignment(form))
        records.save(self.db, self.doctor, 'D01', 'visit', {'request_key': secrets.token_hex(16),
            'observed_on': records.today().isoformat(), 'age_status': 'known', 'age_years': '35'})
        self.assertEqual([], assessments.pending(self.db, self.patient, 'D01'))
        new = assessments.assign(self.db, self.doctor, 'D01', self.assignment(form))
        self.assertNotEqual(old, new)
        self.assertEqual([new], [p['id'] for p in assessments.pending(self.db, self.patient, 'D01')])

    def test_source_withdrawal_blocks_only_chosen_form_and_preserves_history(self):
        form = self.forms[1]
        task = assessments.assign(self.db, self.doctor, 'D01', self.assignment(form))
        self.db.execute("UPDATE source_versions SET rights_status='restricted' WHERE id=?", (form['id'] + '-source',))
        with self.assertRaises(assessments.AssessmentError): assessments.submit(self.db, self.patient, task, self.answers(form))
        self.assertEqual(assessments.definition()['id'], assessments.available_form(self.db, assessments.definition()['id'])['id'])

    def test_concurrent_distinct_assignment_keys_create_one_pending_request(self):
        form = self.forms[1]
        def offer(_):
            db = connect(self.case.path)
            try:
                try: return ('ok', assessments.assign(db, self.doctor, 'D01', self.assignment(form)))
                except assessments.AssessmentError as error: return ('error', error.status)
            finally: db.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(offer, range(2)))
        self.assertEqual(['error', 'ok'], sorted(x[0] for x in results))
        self.assertEqual(1, self.db.execute('SELECT count(*) FROM assessment_requests').fetchone()[0])

    def test_future_source_mandated_interval_is_enforced_with_exact_boundary(self):
        # No released form currently mandates an interval. Exercise the engine with an explicit test-only policy.
        form = self.forms[1]
        task = assessments.assign(self.db, self.doctor, 'D01', self.assignment(form))
        assessments.submit(self.db, self.patient, task, self.answers(form))
        recorded = self.db.execute('SELECT recorded_at FROM assessment_results').fetchone()[0]
        rule = {'mandatory_min_interval_days': 7, 'basis': 'Только тестовое обязательное правило.'}
        with patch.object(assessments, 'policy', return_value=rule):
            with self.assertRaisesRegex(assessments.AssessmentError, 'повтор доступен с'):
                assessments.assign(self.db, self.doctor, 'D01', self.assignment(form))
            due = datetime.fromisoformat(recorded) + timedelta(days=7)
            with patch.object(assessments, 'now', return_value=(due - timedelta(microseconds=1)).isoformat()):
                self.assertFalse(assessments.repeat_state(self.db, 'D01', form)['allowed'])
            with patch.object(assessments, 'now', return_value=due.isoformat()):
                self.assertTrue(assessments.repeat_state(self.db, 'D01', form)['allowed'])

    def test_calendar_spacing_gaps_zero_and_versions_are_separate(self):
        form = self.forms[1]
        task = assessments.assign(self.db, self.doctor, 'D01', self.assignment(form))
        assessments.submit(self.db, self.patient, task, self.answers(form, '0'))
        row = assessments.history(self.db, self.doctor, 'D01')[0]
        rows = [{**row, 'id': str(i), 'observed_on': day, 'scores': score} for i, (day, score) in enumerate([
            ('2026-10-01', {'anxiety': 0}), ('2026-10-02', {'anxiety': 21}),
            ('2026-10-05', None), ('2026-10-11', {'anxiety': 7})])]
        trend = assessments.trends(list(reversed(rows)))[0]
        series = trend['series'][0]
        self.assertEqual([42, 90.8, 530], [p['x'] for p in series['points']])
        self.assertEqual([156, 30, 114], [p['y'] for p in series['points']])
        self.assertEqual([2, 1], [len(s) for s in series['segments']])
        self.assertEqual(-14, series['delta'])
        self.assertEqual(1, trend['missing'])
        self.assertEqual(2, len(assessments.trends([row, {**row, 'scoring_version': 'other'}])))
        many = [{**row, 'id': str(i)} for i in range(35)]
        limited = assessments.trends(many)[0]
        self.assertEqual((35, 30, 35), (limited['total'], limited['shown'], len(limited['rows'])))


if __name__ == '__main__': unittest.main()
