"""Real localhost Waitress restart and HTTP HTML receipt; synthetic data only."""
from datetime import datetime, timezone
import http.cookiejar
import json
from pathlib import Path
import re
import secrets
import socket
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
        path = Path(directory) / 'delivery.sqlite3'
        command = [sys.executable, '-m', 'apps.compass', '--db', str(path)]
        subprocess.run(command + ['seed-demo'], cwd=ROOT, check=True, capture_output=True)
        db = connect(path)
        credentials = {r['login']: r['password'] for r in seed_accounts(db)}
        db.close()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        origin = f'http://127.0.0.1:{port}'
        doctor, patient, other = [build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar())) for _ in range(3)]
        process = None
        server_pids = []

        def start():
            nonlocal process
            process = subprocess.Popen(command + ['serve', '--port', str(port)], cwd=ROOT,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            server_pids.append(process.pid)
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError('Waitress exited during startup')
                try:
                    with urlopen(origin + '/healthz', timeout=1) as response:
                        assert json.load(response)['status'] == 'ok'
                    return
                except OSError:
                    time.sleep(.1)
            raise RuntimeError('Waitress startup timed out')

        def stop():
            nonlocal process
            if process is not None:
                process.terminate()
                process.wait(timeout=10)
                process = None

        def get(browser, route='/'):
            with browser.open(origin + route, timeout=5) as response:
                return response.read().decode()

        def post(browser, route, values=None):
            page = get(browser, '/login' if route == '/login' else '/')
            match = re.search(r'name="csrf" value="([^"]+)"', page)
            assert match, 'CSRF missing'
            with browser.open(origin + route, urlencode({'csrf': match.group(1), **(values or {})}).encode(), timeout=5) as response:
                return response.read().decode()

        def denied(browser, route, values=None):
            try:
                if values is None:
                    return get(browser, route)
                return post(browser, route, values)
            except HTTPError as exc:
                assert exc.code in (403, 404)
                return ''

        try:
            start()
            for browser, uid in ((doctor, 'doctor-demo'), (patient, 'patient-D01'), (other, 'patient-D02')):
                post(browser, '/login', {'login': uid, 'password': credentials[uid]})
            offer = post(doctor, '/invitations', {'patient_id': 'D01'})
            invitation = re.search(r'readonly value="([^"]+)"', offer).group(1)
            post(patient, '/link', {'invitation': invitation})
            values = {'request_key': secrets.token_hex(16), 'observed_on': datetime.now(timezone.utc).date().isoformat(),
                      'summary': 'Synthetic ordinary restart verification', 'wellbeing': 'unknown',
                      'complaints_status': 'unknown', 'risk_factors_status': 'unknown',
                      'concomitant_medications_status': 'unknown', 'adverse_events_status': 'unknown', 'age_status': 'unknown'}
            monotonic_start = time.monotonic()
            post(patient, '/patients/D01/self-reports', values)
            post(patient, '/patients/D01/self-reports', values)
            db = connect(path)
            entry = db.execute('SELECT * FROM clinical_entries').fetchone()
            entry_id, received_at = entry['id'], entry['recorded_at']
            notification = dict(db.execute('SELECT * FROM routine_notifications WHERE id=?', (entry_id,)).fetchone())
            assert notification['ready_at'] is None and notification['delivered_at'] is None
            assert db.execute('SELECT count(*) FROM clinical_entries').fetchone()[0] == 1
            assert db.execute('SELECT count(*) FROM routine_notifications').fetchone()[0] == 1
            db.close()
            stop()  # The report and pending event must outlive this actual process.
            subprocess.run(command + ['worker', '--once'], cwd=ROOT, check=True, capture_output=True)
            db = connect(path)
            ready = db.execute('SELECT * FROM routine_notifications WHERE id=?', (entry_id,)).fetchone()
            assert ready['ready_at'] and ready['delivered_at'] is None
            db.close()
            start()
            html = get(doctor, '/notifications')
            html_received_at = now()
            monotonic_elapsed = time.monotonic() - monotonic_start
            assert entry_id in html
            assert entry_id not in denied(other, '/notifications')
            post(doctor, f'/notifications/{entry_id}/seen')
            post(doctor, f'/notifications/{entry_id}/acknowledged')
            db = connect(path)
            stamps = dict(db.execute('SELECT * FROM routine_notifications WHERE id=?', (entry_id,)).fetchone())
            for name in ('ready_at', 'delivered_at', 'seen_at', 'acknowledged_at'):
                assert stamps[name]
            db.close()
            stop()
            start()
            assert entry_id in get(doctor, '/notifications')
            post(doctor, f'/notifications/{entry_id}/seen')
            post(doctor, f'/notifications/{entry_id}/acknowledged')
            db = connect(path)
            assert stamps == dict(db.execute('SELECT * FROM routine_notifications WHERE id=?', (entry_id,)).fetchone())
            attempts = [dict(r) for r in db.execute('SELECT attempt,outcome,error FROM outbox_attempts WHERE event_id=?', (stamps['event_id'],))]
            assert attempts == [{'attempt': 1, 'outcome': 'processed', 'error': None}]
            db.execute('UPDATE care_relationships SET ends_at=? WHERE id=?', (now(), stamps['relationship_id']))
            assert entry_id not in get(doctor, '/notifications')
            assert denied(doctor, f'/notifications/{entry_id}/seen', {}) == ''
            for table in ('care_actions', 'proposals', 'alerts', 'risk_evaluations', 'assessments', 'adverse_events'):
                assert db.execute('SELECT count(*) FROM ' + table).fetchone()[0] == 0, table
            assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            assert db.execute('PRAGMA foreign_key_check').fetchall() == []
            db.close()
            wall_ms = (datetime.fromisoformat(html_received_at) - datetime.fromisoformat(received_at)).total_seconds() * 1000
            print(json.dumps({'scenario': 'S10A synthetic ordinary self report', 'server': 'Waitress localhost HTTP',
                'real_server_processes': server_pids, 'restarts': len(server_pids) - 1,
                'pending_survived_server_stop': True, 'worker_processed_while_cabinet_closed': True,
                'duplicate_submission_single_notification': True, 'server_stamps_survived_restart': True,
                'other_role_and_ended_relationship_denied': True, 'clinical_actions_created': False,
                'measurement': {'definition': 'server recorded_at to HTTP HTML response fully received; includes deliberate process restarts',
                    'server_received_at': received_at, 'http_html_received_at': html_received_at,
                    'elapsed_wall_ms': round(wall_ms, 3), 'request_to_html_monotonic_ms': round(monotonic_elapsed * 1000, 3),
                    'browser_visibility_measured': False, 'errors': 0},
                'notification_stamps': {k: stamps[k] for k in ('created_at','ready_at','delivered_at','seen_at','acknowledged_at')},
                'attempts': attempts, 'integrity': 'ok', 'foreign_key_violations': 0,
                'limitations': 'Synthetic local HTTP evidence only; no external channel, clinical validation or 24/7 monitoring.'}, ensure_ascii=False, indent=2))
        finally:
            stop()


if __name__ == '__main__':
    main()
