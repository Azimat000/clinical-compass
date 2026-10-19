"""Durable local outbox. No medical rules or external notifications."""
from datetime import datetime, timedelta, timezone
import json
from uuid import uuid4

from .db import now, transaction


def enqueue(db, topic, aggregate_id, payload):
    if not db.in_transaction:
        raise RuntimeError('Enqueue must share the data transaction')
    event_id = str(uuid4())
    stamp = now()
    db.execute('INSERT INTO outbox_events(id,topic,aggregate_id,payload_json,created_at,available_at) VALUES(?,?,?,?,?,?)',
               (event_id, topic, aggregate_id, json.dumps(payload, ensure_ascii=False), stamp, stamp))
    return event_id


def record_demo_receipt(db, event):
    # A technical receipt is not delivery to a doctor or a clinical response.
    db.execute('INSERT OR IGNORE INTO event_receipts VALUES(?,?,?)', (event['id'], 'demo_receipt_v1', now()))


def ready_routine_report(db, event):
    from .notifications import ready_report
    ready_report(db, event)


HANDLERS = {'demo.patient_created.v1': record_demo_receipt,
            'routine.self_report.v1': ready_routine_report}


def process_one(db, handlers=None):
    handlers = HANDLERS if handlers is None else handlers
    with transaction(db):
        event = db.execute("SELECT * FROM outbox_events WHERE status='pending' AND available_at<=? ORDER BY created_at,id LIMIT 1", (now(),)).fetchone()
        if event is None:
            return False
        attempt = event['attempts'] + 1
        attempted_at = now()
        db.execute('SAVEPOINT handler')
        try:
            handlers[event['topic']](db, event)
        except Exception as exc:
            db.execute('ROLLBACK TO handler')
            db.execute('RELEASE handler')
            retry_at = (datetime.now(timezone.utc) + timedelta(seconds=min(2 ** attempt, 60))).isoformat(timespec='microseconds')
            outcome = 'dead' if attempt >= 5 else 'retry'
            # Persist only an exception class; payload/medical text is never logged.
            db.execute('UPDATE outbox_events SET attempts=?,status=?,available_at=?,last_error=? WHERE id=?',
                       (attempt, 'dead' if outcome == 'dead' else 'pending', retry_at, type(exc).__name__, event['id']))
            error = type(exc).__name__
        else:
            db.execute('RELEASE handler')
            db.execute("UPDATE outbox_events SET status='processed',processed_at=?,attempts=attempts+1,last_error=NULL WHERE id=?", (now(), event['id']))
            outcome, error = 'processed', None
        db.execute('INSERT INTO outbox_attempts VALUES(?,?,?,?,?)',
                   (event['id'], attempt, attempted_at, outcome, error))
    return True
