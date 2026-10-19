"""Critical inbox and opt-in local console/macOS reserve, without medical mutations."""
from datetime import datetime, timedelta, timezone
import secrets
import select
import subprocess
import sys

from .db import now, transaction
from .notifications import NotificationError, authorized

TOPIC = 'clinical.critical.medication_safety.v1'


def later(seconds):
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(timespec='microseconds')


def log(db, event_id, action, actor=None, detail=''):
    db.execute('INSERT INTO critical_delivery_log(event_id,actor_id,action,recorded_at,detail) VALUES(?,?,?,?,?)',
               (event_id, actor, action, now(), detail))


def ready(db, event):
    row = db.execute('SELECT * FROM critical_events WHERE outbox_event_id=?', (event['id'],)).fetchone()
    if row is None:
        raise NotificationError('Критическое событие отсутствует.')
    # Unassigned/disabled recipients are retained in the operational ledger; no
    # silent retargeting and no error loop that would erase the alert.
    stamp = now()
    result = db.execute('INSERT OR IGNORE INTO critical_delivery(event_id,ready_at,reserve_after) VALUES(?,?,?)',
                        (row['id'], stamp, stamp))
    if result.rowcount:
        log(db, row['id'], 'ready')


def doctor(db, user):
    row = db.execute('SELECT role,disabled FROM users WHERE id=?', (user['id'],)).fetchone()
    if row is None or row['role'] != 'doctor' or row['disabled']:
        raise NotificationError('Недоступно для этой роли.', 403)


def inbox(db, user):
    doctor(db, user)
    return db.execute('''SELECT c.*,d.*,e.recorded_at AS accepted_at,p.code
        FROM critical_events c JOIN critical_delivery d ON d.event_id=c.id
        JOIN clinical_rule_evaluations v ON v.id=c.evaluation_id
        JOIN clinical_entries e ON e.id=v.entry_id JOIN patients p ON p.id=c.patient_id
        JOIN care_relationships r ON r.id=c.relationship_id
        WHERE c.recipient_id=? AND r.doctor_id=? AND r.patient_id=c.patient_id
        AND r.ends_at IS NULL AND r.starts_at<=? ORDER BY c.created_at DESC,c.id''',
        (user['id'], user['id'], now())).fetchall()


def mark(db, user, event_id, action, reaction=''):
    if action not in ('received', 'seen', 'acknowledged', 'reacted'):
        raise NotificationError('Неизвестное действие.', 400)
    reaction = reaction.strip()
    if action == 'reacted' and not 10 <= len(reaction) <= 2000:
        raise NotificationError('Опишите фактическую реакцию врача: от 10 до 2000 символов.', 400)
    with transaction(db):
        doctor(db, user)
        row = db.execute('''SELECT c.*,d.* FROM critical_events c JOIN critical_delivery d ON d.event_id=c.id
            WHERE c.id=? AND c.recipient_id=?''', (event_id,user['id'])).fetchone()
        if row is None or not authorized(db,user['id'],row['relationship_id']):
            raise NotificationError('Событие недоступно.', 404)
        column = action + '_at'
        if row[column] is not None:
            if action == 'reacted' and row['reaction'] != reaction:
                raise NotificationError('Реакция уже сохранена. Историю нельзя перезаписать.')
            return
        required = {'seen':'received_at','acknowledged':'seen_at','reacted':'acknowledged_at'}.get(action)
        if required and row[required] is None:
            raise NotificationError('Сначала подтвердите предыдущее действие.')
        if action == 'reacted':
            db.execute('UPDATE critical_delivery SET reacted_at=?,reaction=? WHERE event_id=?', (now(),reaction,event_id))
        else:
            db.execute(f'UPDATE critical_delivery SET {column}=? WHERE event_id=?', (now(),event_id))
        log(db,event_id,action,user['id'])


