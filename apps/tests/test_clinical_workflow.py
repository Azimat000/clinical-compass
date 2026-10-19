"""HTTP integration of source-based advice, safety events and physician confirmation."""
import json
import secrets
import unittest
from unittest.mock import patch
import test_access
from apps.compass import clinical_rules, records, decisions, events
from apps.compass.db import now


class ClinicalWorkflowTests(unittest.TestCase):
    setUp = test_access.AccessTests.setUp
    tearDown = test_access.AccessTests.tearDown
    post = test_access.AccessTests.post
    offer = test_access.AccessTests.offer
    link = test_access.AccessTests.link

    def context(self, **changes):
        return {'request_key': secrets.token_hex(16), 'observed_on': records.today().isoformat(),
                'gad_status': 'present', 'severity': 'nonsevere', 'suicide_risk': 'denied',
                'psychiatric_comorbidity': 'denied', 'treatment_resistance': 'denied',
                'aviandr_prescription': 'active', 'clinical_basis': 'Синтетический врачебный источник',
                'prescription_basis': 'Вымышленное ранее сделанное назначение', **changes}

    def report(self, **changes):
        return {'request_key': secrets.token_hex(16), 'observed_on': records.today().isoformat(),
                'safety_form_version': 'aviandr-safety-v1', 'safety_taken': 'present',
                'safety_after_dose': 'present', 'safety_current': 'present',
                'safety_rigidity': 'present', **changes}

    def test_advice_prefill_two_categories_confirmation_and_stale_context(self):
        self.link()
        from test_decisions import DecisionTests
        for severity, expected in [('nonsevere', 'desirable'), ('severe', 'mandatory')]:
            self.assertEqual(303, self.post('doc-a', '/patients/D01/clinical-context', self.context(severity=severity)).status_code)
            advice = clinical_rules.recommendation(self.db, {'id': 'doc-a', 'role': 'doctor'}, 'D01')
            self.assertEqual(expected, advice['category'])
            self.assertEqual('unknown', advice['urgency'])
            response = self.clients['doc-a'].get('/patients/D01/decisions?from_context=' + advice['context_id'])
            self.assertEqual(200, response.status_code)
            self.assertIn('route_rule_context_id', response.text)
            self.assertIn('selected>Не определена', response.text)
            form = DecisionTests.values(self, kind='referral', route_category=expected,
                route_urgency='unknown', route_rule_context_id=advice['context_id'])
            self.assertEqual(303, self.post('doc-a', '/patients/D01/decisions', form).status_code)
            draft = self.db.execute('SELECT * FROM proposals ORDER BY version DESC LIMIT 1').fetchone()
            stored = json.loads(draft['payload_json'])['routing_review']['suggestion']
            self.assertEqual(advice['context_id'], stored['context_id'])
            confirm = {'version': str(draft['version']), 'decision': 'approved', 'rationale': 'Синтетическая проверка', 'reviewed': 'yes'}
            self.assertEqual(409, self.post('doc-a', f'/patients/D01/decisions/{draft["id"]}/confirm', confirm).status_code)
            self.assertEqual(303, self.post('doc-a', '/patients/D01/decisions', {**form, 'request_key': secrets.token_hex(16), 'route_urgency': 'planned'}).status_code)
            draft = self.db.execute('SELECT * FROM proposals ORDER BY version DESC LIMIT 1').fetchone()
            confirm['version'] = str(draft['version'])
            self.assertEqual(303, self.post('doc-a', f'/patients/D01/decisions/{draft["id"]}/confirm', confirm).status_code)
            patient = self.clients['pat-a'].get('/api/patients/D01/decisions').json['decisions'][0]
            self.assertEqual(expected, patient['payload']['route']['category'])
            self.assertNotIn('suggestion', str(patient))
        old = advice['context_id']
        self.assertEqual(303, self.post('doc-a', '/patients/D01/clinical-context', self.context()).status_code)
        self.assertEqual(409, self.clients['doc-a'].get('/patients/D01/decisions?from_context=' + old).status_code)
        self.assertEqual(404, self.clients['doc-b'].get('/patients/D01/decisions?from_context=' + old).status_code)
        self.assertEqual(403, self.clients['pat-a'].get('/patients/D01/decisions?from_context=' + old).status_code)

    def test_real_safety_event_survives_unavailable_recipient_and_routine_worker(self):
        self.link()
        self.post('doc-a', '/patients/D01/clinical-context', self.context())
        self.db.execute("UPDATE users SET disabled=1 WHERE id='doc-a'")
        report = self.report()
        self.assertEqual(303, self.post('pat-a', '/patients/D01/self-reports', report).status_code)
        self.assertEqual(303, self.post('pat-a', '/patients/D01/self-reports', report).status_code)
        event = self.db.execute('SELECT * FROM critical_events').fetchone()
        self.assertEqual('doc-a', event['recipient_id'])
        self.assertEqual(1, self.db.execute('SELECT count(*) FROM critical_events').fetchone()[0])
        while events.process_one(self.db):
            pass
        queued = self.db.execute('SELECT * FROM outbox_events WHERE id=?', (event['outbox_event_id'],)).fetchone()
        self.assertEqual(('pending', 0), (queued['status'], queued['attempts']))
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])
        self.assertEqual(3, self.db.execute('SELECT schema_version FROM self_reports').fetchone()[0])
        self.db.execute("UPDATE users SET disabled=0 WHERE id='doc-a'")
        page = self.clients['doc-a'].get('/demo/D01')
        self.assertEqual(200, page.status_code)
        self.assertIn(event['id'], page.text)
        self.assertIn('критическое событие', page.text)
        patient_page = self.clients['pat-a'].get('/demo/D01').text
        self.assertNotIn('Источник назначения:', patient_page)
        self.assertNotIn('Суицидальный риск в оценке врача', patient_page)
        self.assertNotIn(event['id'], patient_page)
        self.db.execute('UPDATE care_relationships SET ends_at=?', (now(),))
        self.assertEqual(303, self.post('pat-a', '/patients/D01/self-reports', self.report()).status_code)
        unassigned = self.db.execute("SELECT * FROM critical_events WHERE delivery_state='unassigned'").fetchone()
        self.assertIsNotNone(unassigned)
        self.assertIsNone(unassigned['recipient_id'])
        self.assertEqual(404, self.clients['doc-a'].get('/demo/D01').status_code)

    def test_context_auth_csrf_and_changed_source_fail_closed(self):
        self.link()
        context = self.context(clinical_basis='<script>synthetic()</script>')
        self.assertEqual(403, self.post('pat-a', '/patients/D01/clinical-context', context).status_code)
        self.assertEqual(404, self.post('doc-b', '/patients/D01/clinical-context', context).status_code)
        self.assertEqual(403, self.clients['doc-a'].post('/patients/D01/clinical-context', data=context).status_code)
        self.assertEqual(303, self.post('doc-a', '/patients/D01/clinical-context', context).status_code)
        self.assertNotIn('<script>synthetic()', self.clients['doc-a'].get('/demo/D01').text)
        with patch.object(clinical_rules, 'release', side_effect=clinical_rules.RuleError('Источник изменён.')):
            self.assertEqual(409, self.post('pat-a', '/patients/D01/self-reports', self.report()).status_code)
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM self_reports').fetchone()[0])
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM critical_events').fetchone()[0])
