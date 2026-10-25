"""Patient diaries and physician histories stay distinct, including future writes."""
from datetime import timedelta
import re
import secrets
import unittest

from apps.compass import records, first_visits, follow_up
import test_records


class RecordRoutingTests(unittest.TestCase):
    setUp = test_records.RecordsTests.setUp
    tearDown = test_records.RecordsTests.tearDown
    values = test_records.RecordsTests.values
    submit = test_records.RecordsTests.submit

    def save(self, who, text, **kw):
        kind = 'self_report' if who == 'pat-a' else 'visit'
        return records.save(self.db, {'id': who, 'role': 'patient' if who == 'pat-a' else 'doctor'},
                            'D01', kind, self.values(summary=text, **kw))

    def section(self, page, section_id):
        return re.search(r'<section\b[^>]*id="' + section_id + r'".*?</section>', page, re.S)[0]

    def test_existing_and_new_entries_are_shown_in_their_own_sections(self):
        patient = self.save('pat-a', 'PATIENT-ONLY', wellbeing='better')
        doctor = self.save('doc-a', 'DOCTOR-ONLY', wellbeing='worse', complaints_status='known',
                           complaints_text='DOCTOR-DETAIL', age_status='known', age_years='35')
        before = [tuple(r) for r in self.db.execute('SELECT * FROM clinical_entries')]
        for path, diary, visits in [('/demo/D01', 'records', 'visit-history'),
                                    ('/patients/D01/follow-up', 'fu-records', 'fu-visits')]:
            html = self.clients['doc-a'].get(path).text
            diary_html, visit_html = self.section(html, diary), self.section(html, visits)
            self.assertIn('PATIENT-ONLY', diary_html)
            self.assertNotIn('DOCTOR-ONLY', diary_html)
            self.assertIn('DOCTOR-ONLY', visit_html)
            self.assertIn('DOCTOR-DETAIL', visit_html)
            self.assertIn('35 лет', visit_html)
            self.assertNotIn('PATIENT-ONLY', visit_html)
            self.assertEqual(1, html.count('id="entry-' + doctor + '"'))
        history = self.clients['doc-a'].get('/patients/D01/first-visits').text
        self.assertIn('DOCTOR-ONLY', self.section(history, 'v-list'))
        self.assertNotIn('PATIENT-ONLY', history)
        diary = self.clients['pat-a'].get('/demo/D01/diary').text
        self.assertIn('id="entry-' + patient + '"', diary)
        self.assertNotIn('DOCTOR-ONLY', diary)
        self.assertIn('История приёмов', diary)
        patient_visits = self.clients['pat-a'].get('/demo/D01/visits').text
        self.assertIn('DOCTOR-ONLY', patient_visits)
        self.assertNotIn('PATIENT-ONLY', patient_visits)
        self.assertEqual(before, [tuple(r) for r in self.db.execute('SELECT * FROM clinical_entries')])

    def test_future_short_visit_saves_once_and_redirects_to_history(self):
        form = self.values(summary='FUTURE-VISIT', complaints_status='known', complaints_text='Visit facts')
        response = self.submit('doc-a', kind='visits', data=form)
        self.assertEqual(303, response.status_code)
        self.assertTrue(response.location.startswith('/patients/D01/first-visits#entry-'))
        self.assertIn('FUTURE-VISIT', self.clients['doc-a'].get(response.location).text)
        self.assertEqual(response.location, self.submit('doc-a', kind='visits', data=form).location)
        self.assertEqual(409, self.submit('doc-a', kind='visits', data={**form, 'summary': 'changed'}).status_code)
        self.assertEqual(1, self.db.execute('SELECT count(*) FROM clinical_entries').fetchone()[0])
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM self_reports').fetchone()[0])
        entry = self.db.execute('SELECT * FROM clinical_entries').fetchone()
        self.assertEqual(('visit', 'doc-a', entry['id'], None),
                         (entry['kind'], entry['actor_id'], entry['encounter_id'], entry['self_report_id']))
        self.assertEqual(1, self.clients['doc-a'].get(response.location).text.count('id="entry-' + entry['id'] + '"'))

    def test_future_self_report_saves_only_in_diary_and_correct_storage(self):
        form = self.values(summary='FUTURE-REPORT')
        response = self.submit(data=form)
        self.assertEqual(303, response.status_code)
        self.assertTrue(response.location.startswith('/demo/D01/diary#entry-'))
        self.assertEqual(response.location, self.submit(data=form).location)
        self.assertIn('FUTURE-REPORT', self.clients['pat-a'].get(response.location).text)
        self.assertNotIn('FUTURE-REPORT', self.clients['doc-a'].get('/patients/D01/first-visits').text)
        entry = self.db.execute('SELECT * FROM clinical_entries').fetchone()
        self.assertEqual(('self_report', 'pat-a', None, entry['id']),
                         (entry['kind'], entry['actor_id'], entry['encounter_id'], entry['self_report_id']))
        self.assertEqual(1, self.db.execute('SELECT count(*) FROM self_reports').fetchone()[0])
        self.assertEqual(1, self.db.execute('SELECT count(*) FROM clinical_entries').fetchone()[0])

    def test_future_detailed_visit_retains_versions_without_becoming_a_diary_entry(self):
        values = {'request_key': secrets.token_hex(16), 'observed_on': records.today().isoformat(),
                  'visit_kind': 'repeat', 'age_source': 'patient', 'not_collected': 'yes',
                  'documented_facts': 'MODERN-VISIT', 'document_basis': 'Synthetic document',
                  'base_revision': '0', 'state': 'draft'}
        doctor = {'id': 'doc-a', 'role': 'doctor'}
        visit = first_visits.save(self.db, doctor, 'D01', 'new', values)
        first_visits.save(self.db, doctor, 'D01', visit,
                          {**values, 'request_key': secrets.token_hex(16), 'base_revision': '1'})
        data = follow_up.view(self.db, doctor, 'D01', {})
        self.assertEqual([], data['entries'])
        self.assertEqual([], data['doctor_entries'])
        self.assertEqual(1, len(data['visits']))
        self.assertEqual(2, data['visits'][0]['revision'])
        self.assertIn('MODERN-VISIT', self.section(self.clients['doc-a'].get('/patients/D01/follow-up').text, 'fu-visits'))
        self.assertNotIn('MODERN-VISIT', self.clients['pat-a'].get('/demo/D01/diary').text)
        self.assertNotIn('MODERN-VISIT', self.clients['pat-a'].get('/demo/D01/visits').text)
        self.assertEqual(403, self.clients['pat-a'].get('/patients/D01/first-visits/' + visit).status_code)
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM clinical_entries').fetchone()[0])

    def test_period_filter_conflicts_and_missing_diary_days_keep_their_meaning(self):
        day = records.today().isoformat()
        self.save('doc-a', 'TODAY-VISIT', observed_on=day, adverse_events_status='denied')
        old = self.save('doc-a', 'OUTSIDE', observed_on=(records.today()-timedelta(days=2)).isoformat())
        doctor = {'id': 'doc-a', 'role': 'doctor'}
        data = follow_up.view(self.db, doctor, 'D01', {'start': day, 'end': day})
        self.assertEqual([], data['entries'])
        self.assertEqual(1, len(data['doctor_entries']))
        self.assertNotIn(old, [e['id'] for e in data['doctor_entries']])
        self.assertEqual(1, data['missing_diary_days'])
        self.save('pat-a', 'TODAY-REPORT', observed_on=day, adverse_events_status='known', adverse_events_text='Patient event')
        data = follow_up.view(self.db, doctor, 'D01', {'start': day, 'end': day})
        self.assertTrue(any('различаются сведения' in w for w in data['warnings']))
        self.assertEqual(0, data['missing_diary_days'])

    def test_typed_links_and_access_for_each_role_and_patient(self):
        report = self.save('pat-a', 'REPORT')
        visit = self.save('doc-a', 'VISIT')
        for who, eid, target in [('pat-a', report, '/demo/D01/diary'), ('pat-a', visit, '/demo/D01/visits'),
                                 ('doc-a', report, '/demo/D01'), ('doc-a', visit, '/patients/D01/first-visits')]:
            path = '/patients/D01/records/' + eid
            response = self.clients[who].get(path)
            self.assertEqual(302, response.status_code)
            self.assertEqual(target + '#entry-' + eid, response.location)
            self.assertIn('id="entry-' + eid + '"', self.clients[who].get(response.location).text)
            self.assertEqual(404, self.clients['pat-b'].get(path).status_code)
            self.assertEqual(404, self.clients['doc-b'].get(path).status_code)
            self.assertEqual(404, self.clients[who].get('/patients/D02/records/' + eid).status_code)
        self.assertEqual(404, self.clients['doc-a'].get('/patients/D01/records/missing').status_code)
        self.assertEqual(403, self.clients['doc-a'].get('/demo/D01/visits').status_code)
        self.assertEqual(404, self.clients['pat-b'].get('/demo/D01/visits').status_code)
        self.assertEqual(403, self.submit('doc-a').status_code)
        self.assertEqual(403, self.submit('pat-a', kind='visits').status_code)

    def test_bad_doctor_submission_has_visible_error_and_no_partial_write(self):
        response = self.submit('doc-a', kind='visits', data=self.values(observed_on='invalid'))
        self.assertEqual(400, response.status_code)
        self.assertIn('Запись не сохранена', response.text)
        self.assertIn('Укажите дату наблюдения', response.text)
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM clinical_entries').fetchone()[0])
        with self.assertRaises(records.RecordError):
            records.save(self.db, {'id': 'doc-a', 'role': 'doctor'}, 'D01', 'not-a-kind', self.values())
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM clinical_entries').fetchone()[0])

    def test_standalone_archives_and_linked_visit_are_never_duplicated(self):
        visit = self.save('doc-a', 'LINKED-VISIT')
        self.db.execute("INSERT INTO encounters(id,patient_id,occurred_at,author_id,narrative,origin) VALUES('old-visit','D01',?,'doc-a','ARCHIVE-ONLY','archive')",
                         (records.today().isoformat(),))
        for path, section in [('/demo/D01', 'visit-history'), ('/patients/D01/first-visits', 'v-list'),
                              ('/patients/D01/follow-up', 'fu-visits')]:
            response = self.clients['doc-a'].get(path)
            self.assertEqual(200, response.status_code)
            html = self.section(response.text, section)
            self.assertIn('ARCHIVE-ONLY', html)
            self.assertEqual(1, html.count('id="entry-' + visit + '"'))
            self.assertNotIn('id="encounter-' + visit + '"', html)
            self.assertEqual(1, html.count('id="encounter-old-visit"'))

    def test_message_links_follow_record_type_for_both_roles(self):
        from apps.compass import communication
        for who, summary in [('pat-a', 'MESSAGE-REPORT'), ('doc-a', 'MESSAGE-VISIT')]:
            entry = self.save(who, summary)
            communication.send(self.db, {'id': who, 'role': 'patient' if who == 'pat-a' else 'doctor'},
                               'D01', {'request_key': secrets.token_hex(16), 'body': 'Синтетическое обсуждение', 'entry_id': entry})
            for reader in ('pat-a', 'doc-a'):
                page = self.clients[reader].get('/patients/D01/communication')
                self.assertEqual(200, page.status_code)
                self.assertIn('href="/patients/D01/records/' + entry + '"', page.text)
                self.assertIn('записи приёма' if who == 'doc-a' else 'записи самочувствия', page.text)
                target = self.clients[reader].get('/patients/D01/records/' + entry)
                self.assertIn('id="entry-' + entry + '"', self.clients[reader].get(target.location).text)
