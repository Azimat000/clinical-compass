"""Conservative age consistency and explicit, append-only physician reconciliation."""
from datetime import date
import hashlib
import json
import secrets
from . import access, records
from .db import now, transaction


class AgeError(ValueError):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def source_snapshot(db, patient):
    sources = [{'id': 'profile:' + patient['id'], 'observed_on': patient['created_at'][:10],
                'age': {'status': patient['age_status'], 'years': patient['age_years'],
                        'birth_date': patient['birth_date']}}]
    for entry in reversed(records.history(db, patient['id'])):
        if entry['payload']['age']['status'] != 'unknown':
            sources.append({'id': entry['id'], 'actor_id': entry['actor_id'], 'kind': entry['kind'],
                            'observed_on': entry['observed_on'], 'recorded_at': entry['recorded_at'],
                            'age': entry['payload']['age']})
    return canonical(sources)


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def history(db, patient_id):
    return [dict(r) for r in db.execute('SELECT * FROM age_reviews WHERE patient_id=? ORDER BY rowid DESC', (patient_id,))]


def view(db, patient):
    snapshot = source_snapshot(db, patient)
    rows = history(db, patient['id'])
    return {'sources': json.loads(snapshot), 'fingerprint': digest(snapshot), 'reviews': rows,
            'current': rows[0] if rows and rows[0]['sources_json'] == snapshot else None}


def years_on(birth, on):
    return on.year - birth.year - ((on.month, on.day) < (birth.month, birth.day))


def possible_years(source, on):
    """An integer at an earlier observation gives a range; a DOB gives an exact age."""
    age = source['age']
    if age['status'] == 'conflicting':
        raise AgeError('Есть противоречие возраста. Нужна явная сверка ведущим врачом.')
    try:
        observed = date.fromisoformat(source['observed_on'])
        if observed > on:
            raise ValueError()
        birth = date.fromisoformat(age['birth_date']) if age.get('birth_date') else None
        years = age.get('years')
        if birth:
            old = years_on(birth, observed)
            current = years_on(birth, on)
            if birth > observed or birth.year < 1900 or not 0 <= current <= 120 or (years is not None and years != old):
                raise ValueError()
            return {current}
        if years is None:
            if age['status'] == 'known':
                raise ValueError()
            return None
        if age['status'] != 'known' or type(years) is not int or not 0 <= years <= 120:
            raise ValueError()
        delta = years_on(observed, on)
        low = years + delta
        return {low} if (observed.month, observed.day) == (on.month, on.day) else {low, low + 1}
    except (ValueError, TypeError):
        raise AgeError('Возраст или дата рождения в источниках требуют явной сверки ведущим врачом.') from None


def verify(db, patient, years):
    state = view(db, patient)
    if state['current']:
        try:
            expected = years_on(date.fromisoformat(state['current']['birth_date']), records.today())
        except ValueError:
            raise AgeError('Сверка возраста повреждена.') from None
        allowed = {expected}
        token = state['current']['id']
    else:
        allowed = set(range(121))
        for source in state['sources']:
            candidates = possible_years(source, records.today())
            if candidates is not None:
                allowed &= candidates
        token = None
    if years not in allowed:
        raise AgeError('Возраст расходится с известными источниками. Сначала выполните явную сверку возраста.')
    return digest(canonical({'sources': state['fingerprint'], 'review': token}))


def reconcile(db, user, patient_id, form):
    if user['role'] != 'doctor':
        raise AgeError('Сверка возраста доступна только ведущему врачу.', 403)
    try:
        basis = records.text_field(form, 'basis', 2000)
        key = records.text_field(form, 'request_key', 32)
        fingerprint = records.text_field(form, 'sources_fingerprint', 64)
        raw_birth = records.text_field(form, 'birth_date', 10)
        validated = records.validate({'observed_on': records.today().isoformat(), 'age_status': 'known', 'birth_date': raw_birth})
    except records.RecordError as error:
        raise AgeError(str(error), 400) from None
    if not basis or form.get('reviewed_sources') != 'yes' or len(key) != 32 or any(c not in '0123456789abcdef' for c in key):
        raise AgeError('Укажите основание и подтвердите сверку перечисленных источников.', 400)
    if not validated['age']['birth_date']:
        raise AgeError('Укажите сверенную дату рождения.', 400)
    payload = canonical({'birth_date': raw_birth, 'basis': basis, 'sources_fingerprint': fingerprint})
    retry = digest(f'{user["id"]}:{patient_id}:{key}')
    with transaction(db):
        patient = access.visible_patient(db, user, patient_id)
        if patient is None:
            raise AgeError('Карточка недоступна.', 404)
        active = db.execute("SELECT 1 FROM users WHERE id=? AND role='doctor' AND disabled=0", (user['id'],)).fetchone()
        relationship = db.execute('''SELECT id FROM care_relationships WHERE patient_id=? AND doctor_id=?
            AND ends_at IS NULL AND starts_at<=?''', (patient_id, user['id'], now())).fetchone()
        if not active or not relationship or patient['synthetic'] != 1:
            raise AgeError('Нужна действующая связь врача с синтетическим случаем.')
        snapshot = source_snapshot(db, patient)
        if fingerprint != digest(snapshot):
            raise AgeError('Источники возраста изменились. Обновите карточку и сверьте их заново.')
        old = db.execute('SELECT id,payload_json FROM age_reviews WHERE request_key=?', (retry,)).fetchone()
        if old:
            if old['payload_json'] != payload:
                raise AgeError('Эта сверка уже сохранена с другим содержимым.')
            return old['id']
        review_id = secrets.token_hex(16)
        db.execute('INSERT INTO age_reviews VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                   (review_id, patient_id, user['id'], relationship['id'], now(), raw_birth, basis,
                    snapshot, fingerprint, retry, payload))
        access.audit(db, user['id'], 'age.reviewed', review_id)
        return review_id
