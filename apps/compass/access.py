"""Opaque sessions and recipient-bound invitations. No clinical actions."""
from datetime import datetime, timedelta, timezone
import hashlib
import re
import secrets
from werkzeug.security import check_password_hash, generate_password_hash
from .db import now, transaction

COOKIE = 'compass_session'
CHALLENGE_COOKIE = 'compass_login'
SESSION_HOURS = 8
IDLE_MINUTES = 30
# Same expensive check for unknown IDs; no public user registration.
DUMMY_HASH = generate_password_hash(secrets.token_urlsafe(32), method='scrypt:32768:8:1')


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def future(**kwargs):
    return (datetime.now(timezone.utc) + timedelta(**kwargs)).isoformat(timespec='microseconds')


def audit(db, actor, event, entity):
    db.execute('INSERT INTO audit_entries(actor_id,event,entity_id,occurred_at,metadata_json) VALUES(?,?,?,?,?)',
               (actor, event, entity, now(), '{}'))


def login_challenge(db):
    token = secrets.token_urlsafe(32)
    with transaction(db):
        db.execute('DELETE FROM login_challenges WHERE expires_at<=?', (now(),))
        db.execute('INSERT INTO login_challenges VALUES(?,?)', (digest(token), future(minutes=10)))
    return token


def matches_token(expected, supplied):
    """Reject malformed browser input before the constant-time ASCII comparison."""
    return (isinstance(expected, str) and isinstance(supplied, str)
            and re.fullmatch(r'[A-Za-z0-9_-]{43}', expected) is not None
            and re.fullmatch(r'[A-Za-z0-9_-]{43}', supplied) is not None
            and secrets.compare_digest(expected, supplied))


def consume_challenge(db, cookie, form):
    if not matches_token(cookie, form):
        return False
    with transaction(db):
        return db.execute('DELETE FROM login_challenges WHERE token_hash=? AND expires_at>?',
                          (digest(cookie), now())).rowcount == 1


def authenticate(db, user_id, password, address, previous_token=''):
    """Persistent fixed-window limits per account and IP; no IP/password in audit."""
    subjects = [digest('account:' + user_id), digest('address:' + address)]
    stamp = now()
    with transaction(db):
        for subject in subjects:
            row = db.execute('SELECT * FROM login_limits WHERE subject_hash=?', (subject,)).fetchone()
            if row and row['window_end'] > stamp and row['attempts'] >= 10:
                return None, 'limited'
        # Reserve an attempt before checking the password, also across processes.
        for subject in subjects:
            db.execute('''INSERT INTO login_limits VALUES(?,1,?) ON CONFLICT(subject_hash) DO UPDATE SET
                       attempts=CASE WHEN window_end<=? THEN 1 ELSE attempts+1 END,
                       window_end=CASE WHEN window_end<=? THEN excluded.window_end ELSE window_end END''',
                       (subject, future(minutes=15), stamp, stamp))
    user = db.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
    valid = check_password_hash((user['password_hash'] if user and user['password_hash'] else DUMMY_HASH), password)
    if not valid or not user or user['disabled']:
        return None, 'invalid'
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    with transaction(db):
        # Recheck current account state under the write lock.
        current = db.execute('SELECT * FROM users WHERE id=? AND disabled=0', (user_id,)).fetchone()
        if not current or current['password_hash'] != user['password_hash']:
            return None, 'invalid'
        if previous_token:
            db.execute('UPDATE sessions SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL',
                       (now(), digest(previous_token)))
        db.execute('INSERT INTO sessions(token_hash,user_id,expires_at,csrf_token,last_seen_at) VALUES(?,?,?,?,?)',
                   (digest(token), user_id, future(hours=SESSION_HOURS), csrf, now()))
        audit(db, user_id, 'auth.login', user_id)
    return token, None


def resolve_session(db, token):
    if not token or len(token) > 128:
        return None
    stamp = now()
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=IDLE_MINUTES)).isoformat(timespec='microseconds')
    with transaction(db):
        row = db.execute('''SELECT u.id,u.role,u.display_name,s.csrf_token FROM sessions s JOIN users u ON u.id=s.user_id
            WHERE s.token_hash=? AND s.revoked_at IS NULL AND s.expires_at>?
            AND s.last_seen_at>? AND s.csrf_token IS NOT NULL AND u.disabled=0''', (digest(token), stamp, cutoff)).fetchone()
        if row:
            db.execute('UPDATE sessions SET last_seen_at=? WHERE token_hash=?', (stamp, digest(token)))
    return row


