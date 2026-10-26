"""Durable physician API channel for synthetic review episodes, never care orders."""
import re
import secrets

from . import access, backend_analyses as analyses, backend_risk_episodes as episodes, events
from .db import now
from .notifications import authorized

VERSION = 'backend-alerts-v1'
TOPIC = 'backend.risk_alert.v1'
CHANNEL = 'physician_api_v1'


def doctor(db, user):
    row = db.execute('SELECT role,disabled FROM users WHERE id=?', (user['id'],)).fetchone()
    if row is None or row['role'] != 'doctor' or row['disabled']:
        raise analyses.AnalysisError('Недоступно для этой роли.', 403, 'access_denied')


def enqueue_pending(db):
    """Catch up an existing BE08 ledger, in the caller's publication/outbox txn.

    Immutable original recipient only. A revoked link stays undelivered; a new
    relationship does not grant access to the old episode or silently redirect it.
    """
    if not db.in_transaction:
        raise RuntimeError('Alert must share the publication transaction')
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='backend_alerts'").fetchone():
        return
    rows = db.execute('''SELECT e.*,v.revision,v.recorded_at,r.doctor_id FROM backend_risk_episodes e
        JOIN backend_risk_episode_versions v ON v.episode_id=e.id
        JOIN care_relationships r ON r.id=e.relationship_id
        WHERE v.state='open' AND v.revision=(SELECT max(w.revision) FROM backend_risk_episode_versions w WHERE w.episode_id=e.id)
        AND NOT EXISTS(SELECT 1 FROM backend_alerts a WHERE a.episode_id=e.id AND a.episode_revision=v.revision)''').fetchall()
    for row in rows:
        alert_id = secrets.token_hex(16)
        # Transport carries only an opaque alert identifier; never a clinical quote.
        event_id = events.enqueue(db, TOPIC, alert_id, {'alert_id': alert_id})
        stamp = now()
        db.execute('INSERT INTO backend_alerts VALUES(?,?,?,?,?,?,?,?)',
                   (alert_id, row['id'], row['revision'], event_id, row['relationship_id'], row['doctor_id'], row['recorded_at'], stamp))
        access.audit(db, None, 'backend_alert.queued', alert_id)


def deliver(db, event):
    """Actual local channel = durable inbox row, not a claim of browser receipt."""
    row = db.execute('SELECT * FROM backend_alerts WHERE event_id=?', (event['id'],)).fetchone()
    if row is None or not authorized(db, row['recipient_id'], row['relationship_id']):
        raise analyses.AnalysisError('Адресат недоступен.', 409, 'recipient_unavailable')
    stamp = now()
    result = db.execute('''INSERT OR IGNORE INTO deliveries
        (id,event_id,recipient_id,channel,status,attempts,next_attempt_at,delivered_at)
        VALUES(?,?,?,?,'delivered',1,?,?)''',
        (row['id'], row['event_id'], row['recipient_id'], CHANNEL, stamp, stamp))
    if result.rowcount:
        access.audit(db, None, 'backend_alert.delivered', row['id'])


def _row(db, user, alert_id):
    doctor(db, user)
    row = db.execute('''SELECT a.*,e.patient_id FROM backend_alerts a
        JOIN backend_risk_episodes e ON e.id=a.episode_id WHERE a.id=? AND a.recipient_id=?''',
        (alert_id, user['id'])).fetchone()
    if row is None or not authorized(db, user['id'], row['relationship_id']):
        raise analyses.AnalysisError('Сигнал недоступен.', 404, 'not_found')
    return row


def _value(db, row, detail=False, user=None):
    outbox = db.execute('SELECT status,attempts,available_at,last_error FROM outbox_events WHERE id=?', (row['event_id'],)).fetchone()
    delivery = db.execute('SELECT delivered_at FROM deliveries WHERE event_id=? AND recipient_id=? AND channel=?',
                          (row['event_id'], row['recipient_id'], CHANNEL)).fetchone()
    actions = [dict(r) for r in db.execute('SELECT action,actor_id,reason,recorded_at FROM backend_alert_actions WHERE alert_id=? ORDER BY sequence', (row['id'],))]
    value = {key: row[key] for key in ('id','episode_id','episode_revision','created_at','queued_at')}
    # No request keys, recipient credentials, outbox payloads or model secrets.
    value.update(version=VERSION, clinical_ready=False, channel=CHANNEL,
                 delivered_at=delivery['delivered_at'] if delivery else None,
                 state=actions[-1]['action'] if actions else ('delivered' if delivery else ('undelivered' if outbox['status']=='dead' else 'queued')),
                 queue=dict(outbox), actions=actions)
    if detail:
        value['episode'] = episodes.read(db, user, row['patient_id'], row['episode_id'])
        value['attempt_log'] = [dict(r) for r in db.execute('SELECT attempt,attempted_at,outcome,error FROM outbox_attempts WHERE event_id=? ORDER BY attempt', (row['event_id'],))]
    return value


