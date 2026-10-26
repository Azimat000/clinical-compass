"""Durable synthetic jobs, short SQLite claims and fenced publication.

No generator is available by default. A missing implementation is a technical
failure, never a negative risk assessment. Clinical release stays blocked.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import secrets

from . import backend_analyses as analyses
from .db import now, transaction

TOPIC = 'backend.data_changed.v1'
MAX_ATTEMPTS = 3
LEASE_SECONDS = 90  # Greater than the model adapter's hard 60-second deadline.


def settings(db):
    # The running service may still use schema015; importing new code is harmless.
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='backend_job_settings'").fetchone():
        return None
    row = db.execute('SELECT * FROM backend_job_settings WHERE id=1').fetchone()
    return row if row and row['enabled'] else None


def fingerprint(db):
    config = settings(db)
    if config is None:
        return None
    # Lazy import avoids the model -> analyses dependency cycle.
    from . import backend_model, backend_extraction, backend_risk_rules
    return {'jobs_version': 'backend-jobs-v1', 'generation_version': config['generation_version'],
            'model': 'deepseek-flash', 'adapter': backend_model.PROMPT_VERSION,
            'system_sha256': hashlib.sha256(backend_model.SYSTEM.encode()).hexdigest(),
            'extraction': backend_extraction.VERSION,
            'risk_rules': backend_risk_rules.release()['engine_sha256']}


def schedule(db, value):
    if not db.in_transaction:
        raise RuntimeError('Job must share the analysis transaction')
    if settings(db) is not None and value['status'] == 'queued':
        db.execute('INSERT OR IGNORE INTO backend_jobs(run_id,state,lane,available_at,created_at) VALUES(?,?,?,?,?)',
                   (value['run_id'], 'pending', 'risk' if value['operation'] == 'risk' else 'generation', now(), now()))


def ready_data(db, event):
    """Outbox handler: coalesce data events by exact current snapshot and physician."""
    if settings(db) is None:
        return
    payload = json.loads(event['payload_json'])
    user = {'id': payload['doctor_id'], 'role': 'doctor'}
    try:
        relationship = analyses.authorize(db, user, event['aggregate_id'])
    except analyses.AnalysisError:
        return  # Revoked event is not reassigned to a new physician.
    if relationship != payload['relationship_id']:
        return
    try:
        raw = analyses.capture(db, event['aggregate_id'], relationship)
    except analyses.AnalysisError:
        # Keep intent in outbox with its bounded retries; never discard on failure.
        raise RuntimeError('snapshot_unavailable') from None
    key = hashlib.sha256(('auto-risk:' + raw).encode()).hexdigest()[:32]
    analyses.create(db, user, event['aggregate_id'],
                    {'contract_version': '1.0', 'operation': 'risk', 'request_key': key})


def _identity(db, job):
    return dict(db.execute('SELECT * FROM analysis_runs WHERE id=?', (job['run_id'],)).fetchone())


def _stale(db, run, reason):
    value = analyses._latest(db, run['id'])
    if value['status'] != 'stale':
        value.update(status='stale', stale_reason=reason, revision=value['revision'] + 1, updated_at=now())
        analyses._append(db, value)


def _current(db, run):
    """Executed under the publication write lock, using database identity again."""
    try:
        user = {'id': run['actor_id'], 'role': 'doctor'}
        relationship = analyses.authorize(db, user, run['patient_id'])
        if relationship != run['relationship_id']:
            return False
        return analyses.read(db, user, run['patient_id'], run['id'])['status'] != 'stale'
    except analyses.AnalysisError:
        return False


def _terminal(db, run, code):
    value = analyses._latest(db, run['id'])
    if value['status'] in ('queued', 'running'):
        value.update(status='failed', revision=value['revision'] + 1, updated_at=now(), result=None,
                     errors=[{'code': code, 'message': 'Анализ недоступен из-за технической ошибки; оценка риска не получена.',
                              'retryable': False}])
        analyses._append(db, value)


def claim(db, lane='all'):
    if lane not in ('all', 'risk', 'generation'):
        raise ValueError('invalid lane')
    with transaction(db):
        if settings(db) is None:
            return None
        # Reclaim expired processes. Old tokens can never publish after reclamation.
        expired = db.execute("SELECT * FROM backend_jobs WHERE state='running' AND lease_until<=?", (now(),)).fetchall()
        for job in expired:
            db.execute("UPDATE backend_job_attempts SET finished_at=?,outcome='expired',error_code='lease_expired' WHERE token=? AND outcome='running'", (now(), job['token']))
            exhausted = job['attempts'] >= MAX_ATTEMPTS
            db.execute("UPDATE backend_jobs SET state=?,token=NULL,lease_until=NULL,last_error='lease_expired' WHERE run_id=?",
                       ('done' if exhausted else 'pending', job['run_id']))
            if exhausted:
                _terminal(db, _identity(db, job), 'lease_expired')
        clause = '' if lane == 'all' else ' AND lane=?'
        params = (now(),) if lane == 'all' else (now(), lane)
        job = db.execute("SELECT * FROM backend_jobs WHERE state='pending' AND available_at<=?" + clause +
                         " ORDER BY CASE lane WHEN 'risk' THEN 0 ELSE 1 END,created_at,run_id LIMIT 1", params).fetchone()
        if job is None:
            return None
        run = _identity(db, job)
        if not _current(db, run):
            _stale(db, run, 'Данные, связь, источник или версия исполнения изменились; нужен новый запуск.')
            db.execute("UPDATE backend_jobs SET state='done',last_error='stale' WHERE run_id=?", (run['id'],))
            return {'skipped': True}
        value = analyses._latest(db, run['id'])
        if value['status'] not in ('queued', 'running'):
            db.execute("UPDATE backend_jobs SET state='done' WHERE run_id=?", (run['id'],))
            return {'skipped': True}
        if value['status'] == 'queued':
            value.update(status='running', revision=value['revision'] + 1, updated_at=now())
            analyses._append(db, value)
        token = secrets.token_hex(16)
        attempt = job['attempts'] + 1
        lease = (datetime.now(timezone.utc) + timedelta(seconds=LEASE_SECONDS)).isoformat(timespec='microseconds')
        db.execute("UPDATE backend_jobs SET state='running',attempts=?,token=?,lease_until=? WHERE run_id=?", (attempt, token, lease, run['id']))
        db.execute('INSERT INTO backend_job_attempts VALUES(?,?,?,?,NULL,?,NULL)', (run['id'], attempt, token, now(), 'running'))
        raw = db.execute('SELECT payload_json FROM analysis_input_snapshots WHERE id=?', (run['snapshot_id'],)).fetchone()[0]
        return {'run': run, 'token': token, 'attempt': attempt, 'snapshot': json.loads(raw)}


def unavailable(operation, snapshot):
    # BE07/10/12 provide the real, source-gated implementations in later slices.
    from .backend_model import ModelError
    raise ModelError('operation_unavailable')


def execute(operation, snapshot):
    from . import backend_risk_rules
    return backend_risk_rules.execute(operation, snapshot)


def finish(db, claim_value, outcome=None, error=None):
    with transaction(db):
        run = claim_value['run']
        job = db.execute('SELECT * FROM backend_jobs WHERE run_id=?', (run['id'],)).fetchone()
        if (job['state'] != 'running' or job['token'] != claim_value['token']
                or job['lease_until'] <= now()):
            return False
        if settings(db) is None or not _current(db, run):
            _stale(db, run, 'Данные, доступ или версия исполнения изменились во время анализа.')
            outcome_code, error = 'stale', 'stale'
        elif error:
            outcome_code = 'failed' if job['attempts'] >= MAX_ATTEMPTS else 'retry'
        else:
            value = analyses._latest(db, run['id'])
            try:
                # SAVEPOINT: validator or INSERT failure cannot leave partial results.
                db.execute('SAVEPOINT publication')
                analyses.advance_in_job(db, run, value, outcome)
                db.execute('RELEASE publication')
            except Exception:
                db.execute('ROLLBACK TO publication')
                db.execute('RELEASE publication')
                error = 'invalid_result'
                outcome_code = 'failed' if job['attempts'] >= MAX_ATTEMPTS else 'retry'
            else:
                outcome_code = 'done'
        if outcome_code == 'failed':
            _terminal(db, run, error)
        retry_at = (datetime.now(timezone.utc) + timedelta(seconds=2 ** job['attempts'])).isoformat(timespec='microseconds')
        db.execute('UPDATE backend_jobs SET state=?,available_at=?,token=NULL,lease_until=NULL,last_error=? WHERE run_id=?',
                   ('pending' if outcome_code == 'retry' else 'done', retry_at, error, run['id']))
        db.execute('UPDATE backend_job_attempts SET finished_at=?,outcome=?,error_code=? WHERE token=?',
                   (now(), outcome_code, error, claim_value['token']))
        return True


def process_one(db, lane='all', executor=None):
    work = claim(db, lane)
    if work is None:
        return False
    if work.get('skipped'):
        return True
    # No database write lock across network or generator work.
    try:
        outcome = (executor or execute)(work['run']['operation'], work['snapshot'])
    except Exception as exc:
        # Never store provider bodies, clinical text, exception strings or secrets.
        from .backend_model import ModelError
        code = exc.code if isinstance(exc, ModelError) and exc.code in {
            'operation_unavailable', 'timeout', 'transport_error', 'budget_exceeded', 'input_too_large'} else 'executor_error'
        finish(db, work, error=code)
    else:
        finish(db, work, outcome=outcome)
    return True


def cancel(db, user, patient_id, run_id):
    with transaction(db):
        analyses.read(db, user, patient_id, run_id)  # Live role, relationship and identity.
        job = db.execute('SELECT * FROM backend_jobs WHERE run_id=?', (run_id,)).fetchone()
        if job and job['state'] in ('pending', 'running'):
            _terminal(db, _identity(db, job), 'cancelled')
            db.execute("UPDATE backend_jobs SET state='cancelled',token=NULL,lease_until=NULL,last_error='cancelled' WHERE run_id=?", (run_id,))
            if job['token']:
                db.execute("UPDATE backend_job_attempts SET finished_at=?,outcome='cancelled',error_code='cancelled' WHERE token=?", (now(), job['token']))
            from . import access
            access.audit(db, user['id'], 'analysis.cancelled', run_id)
        return analyses.read(db, user, patient_id, run_id)
