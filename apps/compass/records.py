"""Append-only, attributed synthetic records. No scoring or clinical decisions."""
from datetime import date, datetime
import hashlib
import json
import re
import secrets
from zoneinfo import ZoneInfo
from . import access
from .db import now, transaction

FIELDS = {
    'complaints': 'Жалобы',
    'risk_factors': 'Сообщённые факторы риска',
    'concomitant_medications': 'Сопутствующие препараты',
    'adverse_events': 'Нежелательные явления',
}
STATUSES = {'known': 'Есть сведения', 'unknown': 'Неизвестно',
            'denied': 'Явно отрицает', 'conflicting': 'Противоречивые сведения'}
WELLBEING = {'unknown': 'Не указано', 'better': 'Лучше', 'same': 'Без изменений', 'worse': 'Хуже'}


class RecordError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def today():
    return datetime.now(ZoneInfo('Europe/Moscow')).date()


def text_field(form, name, limit):
    value = form.get(name, '')
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 and c not in '\n\r\t' for c in value):
        raise RecordError('Недопустимое значение или слишком длинный текст.')
    return value.strip()


def validate(form):
    try:
        observed = date.fromisoformat(text_field(form, 'observed_on', 10))
        if observed > today() or observed.year < 1900:
            raise ValueError()
    except ValueError:
        raise RecordError('Укажите дату наблюдения с 1900 года, не позднее сегодняшней.') from None
    payload = {'observed_on': observed.isoformat(), 'summary': text_field(form, 'summary', 4000), 'fields': {}}
    for code in FIELDS:
        status = text_field(form, code + '_status', 20) or 'unknown'
        detail = text_field(form, code + '_text', 2000)
        if status not in STATUSES or (status in ('known', 'conflicting') and not detail) or (status in ('unknown', 'denied') and detail):
            raise RecordError('Для имеющихся или противоречивых сведений нужен текст; для «неизвестно» и отрицания оставьте текст пустым.')
        payload['fields'][code] = {'status': status, 'text': detail or None}
    age_status = text_field(form, 'age_status', 20) or 'unknown'
    years, birth, detail = (text_field(form, n, size) for n, size in [('age_years', 3), ('birth_date', 10), ('age_detail', 1000)])
    if age_status not in ('known', 'unknown', 'conflicting'):
        raise RecordError('Проверьте статус возраста.')
    if age_status == 'unknown' and (years or birth or detail):
        raise RecordError('Неизвестный возраст не должен содержать значения.')
    if age_status == 'conflicting' and not detail:
        raise RecordError('Опишите противоречие возраста.')
    if age_status == 'known' and (not (years or birth) or detail):
        raise RecordError('Укажите возраст на дату наблюдения или дату рождения; пояснение противоречий допустимо только при соответствующем статусе.')
    try:
        age = int(years) if years and re.fullmatch(r'[0-9]{1,3}', years) else None
        if years and (age is None or not 0 <= age <= 120):
            raise ValueError()
        born = date.fromisoformat(birth) if birth else None
        if born and (born > observed or born.year < 1900):
            raise ValueError()
        calculated = observed.year - born.year - ((observed.month, observed.day) < (born.month, born.day)) if born else None
        if calculated is not None and not 0 <= calculated <= 120:
            raise ValueError()
    except ValueError:
        raise RecordError('Проверьте возраст (0–120) и дату рождения относительно даты наблюдения.') from None
    # Inconsistent raw values remain visible; never silently choose one of them.
    if age is not None and calculated is not None and age != calculated:
        age_status, detail = 'conflicting', detail or 'Возраст не соответствует дате рождения на дату наблюдения.'
    payload['age'] = {'status': age_status, 'years': age, 'birth_date': birth or None,
                      'calculated_years': calculated, 'detail': detail or None}
    wellbeing = text_field(form, 'wellbeing', 20) or 'unknown'
    if wellbeing not in WELLBEING:
        raise RecordError('Проверьте значение самочувствия.')
    payload['wellbeing'] = wellbeing
    from . import clinical_rules
    try:
        safety = clinical_rules.parse_safety(form)
    except clinical_rules.RuleError as error:
        raise RecordError(str(error), error.status) from None
    if safety is not None:
        payload['medication_safety'] = safety
    return payload