def native_dialog():
    """Fixed generic text: no patient data, URL, shell interpolation or credentials."""
    if sys.platform != 'darwin':
        raise RuntimeError('macOS reserve unavailable')
    script = '''display dialog "Синтетическое демо: есть критический сигнал. Откройте кабинет врача Клинического компаса. Это не служба 24/7. Закрытие окна не является реакцией врача." with title "Клинический компас — резерв" buttons {"Сигнал замечен"} default button 1 with icon caution giving up after 20'''
    result = subprocess.run(['/usr/bin/osascript', '-e', script], capture_output=True, text=True, timeout=25, check=True)
    if 'gave up:false' not in result.stdout or 'button returned:Сигнал замечен' not in result.stdout:
        raise TimeoutError('No local operator receipt')


def console_signal():
    """Actual local terminal receipt; refuses redirected stdin or stdout."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise RuntimeError('Interactive local terminal required')
    print('\a\n⚠ КЛИНИЧЕСКИЙ КОМПАС — СИНТЕТИЧЕСКИЙ РЕЗЕРВ', flush=True)
    print('Есть критический сигнал. Откройте кабинет врача. Это не служба 24/7.', flush=True)
    print('Введите SIGNAL в течение 20 секунд, чтобы отметить получение местным оператором.', flush=True)
    if not select.select([sys.stdin], [], [], 20)[0] or sys.stdin.readline().strip() != 'SIGNAL':
        raise TimeoutError('No local operator receipt')


def reserve_one(db, recipient_id, sender=None, channel='macos_dialog'):
    """Separate opt-in process. Lease before external effect; repeats may show twice."""
    with transaction(db):
        user = {'id':recipient_id}
        doctor(db,user)
        rows = inbox(db,user)
        row = next((r for r in rows if r['acknowledged_at'] is None and r['reserve_state'] in ('pending','leased')
                    and r['reserve_after'] <= now()), None)
        if row is None:
            return False
        token = secrets.token_hex(16)
        attempt = row['reserve_attempts'] + 1
        db.execute("UPDATE critical_delivery SET reserve_state='leased',reserve_after=?,reserve_attempts=?,reserve_token=? WHERE event_id=?",
                   (later(35),attempt,token,row['id']))
        log(db,row['id'],'reserve_started',detail=channel + ':' + str(attempt))
    # Never hold a write lock while waiting for an OS dialog. After a crash the
    # lease expires and the same stable event is retried, possibly visibly twice.
    try:
        # Recheck authorization immediately before external action.
        if not authorized(db,recipient_id,row['relationship_id']):
            raise NotificationError('Адресат недоступен.')
        doctor(db,user)
        (sender or native_dialog)()
    except Exception as exc:
        state, action, detail = ('dead' if attempt >= 5 else 'pending'), 'reserve_failed', type(exc).__name__
    else:
        state, action, detail = 'operator_received', 'reserve_operator_received', ''
    with transaction(db):
        current = db.execute('SELECT reserve_token FROM critical_delivery WHERE event_id=?',(row['id'],)).fetchone()
        if current['reserve_token'] == token:
            db.execute('UPDATE critical_delivery SET reserve_state=?,reserve_after=?,reserve_token=NULL WHERE event_id=?',
                       (state,later(min(2**attempt,60)),row['id']))
            log(db,row['id'],action,detail=detail)
        else:
            log(db,row['id'],'reserve_lease_lost',detail=str(attempt))
    return True


def status(db):
    """Local administrative metadata only; never clinical text or patient IDs."""
    return [dict(r) for r in db.execute('''SELECT c.id,c.delivery_state AS original_state,
        o.status AS queue_status,o.attempts,o.last_error,d.ready_at,d.received_at,d.acknowledged_at,d.reacted_at,
        d.reserve_state,d.reserve_attempts,
        CASE WHEN c.recipient_id IS NULL THEN 'unassigned'
             WHEN u.disabled=1 OR r.ends_at IS NOT NULL THEN 'recipient_unavailable'
             ELSE 'assigned' END AS recipient_state
        FROM critical_events c JOIN outbox_events o ON o.id=c.outbox_event_id
        LEFT JOIN critical_delivery d ON d.event_id=c.id LEFT JOIN users u ON u.id=c.recipient_id
        LEFT JOIN care_relationships r ON r.id=c.relationship_id ORDER BY c.created_at''')]
