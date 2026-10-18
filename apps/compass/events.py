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


HANDLERS = {'demo.patient_created.v1': record_demo_receipt}


def process_one(db, handlers=None):
    handlers = HANDLERS if handlers is None else handlers
    with transaction(db):
        event = db.execute("SELECT * FROM outbox_events WHERE status='pending' AND available_at<=? ORDER BY created_at,id LIMIT 1", (now(),)).fetchone()
        if event is None:
            return False
        db.execute('SAVEPOINT handler')
        try:
            handlers[event['topic']](db, event)
        except Exception as exc:
            db.execute('ROLLBACK TO handler')
            db.execute('RELEASE handler')
            attempts = event['attempts'] + 1
            retry_at = (datetime.now(timezone.utc) + timedelta(seconds=min(2 ** attempts, 60))).isoformat(timespec='microseconds')
            # Persist only an exception class; payload/medical text is never logged.
            db.execute('UPDATE outbox_events SET attempts=?,status=?,available_at=?,last_error=? WHERE id=?',
                       (attempts, 'dead' if attempts >= 5 else 'pending', retry_at, type(exc).__name__, event['id']))
        else:
            db.execute('RELEASE handler')
            db.execute("UPDATE outbox_events SET status='processed',processed_at=?,attempts=attempts+1,last_error=NULL WHERE id=?", (now(), event['id']))
    return True
