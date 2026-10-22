"""S14: cross-route denials, malformed security input and fault boundaries."""
import io
import logging
import os
from pathlib import Path
import secrets
import sqlite3
import unittest
from unittest.mock import patch
from werkzeug.datastructures import MultiDict
import test_access
import test_decisions
from apps.compass import access, records
from apps.compass.db import connect


class SecurityTests(unittest.TestCase):
    setUp = test_decisions.DecisionTests.setUp
    tearDown = test_access.AccessTests.tearDown
    post = test_access.AccessTests.post
    offer = test_access.AccessTests.offer
    link = test_access.AccessTests.link
    values = test_decisions.DecisionTests.values
    draft = test_decisions.DecisionTests.draft
    confirm = test_decisions.DecisionTests.confirm

    def rows(self):
        tables = ('clinical_entries','proposals','doctor_confirmations','care_actions',
                  'text_imports','messages','adherence_tasks','critical_events','outbox_events')
        return {t: [tuple(r) for r in self.db.execute('SELECT * FROM '+t+' ORDER BY rowid')] for t in tables}

    def routes(self, method):
        for rule in self.app.url_map.iter_rules():
            if method in rule.methods and rule.endpoint not in ('static','login','healthz'):
                values = {name: ('D02' if name == 'patient_id' else 'foreign-missing-id') for name in rule.arguments}
                with self.app.test_request_context():
                    from flask import url_for
                    yield rule.endpoint, url_for(rule.endpoint, **values)

    def test_every_mutation_requires_session_and_csrf(self):
        before = self.rows()
        anonymous = self.app.test_client()
        for endpoint, path in self.routes('POST'):
            with self.subTest(endpoint=endpoint):
                r = anonymous.post(path)
                self.assertEqual(401 if path.startswith('/api/') else 302, r.status_code)
                for uid in ('doc-a','pat-a'):
                    self.assertEqual(403, self.clients[uid].post(path).status_code)
        self.assertEqual(before, self.rows())

    def test_all_patient_routes_deny_foreign_patient_even_with_valid_csrf(self):
        self.link('doc-b','pat-b','D02')
        before = self.rows()
        for method in ('GET','POST'):
            for rule in self.app.url_map.iter_rules():
                if 'patient_id' not in rule.arguments or method not in rule.methods:
                    continue
                args = {k: 'D02' if k=='patient_id' else 'missing-child' for k in rule.arguments}
                with self.app.test_request_context():
                    from flask import url_for
                    path = url_for(rule.endpoint, **args)
                for uid in ('doc-a','pat-a'):
                    with self.subTest(method=method,endpoint=rule.endpoint,uid=uid):
                        r = self.clients[uid].get(path) if method=='GET' else self.post(uid,path)
                        self.assertIn(r.status_code,(403,404))
                        self.assertNotIn('Демо 02', r.text)
        self.assertEqual(before,self.rows())

    def test_non_ascii_and_oversized_security_tokens_are_rejected(self):
        before = self.rows()
        for value in ('кириллица','🔑','x'*129,'', 'x,y'):
            with self.subTest(token=value[:12]):
                r = self.clients['doc-a'].post('/logout',data={'csrf':value})
                self.assertEqual(403,r.status_code)
                c = self.app.test_client()
                test_access.csrf(c,'/login')
                self.assertEqual(403,c.post('/login',data={'csrf':value,'login':'doc-a','password':'bad'}).status_code)
        self.assertEqual(before,self.rows())

    def test_duplicate_security_and_clinical_fields_are_rejected(self):
        c = self.clients['pat-a']; token = test_access.csrf(c)
        before=self.rows()
        for name in ('csrf','wellbeing','request_key','complaints_status'):
            fields = [('csrf',token),('request_key',secrets.token_hex(16)),('observed_on',records.today().isoformat()),
                      ('wellbeing','same'),('complaints_status','unknown'),(name,'different')]
            self.assertEqual(400,c.post('/patients/D01/self-reports',data=MultiDict(fields)).status_code)
        doctor=self.clients['doc-a']
        duplicate_files=MultiDict([('csrf',test_access.csrf(doctor)),('request_key',secrets.token_hex(16)),
                                   ('file',(io.BytesIO(b'one'),'one.txt')),('file',(io.BytesIO(b'two'),'two.txt'))])
        self.assertEqual(400,doctor.post('/patients/D01/imports',data=duplicate_files).status_code)
        self.assertEqual(before,self.rows())

    def test_unexpected_exception_hides_text_from_response_and_log(self):
        sentinel='SYNTHETIC_PRIVATE_SENTINEL_PASSWORD_TOKEN'
        stream=io.StringIO(); handler=logging.StreamHandler(stream)
        self.app.logger.addHandler(handler)
        try:
            with patch('apps.compass.web.patient_list',side_effect=RuntimeError(sentinel)):
                r=self.clients['doc-a'].get('/?q='+sentinel)
            self.assertEqual(500,r.status_code)
            self.assertIn('результат операции неизвестен',r.text)
            self.assertNotIn(sentinel,r.text+stream.getvalue())
            self.assertNotIn('Traceback',stream.getvalue())
            self.assertIn('RuntimeError',stream.getvalue())
        finally:
            self.app.logger.removeHandler(handler)

    def test_template_fault_has_safe_fallback_without_rethrow_or_secret(self):
        stream=io.StringIO(); handler=logging.StreamHandler(stream)
        self.app.logger.addHandler(handler)
        sentinel='SYNTHETIC_TEMPLATE_PRIVATE_VALUE'
        try:
            # '/login' is a rebuilt page (UI02); '/' has no template yet and answers 503 without rendering.
            with patch('apps.compass.web.render_template',side_effect=RuntimeError(sentinel)):
                r=self.app.test_client().get('/login')
                missing=self.clients['doc-a'].get('/missing')
            self.assertEqual(500,r.status_code)
            self.assertEqual(404,missing.status_code)
            self.assertIn('результат операции неизвестен',r.text)
            self.assertNotIn(sentinel,r.text+missing.text+stream.getvalue())
            self.assertNotIn('Traceback',stream.getvalue())
        finally:
            self.app.logger.removeHandler(handler)

    def test_database_fault_is_unavailable_not_safe_and_retry_can_succeed(self):
        before=self.rows()
        with patch('apps.compass.web.patient_list',side_effect=sqlite3.OperationalError('private db path')):
            r=self.clients['doc-a'].get('/')
        self.assertEqual(503,r.status_code)
        self.assertIn('неизвестен',r.text)
        self.assertNotIn('private db path',r.text)
        self.assertEqual('no-store',r.headers['Cache-Control'])
        self.assertEqual(200,self.clients['doc-a'].get('/').status_code)
        self.assertEqual(before,self.rows())

    def test_mid_write_fault_rolls_back_and_original_retry_succeeds(self):
        c=self.clients['pat-a']; form={'request_key':secrets.token_hex(16),'observed_on':records.today().isoformat()}
        before=self.rows()
        # Fail after report/observations/outbox insertion, before commit.
        with patch('apps.compass.records.access.audit',side_effect=sqlite3.OperationalError('synthetic disk fault')):
            r=self.post('pat-a','/patients/D01/self-reports',form)
        self.assertEqual(503,r.status_code)
        self.assertEqual(before,self.rows())
        self.assertEqual(303,self.post('pat-a','/patients/D01/self-reports',form).status_code)
        self.assertEqual(303,self.post('pat-a','/patients/D01/self-reports',form).status_code)
        self.assertEqual(1,self.db.execute('SELECT count(*) FROM clinical_entries').fetchone()[0])

    def test_private_files_and_headers_hosts_forwarding_and_oversized_input(self):
        if os.name=='posix':
            self.assertEqual(0o600,self.path.stat().st_mode & 0o777)
            private=Path(self.tmp.name)/'private'/'new.sqlite3'
            other=connect(private)
            try:
                self.assertEqual(0o700,private.parent.stat().st_mode & 0o777)
                self.assertEqual(0o600,private.stat().st_mode & 0o777)
            finally: other.close()
        for path in ('/login','/demo/D01','/api/patients/D01','/not-found'):
            r=self.clients['doc-a'].get(path)
            self.assertEqual('no-store',r.headers['Cache-Control'])
            self.assertIn("object-src 'none'",r.headers['Content-Security-Policy'])
            self.assertNotIn('Access-Control-Allow-Origin',r.headers)
        for path in ('/.env','/var/compass.sqlite3','/var/demo-credentials.json','/static/../var/compass.sqlite3'):
            self.assertEqual(404,self.clients['doc-a'].get(path).status_code)
        c=self.app.test_client()
        self.assertEqual(400,c.get('/login',headers={'Host':'attacker.example'}).status_code)
        r=c.get('/login',headers={'X-Forwarded-Host':'attacker.example','X-Forwarded-For':'192.0.2.44'})
        self.assertEqual(200,r.status_code)
        self.assertNotIn('attacker.example',r.text)
        self.assertEqual(413,c.post('/login',data={'csrf':'x'*70000}).status_code)

    def test_all_five_actions_require_doctor_and_fresh_review(self):
        for kind in ('therapy_start','therapy_change','therapy_stop','referral','plan_change'):
            p=self.draft(kind=kind)
            for uid,code in [('pat-a',403),('doc-b',404)]:
                r=self.post(uid,f'/patients/D01/decisions/{p["id"]}/confirm',
                            {'version':str(p['version']),'decision':'approved','reviewed':'yes','rationale':'forged'})
                self.assertEqual(code,r.status_code)
            self.assertEqual(0,self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])
            self.db.execute("UPDATE patients SET age_status='unknown' WHERE id='D01'")
            self.assertEqual(409,self.confirm(p).status_code)
            self.assertEqual(0,self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])
            self.db.execute("UPDATE patients SET age_status='known' WHERE id='D01'")
