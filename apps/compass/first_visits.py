"""Versioned physician notes before diagnosis; no screening or decision engine."""
from datetime import date
import hashlib
import json
import re
import secrets
from . import access, records
from .db import now, transaction

PROTOCOL = 'first-visit-s17b-v1'
FIELDS = {
    'complaints': ('V02', 'Жалобы своими словами'),
    'course': ('V03', 'Начало, течение и длительность'),
    'impact': ('V04', 'Влияние на повседневную жизнь'),
    'history': ('V05', 'Прежние эпизоды, помощь и эффект'),
    'other_states': ('V06', 'Другие психические проявления: сведения врача'),
    'medications': ('V07', 'Фактический приём препаратов, вещества и реакции'),
    'somatic': ('V08', 'Соматические и неврологические обстоятельства'),
    'safety': ('V09', 'Сведения о безопасности: запись врача'),
    'acute': ('V10', 'Внезапные или острые телесные жалобы'),
    'followup': ('V12', 'Повторный приём: изменения и выполнение плана'),
}
SOURCES = {'patient': 'Со слов пациента', 'doctor': 'Наблюдение врача', 'document': 'Из документа'}


class Error(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def text(values, key, limit=2000):
    try:
        return records.text_field(values, key, limit)
    except records.RecordError as error:
        raise Error(str(error)) from None


def observed(value):
    try:
        day = date.fromisoformat(value)
        if day.year < 1900 or day > records.today():
            raise ValueError()
        return day.isoformat()
    except ValueError:
        raise Error('Дата наблюдения должна быть с 1900 года и не позднее сегодняшней.') from None


def validate(values):
    day = observed(text(values, 'observed_on', 10))
    kind = text(values, 'visit_kind', 20)
    if kind not in ('first', 'repeat'):
        raise Error('Выберите первый или повторный приём.')
    try:
        age = records.validate({k: values.get(k, '') for k in
            ('observed_on', 'age_status', 'age_years', 'birth_date', 'age_detail')})['age']
    except records.RecordError as error:
        raise Error(str(error)) from None
    age_source = text(values, 'age_source', 20)
    age_basis = text(values, 'age_basis', 1000)
    if age_source not in SOURCES or (age['status'] != 'unknown' and not age_basis):
        raise Error('Для возраста выберите источник; известные или противоречивые сведения требуют основания.')
    payload = {'observed_on': day, 'visit_kind': kind, 'age': age,
               'age_source': age_source, 'age_basis': age_basis, 'fields': {}}
    for code, (_, label) in FIELDS.items():
        status = text(values, code + '_status', 20) or 'unknown'
        detail = text(values, code + '_text')
        source = text(values, code + '_source', 20) or 'patient'
        basis = text(values, code + '_basis', 1000)
        field_day = observed(text(values, code + '_on', 10) or day)
        if status not in records.STATUSES or source not in SOURCES:
            raise Error('Проверьте состояние и источник: ' + label)
        if (status in ('known', 'conflicting') and not detail) or (status in ('unknown', 'denied') and detail):
            raise Error(label + ': при наличии или противоречии нужен текст; для неизвестного или отрицания оставьте описание пустым.')
        if status != 'unknown' and not basis:
            raise Error('Укажите основание сведений: ' + label)
        payload['fields'][code] = {'status': status, 'text': detail, 'source': source,
                                   'basis': basis, 'observed_on': field_day}
    payload['not_collected'] = values.get('not_collected') == 'yes'
    if payload['fields']['complaints']['status'] == 'unknown' and not payload['not_collected']:
        raise Error('Запишите жалобы либо отметьте, что сведения пока не собраны.')
    payload['documented_facts'] = text(values, 'documented_facts', 4000)
    payload['document_basis'] = text(values, 'document_basis', 1000)
    if payload['documented_facts'] and not payload['document_basis']:
        raise Error('Укажите документ и дату для документированных врачебных фактов.')
    payload['action_draft'] = text(values, 'action_draft', 4000)
    return payload


def require_doctor(db, user, patient_id):
    if user['role'] != 'doctor':
        raise Error('Первый приём ведёт врач. Самоотчёт доступен в вашей карточке.', 403)
    patient = access.visible_patient(db, user, patient_id)
    if patient is None:
        raise Error('Карточка недоступна.', 404)
    return patient


def history(db, user, patient_id):
    require_doctor(db, user, patient_id)
    return [{**dict(row), 'payload': json.loads(row['payload_json'])} for row in db.execute(
        'SELECT * FROM first_visit_versions WHERE patient_id=? ORDER BY rowid DESC', (patient_id,))]


def save(db, user, patient_id, visit_id, values):
    require_doctor(db, user, patient_id)
    # Document fields live on the documents screen. An ordinary visit submission
    # inherits them from its exact base version, including an idempotent retry.
    base_row = db.execute('SELECT payload_json FROM first_visit_versions WHERE visit_id=? AND patient_id=? AND revision=?',
                          (visit_id, patient_id, values.get('base_revision', ''))).fetchone()
    inherited = {key: json.loads(base_row['payload_json']).get(key, '') if base_row else ''
                 for key in ('documented_facts', 'document_basis')}
    payload = validate({**inherited, **values})
    retry = text(values, 'request_key', 32)
    if not re.fullmatch('[0-9a-f]{32}', retry):
        raise Error('Обновите форму перед сохранением.')
    try:
        base = int(text(values, 'base_revision', 10))
    except ValueError:
        raise Error('Обновите версию приёма.') from None
    state = text(values, 'state', 20)
    if state not in ('draft', 'completed'):
        raise Error('Выберите сохранение черновика или завершение записи.')
    canonical = json.dumps({'payload': payload, 'base': base, 'state': state}, ensure_ascii=False, sort_keys=True)
    key = hashlib.sha256(f'{user["id"]}:{patient_id}:{visit_id}:{retry}'.encode()).hexdigest()
    with transaction(db):
        patient = require_doctor(db, user, patient_id)
        relationship = db.execute('''SELECT r.id FROM care_relationships r JOIN users u ON u.id=r.doctor_id
            WHERE r.patient_id=? AND r.doctor_id=? AND r.ends_at IS NULL AND r.starts_at<=? AND u.disabled=0''',
            (patient_id, user['id'], now())).fetchone()
        if not relationship or patient['synthetic'] != 1:
            raise Error('Нужна действующая связь врача с синтетическим пациентом.', 409)
        previous = db.execute('SELECT * FROM first_visit_versions WHERE request_key=?', (key,)).fetchone()
        if previous:
            saved = json.dumps({'payload': json.loads(previous['payload_json']), 'base': previous['revision'] - 1,
                                'state': previous['state']}, ensure_ascii=False, sort_keys=True)
            if saved != canonical:
                raise Error('Эта отправка уже сохранена с другим содержимым. Прежняя запись сохранена.', 409)
            return previous['visit_id']
        latest = db.execute('SELECT * FROM first_visit_versions WHERE visit_id=? ORDER BY revision DESC LIMIT 1', (visit_id,)).fetchone()
        if latest and latest['patient_id'] != patient_id:
            raise Error('Приём недоступен.', 404)
        if (latest and (latest['revision'] != base or latest['state'] == 'completed')) or (not latest and (base != 0 or visit_id != 'new')):
            raise Error('Приём изменился или завершён. Откройте сохранённую версию; ваш ввод показан ниже.', 409)
        actual_id = secrets.token_hex(16) if not latest else visit_id
        db.execute('INSERT INTO first_visit_versions VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            (secrets.token_hex(16), actual_id, base + 1, patient_id, user['id'], relationship['id'], now(),
             PROTOCOL, state, json.dumps(payload, ensure_ascii=False, sort_keys=True), key))
        access.audit(db, user['id'], 'first_visit.' + state, actual_id)
        return actual_id