def inbox(db, user, page=1):
    if type(page) is not int or not 1 <= page <= 1000000:
        raise analyses.AnalysisError('Неверная страница.', 400, 'invalid_page')
    with episodes.atomic(db):
        doctor(db, user)
        rows = db.execute('''SELECT a.* FROM backend_alerts a JOIN care_relationships r ON r.id=a.relationship_id
            WHERE a.recipient_id=? AND r.doctor_id=? AND r.ends_at IS NULL AND r.starts_at<=?
            ORDER BY a.queued_at,a.id LIMIT 51 OFFSET ?''', (user['id'], user['id'], now(), (page-1)*50)).fetchall()
        return {'version': VERSION, 'items': [_value(db, r) for r in rows[:50]],
                'page': page, 'next_page': page+1 if len(rows)>50 else None, 'clinical_ready': False}


def read(db, user, alert_id):
    with episodes.atomic(db):
        return _value(db, _row(db, user, alert_id), True, user)


def act(db, user, alert_id, body):
    if type(body) is not dict or set(body) != {'action','expected_revision','reason','request_key'}:
        raise analyses.AnalysisError('Нужны action, expected_revision, reason, request_key.')
    action, revision, reason, key = (body[k] for k in ('action','expected_revision','reason','request_key'))
    if (action not in ('received','seen','processed') or type(revision) is not int or revision<1
            or not isinstance(reason,str) or len(reason)>1000 or '\x00' in reason
            or (action=='processed' and not reason.strip()) or (action!='processed' and reason!='')
            or not isinstance(key,str) or re.fullmatch(r'[a-zA-Z0-9_-]{16,80}',key) is None):
        raise analyses.AnalysisError('Недопустимое действие или основание.')
    with episodes.atomic(db):
        row = _row(db, user, alert_id)
        previous = db.execute('SELECT * FROM backend_alert_actions WHERE request_key=?', (key,)).fetchone()
        if previous:
            if (previous['alert_id'] != alert_id or previous['action'] != action
                    or previous['reason'] != reason or previous['actor_id'] != user['id'] or revision != row['episode_revision']):
                raise analyses.AnalysisError('Ключ уже использован.', 409, 'idempotency_conflict')
            return _value(db, row, True, user)
        if revision != row['episode_revision']:
            raise analyses.AnalysisError('Версия сигнала изменилась.', 409, 'revision_conflict')
        if db.execute('SELECT 1 FROM backend_alert_actions WHERE alert_id=? AND action=?', (alert_id,action)).fetchone():
            raise analyses.AnalysisError('Действие уже сохранено.', 409, 'action_conflict')
        if not db.execute('SELECT 1 FROM deliveries WHERE event_id=? AND recipient_id=? AND channel=? AND status=\'delivered\'',
                          (row['event_id'],user['id'],CHANNEL)).fetchone():
            raise analyses.AnalysisError('Сигнал ещё не доставлен.', 409, 'not_delivered')
        prerequisite = {'seen':'received','processed':'seen'}.get(action)
        if prerequisite and not db.execute('SELECT 1 FROM backend_alert_actions WHERE alert_id=? AND action=?', (alert_id,prerequisite)).fetchone():
            raise analyses.AnalysisError('Сначала подтвердите предыдущее действие.',409,'action_order')
        if action == 'processed':
            # Closing is one atomic physician review decision. It cannot mutate care.
            episodes.close(db,user,row['patient_id'],row['episode_id'],revision,reason,key)
        db.execute('INSERT INTO backend_alert_actions(alert_id,action,actor_id,reason,request_key,recorded_at) VALUES(?,?,?,?,?,?)',
                   (alert_id,action,user['id'],reason,key,now()))
        access.audit(db,user['id'],'backend_alert.'+action,alert_id)
        return _value(db,row,True,user)


def status(db):
    """Local operator metadata only, including revoked/disabled/absent recipients."""
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='backend_alerts'").fetchone():
        return []
    return [{**dict(r), 'recipient_state': 'assigned' if authorized(db,r['recipient_id'],r['relationship_id']) else 'recipient_unavailable'}
            for r in db.execute('''SELECT a.id,a.recipient_id,a.relationship_id,o.status,o.attempts,o.last_error
                FROM backend_alerts a JOIN outbox_events o ON o.id=a.event_id ORDER BY a.queued_at,a.id''')]
