"""S48: decisions retain all evidence when the visit editor stops repeating a plan."""
import secrets
import unittest
from apps.compass import decisions, records, first_visits
import test_decisions as base


class VisitPlanDeduplicationTests(unittest.TestCase):
    def setUp(self):
        self.case = base.DecisionTests('test_five_actions_draft_separate_review_and_patient_projection')
        self.case.setUp()
        self.addCleanup(self.case.tearDown)
        self.db = self.case.db
        self.client = self.case.clients['doc-a']
        self.doctor = {'id': 'doc-a', 'role': 'doctor'}

    def snapshot(self):
        tables = [r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return {t: sorted(repr(tuple(r)) for r in self.db.execute('SELECT * FROM "'+t+'"'))
                for t in tables if t not in {'sessions', 'audit_entries', 'login_limits', 'login_challenges'}}

    def assert_editor(self, page):
        self.assertIn('<span id="v-plan"></span>', page)
        self.assertIn('href="/patients/D01/decisions"', page)
        for removed in ('Подтверждённый план', 'Подтверждённого плана нет', 'id="h-vplan"',
                        'id="decision-', 'class="plan current-plan"', 'Открыть в плане и решениях', 'name="action_draft"'):
            self.assertNotIn(removed, page)
        for kept in ('Короткая оценка пока недоступна', 'Правила оценки не подтверждены источниками',
                     'value="draft"', 'value="completed"'):
            self.assertIn(kept, page)

    def visit_values(self, **updates):
        return {'request_key': secrets.token_hex(16), 'base_revision': '0', 'state': 'draft',
                'observed_on': records.today().isoformat(), 'visit_kind': 'repeat',
                'not_collected': 'yes', 'age_source': 'patient', 'action_draft': 'Уникальная заметка о будущем действии', **updates}

    def test_confirmed_previous_pending_rejected_and_confirmation_evidence_stays_in_decisions(self):
        for kind in decisions.KINDS:
            item = self.case.draft(kind=kind, content='Текст решения '+kind,
                                   basis='Основание решения '+kind, uncertainties='Неясность '+kind)
            self.assertEqual(303, self.case.confirm(item, rationale='Проверено врачом '+kind).status_code)
        rejected = self.case.draft(kind='plan_change', content='Отклонённый отдельный текст')
        self.assertEqual(303, self.case.confirm(rejected, 'rejected').status_code)
        pending = self.case.draft(kind='plan_change', content='Ожидающий отдельный текст')
        rows = decisions.history(self.db, self.doctor, 'D01')
        self.assertEqual(7, len(rows))
        before = self.snapshot()
        page = self.client.get('/patients/D01/decisions').text
        for item in rows:
            self.assertEqual(1, page.count('id="decision-'+item['id']+'"'))
            for value in (decisions.KINDS[item['kind']], item['payload']['content'], item['payload']['basis'],
                          item['payload']['uncertainties'], 'datetime="'+item['created_at']+'"'):
                self.assertIn(value, page)
            if item['decision'] is not None:
                self.assertIn('datetime="'+item['confirmed_at']+'"', page)
                self.assertIn(item['rationale'], page)
        for url in ('/patients/D01/first-visits', '/patients/D01/first-visits/new'):
            self.assert_editor(self.client.get(url).text)
        self.assertEqual(before, self.snapshot())
        patient = self.case.clients['pat-a'].get('/patients/D01/decisions')
        self.assertEqual(200, patient.status_code)
        self.assertEqual(5, patient.text.count('class="plan-entry'))
        for text in ('Отклонённый отдельный текст', 'Ожидающий отдельный текст'):
            self.assertNotIn(text, patient.text)
        for url in ('/patients/D01/decisions', '/patients/D01/first-visits'):
            self.assertIn(self.case.clients['doc-b'].get(url).status_code, (403,404))
        self.assertEqual(403, self.case.clients['pat-a'].get('/patients/D01/first-visits').status_code)

    def test_empty_plan_draft_error_and_completed_visit_keep_unique_notes(self):
        self.assert_editor(self.client.get('/patients/D01/first-visits').text)
        plan = self.client.get('/patients/D01/decisions').text
        self.assertIn('Подтверждённого плана нет', plan)
        response = self.case.post('doc-a', '/patients/D01/first-visits/new', self.visit_values())
        self.assertEqual(303, response.status_code)
        self.assert_editor(self.client.get(response.location).text)
        self.assertNotIn('Уникальная заметка о будущем действии', self.client.get(response.location).text)
        self.assertIn('Уникальная заметка о будущем действии', self.client.get('/demo/D01').text)
        before = self.snapshot()
        error = self.case.post('doc-a', '/patients/D01/first-visits/new', self.visit_values(
            complaints_status='known', complaints_text='Сохранить введённую жалобу'))
        self.assertEqual(400, error.status_code)
        self.assert_editor(error.text)
        self.assertIn('Сохранить введённую жалобу', error.text)
        self.assertNotIn('Уникальная заметка о будущем действии', error.text)
        self.assertEqual(before, self.snapshot())
        complete = self.case.post('doc-a', response.location,
                                 self.visit_values(state='completed', base_revision='1'))
        self.assertEqual(303, complete.status_code)
        self.assertIn('/demo/D01#visit-', complete.location)
        card = self.client.get('/demo/D01').text
        self.assertIn('Уникальная заметка о будущем действии', card)
        versions = first_visits.history(self.db, self.doctor, 'D01')
        self.assertEqual(2, len(versions))
        self.assertTrue(all(v['payload']['action_draft']=='Уникальная заметка о будущем действии' for v in versions))
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])
