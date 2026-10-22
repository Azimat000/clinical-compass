from pathlib import Path
import re
import tempfile
import unittest
from werkzeug.security import generate_password_hash
from apps.compass import access
from apps.compass.db import connect, migrate, now
from apps.compass.repository import seed_demo
from apps.compass.web import create_app

PASSWORD = 'synthetic-test-password-2026'
PASSWORD_HASH = generate_password_hash(PASSWORD, method='scrypt:32768:8:1')


def csrf(client, path='/'):
    """CSRF token from a rendered form (login) or from a technical JSON answer."""
    response = client.get(path, follow_redirects=True)
    if response.is_json:
        return response.get_json()['csrf']
    return re.search(r'name="csrf" value="([^"]+)"', response.text).group(1)


def login(client, uid, password=PASSWORD):
    token = csrf(client, '/login')
    return client.post('/login', data={'csrf': token, 'login': uid, 'password': password})


def setup_identities(db):
    for uid, role in [('doc-a', 'doctor'), ('doc-b', 'doctor'), ('pat-a', 'patient'), ('pat-b', 'patient')]:
        db.execute('INSERT INTO users VALUES(?,?,?,?,0)', (uid, role, uid, PASSWORD_HASH))
    db.execute("UPDATE patients SET user_id='pat-a' WHERE id='D01'")
    db.execute("UPDATE patients SET user_id='pat-b' WHERE id='D02'")


class AccessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'db.sqlite3'
        self.db = connect(self.path)
        migrate(self.db)
        seed_demo(self.db)
        setup_identities(self.db)
        self.app = create_app(self.path)
        self.clients = {u: self.app.test_client() for u in ('doc-a', 'doc-b', 'pat-a', 'pat-b')}
        for uid, client in self.clients.items():
            self.assertEqual(302, login(client, uid).status_code)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def post(self, uid, path, data=None):
        c = self.clients[uid]
        return c.post(path, data={'csrf': csrf(c), **(data or {})})

    def offer(self, uid='doc-a', pid='D01'):
        r = self.post(uid, '/invitations', {'patient_id': pid})
        self.assertEqual(200, r.status_code)
        return r.get_json()['invitation']

    def link(self, doc='doc-a', pat='pat-a', pid='D01'):
        token = self.offer(doc, pid)
        self.assertEqual(302, self.post(pat, '/link', {'invitation': token}).status_code)
        return token

    def test_no_anonymous_cards_or_api(self):
        c = self.app.test_client()
        for path in ('/', '/demo/D01'):
            self.assertEqual(302, c.get(path).status_code)
        for path in ('/api/patients/D01', '/api/patients/D01/documents', '/api/patients/D01/reports', '/api/documents/doc1'):
            self.assertEqual(401, c.get(path).status_code)
        self.assertEqual(401, c.post('/api/patients/D01/actions').status_code)
        self.assertEqual('ok', c.get('/healthz').json['status'])

    def test_roles_invitation_pair_and_shared_technical_report_after_restart(self):
        token = self.link()
        self.assertEqual(43, len(token))
        r = self.post('pat-a', '/patients/D01/connection-check')
        self.assertEqual(302, r.status_code)
        report = self.db.execute('SELECT * FROM relationship_checks').fetchone()
        for uid in ('doc-a', 'pat-a'):
            self.assertIn(report['id'], self.clients[uid].get('/demo/D01').get_data(as_text=True))
        # New application instance, same browser cookie and database.
        fresh = create_app(self.path).test_client()
        fresh.set_cookie(access.COOKIE, self.clients['doc-a'].get_cookie(access.COOKIE).value)
        self.assertIn(report['id'], fresh.get('/demo/D01').get_data(as_text=True))
        self.assertEqual(404, self.clients['doc-b'].get('/demo/D01').status_code)
        self.assertEqual(404, self.clients['pat-b'].get('/demo/D01').status_code)
        self.assertNotIn('Проверка связи получена', self.clients['pat-b'].get('/demo/D02').get_data(as_text=True))
        self.assertEqual(403, self.post('doc-a', '/patients/D01/connection-check').status_code)
        self.assertEqual(403, self.post('pat-a', '/invitations', {'patient_id': 'D02'}).status_code)
        self.assertEqual(403, self.post('doc-a', '/link', {'invitation': token}).status_code)

    def test_invitation_bound_to_recipient_single_use_competing_offer_invalidated(self):
        first, second = self.offer(), self.offer('doc-b')
        self.assertEqual(409, self.post('pat-b', '/link', {'invitation': first}).status_code)
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM care_relationships').fetchone()[0])
        self.assertEqual(302, self.post('pat-a', '/link', {'invitation': first}).status_code)
        for token in (first, second):
            self.assertEqual(409, self.post('pat-a', '/link', {'invitation': token}).status_code)
        self.assertEqual(1, self.db.execute('SELECT count(*) FROM care_relationships').fetchone()[0])
        self.assertEqual(409, self.post('doc-b', '/invitations', {'patient_id': 'D01'}).status_code)

    def test_expired_revoked_disabled_doctor_and_wrong_owner_invites(self):
        token = self.offer()
        hashed = access.digest(token)
        self.assertEqual(404, self.post('doc-b', f'/invitations/{hashed}/revoke').status_code)
        self.assertEqual(302, self.post('doc-a', f'/invitations/{hashed}/revoke').status_code)
        self.assertEqual(409, self.post('pat-a', '/link', {'invitation': token}).status_code)
        token = self.offer()
        self.db.execute('UPDATE care_invitations SET expires_at=? WHERE token_hash=?', ('2000-01-01', access.digest(token)))
        self.assertEqual(409, self.post('pat-a', '/link', {'invitation': token}).status_code)
        token = self.offer()
        self.db.execute("UPDATE users SET disabled=1 WHERE id='doc-a'")
        self.assertEqual(409, self.post('pat-a', '/link', {'invitation': token}).status_code)
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM care_relationships').fetchone()[0])

    def test_patient_document_reports_and_actions_access_matrix(self):
        self.link()
        self.link('doc-b', 'pat-b', 'D02')
        for pid in ('D01', 'D02'):
            self.db.execute('INSERT INTO documents VALUES(?,?,?, ?,?,?,?,1)', ('doc-' + pid, pid, 'txt', 'hash', '/private/' + pid, 'synthetic', now()))
            self.db.execute('INSERT INTO self_reports VALUES(?,?,?,?,?,?,1)', ('report-' + pid, pid, now(), now(), '{"marker":"private-' + pid + '"}', 'key-' + pid))
        for uid in ('doc-a', 'doc-b', 'pat-a', 'pat-b'):
            own = 'D01' if uid.endswith('a') else 'D02'
            other = 'D02' if own == 'D01' else 'D01'
            c = self.clients[uid]
            for suffix in ('', '/documents', '/reports'):
                self.assertEqual(200, c.get('/api/patients/' + own + suffix).status_code)
                denied = c.get('/api/patients/' + other + suffix)
                self.assertEqual(404, denied.status_code)
                self.assertNotIn('private-', denied.get_data(as_text=True))
            self.assertEqual(409, c.get('/api/documents/doc-' + own).status_code)
            self.assertEqual(404, c.get('/api/documents/doc-' + other).status_code)
            own_action = self.post(uid, '/api/patients/' + own + '/actions', {'role': 'doctor', 'doctor_id': 'doc-a'})
            self.assertEqual(409 if uid.startswith('doc') else 403, own_action.status_code)
            self.assertEqual(404 if uid.startswith('doc') else 403, self.post(uid, '/api/patients/' + other + '/actions').status_code)
            self.assertEqual(405, c.post('/api/patients/' + own, json={'user_id': uid, 'role': 'doctor'}).status_code)
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])
        for uid in ('doc-a', 'doc-b'):
            html = self.clients[uid].get('/').get_data(as_text=True)
            self.assertIn('Демо 01' if uid.endswith('a') else 'Демо 02', html)
            self.assertNotIn('<h3>Демо 02</h3>' if uid.endswith('a') else '<h3>Демо 01</h3>', html)
            self.assertNotIn('Демо 03', html)

    def test_ended_relationship_immediately_revokes_doctor_access(self):
        self.link()
        self.db.execute('UPDATE care_relationships SET ends_at=?', (now(),))
        self.assertEqual(404, self.clients['doc-a'].get('/demo/D01').status_code)
        self.assertEqual(404, self.clients['doc-a'].get('/api/patients/D01/reports').status_code)
        self.assertEqual(200, self.clients['pat-a'].get('/demo/D01').status_code)
        self.assertEqual(409, self.post('pat-a', '/patients/D01/connection-check').status_code)

    def test_sessions_hash_cookie_rotation_logout_expiry_idle_and_disabled(self):
        c = self.clients['doc-a']
        old = c.get_cookie(access.COOKIE).value
        self.assertIsNone(self.db.execute('SELECT 1 FROM sessions WHERE token_hash=?', (old,)).fetchone())
        self.assertIsNotNone(self.db.execute('SELECT 1 FROM sessions WHERE token_hash=?', (access.digest(old),)).fetchone())
        self.assertEqual(302, login(c, 'doc-a').status_code)
        self.assertNotEqual(old, c.get_cookie(access.COOKIE).value)
        attacker = self.app.test_client(); attacker.set_cookie(access.COOKIE, old)
        self.assertEqual(302, attacker.get('/').status_code)
        active = c.get_cookie(access.COOKIE)
        self.assertTrue(active.http_only); self.assertEqual('Strict', active.same_site)
        self.assertEqual(302, self.post('doc-a', '/logout').status_code)
        attacker.set_cookie(access.COOKIE, active.value)
        self.assertEqual(302, attacker.get('/').status_code)
        for field in ('expires_at', 'last_seen_at'):
            self.assertEqual(302, login(c, 'doc-a').status_code)
            self.db.execute('UPDATE sessions SET ' + field + '=? WHERE token_hash=?', ('2000-01-01', access.digest(c.get_cookie(access.COOKIE).value)))
            self.assertEqual(302, c.get('/').status_code)
        self.assertEqual(302, login(c, 'doc-a').status_code)
        self.db.execute("UPDATE users SET disabled=1 WHERE id='doc-a'")
        self.assertEqual(302, c.get('/').status_code)
        self.assertEqual(401, login(c, 'doc-a').status_code)

    def test_login_csrf_replay_and_authenticated_csrf(self):
        c = self.app.test_client()
        self.assertEqual(403, c.post('/login', data={'login': 'doc-a', 'password': PASSWORD}).status_code)
        challenge = csrf(c, '/login')
        self.assertEqual(302, c.post('/login', data={'login': 'doc-a', 'password': PASSWORD, 'csrf': challenge}).status_code)
        c.set_cookie(access.CHALLENGE_COOKIE, challenge)
        self.assertEqual(403, c.post('/login', data={'login': 'doc-a', 'password': PASSWORD, 'csrf': challenge}).status_code)
        for path in ('/logout', '/invitations', '/api/patients/D01/actions'):
            self.assertEqual(403, c.post(path).status_code)
            self.assertEqual(403, c.post(path, data={'csrf': 'bad'}).status_code)
        # CSRF from another authenticated browser does not work.
        self.assertEqual(403, c.post('/logout', data={'csrf': csrf(self.clients['doc-b'])}).status_code)
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM care_invitations').fetchone()[0])

    def test_login_throttle_persistent_and_generic_errors(self):
        c = self.app.test_client()
        for _ in range(10):
            # Failed attempts remain counted; successful setup logins refund themselves.
            self.assertEqual(401, login(c, 'unknown-user').status_code)
        self.assertEqual(429, login(c, 'doc-a').status_code)
        fresh = create_app(self.path).test_client()
        self.assertEqual(429, login(fresh, 'doc-a').status_code)
        self.db.execute("UPDATE login_limits SET window_end='2000-01-01'")
        missing = login(c, 'unknown-user').get_data(as_text=True)
        wrong = login(c, 'doc-a', 'wrong').get_data(as_text=True)
        self.assertIn('Не удалось войти', missing); self.assertIn('Не удалось войти', wrong)
        self.assertEqual(302, login(c, 'doc-a').status_code)

    def test_successful_shared_ip_logins_refund_only_their_own_attempt(self):
        client=self.app.test_client()
        for n in range(16):
            self.assertEqual(302,login(client,'doc-a' if n%2 else 'pat-a').status_code)
        address=access.digest('address:127.0.0.1')
        self.assertEqual(0,self.db.execute('SELECT attempts FROM login_limits WHERE subject_hash=?',(address,)).fetchone()[0])
        self.assertEqual(401,login(client,'doc-b','wrong').status_code)
        self.assertEqual(302,login(client,'doc-a').status_code)
        self.assertEqual(1,self.db.execute('SELECT attempts FROM login_limits WHERE subject_hash=?',(address,)).fetchone()[0])
        for _ in range(9):self.assertEqual(401,login(client,'doc-b','wrong').status_code)
        self.assertEqual(429,login(client,'doc-a').status_code)
        self.assertEqual(429,login(create_app(self.path).test_client(),'doc-b').status_code)

    def test_successful_auth_never_refunds_a_replaced_limit_window(self):
        from unittest.mock import patch
        original=access.check_password_hash
        account=access.digest('account:doc-a')
        def check(hashed,password):
            result=original(hashed,password)
            self.db.execute("UPDATE login_limits SET attempts=7,window_end='2099-01-01' WHERE subject_hash=?",(account,))
            return result
        with patch.object(access,'check_password_hash',side_effect=check):
            self.assertEqual(302,login(self.app.test_client(),'doc-a').status_code)
        self.assertEqual(7,self.db.execute('SELECT attempts FROM login_limits WHERE subject_hash=?',(account,)).fetchone()[0])

    def test_failed_audit_rolls_back_session_rotation_and_refund(self):
        from unittest.mock import patch
        previous=self.clients['doc-a'].get_cookie(access.COOKIE).value
        before=[tuple(r) for r in self.db.execute('SELECT * FROM sessions ORDER BY token_hash')]
        with patch.object(access,'audit',side_effect=RuntimeError('synthetic audit failure')):
            with self.assertRaises(RuntimeError):
                access.authenticate(self.db,'doc-a',PASSWORD,'rollback-test',previous)
        self.assertEqual(before,[tuple(r) for r in self.db.execute('SELECT * FROM sessions ORDER BY token_hash')])
        for subject in ('account:doc-a','address:rollback-test'):
            self.assertEqual(1,self.db.execute('SELECT attempts FROM login_limits WHERE subject_hash=?',(access.digest(subject),)).fetchone()[0])

    def test_account_changed_during_password_check_never_creates_session(self):
        from unittest.mock import patch
        original=access.check_password_hash
        count=self.db.execute('SELECT count(*) FROM sessions').fetchone()[0]
        for change in ('disabled','password_hash'):
            self.db.execute('DELETE FROM login_limits')
            self.db.execute("UPDATE users SET disabled=0,password_hash=? WHERE id='doc-a'",(PASSWORD_HASH,))
            def check(hashed,password):
                result=original(hashed,password)
                if change=='disabled':self.db.execute("UPDATE users SET disabled=1 WHERE id='doc-a'")
                else:self.db.execute("UPDATE users SET password_hash='changed-during-check' WHERE id='doc-a'")
                return result
            with patch.object(access,'check_password_hash',side_effect=check):
                self.assertEqual((None,'invalid'),access.authenticate(self.db,'doc-a',PASSWORD,'race-test'))
            self.assertEqual(count,self.db.execute('SELECT count(*) FROM sessions').fetchone()[0])
            self.assertEqual([1,1],[r[0] for r in self.db.execute('SELECT attempts FROM login_limits')])

    def test_recipient_reassignment_and_future_relationship_do_not_grant_access(self):
        token = self.offer()
        self.db.execute("UPDATE patients SET user_id=NULL WHERE id='D01'")
        self.db.execute("UPDATE patients SET user_id=NULL WHERE id='D02'")
        self.db.execute("UPDATE patients SET user_id='pat-b' WHERE id='D01'")
        self.assertFalse(access.accept_invite(self.db, 'pat-b', token))
        self.db.execute("INSERT INTO care_relationships VALUES('future','D01','doc-a',?,NULL)", (access.future(days=1),))
        self.assertEqual(404, self.clients['doc-a'].get('/demo/D01').status_code)
        self.assertNotIn('<h3>Демо 01</h3>', self.clients['doc-a'].get('/').get_data(as_text=True))

    def test_forged_cookie_and_hidden_patient_search(self):
        self.link()
        c = self.app.test_client()
        c.set_cookie(access.COOKIE, 'doc-a')
        self.assertEqual(401, c.get('/api/patients/D01', headers={'X-User-ID': 'doc-a', 'X-Role': 'doctor'}).status_code)
        self.db.execute("UPDATE encounters SET narrative='HiddenSensitiveMarker' WHERE patient_id='D02'")
        html = self.clients['doc-a'].get('/?q=HiddenSensitiveMarker').get_data(as_text=True)
        self.assertNotIn('href="/demo/D02"', html)
        self.assertIn('Пациенты не найдены', html)

    def test_secure_configuration_and_no_secrets_in_audit(self):
        self.app.config['AUTH_COOKIE_SECURE'] = True
        c = self.app.test_client()
        response = c.get('/login')
        self.assertIn('Secure', response.headers['Set-Cookie'])
        self.assertIn('HttpOnly', response.headers['Set-Cookie'])
        self.assertIn('SameSite=Strict', response.headers['Set-Cookie'])
        self.assertIn('max-age=', response.headers['Strict-Transport-Security'])
        token = self.link()
        rows = '\n'.join(str(tuple(r)) for r in self.db.execute('SELECT * FROM audit_entries'))
        self.assertNotIn(PASSWORD, rows); self.assertNotIn(token, rows)
        self.assertNotIn(self.clients['doc-a'].get_cookie(access.COOKIE).value, rows)

    def test_seed_accounts_random_idempotent_and_no_implicit_relationship(self):
        created = access.seed_accounts(self.db)
        self.assertEqual(6, len(created))
        self.assertEqual(6, len(set(r['password'] for r in created)))
        self.assertEqual([], access.seed_accounts(self.db))
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM care_relationships').fetchone()[0])
        for r in created:
            self.assertNotEqual(r['password'], self.db.execute('SELECT password_hash FROM users WHERE id=?', (r['login'],)).fetchone()[0])
        self.assertEqual([], self.db.execute('PRAGMA foreign_key_check').fetchall())
