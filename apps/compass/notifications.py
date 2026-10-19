"""Routine report inbox. No risk classifier, external delivery or medical actions."""
from . import access
from .db import now, transaction

TOPIC = 'routine.self_report.v1'


class NotificationError(ValueError):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


def enqueue_report(db, entry_id, patient_id):
    from .events import enqueue
    if not db.in_transaction:
        raise RuntimeError('Report notification must share the report transaction')
    relation = db.execute('''SELECT r.* FROM care_relationships r JOIN users u ON u.id=r.doctor_id
        WHERE r.patient_id=? AND r.ends_at IS NULL AND r.starts_at<=?
        AND u.role='doctor' AND u.disabled=0''', (patient_id, now())).fetchone()
    if relation is None:
        raise NotificationError('Нет активного ведущего врача.')
    event_id = enqueue(db, TOPIC, entry_id, {'entry_id': entry_id})
    db.execute('''INSERT INTO routine_notifications
        (id,entry_id,event_id,relationship_id,recipient_id,created_at)
        VALUES(?,?,?,?,?,?)''', (entry_id, entry_id, event_id, relation['id'], relation['doctor_id'], now()))


def authorized(db, recipient_id, relationship_id):
    return db.execute('''SELECT 1 FROM care_relationships r JOIN users u ON u.id=r.doctor_id
        WHERE r.id=? AND r.doctor_id=? AND r.ends_at IS NULL AND r.starts_at<=?
        AND u.disabled=0 AND u.role='doctor' ''', (relationship_id, recipient_id, now())).fetchone() is not None


def ready_report(db, event):
    row = db.execute('SELECT * FROM routine_notifications WHERE event_id=?', (event['id'],)).fetchone()
    if row is None or not authorized(db, row['recipient_id'], row['relationship_id']):
        # No payload or patient information in the retry log; never retarget an event.
        raise NotificationError('Адресат сейчас недоступен.')
    db.execute('UPDATE routine_notifications SET ready_at=COALESCE(ready_at,?) WHERE id=?', (now(), row['id']))


def inbox(db, user, prepare=True):
    with transaction(db):
        current = db.execute("SELECT role,disabled FROM users WHERE id=?", (user['id'],)).fetchone()
        if current is None or current['disabled'] or current['role'] != 'doctor':
            raise NotificationError('Недоступно для этой роли.', 403)
        rows = db.execute('''SELECT n.*,e.summary,e.patient_id,e.recorded_at,p.code,
                o.status AS queue_status,o.attempts,o.last_error,o.available_at
            FROM routine_notifications n JOIN clinical_entries e ON e.id=n.entry_id
            JOIN patients p ON p.id=e.patient_id JOIN outbox_events o ON o.id=n.event_id
            JOIN care_relationships r ON r.id=n.relationship_id
            WHERE n.recipient_id=? AND r.doctor_id=? AND r.patient_id=e.patient_id
                AND r.ends_at IS NULL AND r.starts_at<=?
            ORDER BY n.created_at DESC,n.id DESC''', (user['id'], user['id'], now())).fetchall()
        items = []
        for row in rows:
            value = dict(row)
            # This only records preparing the authenticated HTML response. It is not
            # proof of browser receipt, reading, or a clinical response.
            if prepare and row['ready_at'] is not None and row['delivered_at'] is None:
                value['delivered_at'] = now()
                db.execute('UPDATE routine_notifications SET delivered_at=? WHERE id=?',
                           (value['delivered_at'], row['id']))
            value['attempt_log'] = db.execute('SELECT * FROM outbox_attempts WHERE event_id=? ORDER BY attempt',
                                             (row['event_id'],)).fetchall()
            items.append(value)
        return items


def mark(db, user, notification_id, action):
    if action not in ('seen', 'acknowledged'):
        raise NotificationError('Неизвестное действие.', 400)
    with transaction(db):
        current = db.execute('SELECT role,disabled FROM users WHERE id=?', (user['id'],)).fetchone()
        if current is None or current['role'] != 'doctor' or current['disabled']:
            raise NotificationError('Недоступно для этой роли.', 403)
        row = db.execute('SELECT * FROM routine_notifications WHERE id=? AND recipient_id=?',
                         (notification_id, user['id'])).fetchone()
        if row is None or not authorized(db, user['id'], row['relationship_id']):
            raise NotificationError('Уведомление недоступно.', 404)
        required = 'delivered_at' if action == 'seen' else 'seen_at'
        if row[required] is None:
            raise NotificationError('Сначала откройте уведомление и отметьте просмотр по порядку.')
        column = action + '_at'
        if row[column] is None:
            db.execute(f'UPDATE routine_notifications SET {column}=? WHERE id=?', (now(), notification_id))
            access.audit(db, user['id'], 'routine_notification.' + action, notification_id)
