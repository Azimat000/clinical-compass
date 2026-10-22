"""UI02: tokens, local fonts, base template, shared components, login and result pages."""
import io
import logging
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

from apps.compass.db import connect, migrate
from apps.compass.repository import seed_demo
from apps.compass.web import create_app
import test_access

ROOT = Path(__file__).resolve().parents[2]
UI = ROOT / 'apps/compass'
CSP = ("default-src 'self'; style-src 'self'; img-src 'self'; object-src 'none'; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")


def token(response):
    return re.search(r'name="csrf" value="([^"]+)"', response.text).group(1)


class UiFoundationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'db.sqlite3'
        self.db = connect(self.path)
        migrate(self.db)
        seed_demo(self.db)
        test_access.setup_identities(self.db)
        self.app = create_app(self.path)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def attempt(self, client, uid, password):
        page = client.get('/login')
        return client.post('/login', data={'csrf': token(page), 'login': uid, 'password': password})

    def test_login_page_is_labelled_html_with_strict_policy(self):
        response = self.app.test_client().get('/login')
        self.assertEqual(200, response.status_code)
        self.assertEqual('text/html', response.mimetype)
        self.assertEqual(CSP, response.headers['Content-Security-Policy'])
        self.assertEqual('no-store', response.headers['Cache-Control'])
        html = response.text
        self.assertIn('<html lang="ru">', html)
        self.assertIn('<label for="f-login">Логин</label>', html)
        self.assertIn('<label for="f-password">Пароль</label>', html)
        self.assertIn('autocomplete="username"', html)
        self.assertIn('autocomplete="current-password"', html)
        self.assertIn('action="/login"', html)
        self.assertIn('Учебные данные', html)
        self.assertEqual(1, html.count('type="submit"'))
        self.assertNotIn('role="alert"', html)
        self.assertRegex(html, r'id="f-login"[^>]* autofocus>')

    def test_failed_login_names_problem_keeps_login_and_never_echoes_password(self):
        client = self.app.test_client()
        response = self.attempt(client, 'doc-a', 'wrong-synthetic-secret')
        self.assertEqual(401, response.status_code)
        html = response.text
        self.assertIn('role="alert"', html)
        self.assertIn('Не удалось войти', html)
        self.assertIn('Проверьте логин и пароль.', html)
        self.assertIn('value="doc-a"', html)
        self.assertNotIn('wrong-synthetic-secret', html)
        self.assertRegex(html, r'id="f-password"[^>]* autofocus>')
        self.assertEqual(2, html.count('aria-describedby="login-problem"'))
        # Unknown account and wrong password look the same.
        unknown = self.attempt(client, 'no-such-user', 'wrong-synthetic-secret').text
        self.assertEqual(html.count('Не удалось войти'), unknown.count('Не удалось войти'))
        self.assertEqual(302, self.attempt(client, 'doc-a', test_access.PASSWORD).status_code)

    def test_lockout_after_attempts_is_explained_and_survives_restart(self):
        client = self.app.test_client()
        for _ in range(10):
            self.assertEqual(401, self.attempt(client, 'doc-a', 'wrong').status_code)
        for app in (self.app, create_app(self.path)):
            locked = self.attempt(app.test_client(), 'doc-a', test_access.PASSWORD)
            self.assertEqual(429, locked.status_code)
            self.assertIn('Вход временно закрыт', locked.text)
            self.assertIn('Повторите через 15 минут.', locked.text)
            self.assertIn('notice--locked', locked.text)
            self.assertNotIn('Не удалось войти', locked.text)

    def test_json_clients_keep_technical_login_answer(self):
        response = self.app.test_client().get('/login', headers={'Accept': 'application/json'})
        self.assertEqual({'csrf', 'error'}, set(response.json))

    def test_result_page_for_browsers_plain_text_for_clients(self):
        client = self.app.test_client()
        page = client.get('/patients/D01/nothing')
        self.assertEqual(404, page.status_code)
        self.assertEqual('text/html', page.mimetype)
        self.assertIn('<h1>Запись недоступна</h1>', page.text)
        self.assertIn('href="/login"', page.text)
        self.assertEqual(CSP, page.headers['Content-Security-Policy'])
        plain = client.get('/patients/D01/nothing', headers={'Accept': 'application/json'})
        self.assertEqual('text/plain', plain.mimetype)
        self.assertEqual('text/plain', client.get('/api/nothing').mimetype)
        doctor = self.app.test_client()
        test_access.login(doctor, 'doc-a')
        signed_in = doctor.get('/patients/D99/follow-up')
        self.assertEqual(404, signed_in.status_code)
        self.assertIn('Открыть кабинет', signed_in.text)

    def test_server_failure_page_shows_incident_without_private_text(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        self.app.logger.addHandler(handler)
        try:
            with patch('apps.compass.web.access.login_challenge', side_effect=RuntimeError('PRIVATE-SYNTHETIC')):
                response = self.app.test_client().get('/login')
        finally:
            self.app.logger.removeHandler(handler)
        self.assertEqual(500, response.status_code)
        self.assertEqual('text/html', response.mimetype)
        self.assertIn('результат операции неизвестен', response.text)
        self.assertRegex(response.text, r'Код ошибки <span class="num">[0-9a-f]{16}</span>')
        self.assertNotIn('PRIVATE-SYNTHETIC', response.text + stream.getvalue())

    def test_views_without_template_still_answer_interface_removed(self):
        client = self.app.test_client()
        test_access.login(client, 'doc-a')
        response = client.get('/')
        self.assertEqual(503, response.status_code)
        self.assertEqual('interface_removed', response.json['status'])

    def test_tokens_match_design_md(self):
        design = (ROOT / 'DESIGN.md').read_text()
        front = design.split('---')[1]
        colors = re.findall(r'^  ([a-z-]+): "(#[0-9a-f]{6})"$', front.split('typography:')[0], re.M)
        self.assertGreaterEqual(len(colors), 16)
        css = (UI / 'static/app.css').read_text()
        for name, value in colors:
            self.assertIn('--%s: %s;' % (name, value), css, name)
        for name, value in re.findall(r'^  ([a-z]+): "(\d+px)"$', front.split('rounded:')[1].split('spacing:')[0], re.M):
            self.assertIn('--r-%s: %s;' % (name, value), css, name)

    def test_assets_are_local_licensed_and_templates_have_no_inline_code(self):
        sys.path.insert(0, str(ROOT / 'tools'))
        import check_fonts
        report, problems = check_fonts.check()
        self.assertEqual([], problems)
        css = (UI / 'static/app.css').read_text()
        faces = re.findall(r'url\("(fonts/[^"]+)"\)', css)
        self.assertEqual({'fonts/PTSans-Regular.ttf', 'fonts/PTSans-Bold.ttf', 'fonts/PTMono-Regular.ttf'}, set(faces))
        for face in faces:
            self.assertTrue((UI / 'static' / face).exists(), face)
        self.assertNotIn('@import', css)
        self.assertNotRegex(css, r'url\(["\']?(https?:)?//')
        for template in (UI / 'templates').glob('*.html'):
            text = template.read_text()
            with self.subTest(template=template.name):
                self.assertNotRegex(text, r'\sstyle\s*=')
                self.assertNotIn('<script', text)
                self.assertNotRegex(text, r'\son[a-z]+\s*=')
                self.assertNotRegex(text, r'(src|href)="(https?:)?//')

    def test_static_assets_revalidate_and_stay_under_policy(self):
        client = self.app.test_client()
        for name, mimetype in (('app.css', 'text/css'), ('fonts/PTMono-Regular.ttf', 'font/ttf'),
                               ('icons/mark.svg', 'image/svg+xml')):
            with client.get('/static/' + name) as response:
                self.assertEqual(200, response.status_code)
                self.assertEqual(mimetype, response.mimetype)
                self.assertEqual('no-cache', response.headers['Cache-Control'])
                self.assertEqual(CSP, response.headers['Content-Security-Policy'])

    def test_component_gallery_is_off_by_default_and_shows_every_state_when_on(self):
        self.assertEqual(404, self.app.test_client().get('/ui/components').status_code)
        with patch.dict(os.environ, {'COMPASS_UI_GALLERY': '1'}):
            gallery = create_app(self.path).test_client().get('/ui/components')
        self.assertEqual(200, gallery.status_code)
        html = gallery.text
        for marker in ('button--primary', ' disabled', 'aria-busy="true"', 'aria-invalid="true"',
                       'field-error', 'choice--invalid', 'notice--error', 'notice--locked', 'notice--done',
                       'class="empty"', 'class="loading"', 'class="flag"', 'class="wb', 'state--conflict',
                       'class="marker"', 'class="seg"', '<select', '<textarea', 'type="checkbox"', 'type="radio"'):
            self.assertIn(marker, html, marker)

    def test_worst_case_previews_render_without_overflowing_policy(self):
        with patch.dict(os.environ, {'COMPASS_UI_GALLERY': '1'}):
            client = create_app(self.path).test_client()
        for page in ('', '/login', '/login-error', '/login-locked', '/result'):
            for case in ('demo', 'worst'):
                with self.subTest(page=page, case=case):
                    response = client.get('/ui/components%s?data=%s' % (page, case))
                    self.assertEqual(200, response.status_code)
                    self.assertIn('class="dev-toggle"', response.text)
                    self.assertEqual(CSP, response.headers['Content-Security-Policy'])
        self.assertIn('Вход временно закрыт', client.get('/ui/components/login-locked').text)
        self.assertIn('9f3c27d4a1b08e65', client.get('/ui/components/result?data=worst').text)
        self.assertEqual(404, client.get('/ui/components?data=other').status_code)
        self.assertEqual(404, client.get('/ui/components/dashboard').status_code)
        self.assertNotIn('dev-toggle', self.app.test_client().get('/login').text)


if __name__ == '__main__':
    unittest.main()