def form_values(item):
    p = item['payload']
    values = {k: p[k] for k in ('observed_on', 'visit_kind', 'age_source', 'age_basis', 'documented_facts', 'document_basis', 'action_draft')}
    values.update(age_status=p['age']['status'], age_years=p['age']['years'] if p['age']['years'] is not None else '',
                  birth_date=p['age']['birth_date'] or '', age_detail=p['age']['detail'] or '',
                  not_collected='yes' if p['not_collected'] else '', base_revision=str(item['revision']))
    for code, fact in p['fields'].items():
        for suffix, key in [('status', 'status'), ('text', 'text'), ('source', 'source'), ('basis', 'basis'), ('on', 'observed_on')]:
            values[code + '_' + suffix] = fact[key]
    return values


def save_documents(db, user, patient_id, visit_id, values):
    """Change only document notes of a draft; the same version/retry guards apply."""
    require_doctor(db, user, patient_id)
    try:
        revision = int(text(values, 'base_revision', 10))
    except ValueError:
        raise Error('Обновите версию приёма.') from None
    base = next((row for row in history(db, user, patient_id)
                 if row['visit_id'] == visit_id and row['revision'] == revision), None)
    if base is None:
        raise Error('Версия приёма недоступна.', 404)
    if base['state'] != 'draft':
        raise Error('Завершённая запись закрыта для правок.', 409)
    form = form_values(base)
    form.update({key: values.get(key, '') for key in ('documented_facts', 'document_basis', 'request_key')})
    form['state'] = 'draft'
    save(db, user, patient_id, visit_id, form)
    return db.execute('SELECT id FROM first_visit_versions WHERE visit_id=? AND patient_id=? AND revision=?',
                      (visit_id, patient_id, revision + 1)).fetchone()['id']