def save(db, user, patient_id, kind, form):
    expected = 'patient' if kind == 'self_report' else 'doctor'
    if user['role'] != expected:
        raise RecordError('Эта функция недоступна вашей роли.', 403)
    payload = validate(form)
    retry = text_field(form, 'request_key', 64)
    if not re.fullmatch(r'[0-9a-f]{32}', retry):
        raise RecordError('Обновите форму перед отправкой.')
    from . import medication_feedback
    feedback = medication_feedback.parse(form) if kind == 'self_report' else None
    key = hashlib.sha256(f'{user["id"]}:{patient_id}:{kind}:{retry}'.encode()).hexdigest()
    with transaction(db):
        # Recheck authorization while holding the write transaction.
        if access.visible_patient(db, user, patient_id) is None:
            raise RecordError('Карточка недоступна.', 404)
        if feedback is not None:
            payload['medication_feedback'] = medication_feedback.resolve(db, patient_id, feedback)
            payload['medication_feedback_plan'] = feedback['plan_id']
            adverse = medication_feedback.adverse_text(payload['medication_feedback'])
            if adverse:
                payload['fields']['adverse_events'] = {'status': 'known', 'text': adverse}
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        available_doctor = db.execute('''SELECT 1 FROM care_relationships r JOIN users u ON u.id=r.doctor_id
                WHERE r.patient_id=? AND r.ends_at IS NULL AND r.starts_at<=? AND u.disabled=0''', (patient_id, now())).fetchone()
        if kind == 'self_report' and not available_doctor and 'medication_safety' not in payload:
            raise RecordError('Сначала установите связь с ведущим врачом.', 409)
        existing = db.execute('SELECT id,payload_json FROM clinical_entries WHERE request_key=?', (key,)).fetchone()
        if existing:
            if existing['payload_json'] != canonical:
                raise RecordError('Эта отправка уже сохранена с другим содержимым. Откройте новую форму.', 409)
            return existing['id']
        if feedback is not None:
            from . import medications
            if medications.base_id(db, patient_id) != feedback['plan_id']:
                raise RecordError('Врач изменил назначения. Ответы остались у вас; откройте новую форму и сверьте препараты.', 409)
        if kind == 'self_report':
            from . import report_drafts
            try:
                report_drafts.check_submission(db, user, patient_id, form)
            except report_drafts.Error as error:
                raise RecordError(str(error), error.status) from None
        entry_id, stamp = secrets.token_hex(16), now()
        encounter_id = entry_id if kind == 'visit' else None
        report_id = entry_id if kind == 'self_report' else None
        if encounter_id:
            db.execute('INSERT INTO encounters(id,patient_id,occurred_at,author_id,narrative,origin) VALUES(?,?,?,?,?,?)',
                       (entry_id, patient_id, payload['observed_on'], user['id'], payload['summary'], 'doctor_visit / ' + entry_id))
        else:
            db.execute('INSERT INTO self_reports VALUES(?,?,?,?,?,?,?)',
                       (entry_id, patient_id, stamp, payload['observed_on'], canonical, key,
                        4 if feedback is not None else 3 if 'medication_safety' in payload else 2))
        db.execute('INSERT INTO clinical_entries VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                   (entry_id, patient_id, user['id'], kind, payload['observed_on'], stamp, payload['summary'], canonical, key, encounter_id, report_id))
        provenance = json.dumps({'entry_id': entry_id, 'actor_id': user['id'], 'role': user['role'],
                                 'origin': kind, 'self_report_id': report_id, 'synthetic': True})
        for code, field in payload['fields'].items():
            db.execute('''INSERT INTO observations(id,patient_id,encounter_id,code,value_json,data_status,observed_at,recorded_at,provenance_json)
                          VALUES(?,?,?,?,?,?,?,?,?)''',
                       (secrets.token_hex(16), patient_id, encounter_id, code,
                        json.dumps(field['text'], ensure_ascii=False) if field['text'] else None,
                        field['status'], payload['observed_on'], stamp, provenance))
            if code == 'adverse_events' and field['status'] in ('known', 'conflicting'):
                db.execute('''INSERT INTO adverse_events(id,patient_id,reported_at,description,review_status,source_entry_id)
                              VALUES(?,?,?,?,'unreviewed',?)''', (secrets.token_hex(16), patient_id, payload['observed_on'], field['text'], entry_id))
        db.execute('''INSERT INTO observations(id,patient_id,encounter_id,code,value_json,data_status,observed_at,recorded_at,provenance_json)
                      VALUES(?,?,?,?,?,?,?,?,?)''', (secrets.token_hex(16), patient_id, encounter_id, 'reported_age',
                      None if payload['age']['status'] == 'unknown' else json.dumps(payload['age'], ensure_ascii=False),
                      payload['age']['status'], payload['observed_on'], stamp, provenance))
        if kind == 'self_report' and available_doctor:
            from .notifications import enqueue_report
            enqueue_report(db, entry_id, patient_id)
        if kind == 'self_report':
            from .clinical_rules import evaluate_safety
            evaluate_safety(db, user, patient_id, entry_id, payload)
            report_drafts.consumed(db, user, patient_id, form)
        access.audit(db, user['id'], 'record.' + kind + '_created', entry_id)
        return entry_id


def history(db, patient_id):
    rows = db.execute('''SELECT e.*,u.display_name FROM clinical_entries e JOIN users u ON u.id=e.actor_id
                        WHERE e.patient_id=? ORDER BY e.observed_on DESC,e.recorded_at DESC,e.id DESC''', (patient_id,)).fetchall()
    return [{**dict(r), 'payload': json.loads(r['payload_json'])} for r in rows]


def warnings(patient, entries):
    """Flag unresolved data disagreement, never infer a clinical risk assessment."""
    result = []
    if patient['age_status'] != 'known':
        result.append('Исходный возраст: ' + STATUSES[patient['age_status']] + '. Взрослая применимость не установлена.')
    # Compare only facts for the SAME observation day. Different dates remain history.
    by_day = {}
    for entry in entries:
        payload = entry['payload']
        day = by_day.setdefault(entry['observed_on'], {})
        for code, field in payload['fields'].items():
            if field['status'] == 'conflicting':
                result.append(f'{entry["observed_on"]}: {FIELDS[code]} — противоречивые сведения ({entry["id"]}).')
            if field['status'] in ('known', 'denied'):
                day.setdefault(code, set()).add((field['status'], field['text']))
        age = payload['age']
        if age['status'] == 'conflicting':
            result.append(f'{entry["observed_on"]}: противоречие возраста — {age["detail"]}')
        elif age['status'] == 'known':
            value = age['years'] if age['years'] is not None else age['calculated_years']
            day.setdefault('age', set()).add(value)
    for day, codes in by_day.items():
        for code, values in codes.items():
            if len(values) > 1:
                result.append(f'{day}: различаются сведения «{FIELDS.get(code, "Возраст") }». Нужно сверить источники; записи сохранены отдельно.')
    return result


def wellbeing_trend(entries):
    """A categorical diary, not a scale, severity estimate or accumulated score."""
    rows = sorted((e for e in entries if e['kind'] == 'self_report'),
                  key=lambda e: (e['observed_on'], e['recorded_at'], e['id']))[-30:]
    levels = {'better': 48, 'same': 96, 'worse': 144, 'unknown': 192}
    return [{'x': 170 + i * 340 / max(1, len(rows) - 1), 'y': levels[e['payload']['wellbeing']],
             'date': e['observed_on'], 'id': e['id'], 'label': WELLBEING[e['payload']['wellbeing']]}
            for i, e in enumerate(rows)]
