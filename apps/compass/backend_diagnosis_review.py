"""Append-only physician diagnoses for synthetic cases; never treatment actions."""
from contextlib import nullcontext
import hashlib
import json
import secrets

from . import access, backend_analyses as analyses, decisions
from .db import now, transaction

VERSION = 'diagnosis-review-v1'
text = lambda limit: {'type': 'string', 'minLength': 1, 'maxLength': limit}
nullable = lambda schema: {'oneOf': [schema, {'type': 'null'}]}
IDENTIFIER = {**text(64), 'pattern': '[a-zA-Z0-9_-]+'}
SCHEMA = {'type': 'object', 'additionalProperties': False, 'properties': {
    'request_key': {**text(32), 'pattern': '[0-9a-f]{32}'},
    'expected_version': {'type': 'integer', 'minimum': 0},
    'snapshot_id': {**text(64), 'pattern': '[0-9a-f]{64}'},
    'action': {'enum': ['accept', 'modify', 'reject', 'manual']},
    'run_id': nullable(IDENTIFIER),
    'analysis_revision': nullable({'type': 'integer', 'minimum': 1}),
    'hypothesis_id': nullable(IDENTIFIER),
    'diagnosis': nullable(text(2000)),
    'diagnosis_code': nullable(text(64)),
    'basis': text(4000), 'uncertainties': text(4000),
    'reviewed': {'type': 'boolean', 'const': True}},
}
SCHEMA['required'] = list(SCHEMA['properties'])


def head(db, patient_id):
    # Old live schema015 remains usable until an explicit service migration.
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='backend_diagnosis_reviews'").fetchone():
        return None
    return db.execute('SELECT * FROM backend_diagnosis_reviews WHERE patient_id=? ORDER BY version DESC LIMIT 1',
                      (patient_id,)).fetchone()


