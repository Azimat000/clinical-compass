"""Durable UI update coordinator; reads never enqueue or call a provider."""
import hashlib
import json
import time

from . import backend_analyses as analyses, backend_jobs, backend_snapshot, decisions
from .db import now, transaction

_last_tick = 0.0
MESSAGES = {
    'waiting_diagnosis': 'Нужно актуальное решение врача по диагнозу с кодом.',
    'quality_blocked': 'Автоматический модельный анализ ожидает допуска качества. Сохранённые результаты доступны.',
    'source_unavailable': 'Источники недоступны или требуют обновления. Новый анализ не запущен.',
    'scope_unavailable': 'Возраст или область применения требуют уточнения.',
    'queued': 'Обновление поставлено в очередь.',
    'unchanged': 'Новых данных для обновления нет.',
    'unavailable': 'Автообновление временно недоступно; повтор будет выполнен сервером.',
}


def admitted():
    from . import backend_packet_pipeline as packets
    try:
        q = json.loads(packets.QUALITY.read_text())
        return q.get('pass') is True and q.get('runtime_sha256') == backend_snapshot.digest(packets.release())
    except (OSError, ValueError, TypeError):
        return False


def view(db, patient_id, relationship):
    rows = db.execute('SELECT operation,status,updated_at,run_id FROM backend_ui_update_cursors '
                      'WHERE patient_id=? AND relationship_id=?', (patient_id, relationship))
    values = []
    for row in rows:
        value = dict(row)
        message = MESSAGES.get(row['status'], MESSAGES['unavailable'])
        if row['run_id']:
            run = db.execute('SELECT actor_id FROM analysis_runs WHERE id=?', (row['run_id'],)).fetchone()
            current = analyses.read(db, {'id': run['actor_id'], 'role': 'doctor'}, patient_id, row['run_id'])
            state = current['status']
            message = {'ready': 'Обновление завершено.', 'stale': 'Появились новые данные; сервер обновит предложение.',
                'running': 'Автоматический анализ выполняется.', 'failed': 'Автоматическое обновление не выполнено.',
                'insufficient_data': 'Для обновления нужны дополнительные сведения.',
                'unsupported': 'Случай вне области применения.'}.get(state, message)
        value['message'] = message
        values.append(value)
    return values


def _save(db, patient, relationship, operation, fingerprint, status, run_id=None):
    db.execute('''INSERT INTO backend_ui_update_cursors
        (patient_id,relationship_id,operation,fingerprint,status,run_id,updated_at)
        VALUES(?,?,?,?,?,?,?) ON CONFLICT(patient_id,relationship_id,operation)
        DO UPDATE SET fingerprint=excluded.fingerprint,status=excluded.status,
                      run_id=excluded.run_id,updated_at=excluded.updated_at''',
        (patient, relationship, operation, fingerprint, status, run_id, now()))


def synchronize(db, user, patient, operation, quality):
    with transaction(db):
        relationship = analyses.authorize(db, user, patient)
        try:
            raw = json.loads(analyses.capture(db, patient, relationship, operation=operation))
        except analyses.AnalysisError:
            _save(db, patient, relationship, operation, 'unavailable', 'source_unavailable')
            return
        # Own diagnosis receipts and pending plan drafts are not new symptoms.
        # Clinical history, source/runtime versions and day remain dependencies.
        evidence = dict(raw)
        if operation == 'diagnosis':
            evidence.pop('diagnosis_review', None)
        fingerprint = backend_snapshot.digest(evidence)
        old = db.execute('SELECT * FROM backend_ui_update_cursors WHERE patient_id=? '
                         'AND relationship_id=? AND operation=?', (patient, relationship, operation)).fetchone()
        if old and old['fingerprint'] == fingerprint and old['status'] == 'queued':
            return
        state, _ = analyses.age_scope(db, patient)
        if state:
            status = 'scope_unavailable'
        elif operation == 'plan' and not (raw.get('care_plan_input', {}).get('review_fresh')
                and raw['care_plan_input'].get('review', {}).get('diagnosis')
                and raw['care_plan_input'].get('condition')):
            status = 'waiting_diagnosis'
        elif operation == 'diagnosis' and not quality:
            status = 'quality_blocked'
        else:
            # Snapshot + relationship + operation is a stable idempotency key,
            # surviving process restart and independent of browser tabs.
            request_key = hashlib.sha256(decisions.canonical(
                ['ui-auto-v1', relationship, operation, fingerprint]).encode()).hexdigest()[:32]
            value = analyses.create(db, user, patient, {'contract_version': '1.0',
                'operation': operation, 'request_key': request_key})
            _save(db, patient, relationship, operation, fingerprint, 'queued', value['run_id'])
            return
        if not old or old['fingerprint'] != fingerprint or old['status'] != status:
            _save(db, patient, relationship, operation, fingerprint, status)


def tick(db):
    global _last_tick
    if time.monotonic() - _last_tick < 10 or backend_jobs.settings(db) is None:
        return
    _last_tick = time.monotonic()
    quality = admitted()
    rows = db.execute('''SELECT r.patient_id,r.id,r.doctor_id FROM care_relationships r
        JOIN patients p ON p.id=r.patient_id JOIN users u ON u.id=r.doctor_id
        WHERE r.ends_at IS NULL AND r.starts_at<=? AND p.synthetic=1 AND u.disabled=0
        ORDER BY r.patient_id''', (now(),)).fetchall()
    for row in rows:
        for operation in ('diagnosis', 'plan'):
            try:
                synchronize(db, {'id': row['doctor_id'], 'role': 'doctor'}, row['patient_id'], operation, quality)
            except Exception:
                # No clinical text or provider exceptions in coordinator logs.
                with transaction(db):
                    _save(db, row['patient_id'], row['id'], operation, 'unavailable', 'unavailable')
