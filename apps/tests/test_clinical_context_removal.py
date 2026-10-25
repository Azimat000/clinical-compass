"""Retired physician-context workflow: no UI, writer or HTTP mutation."""
import unittest
from unittest.mock import patch
from apps.compass import clinical_rules
import test_access
import test_decisions
from context_fixture import historical_context


class ClinicalContextRemovalTests(unittest.TestCase):
    setUp = test_decisions.DecisionTests.setUp
    tearDown = test_access.AccessTests.tearDown
    post = test_access.AccessTests.post
    offer = test_access.AccessTests.offer
    link = test_access.AccessTests.link

    def test_all_pages_omit_section_form_links_and_advice(self):
        for uid, paths in {
            'doc-a': ('/', '/demo/D01', '/patients/D01/follow-up', '/patients/D01/first-visits', '/patients/D01/decisions'),
            'pat-a': ('/demo/D01', '/demo/D01/diary', '/patients/D01/decisions'),
        }.items():
            for path in paths:
                response = self.clients[uid].get(path)
                self.assertEqual(200, response.status_code, path)
                for retired in ('Врачебные сведения', 'id="clinical-rules"', '#clinical-rules', '/clinical-context',
                                'name="clinical_basis"', 'name="prescription_basis"', 'Рекомендация не сформирована'):
                    self.assertNotIn(retired, response.text, (uid, path, retired))

    def test_removed_endpoint_cannot_write_even_with_valid_form_and_csrf(self):
        form = {'request_key': 'a'*32, 'observed_on': '2026-10-25', 'gad_status': 'present',
                'severity': 'severe', 'suicide_risk': 'present', 'clinical_basis': 'Synthetic basis',
                'aviandr_prescription': 'active', 'prescription_basis': 'Synthetic prescription'}
        before = {t: [tuple(r) for r in self.db.execute('SELECT * FROM '+t)]
                  for t in ('clinical_contexts', 'proposals', 'care_actions', 'critical_events', 'clinical_rule_evaluations')}
        for uid in self.clients:
            for pid in ('D01', 'D02', 'missing'):
                for accept in ('text/html', 'application/json'):
                    response = self.clients[uid].post('/patients/'+pid+'/clinical-context',
                        data={'csrf': test_access.csrf(self.clients[uid]), **form}, headers={'Accept': accept})
                    self.assertEqual(404, response.status_code, (uid, pid, accept))
        self.assertEqual(404, self.app.test_client().post('/patients/D01/clinical-context', data=form).status_code)
        self.assertEqual(before, {t: [tuple(r) for r in self.db.execute('SELECT * FROM '+t)] for t in before})
        self.assertFalse(hasattr(clinical_rules, 'save_context'))
        self.assertFalse(hasattr(clinical_rules, 'panel'))
        self.assertNotIn('clinical_context', self.app.view_functions)

    def test_historical_context_is_preserved_but_card_does_not_load_it(self):
        historical_context(self.db, 'D01', 'doc-a', {'observed_on': '2026-10-25', 'clinical_basis': 'PRIVATE_CONTEXT_MARKER'})
        before = [tuple(r) for r in self.db.execute('SELECT * FROM clinical_contexts')]
        with patch.object(clinical_rules, '_context', side_effect=AssertionError('Card must not load removed context')):
            response = self.clients['doc-a'].get('/demo/D01')
        self.assertEqual(200, response.status_code)
        self.assertNotIn('PRIVATE_CONTEXT_MARKER', response.text)
        self.assertIn('История приёмов', response.text)
        self.assertIn('Анкеты и динамика', response.text)
        self.assertEqual(before, [tuple(r) for r in self.db.execute('SELECT * FROM clinical_contexts')])

    def test_connection_check_still_reaches_doctor(self):
        self.assertEqual(302, self.post('pat-a', '/patients/D01/connection-check').status_code)
        self.assertEqual(1, self.db.execute('SELECT count(*) FROM relationship_checks').fetchone()[0])
        page = self.clients['doc-a'].get('/demo/D01').text
        self.assertIn('Связь с пациентом', page)
        self.assertIn('последняя получена', page)
        self.assertNotIn('Врачебные сведения', page)
