"""S45: plan facts have one home, with preserved history and access."""
import re
import secrets
import unittest
from apps.compass import communication, records, follow_up
import test_follow_up
import test_medications


class PlanDeduplicationTests(unittest.TestCase):
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
    clinical_state = test_follow_up.FollowUpTests.clinical_state
    schedule = test_medications.MedicationTests.schedule
    url = '/patients/D01/communication'

    def test_card_omits_plan_calendar_routes_and_outcomes_but_plan_retains_them(self):
        proposal = self.schedule(content='UNIQUE-CONFIRMED-PLAN')
        action = self.db.execute('SELECT id FROM care_actions WHERE confirmation_id=(SELECT id FROM doctor_confirmations WHERE proposal_id=?)', (proposal['id'],)).fetchone()[0]
        task, _ = self.task(action, label='UNIQUE-TASK')
        report = self.entry(follow_up.local_day(task['due_at']), summary='PATIENT-SOURCE')
        for outcome, reason in [('missed', 'OLD-REASON'), ('taken', 'LATEST-REASON')]:
            communication.report(self.db, {'id': 'pat-a', 'role': 'patient'}, 'D01', task['id'],
                                 {'request_key': secrets.token_hex(16), 'outcome': outcome, 'reason': reason})
        before = self.clinical_state()
        for path in ('/demo/D01', '/patients/D01/follow-up'):
            page = self.clients['doc-a'].get(path).text
            for duplicate in ('UNIQUE-CONFIRMED-PLAN', 'UNIQUE-TASK', 'OLD-REASON', 'LATEST-REASON',
                              'Приём препаратов', 'Изменить расписание', 'Записанные направления', 'class="plan-tasks"'):
                self.assertNotIn(duplicate, page)
            self.assertIn('PATIENT-SOURCE', page)
            self.assertIn('href="/patients/D01/decisions"', page)
            jump = re.search(r'<nav[^>]*aria-label="Разделы карточки".*?</nav>', page, re.S).group()
            self.assertNotIn('#medications', jump)
            self.assertNotIn('#fu-plan', jump)
        page = self.clients['doc-a'].get('/patients/D01/decisions').text
        for value in ('UNIQUE-CONFIRMED-PLAN', 'UNIQUE-TASK', 'LATEST-REASON', 'OLD-REASON',
                      'Приём препаратов', 'Ответы пациента по плану', 'Предыдущие отметки (1)', '/demo/D01#entry-' + report):
            self.assertIn(value, page)
        outcomes = re.search(r'<section[^>]*id="fu-plan".*?</section>', page, re.S).group()
        self.assertNotIn('UNIQUE-CONFIRMED-PLAN', outcomes)
        self.assertIn('LATEST-REASON', re.sub(r'<details\b.*?</details>', '', outcomes, flags=re.S))
        self.assertNotIn('OLD-REASON', re.sub(r'<details\b.*?</details>', '', outcomes, flags=re.S))
        for anchor in re.findall(r'href="#([^"]+)"', outcomes):
            self.assertIn('id="' + anchor + '"', page)
        self.assertEqual(before, self.clinical_state())

    def test_review_reasons_go_to_plan_and_unknown_remains_unknown(self):
        task, _ = self.task(label='UNKNOWN-TASK')
        page = self.clients['doc-a'].get('/').text
        self.assertIn('/patients/D01/decisions#fu-plan', page)
        plan = self.clients['doc-a'].get('/patients/D01/decisions').text
        self.assertIn('UNKNOWN-TASK', plan)
        self.assertIn('Пациент пока не ответил.', plan)
        self.assertIn('Выполнение не отмечено', plan)
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM adherence_entries').fetchone()[0])

    def test_legacy_medication_bookmarks_and_patient_boundaries(self):
        self.schedule(content='APPROVED-PATIENT-PLAN')
        day = records.today().isoformat()
        for base in ('/demo/D01', '/patients/D01/follow-up'):
            response = self.clients['doc-a'].get(base + '?med_day=' + day)
            self.assertEqual(302, response.status_code)
            self.assertEqual('/patients/D01/decisions?med_day=' + day + '#medications', response.location)
            self.assertIn('Приём препаратов', self.clients['doc-a'].get(response.location).text)
            self.assertEqual(404, self.clients['doc-b'].get(base + '?med_day=' + day).status_code)
        for path in ('/demo/D01', '/patients/D01/decisions'):
            page = self.clients['pat-a'].get(path + '?med_day=' + day)
            self.assertEqual(200, page.status_code)
            self.assertIn('APPROVED-PATIENT-PLAN', page.text)
            self.assertIn('Приём препаратов', page.text)
            self.assertNotIn('Выполнение плана', page.text)
        self.assertEqual(403, self.clients['pat-a'].get('/patients/D01/follow-up').status_code)
        self.assertEqual(404, self.clients['doc-b'].get('/patients/D01/decisions').status_code)
