"""Historical physician context fixtures; never an application write operation."""
import json
import secrets
from apps.compass.db import now


def historical_context(db, patient_id, doctor_id, form):
    relationship = db.execute('SELECT id FROM care_relationships WHERE patient_id=? AND doctor_id=? AND ends_at IS NULL',
                              (patient_id, doctor_id)).fetchone()[0]
    author = dict(db.execute('SELECT id,role,display_name FROM users WHERE id=?', (doctor_id,)).fetchone())
    payload = {k: v for k, v in form.items() if k != 'request_key'}
    payload['source_author'] = author
    context_id = secrets.token_hex(16)
    db.execute('INSERT INTO clinical_contexts VALUES(?,?,?,?,?,?,?,?)',
               (context_id, patient_id, doctor_id, relationship, payload['observed_on'], now(),
                json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')), secrets.token_hex(32)))
    return context_id
