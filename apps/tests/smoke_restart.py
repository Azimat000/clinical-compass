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
    from apps.compass.decisions import reference
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

        result, report_id, clinical_id, assessment_tasks = [], None, None, []
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
                        key = re.search(r'name="request_key" value="([^"]+)"', html).group(1)
                        values = {'request_key': key, 'observed_on': '2026-10-18', 'wellbeing': 'worse',
                                  'complaints_status': 'known', 'complaints_text': 'Синтетическая жалоба после перезапуска',
                                  'risk_factors_status': 'unknown', 'adverse_events_status': 'known',
                                  'adverse_events_text': 'Синтетическое нежелательное явление', 'age_status': 'unknown'}
                        html = post(patient, '/patients/D01/self-reports', values)
                        clinical_id = json.loads(get(doctor, '/api/patients/D01/history'))['entries'][0]['id']
                        post(patient, '/patients/D01/self-reports', values)  # Same retry does not duplicate.
                        html = get(doctor, '/demo/D01')
                        visit_key = re.search(r'name="request_key" value="([^"]+)"', html).group(1)
                        post(doctor, '/patients/D01/visits', {'request_key': visit_key, 'observed_on': '2026-10-18',
                            'risk_factors_status': 'denied', 'summary': 'Синтетический визит врача', 'wellbeing': 'same'})
                        for incomplete in (False, True):
                            html = get(doctor, '/demo/D01')
                            assignment_key = re.search(r'name="assignment_key" value="([^"]+)"', html).group(1)
                            version = re.search(r'name="form_version_id" value="([^"]+)"', html).group(1)
                            html = post(doctor, '/patients/D01/assessment-requests', {
                                'assignment_key': assignment_key, 'form_version_id': version, 'age_years': '35',
                                'age_status': 'known', 'age_basis': 'Синтетический профиль D01, сверено для теста'})
                            task = re.search(r'href="/assessments/([0-9a-f]+)"', html).group(1)
                            assert 'Шкала депрессии, тревоги и стресса' in get(patient, '/assessments/' + task)
                            answers = {'form_version_id': version, **{f'answer_{i}': str(i % 4) for i in range(1, 43)}}
                            if incomplete:
                                answers['answer_21'] = ''
                            receipt = post(patient, '/assessments/' + task, answers)
                            assert 'Анкета отправлена врачу' in receipt and 'Депрессивные симптомы:' not in receipt
                            post(patient, '/assessments/' + task, answers)
                            assessment_tasks.append(task)
                        decision_page = get(doctor, '/patients/D01/decisions')
                        decision_key = re.search(r'name="request_key" value="([^"]+)"', decision_page).group(1)
                        post(doctor, '/patients/D01/decisions', {'request_key':decision_key,'kind':'therapy_change',
                            'therapy_reference': reference()['version'],
                            'aviandr_conclusion':'insufficient_data','aviandr_basis':'Синтетика: препарат не выбран, данные неполны',
                            **{'note_'+area['id']: 'Синтетика: требует проверки врачом' for area in reference()['review_areas']},
                            'content':'Синтетический план после просмотра','basis':'Вымышленный визит',
                            'uncertainties':'Профессиональная проверка правил не выполнена'})
                        drafts = json.loads(get(doctor, '/api/patients/D01/decisions'))['decisions']
                        proposal = drafts[0]
                        assert json.loads(get(patient, '/api/patients/D01/decisions'))['decisions'] == []
                        post(doctor, '/patients/D01/decisions/'+proposal['id']+'/confirm',
                            {'version':str(proposal['version']),'decision':'approved','rationale':'Просмотрено на синтетике','reviewed':'yes'})
                    assert report_id in get(patient) and report_id in get(doctor, '/demo/D01')
                    for browser in (doctor, patient):
                        clinical = json.loads(get(browser, '/api/patients/D01/history'))['entries']
                        assert len(clinical) == 2 and clinical_id in [e['id'] for e in clinical]
                        assert {e['kind'] for e in clinical} == {'visit', 'self_report'}
                        assert 'Синтетическое нежелательное явление' in get(browser, '/demo/D01')
                    assert 'Демо 01' in get(doctor) and 'Демо 02' not in get(doctor)
                    measured = json.loads(get(doctor, '/api/patients/D01/assessments'))['assessments']
                    assert len(measured) == 2
                    complete = next(r for r in measured if r['completeness'] == 'complete')
                    missing = next(r for r in measured if r['completeness'] == 'incomplete')
                    assert complete['scores'] == {'depression': 21, 'anxiety': 19, 'stress': 23}
                    assert missing['scores'] is None and missing['answers'][20] is None
                    assert complete['source_sha256'] == '5d3fa16c44edd0be88dc0448d0a129f706e0d9ef5954d8e7b932291b2fe33c86'
                    receipts = json.loads(get(patient, '/api/patients/D01/assessments'))['assessments']
                    assert len(receipts) == 2 and all(set(r) == {'request_id','requested_at','recorded_at','form_version_id'} for r in receipts)
                    for task in assessment_tasks:
                        receipt = get(patient, '/assessments/' + task)
                        assert 'Анкета отправлена врачу' in receipt and 'scores' not in receipt and 'answers' not in receipt
                    for browser in (doctor, patient):
                        try:
                            get(browser, '/api/patients/D02')
                            raise AssertionError('Foreign patient was accessible')
                        except HTTPError as error:
                            assert error.code == 404
                    for browser in (doctor, patient):
                        actions = json.loads(get(browser, '/api/patients/D01/decisions'))['decisions']
                        assert len(actions) == 1 and actions[0]['decision'] == 'approved'
                        assert 'Синтетический план после просмотра' in get(browser, '/patients/D01/decisions')
                    assert 'input_snapshot' not in json.loads(get(patient, '/api/patients/D01/decisions'))['decisions'][0]
                    assert 'therapy_review' not in json.loads(get(patient, '/api/patients/D01/decisions'))['decisions'][0]['payload']
                    assert len(json.loads(get(doctor, '/api/patients/D01/decisions'))['decisions'][0]['payload']['therapy_review']['unresolved']) == 8
                    result.append({'manual_decision_preserved': True, 'restart_round': round_number, 'health': status, 'shared_report': True,
                                   'foreign_denied': True, 'shared_clinical_history': True,
                                   'doctor_assessments_preserved': True, 'patient_scores_hidden': True})
                finally:
                    process.terminate(); process.wait(timeout=10)
        subprocess.run(command + ['worker', '--once'], cwd=ROOT, check=True)
        with sqlite3.connect(path) as db:
            assert db.execute('SELECT count(*) FROM patients').fetchone()[0] == 6
            assert db.execute("SELECT count(*) FROM outbox_events WHERE status='processed' AND topic='demo.patient_created.v1'").fetchone()[0] == 6
            assert db.execute("SELECT count(*) FROM outbox_events WHERE status='processed' AND topic='routine.self_report.v1'").fetchone()[0] == 1
            assert db.execute('SELECT count(*) FROM routine_notifications WHERE ready_at IS NOT NULL AND delivered_at IS NULL').fetchone()[0] == 1
            assert db.execute('SELECT count(*) FROM event_receipts').fetchone()[0] == 6
            assert db.execute('SELECT count(*) FROM relationship_checks').fetchone()[0] == 1
            assert db.execute('SELECT count(*) FROM clinical_entries').fetchone()[0] == 2
            assert db.execute('SELECT count(*) FROM self_reports').fetchone()[0] == 1
            assert db.execute('SELECT count(*) FROM adverse_events').fetchone()[0] == 1
            assert db.execute('SELECT count(*) FROM assessments').fetchone()[0] == 2
            assert db.execute('SELECT count(*) FROM assessment_results').fetchone()[0] == 2
            assert db.execute('SELECT count(*) FROM care_actions').fetchone()[0] == 1
            assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        print(json.dumps({'process_restart': result, 'durable_events_after_restart': 7, 'durable_routine_notifications': 1, 'durable_technical_reports': 1,
                          'durable_clinical_entries': 2, 'durable_adverse_events': 1, 'durable_assessments': 2,
                          'integrity': 'ok'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
