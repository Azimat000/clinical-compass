"""Versioned physician notes before diagnosis; no screening or decision engine."""
from datetime import date
import hashlib
import json
import re
import secrets
from . import access, records
from .db import now, transaction

PROTOCOL = 'physician-visit-s51-v2'
NOTE_SCHEMA = 'outpatient-v1'
TEXT_EDITOR = 'text-only-v1'
FIELDS = {
    'complaints': ('V02', 'Жалобы'),
    'course': ('V03', 'Анамнез заболевания: начало и течение'),
    'impact': ('V04', 'Влияние на повседневную жизнь'),
    'history': ('V05', 'Анамнез заболевания: прежние эпизоды'),
    'other_states': ('V06', 'Другие психические проявления: сведения врача'),
    'medications': ('V07', 'Фактический приём препаратов, вещества и реакции'),
    'somatic': ('V08', 'Соматические и неврологические обстоятельства'),
    'safety': ('V09', 'Сведения о безопасности: запись врача'),
    'acute': ('V10', 'Внезапные или острые телесные жалобы'),
    'followup': ('V12', 'Изменения с прошлого приёма'),
    'life_history': ('V13', 'Анамнез жизни'),
    'family_history': ('V14', 'Семейный анамнез'),
    'allergies': ('V15', 'Аллергии и непереносимость'),
    'mental_status': ('V16', 'Психический статус'),
    'physical_status': ('V17', 'Объективные данные осмотра'),
    'conclusion': ('V18', 'Заключение врача о текущем состоянии'),
}
LEGACY_FIELDS = tuple(FIELDS)[:10]
STATIC_FIELDS = ('history', 'life_history', 'family_history', 'somatic', 'allergies')
CURRENT_FIELDS = ('complaints', 'followup', 'course', 'impact', 'mental_status',
                  'physical_status', 'other_states', 'safety', 'acute', 'conclusion')
DOCTOR_FIELDS = ('mental_status', 'physical_status', 'other_states', 'safety', 'acute', 'conclusion')
FIELDS = {code: FIELDS[code] for code in (*CURRENT_FIELDS[:4], *STATIC_FIELDS, *CURRENT_FIELDS[4:], 'medications')}
SOURCES = {'patient': 'Со слов пациента', 'doctor': 'Наблюдение врача', 'document': 'Из документа',
           'physician_note': 'Запись врача'}


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
    schema = text(values, 'note_schema', 30)
    if schema and schema != NOTE_SCHEMA:
        raise Error('Обновите форму приёма.')
    modern = schema == NOTE_SCHEMA
    kind = text(values, 'visit_kind', 20)
    if kind not in ('first', 'repeat'):
        raise Error('Выберите первый или повторный приём.')
    age_on = observed(text(values, 'age_observed_on', 10) or day)
    if age_on > day:
        raise Error('Дата сведений о возрасте не может быть позже приёма.')
    try:
        age = records.validate({**{k: values.get(k, '') for k in
            ('age_status', 'age_years', 'birth_date', 'age_detail')}, 'observed_on': age_on})['age']
    except records.RecordError as error:
        raise Error(str(error)) from None
    age_source = text(values, 'age_source', 20)
    age_basis = text(values, 'age_basis', 1000)
    if age_source not in SOURCES or (age['status'] != 'unknown' and not age_basis):
        raise Error('Для возраста выберите источник; известные или противоречивые сведения требуют основания.')
    payload = {'observed_on': day, 'visit_kind': kind, 'age': age,
               'age_source': age_source, 'age_basis': age_basis, 'fields': {}}
    if modern or 'age_observed_on' in values:
        payload['age_observed_on'] = age_on
    if modern:
        payload['note_schema'] = schema
    if modern or 'wellbeing' in values:
        wellbeing = text(values, 'wellbeing', 20) or 'unknown'
        if wellbeing not in records.WELLBEING:
            raise Error('Выберите динамику состояния: хуже, без изменений, лучше или не оценено.')
        payload['wellbeing'] = wellbeing
    for code, (_, label) in FIELDS.items():
        if code == 'medications' and modern and code + '_status' not in values:
            continue
        if not modern and code not in LEGACY_FIELDS and code + '_status' not in values:
            continue
        status = text(values, code + '_status', 20) or 'unknown'
        detail = text(values, code + '_text')
        if modern and status == 'auto':
            status = 'known' if detail else 'unknown'
        source = text(values, code + '_source', 20) or ('doctor' if modern and code in DOCTOR_FIELDS else 'patient')
        basis = text(values, code + '_basis', 1000)
        if modern and status != 'unknown' and not basis:
            basis = {'patient': 'Беседа на приёме', 'doctor': 'Запись врача на приёме'}.get(source, '')
        field_day = observed(text(values, code + '_on', 10) or day)
        if modern and field_day > day:
            raise Error('Дата сведений не может быть позже приёма: ' + label)
        if status not in records.STATUSES or source not in SOURCES:
            raise Error('Проверьте состояние и источник: ' + label)
        if (status in ('known', 'conflicting') and not detail) or (status in ('unknown', 'denied') and detail):
            raise Error(label + ': при наличии или противоречии нужен текст; для неизвестного или отрицания оставьте описание пустым.')
        if status != 'unknown' and not basis:
            raise Error('Укажите основание сведений: ' + label)
        payload['fields'][code] = {'status': status, 'text': detail, 'source': source,
                                   'basis': basis, 'observed_on': field_day}
    payload['not_collected'] = (payload['fields']['complaints']['status'] == 'unknown') if modern else values.get('not_collected') == 'yes'
    if not modern and payload['fields']['complaints']['status'] == 'unknown' and not payload['not_collected']:
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
    # Keep fields omitted by the current UI from their exact base version,
    # including document notes and retired action notes, also on a retry.
    base_row = db.execute('SELECT payload_json FROM first_visit_versions WHERE visit_id=? AND patient_id=? AND revision=?',
                          (visit_id, patient_id, values.get('base_revision', ''))).fetchone()
    base_payload = json.loads(base_row['payload_json']) if base_row else {}
    inherited = {key: base_payload.get(key, '')
                 for key in ('documented_facts', 'document_basis', 'action_draft')}
    # The retired medication section remains in old records, outside the new editor.
    for suffix, key in [('status', 'status'), ('text', 'text'), ('source', 'source'), ('basis', 'basis'), ('on', 'observed_on')]:
        if 'medications' in base_payload.get('fields', {}):
            inherited['medications_' + suffix] = base_payload['fields']['medications'][key]
    working = {**inherited, **values}
    editor_mode = text(values, 'editor_mode', 30)
    if editor_mode:
        if editor_mode != TEXT_EDITOR:
            raise Error('Обновите форму приёма.')
        working = editor_metadata(db, patient_id, base_payload, working)
    payload = validate(working)
    if editor_mode:
        payload['editor_mode'] = editor_mode
    attach_provenance(db, patient_id, working, payload)
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
        if fact.get('carried_from'):
            values[code + '_from'] = fact['carried_from']['version_id']
    for key in ('note_schema', 'wellbeing', 'age_observed_on', 'editor_mode'):
        if key in p:
            values[key] = p[key]
    if p.get('age_carried_from'):
        values['age_from'] = p['age_carried_from']['version_id']
    return values


