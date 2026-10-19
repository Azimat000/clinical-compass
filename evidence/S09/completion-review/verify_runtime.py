"""Actual HTTP intake and durable S09 events; this deliberately does not test S10 delivery."""
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
from urllib.parse import urlencode
from urllib.request import build_opener, HTTPCookieProcessor, urlopen

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def main():
    from apps.compass.db import connect
    from apps.compass.access import seed_accounts
    from apps.compass.records import today
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / 'critical.sqlite3'
        command = [sys.executable, '-m', 'apps.compass', '--db', str(path)]
        subprocess.run(command + ['seed-demo'], cwd=ROOT, check=True, capture_output=True)
        db = connect(path)
        credentials = {r['login']: r['password'] for r in seed_accounts(db)}
        db.close()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        origin = f'http://127.0.0.1:{port}'
        doctor, patient = [build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar())) for _ in range(2)]
        process = None
        pids = []

        def start():
            nonlocal process
            process = subprocess.Popen(command + ['serve', '--port', str(port)], cwd=ROOT,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            pids.append(process.pid)
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError('Server stopped on startup')
                try:
                    with urlopen(origin + '/healthz', timeout=1) as response:
                        assert json.load(response)['status'] == 'ok'
                    return
                except OSError:
                    time.sleep(.1)
            raise RuntimeError('Startup timeout')

        def stop():
            nonlocal process
            if process is not None:
                process.kill()
                process.wait(timeout=10)
                process = None

        def get(browser, route):
            with browser.open(origin + route, timeout=5) as response:
                return response.read().decode()

        def post(browser, route, values, token_route='/'):
            token = re.search(r'name="csrf" value="([^"]+)"', get(browser, token_route)).group(1)
            with browser.open(origin + route, urlencode({'csrf': token, **values}).encode(), timeout=5) as response:
                return response.read().decode()

        try:
            start()
            for browser, uid in ((doctor, 'doctor-demo'), (patient, 'patient-D01')):
                post(browser, '/login', {'login': uid, 'password': credentials[uid]}, '/login')
            invitation = post(doctor, '/invitations', {'patient_id': 'D01'})
            token = re.search(r'readonly value="([^"]+)"', invitation).group(1)
            post(patient, '/link', {'invitation': token})
            context = {'request_key': secrets.token_hex(16), 'observed_on': today().isoformat(),
                       'gad_status': 'present', 'severity': 'nonsevere', 'suicide_risk': 'denied',
                       'psychiatric_comorbidity': 'denied', 'treatment_resistance': 'denied',
                       'aviandr_prescription': 'active', 'clinical_basis': 'Вымышленный врачебный источник F41.1',
                       'prescription_basis': 'Вымышленный документ существующего назначения'}
            html = post(doctor, '/patients/D01/clinical-context', context)
            assert '◇ Желательно' in html and 'психотерапевтом' in html
            html = post(doctor, '/patients/D01/clinical-context', {**context, 'request_key': secrets.token_hex(16), 'severity': 'severe'})
            assert '⚠ Обязательно' in html and 'Срочность не определена источником' in html
            report = {'request_key': secrets.token_hex(16), 'observed_on': today().isoformat(),
                      'safety_form_version': 'aviandr-safety-v1', 'safety_taken': 'present',
                      'safety_after_dose': 'present', 'safety_current': 'present',
                      'safety_hyperhidrosis': 'present'}
            post(patient, '/patients/D01/self-reports', report)
            post(patient, '/patients/D01/self-reports', report)
            db = connect(path)
            event = dict(db.execute('SELECT * FROM critical_events').fetchone())
            evaluation = dict(db.execute('SELECT * FROM clinical_rule_evaluations').fetchone())
            assert evaluation['result'] == 'triggered'
            assert db.execute('SELECT count(*) FROM critical_events').fetchone()[0] == 1
            assert db.execute('SELECT count(*) FROM self_reports').fetchone()[0] == 1
            before = dict(db.execute('SELECT * FROM outbox_events WHERE id=?', (event['outbox_event_id'],)).fetchone())
            assert before['status'] == 'pending' and before['attempts'] == 0
            db.close()
            stop()
            # Existing routine worker can drain its own topics without consuming S09 critical events.
            subprocess.run(command + ['worker', '--once'], cwd=ROOT, check=True, capture_output=True)
            start()
            html = get(doctor, '/demo/D01')
            assert event['id'] in html and 'Создано критическое событие' in html
            assert event['id'] not in get(patient, '/demo/D01')
            assert event['id'] not in get(doctor, '/notifications')
            db = connect(path)
            assert event == dict(db.execute('SELECT * FROM critical_events').fetchone())
            assert evaluation == dict(db.execute('SELECT * FROM clinical_rule_evaluations').fetchone())
            queued = dict(db.execute('SELECT * FROM outbox_events WHERE id=?', (event['outbox_event_id'],)).fetchone())
            assert queued == before
            counts = {table: db.execute('SELECT count(*) FROM ' + table).fetchone()[0]
                      for table in ('care_actions', 'proposals', 'doctor_confirmations', 'therapy_courses')}
            assert not any(counts.values())
            assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            assert not db.execute('PRAGMA foreign_key_check').fetchall()
            db.close()
            print(json.dumps({'server_processes': pids, 'forced_server_kill_and_restart': True,
                'both_source_categories_generated_over_http': True, 'source_urgency_remains_unknown': True,
                'actual_critical_event': event, 'evaluation_result': evaluation['result'],
                'duplicate_request_single_report_event': True, 'all_event_and_evaluation_fields_survived': True,
                'routine_worker_preserved_critical_outbox_pending': True, 'patient_internal_event_hidden': True,
                'clinical_action_counts': counts, 'integrity': 'ok', 'foreign_key_violations': 0,
                'verified_at': datetime.now(timezone.utc).isoformat(),
                'scope': 'S09 event creation and persistence only; no critical delivery or clinical validation claimed.'}, ensure_ascii=False, indent=2))
        finally:
            stop()


if __name__ == '__main__':
    main()
