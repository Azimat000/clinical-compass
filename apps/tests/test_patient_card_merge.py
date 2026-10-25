"""S44: one doctor card, historical periods, source anchors and unchanged data."""
from datetime import timedelta
import re
import unittest
from apps.compass import follow_up, records
import test_follow_up


class PatientCardMergeTests(unittest.TestCase):
    setUp = test_follow_up.FollowUpTests.setUp
    tearDown = test_follow_up.FollowUpTests.tearDown
    post = test_follow_up.FollowUpTests.post
    offer = test_follow_up.FollowUpTests.offer
    link = test_follow_up.FollowUpTests.link
    values = test_follow_up.FollowUpTests.values
    draft = test_follow_up.FollowUpTests.draft
    confirm = test_follow_up.FollowUpTests.confirm
    action = test_follow_up.FollowUpTests.action
    task = test_follow_up.FollowUpTests.task
    entry = test_follow_up.FollowUpTests.entry
    assessment = test_follow_up.FollowUpTests.assessment
    clinical_state = test_follow_up.FollowUpTests.clinical_state

    def test_one_card_with_all_sources_and_original_answers_on_both_addresses(self):
        old = self.entry((records.today() - timedelta(days=70)).isoformat(), summary='OLD-FACT')
        new = self.entry(summary='NEW-FACT')
        visit = self.entry(uid='doc-a', summary='DOCTOR-FACT')
        self.assessment()
        before = self.clinical_state()
        for path in ('/demo/D01', '/patients/D01/follow-up'):
            html = self.clients['doc-a'].get(path).text
            self.assertNotIn('Сводка к приёму', html)
            self.assertNotIn('/follow-up', html)
            for section in ('records', 'visit-history', 'assessments', 'fu-plan', 'medications', 'link'):
                self.assertEqual(1, html.count('id="' + section + '"'), section)
            for source in (old, new, visit):
                self.assertEqual(1, html.count('id="entry-' + source + '"'))
            self.assertIn('OLD-FACT', html)
            self.assertIn('NEW-FACT', html)
            self.assertIn('DOCTOR-FACT', html)
            self.assertIn('Исходные ответы (42 пункта)', html)
            ids = re.findall(r'\bid="([^"]+)"', html)
            self.assertEqual(len(ids), len(set(ids)))
            for anchor in re.findall(r'href="#([^"]+)"', html):
                self.assertIn(anchor, ids, anchor)
            nav = re.search(r'<nav[^>]*class="jump patient-nav".*?</nav>', html, re.S).group()
            self.assertEqual(5, nav.count('<a '))
            self.assertEqual(1, nav.count('aria-current="page"'))
        self.assertEqual(before, self.clinical_state())

    def test_period_applies_to_records_visits_assessments_and_plan_not_current_actions(self):
        old_day = (records.today() - timedelta(days=70)).isoformat()
        old = self.entry(old_day, summary='OUTSIDE-FACT')
        new = self.entry(summary='INSIDE-FACT')
        self.entry(old_day, uid='doc-a', summary='OUTSIDE-VISIT')
        self.entry(uid='doc-a', summary='INSIDE-VISIT')
        self.assessment()
        day = records.today().isoformat()
        for path in ('/demo/D01', '/patients/D01/follow-up'):
            html = self.clients['doc-a'].get(path, query_string={'start': day, 'end': day}).text
            self.assertIn('INSIDE-FACT', html)
            self.assertIn('INSIDE-VISIT', html)
            self.assertNotIn('OUTSIDE-FACT', html)
            self.assertNotIn('OUTSIDE-VISIT', html)
            self.assertNotIn('id="entry-' + old + '"', html)
            self.assertIn('id="entry-' + new + '"', html)
            self.assertIn('Исходные ответы (42 пункта)', html)
            self.assertIn('1 из 1', html)
            empty = self.clients['doc-a'].get(path, query_string={'start': '2000-01-01', 'end': '2000-01-01'}).text
            for missing in ('Записей за период нет', 'Анкет за период нет', 'Подтверждённого плана за период нет'):
                self.assertIn(missing, empty)
            self.assertNotIn('INSIDE-FACT', empty)
            self.assertNotIn('Исходные ответы (42 пункта)', empty)
            self.assertIn('id="assessment-form"', empty)

    def test_period_errors_preserve_values_and_never_write_or_show_unfiltered_facts(self):
        self.entry(summary='PRIVATE-FACT')
        before = self.clinical_state()
        for path in ('/demo/D01', '/patients/D01/follow-up'):
            for query in ('start=2026-10-20&end=2026-10-01', 'start=bad&end=bad', 'start=2026-10-01',
                          'start=2026-10-01&start=2026-10-02&end=2026-10-03'):
                response = self.clients['doc-a'].get(path + '?' + query)
                self.assertEqual(400, response.status_code)
                self.assertIn('id="period-error"', response.text)
                self.assertNotIn('PRIVATE-FACT', response.text)
        self.assertEqual(before, self.clinical_state())

    def test_full_history_projection_is_opt_in_and_interval_totals_are_real(self):
        day = (records.today() - timedelta(days=70)).isoformat()
        old = self.entry(day, summary='OLD')
        doctor = {'id': 'doc-a', 'role': 'doctor'}
        recent = follow_up.view(self.db, doctor, 'D01', {})
        full = follow_up.view(self.db, doctor, 'D01', {}, all_history=True)
        self.assertNotIn(old, [e['id'] for e in recent['entries']])
        self.assertIn(old, [e['id'] for e in full['entries']])
        self.assertEqual(day, full['start'])
        self.assertEqual(70, full['missing_diary_days'])

    def test_old_fragment_targets_and_access_are_preserved(self):
        for path in ('/demo/D01', '/patients/D01/follow-up'):
            html = self.clients['doc-a'].get(path).text
            for target in ('fu-records', 'fu-visits', 'fu-assessments', 'fu-plan', 'fu-warnings'):
                self.assertIn('id="' + target + '"', html)
            self.assertEqual(404, self.clients['doc-b'].get(path).status_code)
            self.assertEqual(404 if path.startswith('/demo') else 403, self.clients['pat-b'].get(path).status_code)
        self.assertEqual(403, self.clients['pat-a'].get('/patients/D01/follow-up').status_code)
        self.assertNotIn('Показать период', self.clients['pat-a'].get('/demo/D01').text)
