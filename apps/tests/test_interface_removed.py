"""Presentation removal must preserve real server transactions and access checks."""
from pathlib import Path
import secrets
import sqlite3
import unittest
from unittest.mock import patch

from apps.compass import access, assessments, records
from apps.compass.web import create_app
import test_access
import test_decisions


class InterfaceRemovedTests(unittest.TestCase):
    setUp = test_decisions.DecisionTests.setUp
    tearDown = test_access.AccessTests.tearDown
    post = test_access.AccessTests.post
    offer = test_access.AccessTests.offer
    link = test_access.AccessTests.link
    values = test_decisions.DecisionTests.values
    draft = test_decisions.DecisionTests.draft
    confirm = test_decisions.DecisionTests.confirm

    def send(self, path, values, who='pat-a'):
        client = self.clients[who]
        return client.post(path, data={'csrf': test_access.csrf(client), **values},
                           headers={'Accept': 'application/json'})

    def test_only_rebuilt_templates_and_new_assets_are_served(self):
        # UI02 rebuilt login/result, UI03 the patient cabinet, UI04 the doctor's list, card and follow-up, UI05 decisions, first visit and imports, UI06 messages (notification and critical screens subsequently removed in S39/S31), UI06B the patient's plan; the rest of the S29 assets stay removed.
        root = Path(__file__).resolve().parents[1] / 'compass'
        self.assertEqual({'base.html', 'components.html', 'components_gallery.html', 'dev_toggle.html', 'login.html', 'result.html',
                          'patient_base.html', 'patient.html', 'assessment_form.html', 'assessment_receipt.html', 'invitation.html',
                          'doctor_base.html', 'dashboard.html', 'invitation_content.html', 'invitation_manage.html', 'doctor_patient.html',
                          'decisions.html', 'plan_outcomes.html', 'patient_plan_tasks.html', 'first_visit.html', 'imports.html',
                          'communication.html', 'plan.html', 'visit_records.html', 'medication_components.html', 'medication_editor.html', 'assessment_charts.html'},
                         {p.name for p in (root / 'templates').iterdir()})
        for name in ('interface.js', 'communication.js', 'critical.js', 'first_visit.js', 'fonts/PTSerif-Bold.ttf'):
            response = self.app.test_client().get('/static/' + name)
            self.assertEqual(404, response.status_code)
            self.assertEqual('text/html', response.mimetype)  # result page, not the removed file
        for name in ('app.css', 'fonts/PTSans-Regular.ttf', 'fonts/PTMono-Regular.ttf'):
            with self.app.test_client().get('/static/' + name) as response:
                self.assertEqual(200, response.status_code)

    def test_patient_plan_page_is_a_page_and_stays_technical_for_json_clients(self):
        # UI06B: пациент получает экран плана; клиенты, просящие JSON, по-прежнему получают техническое 503.
        path = '/patients/D01/decisions'
        page = self.clients['pat-a'].get(path)
        self.assertEqual(200, page.status_code)
        self.assertIn('<html', page.text)
        self.assertEqual(200, self.clients['pat-a'].head(path).status_code)
        for path in ('/patients/D01/decisions',):
            with self.subTest(path=path):
                response = self.clients['pat-a'].get(path, headers={'Accept': 'application/json'})
                self.assertEqual(503, response.status_code)
                self.assertEqual('interface_removed', response.json['status'])
                self.assertEqual({'status', 'message', 'csrf'}, set(response.json))
                self.assertNotIn('Демо 01', response.text)
                self.assertNotIn('<html', response.text)
                self.assertEqual('no-store', response.headers['Cache-Control'])
                self.assertEqual(503, self.clients['pat-a'].head(path, headers={'Accept': 'application/json'}).status_code)

    def test_doctor_screens_are_pages_for_browsers_and_stay_technical_for_json_clients(self):
        for path in ('/', '/demo/D01', '/patients/D01/follow-up', '/patients/D01/first-visits',
                     '/patients/D01/decisions', '/patients/D01/imports', '/patients/D01/communication',):
            with self.subTest(path=path):
                page = self.clients['doc-a'].get(path)
                self.assertEqual(200, page.status_code)
                self.assertIn('<html', page.text)
                self.assertIn('Демо 01', page.text)
                technical = self.clients['doc-a'].get(path, headers={'Accept': 'application/json'})
                self.assertEqual(503, technical.status_code)
                self.assertEqual('interface_removed', technical.json['status'])
                self.assertNotIn('Демо 01', technical.text)

    def test_login_logout_and_csrf_work_for_json_clients(self):
        client = self.app.test_client()
        json_only = {'Accept': 'application/json'}
        challenge = client.get('/login', headers=json_only)
        self.assertEqual(200, challenge.status_code)
        self.assertEqual({'csrf', 'error'}, set(challenge.json))
        self.assertEqual(403, client.post('/login', data={
            'login': 'doc-a', 'password': test_access.PASSWORD}).status_code)
        response = client.post('/login', data={'csrf': challenge.json['csrf'],
            'login': 'doc-a', 'password': test_access.PASSWORD}, headers=json_only)
        self.assertEqual(302, response.status_code)
        self.assertEqual(200, client.get('/api/patients/D01').status_code)
        self.assertEqual(403, client.post('/logout').status_code)
        token = test_access.csrf(client)
        self.assertEqual(302, client.post('/logout', data={'csrf': token}).status_code)
        self.assertEqual(401, client.get('/api/patients/D01').status_code)

    def test_existing_apis_and_foreign_access_remain_protected(self):
        for who in ('doc-a', 'pat-a'):
            for suffix in ('', '/documents', '/reports', '/history', '/assessments', '/decisions'):
                path = '/api/patients/D01' + suffix
                self.assertEqual(200, self.clients[who].get(path).status_code, path)
                self.assertEqual(401, self.app.test_client().get(path).status_code, path)
                for other in ('doc-b', 'pat-b'):
                    self.assertEqual(404, self.clients[other].get(path).status_code, path)
        self.assertEqual('ok', self.app.test_client().get('/healthz').json['status'])

    def test_private_draft_send_retry_and_restart_preserve_records(self):
        draft_url = '/patients/D01/self-report-draft'
        report_url = '/patients/D01/self-reports'
        values = {'request_key': secrets.token_hex(16), 'draft_revision': '0',
                  'observed_on': records.today().isoformat(), 'summary': 'PRIVATE-SYNTHETIC-DRAFT',
                  'adverse_events_status': 'known', 'adverse_events_text': 'Синтетическая тошнота'}
        saved = self.send(draft_url, values)
        self.assertEqual(200, saved.status_code)
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM clinical_entries').fetchone()[0])
        for who, status in (('doc-a', 403), ('doc-b', 403), ('pat-b', 404)):
            self.assertEqual(status, self.clients[who].get(draft_url).status_code)
        fresh = create_app(self.path).test_client()
        fresh.set_cookie(access.COOKIE, self.clients['pat-a'].get_cookie(access.COOKIE).value)
        self.assertEqual(values['summary'], fresh.get(draft_url).json['values']['summary'])
        values['draft_revision'] = str(saved.json['revision'])
        sent = self.send(report_url, values)
        self.assertEqual(200, sent.status_code)
        self.assertEqual(sent.json, self.send(report_url, values).json)
        self.assertFalse(fresh.get(draft_url).json['active'])
        self.assertEqual(409, self.send(draft_url, values).status_code)
        self.assertEqual(1, self.db.execute('SELECT count(*) FROM clinical_entries').fetchone()[0])
        self.assertEqual(1, self.db.execute('SELECT count(*) FROM adverse_events').fetchone()[0])
        history = self.clients['doc-a'].get('/api/patients/D01/history').json['entries']
        self.assertEqual(values['summary'], history[0]['payload']['summary'])
        self.assertNotIn('request_key', history[0])

    def test_all_five_actions_still_require_fresh_physician_confirmation(self):
        for kind in ('therapy_start', 'therapy_change', 'therapy_stop', 'referral', 'plan_change'):
            proposal = self.draft(kind=kind)
            before = self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0]
            self.assertEqual(before, len(self.clients['pat-a'].get(
                '/api/patients/D01/decisions').json['decisions']))
            path = '/patients/D01/decisions/' + proposal['id'] + '/confirm'
            form = {'version': str(proposal['version']), 'decision': 'approved',
                    'reviewed': 'yes', 'rationale': 'Синтетическая проверка'}
            self.assertEqual(403, self.post('pat-a', path, form).status_code)
            self.assertEqual(404, self.post('doc-b', path, form).status_code)
            self.assertEqual(303, self.confirm(proposal).status_code)
            self.assertEqual(303, self.confirm(proposal).status_code)
            self.assertEqual(before + 1, self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])

    def test_assessments_keep_scoring_private_and_unknown_age_blocks_assignment(self):
        definition = assessments.definition()
        form = {'assignment_key': secrets.token_hex(16), 'form_version_id': definition['id'],
                'age_status': 'known', 'age_years': '35', 'age_basis': 'Синтетический профиль'}
        path = '/patients/D01/assessment-requests'
        self.assertEqual(303, self.post('doc-a', path, form).status_code)
        task = self.db.execute('SELECT id FROM assessment_requests').fetchone()[0]
        answers = {'form_version_id': definition['id'],
                   **{f'answer_{i}': '2' for i in range(1, 43)}}
        self.assertEqual(303, self.post('pat-a', '/assessments/' + task, answers).status_code)
        receipt = self.clients['pat-a'].get('/assessments/' + task, headers={'Accept': 'application/json'})
        self.assertEqual(200, receipt.status_code)
        self.assertEqual({'status', 'request_id', 'received_at'}, set(receipt.json))
        doctor = self.clients['doc-a'].get('/api/patients/D01/assessments').json['assessments'][0]
        self.assertEqual({'depression': 28, 'anxiety': 28, 'stress': 28}, doctor['scores'])
        patient = self.clients['pat-a'].get('/api/patients/D01/assessments').json['assessments'][0]
        self.assertNotIn('scores', patient)
        self.assertNotIn('answers', patient)
        self.db.execute("UPDATE patients SET age_status='unknown', age_years=NULL WHERE id='D01'")
        form.update(assignment_key=secrets.token_hex(16), age_status='unknown', age_years='', age_basis='')
        self.assertEqual(400, self.post('doc-a', path, form).status_code)
        self.assertEqual(1, self.db.execute('SELECT count(*) FROM assessment_requests').fetchone()[0])

    def test_server_failure_keeps_safe_errors_and_atomic_rollback(self):
        values = {'request_key': secrets.token_hex(16),
                  'observed_on': records.today().isoformat(), 'summary': 'Синтетика'}
        with patch('apps.compass.records.access.audit', side_effect=sqlite3.OperationalError('PRIVATE-PATH')):
            response = self.send('/patients/D01/self-reports', values)
        self.assertEqual(503, response.status_code)
        self.assertIn('результат операции неизвестен', response.text)
        self.assertNotIn('PRIVATE-PATH', response.text)
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM clinical_entries').fetchone()[0])
        self.assertEqual(200, self.send('/patients/D01/self-reports', values).status_code)