def _digest(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


def _clinical_digest(raw):
    # The row itself changes the dependency head, not the evidence it reviewed.
    value = json.loads(raw)
    value.pop('diagnosis_review', None)
    return _digest(decisions.canonical(value))


def _available(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='backend_diagnosis_reviews'").fetchone():
        raise analyses.AnalysisError('Нужна отдельная миграция копии базы.', 409, 'review_unavailable')


def record(db, user, patient_id, body):
    analyses.validate_schema(body, SCHEMA)
    action = body['action']
    if action == 'manual':
        if any(body[k] is not None for k in ('run_id', 'analysis_revision', 'hypothesis_id')):
            raise analyses.AnalysisError('Ручная запись не является модельным предложением.')
    elif any(body[k] is None for k in ('run_id', 'analysis_revision', 'hypothesis_id')):
        raise analyses.AnalysisError('Укажите точную гипотезу и версию анализа.')
    if action in ('accept', 'reject'):
        if body['diagnosis'] is not None or body['diagnosis_code'] is not None:
            raise analyses.AnalysisError('Для собственного диагноза выберите изменение или ручную запись.')
    elif body['diagnosis'] is None:
        raise analyses.AnalysisError('Нужен собственный текст диагноза врача.')
    with (nullcontext(db) if db.in_transaction else transaction(db)):
        relationship = analyses.authorize(db, user, patient_id)
        _available(db)
        encoded = decisions.canonical(body)
        previous = db.execute('''SELECT * FROM backend_diagnosis_reviews
            WHERE actor_id=? AND patient_id=? AND request_key=?''',
            (user['id'], patient_id, body['request_key'])).fetchone()
        if previous:
            if previous['relationship_id'] != relationship:
                raise analyses.AnalysisError('Связь с врачом изменилась.', 409, 'access_denied')
            if previous['request_json'] != encoded:
                raise analyses.AnalysisError('Повтор содержит другое решение.', 409, 'idempotency_conflict')
            return json.loads(previous['receipt_json'])
        latest = head(db, patient_id)
        version = latest['version'] if latest else 0
        if body['expected_version'] != version:
            raise analyses.AnalysisError('Решение уже изменилось. Обновите сведения.', 409, 'revision_conflict')
        raw = analyses.capture(db, patient_id, relationship)
        if _digest(raw) != body['snapshot_id']:
            raise analyses.AnalysisError('Сведения или источники изменились.', 409, 'stale_inputs')
        state, reason = analyses.age_scope(db, patient_id)
        if state:
            raise analyses.AnalysisError(reason, 409, 'scope_unavailable')
        suggestion = None
        analysis = None
        if action != 'manual':
            from . import backend_diagnosis_service as service, backend_snapshot
            analysis = analyses.read(db, user, patient_id, body['run_id'])
            if (analysis['operation'] != 'diagnosis' or analysis['status'] != 'ready'
                    or analysis['revision'] != body['analysis_revision']
                    or analysis['snapshot_id'] != body['snapshot_id']
                    or not analysis.get('diagnosis_context')):
                raise analyses.AnalysisError('Нужна актуальная точная гипотеза.', 409, 'hypothesis_unavailable')
            if analysis['diagnosis_context']['runtime_sha256'] != backend_snapshot.digest(service.release()):
                raise analyses.AnalysisError('Механизм анализа изменился.', 409, 'hypothesis_unavailable')
            output = analysis['result']['output']
            suggestion = next((h for h in [output['leading'], *output['alternatives']]
                               if h['id'] == body['hypothesis_id']), None)
            if suggestion is None:
                raise analyses.AnalysisError('Гипотеза отсутствует в этой версии.', 409, 'hypothesis_unavailable')
        diagnosis = None if action == 'reject' else {
            'text': suggestion['text'] if action == 'accept' else body['diagnosis'],
            'code': body['diagnosis_code'],
            'origin': 'physician_acceptance' if action == 'accept' else 'physician_authored'}
        receipt = {'version': version + 1, 'id': secrets.token_hex(16), 'patient_id': patient_id,
            'previous_id': latest['id'] if latest else None, 'actor_id': user['id'],
            'relationship_id': relationship, 'recorded_at': now(), 'action': action,
            'status': 'rejected' if action == 'reject' else 'physician_recorded',
            'origin': 'manual' if action == 'manual' else 'model_review',
            'basis': body['basis'], 'uncertainties': body['uncertainties'],
            'snapshot_id': body['snapshot_id'], 'sources': analyses.source_refs(raw),
            'run_id': body['run_id'], 'analysis_revision': body['analysis_revision'],
            'hypothesis_id': body['hypothesis_id'], 'model_suggestion': suggestion,
            'model_context': analysis['diagnosis_context'] if analysis else None,
            'diagnosis': diagnosis, 'review_version': VERSION,
            'clinical_release': 'blocked', 'clinical_ready': False,
            'treatment_applied': False}
        # Frozen manual input uses the same store as generated analyses.
        db.execute('INSERT OR IGNORE INTO analysis_input_snapshots VALUES(?,?,?,?)',
                   (body['snapshot_id'], patient_id, raw, receipt['recorded_at']))
        db.execute('''INSERT INTO backend_diagnosis_reviews
            (id,patient_id,version,previous_id,actor_id,relationship_id,request_key,
             snapshot_id,run_id,analysis_revision,action,request_json,receipt_json,recorded_at)
             VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (receipt['id'], patient_id, receipt['version'], receipt['previous_id'], user['id'],
             relationship, body['request_key'], body['snapshot_id'], body['run_id'],
             body['analysis_revision'], action, encoded, decisions.canonical(receipt), receipt['recorded_at']))
        access.audit(db, user['id'], 'diagnosis.' + action, receipt['id'])
        return receipt


def view(db, user, patient_id, page=1):
    if not db.in_transaction:
        db.execute('BEGIN')
        try:
            value = view(db, user, patient_id, page)
            db.commit()
            return value
        except BaseException:
            db.rollback()
            raise
    relationship = analyses.authorize(db, user, patient_id)
    _available(db)
    latest = head(db, patient_id)
    count = db.execute('SELECT count(*) FROM backend_diagnosis_reviews WHERE patient_id=? AND relationship_id=?',
                       (patient_id, relationship)).fetchone()[0]
    pages = max(1, (count + 49) // 50)
    if type(page) is not int or not 1 <= page <= pages:
        raise analyses.AnalysisError('Страница истории недоступна.', 400, 'invalid_page')
    rows = db.execute('''SELECT receipt_json FROM backend_diagnosis_reviews
        WHERE patient_id=? AND relationship_id=? ORDER BY version DESC LIMIT 50 OFFSET ?''',
        (patient_id, relationship, (page - 1) * 50)).fetchall()
    freshness_error = None
    try:
        raw = analyses.capture(db, patient_id, relationship)
    except analyses.AnalysisError as exc:
        raw = None
        freshness_error = exc.code
    current = None
    if latest and latest['relationship_id'] == relationship:
        receipt = json.loads(latest['receipt_json'])
        frozen = db.execute('SELECT payload_json FROM analysis_input_snapshots WHERE id=?',
                            (latest['snapshot_id'],)).fetchone()[0]
        fresh = raw is not None and _clinical_digest(frozen) == _clinical_digest(raw)
        current = {'receipt': receipt, 'fresh': fresh,
                   'diagnosis': receipt['diagnosis'] if fresh else None}
    return {'review_version': VERSION, 'head_version': latest['version'] if latest else 0,
            'snapshot_id': _digest(raw) if raw is not None else None,
            'freshness_error': freshness_error, 'current': current,
            'history': [json.loads(r[0]) for r in rows], 'page': page, 'page_count': pages,
            'clinical_release': 'blocked', 'clinical_ready': False}
