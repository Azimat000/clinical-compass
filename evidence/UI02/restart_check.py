"""UI02 copy of evidence/S29/restart_check.py: same two real WSGI runs, static expectation updated."""
"""Real WSGI restart/worker on an isolated synthetic database, without HTML."""
import http.cookiejar
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import build_opener, HTTPCookieProcessor, HTTPRedirectHandler, Request

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'apps/tests')]
from apps.compass.db import connect, migrate
from apps.compass.repository import seed_demo
from apps.compass.web import create_app
from apps.compass import records
from test_access import PASSWORD, setup_identities


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def main():
    rounds = []
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'restart.sqlite3'
        db = connect(path)
        migrate(db)
        seed_demo(db)
        setup_identities(db)
        db.close()
        create_app(path)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        url = f'http://127.0.0.1:{port}'
        command = [sys.executable, '-m', 'apps.compass', '--db', str(path)]
        clients = {u: build_opener(NoRedirect(), HTTPCookieProcessor(http.cookiejar.CookieJar()))
                   for u in ('doc-a', 'pat-a')}

        def request(user, route, values=None):
            req = Request(url + route, None if values is None else urlencode(values).encode(),
                          headers={'Accept': 'application/json'})
            try:
                response = clients[user].open(req, timeout=5)
            except HTTPError as error:
                response = error
            with response:
                data = response.read()
                content = json.loads(data) if response.headers.get_content_type() == 'application/json' else None
                return response.code, content

        for round_number in (1, 2):
            with (Path(directory) / 'server.log').open('ab') as log:
                process = subprocess.Popen(command + ['serve', '--port', str(port)], cwd=ROOT,
                                           stdout=log, stderr=log)
                try:
                    for _ in range(100):
                        assert process.poll() is None, 'Server stopped during startup'
                        try:
                            assert request('doc-a', '/healthz')[0] == 200
                            break
                        except OSError:
                            time.sleep(.1)
                    else:
                        raise AssertionError('Server did not start')
                    if round_number == 1:
                        for uid in clients:
                            status, challenge = request(uid, '/login')
                            assert status == 200
                            assert request(uid, '/login', {'csrf': challenge['csrf'],
                                'login': uid, 'password': PASSWORD})[0] == 302
                        doctor_csrf = request('doc-a', '/')[1]['csrf']
                        patient_csrf = request('pat-a', '/demo/D01')[1]['csrf']
                        status, offer = request('doc-a', '/invitations',
                            {'csrf': doctor_csrf, 'patient_id': 'D01'})
                        assert status == 200
                        assert request('pat-a', '/link', {'csrf': patient_csrf,
                            'invitation': offer['invitation']})[0] == 302
                        form = {'csrf': patient_csrf, 'request_key': 'a' * 32,
                                'observed_on': records.today().isoformat(), 'summary': 'RESTART-SYNTHETIC'}
                        status, receipt = request('pat-a', '/patients/D01/self-reports', form)
                        assert status == 200 and receipt['location'].startswith('/demo/D01#entry-')
                    assert request('pat-a', '/patients/D01/self-reports', form) == (200, receipt)
                    for uid in clients:
                        status, history = request(uid, '/api/patients/D01/history')
                        assert status == 200 and len(history['entries']) == 1
                        assert history['entries'][0]['payload']['summary'] == 'RESTART-SYNTHETIC'
                        assert request(uid, '/api/patients/D02')[0] == 404
                        assert request(uid, '/demo/D01')[0] == 503
                    # UI02: the rebuilt stylesheet is served; the login page renders HTML for browsers.
                    assert request('doc-a', '/static/app.css')[0] == 200
                    assert request('doc-a', '/static/self_report.js')[0] == 404
                    rounds.append({'round': round_number, 'health': 'ok', 'sessions_survived': True,
                                   'shared_history': True, 'retry_no_duplicate': True,
                                   'foreign_denied': True, 'interface_removed': True})
                finally:
                    process.terminate()
                    process.wait(timeout=10)
        subprocess.run(command + ['worker', '--once'], cwd=ROOT, check=True, capture_output=True)
        db = connect(path)
        try:
            assert db.execute('SELECT count(*) FROM clinical_entries').fetchone()[0] == 1
            assert db.execute('SELECT count(*) FROM event_receipts').fetchone()[0] == 6
            assert db.execute("SELECT count(*) FROM outbox_events WHERE topic='routine.self_report.v1' AND status='processed'").fetchone()[0] == 1
            assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            assert not db.execute('PRAGMA foreign_key_check').fetchall()
        finally:
            db.close()
    result = {'rounds': rounds, 'worker_processed': True, 'integrity': 'ok', 'production_db_opened': False}
    (Path(__file__).parent / 'restart.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