def revoke_session(db, token, user_id):
    with transaction(db):
        db.execute('UPDATE sessions SET revoked_at=? WHERE token_hash=?', (now(), digest(token)))
        audit(db, user_id, 'auth.logout', user_id)


def visible_patient(db, user, patient_id):
    return db.execute('''SELECT p.* FROM patients p WHERE p.id=? AND (
        (?='patient' AND p.user_id=?) OR (?='doctor' AND EXISTS (
        SELECT 1 FROM care_relationships r WHERE r.patient_id=p.id AND r.doctor_id=?
        AND r.ends_at IS NULL AND r.starts_at<=?)))''',
        (patient_id, user['role'], user['id'], user['role'], user['id'], now())).fetchone()


def invite(db, doctor_id, patient_id):
    token = secrets.token_urlsafe(32)
    with transaction(db):
        p = db.execute('''SELECT p.id,p.user_id FROM patients p JOIN users u ON u.id=p.user_id
            WHERE p.id=? AND u.role='patient' AND u.disabled=0 AND NOT EXISTS (
            SELECT 1 FROM care_relationships WHERE patient_id=p.id AND ends_at IS NULL)''', (patient_id,)).fetchone()
        if not p:
            return None
        db.execute('INSERT INTO care_invitations VALUES(?,?,?,?,?,?,NULL,NULL)',
                   (digest(token), patient_id, doctor_id, p['user_id'], now(), future(hours=24)))
        audit(db, doctor_id, 'care.invitation_created', patient_id)
    return token


def accept_invite(db, patient_user_id, token):
    if not token or len(token) > 128:
        return False
    with transaction(db):
        row = db.execute('''SELECT i.* FROM care_invitations i JOIN patients p ON p.id=i.patient_id
            JOIN users d ON d.id=i.doctor_id JOIN users u ON u.id=p.user_id
            WHERE i.token_hash=? AND p.user_id=? AND i.recipient_user_id=p.user_id AND i.consumed_at IS NULL AND i.revoked_at IS NULL
            AND i.expires_at>? AND d.disabled=0 AND d.role='doctor' AND u.disabled=0''',
            (digest(token), patient_user_id, now())).fetchone()
        if not row or db.execute('SELECT 1 FROM care_relationships WHERE patient_id=? AND ends_at IS NULL', (row['patient_id'],)).fetchone():
            return False
        relationship = secrets.token_hex(16)
        db.execute('INSERT INTO care_relationships VALUES(?,?,?,?,NULL)',
                   (relationship, row['patient_id'], row['doctor_id'], now()))
        db.execute('UPDATE care_invitations SET consumed_at=? WHERE token_hash=?', (now(), digest(token)))
        # All competing offers become unusable; no implicit doctor reassignment.
        db.execute('UPDATE care_invitations SET revoked_at=? WHERE patient_id=? AND consumed_at IS NULL AND revoked_at IS NULL',
                   (now(), row['patient_id']))
        audit(db, patient_user_id, 'care.invitation_accepted', relationship)
    return True


def seed_accounts(db):
    """Explicit local CLI only; random credentials printed once, never committed."""
    credentials = []
    with transaction(db):
        if not db.execute('SELECT 1 FROM patients').fetchone():
            raise ValueError('Run seed-demo first')
        identities = [('doctor-demo', 'doctor', 'Демо врач', None),
                      ('doctor-other', 'doctor', 'Другой демо врач', None)]
        identities += [('patient-' + p['id'], 'patient', 'Демо пациент ' + p['id'], p['id'])
                       for p in db.execute('SELECT id FROM patients WHERE user_id IS NULL ORDER BY id')]
        for uid, role, label, pid in identities:
            if db.execute('SELECT 1 FROM users WHERE id=?', (uid,)).fetchone():
                continue
            password = secrets.token_urlsafe(18)
            db.execute('INSERT INTO users VALUES(?,?,?,?,0)',
                       (uid, role, label, generate_password_hash(password, method='scrypt:32768:8:1')))
            if pid:
                db.execute('UPDATE patients SET user_id=? WHERE id=? AND user_id IS NULL', (uid, pid))
            audit(db, uid, 'demo.account_created', uid)
            credentials.append({'login': uid, 'password': password})
    return credentials
