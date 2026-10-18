"""Real WSGI restart: authenticated pair, private access and durable report/outbox."""
import http.cookiejar
import json
from pathlib import Path
import re
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import build_opener, HTTPCookieProcessor, urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    from apps.compass.access import seed_accounts
    from apps.compass.db import connect, now
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'fresh.sqlite3'
        command = [sys.executable, '-m', 'apps.compass', '--db', str(path)]
        subprocess.run(command + ['seed-demo'], cwd=ROOT, check=True)
        db = connect(path)
        creds = {c['login']: c['password'] for c in seed_accounts(db)}
        db.close()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
        url = f'http://127.0.0.1:{port}'
        doctor, patient = [build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar())) for _ in range(2)]

        def get(browser, route='/'):
            with browser.open(url + route, timeout=3) as response:
                return response.read().decode()

        def post(browser, route, values):
            page = get(browser, '/login' if route == '/login' else '/')
            csrf = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
            try:
                with browser.open(url + route, urlencode({'csrf': csrf, **values}).encode(), timeout=5) as response:
                    return response.read().decode()
            except HTTPError as error:
                # Synthetic diagnostics only, deliberately exclude cookies/tokens/passwords.
                with sqlite3.connect(path) as diagnostic:
                    print(json.dumps({'failed_route': route, 'status': error.code, 'server_check_time': now(),
                        'relationships': diagnostic.execute('SELECT patient_id,doctor_id,starts_at,ends_at FROM care_relationships').fetchall(),
                        'accounts': diagnostic.execute('SELECT id,role,disabled FROM users').fetchall()}, ensure_ascii=False))
                raise

        result, report_id = [], None
        for round_number in (1, 2):
            with open(Path(directory) / f'server-{round_number}.log', 'wb') as log:
                process = subprocess.Popen(command + ['serve', '--port', str(port)], cwd=ROOT, stdout=log, stderr=log)
                try:
                    for _ in range(100):
                        if process.poll() is not None:
                            raise RuntimeError('Server exited during startup')
                        try:
                            with urlopen(url + '/healthz', timeout=1) as response:
                                status = json.load(response)
                            break
                        except OSError:
                            time.sleep(.1)
                    else:
                        raise RuntimeError('Server did not become ready')
                    assert 'Вход в компас' in urlopen(url, timeout=3).read().decode()
                    if round_number == 1:
                        for browser, uid in ((doctor, 'doctor-demo'), (patient, 'patient-D01')):
                            post(browser, '/login', {'login': uid, 'password': creds[uid]})
                        offer = post(doctor, '/invitations', {'patient_id': 'D01'})
                        token = re.search(r'readonly value="([^"]+)"', offer).group(1)
                        post(patient, '/link', {'invitation': token})
                        html = post(patient, '/patients/D01/connection-check', {})
                        report_id = re.search(r'Технический отчёт ([0-9a-f]+)', html).group(1)
                    assert report_id in get(patient) and report_id in get(doctor, '/demo/D01')
                    assert 'Демо 01' in get(doctor) and 'Демо 02' not in get(doctor)
                    for browser in (doctor, patient):
                        try:
                            get(browser, '/api/patients/D02')
                            raise AssertionError('Foreign patient was accessible')
                        except HTTPError as error:
                            assert error.code == 404
                    result.append({'restart_round': round_number, 'health': status, 'shared_report': True, 'foreign_denied': True})
                finally:
                    process.terminate(); process.wait(timeout=10)
        subprocess.run(command + ['worker', '--once'], cwd=ROOT, check=True)
        with sqlite3.connect(path) as db:
            assert db.execute('SELECT count(*) FROM patients').fetchone()[0] == 6
            assert db.execute("SELECT count(*) FROM outbox_events WHERE status='processed'").fetchone()[0] == 6
            assert db.execute('SELECT count(*) FROM event_receipts').fetchone()[0] == 6
            assert db.execute('SELECT count(*) FROM relationship_checks').fetchone()[0] == 1
            assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        print(json.dumps({'process_restart': result, 'durable_events_after_restart': 6, 'durable_technical_reports': 1, 'integrity': 'ok'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