def display_text(field):
    return 'Явно отрицает.' if field['status'] == 'denied' and not field['text'] else field['text']


def editor_values(values):
    """Expose a prior explicit denial as ordinary editable text, not an empty field."""
    values = dict(values)
    for code in (*CURRENT_FIELDS, *STATIC_FIELDS):
        if values.get(code + '_status') == 'denied' and not values.get(code + '_text'):
            values[code + '_text'] = 'Явно отрицает.'
    return values


def editor_metadata(db, patient_id, base, values):
    """Reconstruct omitted metadata from exact stored versions, never hidden form data."""
    values = dict(values)
    day = observed(text(values, 'observed_on', 10))

    def origin(code):
        if base:
            return base
        token = text(values, code + '_from', 32)
        if not token:
            return {}
        row = db.execute('SELECT payload_json FROM first_visit_versions WHERE id=? AND patient_id=? AND state=?',
                         (token, patient_id, 'completed')).fetchone()
        if not row:
            raise Error('Исходная запись недоступна. Откройте форму заново.', 409)
        return json.loads(row['payload_json'])

    for code in (*CURRENT_FIELDS, *STATIC_FIELDS):
        keys = [code + '_' + suffix for suffix in ('status', 'source', 'basis', 'on')]
        if all(key in values for key in keys):
            continue  # Full attributed submissions, including document edits, keep their semantics.
        previous = origin(code).get('fields', {}).get(code)
        detail = text(values, code + '_text')
        if previous and detail == display_text(previous):
            values[code + '_text'] = previous['text']
            defaults = {suffix: previous[key] for suffix, key in
                        [('status', 'status'), ('source', 'source'), ('basis', 'basis'), ('on', 'observed_on')]}
        else:
            defaults = {'status': 'conflicting' if detail and previous and previous['status'] == 'conflicting'
                        else 'known' if detail else 'unknown', 'source': 'physician_note', 'on': day,
                        'basis': ('Уточнено врачом на текущем приёме' if previous else 'Запись врача на приёме') if detail else ''}
        for suffix, value in defaults.items():
            values.setdefault(code + '_' + suffix, value)
    if 'age_basis' not in values:
        previous = origin('age')
        old = form_values({'payload': previous, 'revision': 0}) if previous else {}
        if previous:
            old['age_observed_on'] = previous.get('age_observed_on', previous['observed_on'])
        age_keys = ('age_status', 'age_years', 'birth_date', 'age_detail', 'age_source', 'age_observed_on')
        unchanged = previous and all(str(values.get(k, '')).strip() == str(old.get(k, '')).strip() for k in age_keys)
        values['age_basis'] = previous['age_basis'] if unchanged else (
            'Возраст записан врачом на приёме' if values.get('age_status', 'unknown') != 'unknown' else '')
    return values


def reference(item):
    return {'version_id': item['id'], 'visit_id': item['visit_id'],
            'revision': item['revision'], 'observed_on': item['payload']['observed_on']}


def initial_values(db, user, patient_id):
    """Only completed visits supply history; current observations never carry forward."""
    patient = require_doctor(db, user, patient_id)
    items = [i for i in history(db, user, patient_id) if i['state'] == 'completed']
    items.sort(key=lambda i: (i['payload']['observed_on'], i['recorded_at']), reverse=True)
    values = {'observed_on': records.today().isoformat(), 'visit_kind': 'repeat' if items else 'first',
              'base_revision': '0', 'age_source': 'patient', 'note_schema': NOTE_SCHEMA, 'wellbeing': 'unknown'}
    for code in STATIC_FIELDS:
        # A modern unknown is an explicit clearing; older empty visits need not erase history.
        source = next((i for i in items if code in i['payload']['fields'] and
                       (i['payload'].get('note_schema') == NOTE_SCHEMA or
                        i['payload']['fields'][code]['status'] != 'unknown')), None)
        if source:
            form = form_values(source)
            values.update({k: v for k, v in form.items() if k.startswith(code + '_')})
            if source['payload']['fields'][code]['status'] != 'unknown':
                values[code + '_from'] = source['id']
            else:
                values.pop(code + '_from', None)
    source = next((i for i in items if i['payload'].get('note_schema') == NOTE_SCHEMA or
                   i['payload']['age']['status'] != 'unknown'), None)
    if source:
        form = form_values(source)
        values.update({k: v for k, v in form.items() if k.startswith('age_') or k == 'birth_date'})
        values['age_observed_on'] = source['payload'].get('age_observed_on', source['payload']['observed_on'])
        if source['payload']['age']['status'] != 'unknown':
            values['age_from'] = source['id']
        else:
            values.pop('age_from', None)
    elif patient['age_status'] != 'unknown':
        values.update(age_status=patient['age_status'], age_years=str(patient['age_years']) if patient['age_years'] is not None else '',
                      birth_date=patient['birth_date'] or '', age_observed_on=patient['created_at'][:10],
                      age_basis='Сохранённые сведения синтетической карточки')
        if patient['age_status'] == 'conflicting':
            values['age_detail'] = 'Сведения карточки о возрасте противоречивы'
    return values


def attach_provenance(db, patient_id, values, payload):
    """Resolve references on the server; never accept client-authored provenance."""
    for code in (*STATIC_FIELDS, 'age'):
        token = text(values, code + '_from', 32)
        if not token:
            continue
        row = db.execute('SELECT * FROM first_visit_versions WHERE id=? AND patient_id=? AND state=?',
                         (token, patient_id, 'completed')).fetchone()
        if not row:
            raise Error('Исходная запись анамнеза недоступна. Откройте форму заново.', 409)
        item = {**dict(row), 'payload': json.loads(row['payload_json'])}
        original = item['payload']
        if code == 'age':
            if (payload['age'] == original['age'] and payload['age_source'] == original['age_source']
                    and payload['age_basis'] == original['age_basis']
                    and payload.get('age_observed_on') == original.get('age_observed_on', original['observed_on'])):
                payload['age_carried_from'] = reference(item)
            continue
        old = original['fields'].get(code)
        if old is None:
            raise Error('В исходной записи нет этого раздела анамнеза.', 409)
        field = payload['fields'][code]
        if all(field[k] == old[k] for k in ('status', 'text', 'source', 'basis', 'observed_on')):
            field['carried_from'] = reference(item)
        elif values.get('editor_mode') != TEXT_EDITOR and field['observed_on'] == old['observed_on'] and (field['text'], field['status']) != (old['text'], old['status']):
            field['observed_on'] = payload['observed_on']
            if (field['source'], field['basis']) == (old['source'], old['basis']):
                field.update(source='doctor', basis='Уточнено врачом на текущем приёме')


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
