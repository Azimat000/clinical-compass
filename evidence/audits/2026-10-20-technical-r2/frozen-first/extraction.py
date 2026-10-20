"""Literal, conservative candidates. No clinical rules or automatic chart writes."""
import hashlib
import json
import re
import secrets
from datetime import date
from . import access, decisions
from .db import now, transaction

VERSION = 'literal-v2'
MAX_BYTES = 24000
ASSERTIONS = ('present', 'negated', 'unknown', 'conflicting', 'suspected', 'considered',
              'historical', 'patient_reported', 'stopped', 'listed', 'incomplete', 'invalid', 'third_party', 'cancelled_proposal', 'not_due')
ASSERTION_LABELS = dict(zip(ASSERTIONS, ('Указано', 'Явно отрицается', 'Неизвестно', 'Противоречие', 'Предположение', 'Обсуждается', 'В прошлом', 'Со слов пациента', 'Отменено в источнике', 'В списке', 'Неполно', 'Некорректно', 'О другом человеке', 'Отменённый проект', 'Срок ещё не наступил')))
FIELDS = {
    'age_years': 'Возраст', 'event_date': 'Дата записи/события', 'diagnosis': 'Диагноз в источнике',
    'medication': 'Упоминание препарата', 'dose': 'Доза в источнике',
    'frequency_per_day': 'Кратность в сутки', 'medication_allergy': 'Лекарственная аллергия',
    'pregnancy_status': 'Беременность', 'lactation_status': 'Грудное вскармливание',
    'symptom': 'Жалоба/симптом', 'self_harm_report': 'Высказывание о самоповреждении',
    'concomitant_medications': 'Сопутствующие лекарства', 'medication_start': 'Начало приёма',
    'received_date': 'Дата получения', 'historical_self_harm_report': 'Прошлое высказывание о самоповреждении',
    'third_party_self_harm_report': 'Высказывание о другом человеке', 'medication_use': 'Фактический приём',
    'current_medications': 'Текущие лекарства', 'current_prescriptions': 'Текущие назначения',
    'current_complaints': 'Текущие жалобы', 'current_condition': 'Текущее состояние',
    'tablet_strength': 'Сила таблетки/концентрация', 'allergen': 'Название аллергена',
    'anxiety': 'Тревога в источнике', 'dizziness': 'Головокружение', 'nausea': 'Тошнота',
    'itch': 'Зуд', 'dyspnea': 'Затруднение дыхания', 'diagnosis_text': 'Уточнение диагноза в источнике',
    'sleep_change': 'Изменение сна', 'insomnia_timing': 'Время появления бессонницы',
    'symptom_onset': 'Начало жалоб', 'adverse_event_causality': 'Сведения о причинности НЯ',
    'scale_name': 'Шкала в источнике', 'scale_complete': 'Полнота анкеты в источнике',
    'scale_version': 'Версия формы в источнике', 'plan_change': 'Изменение плана в источнике',
    'adherence_morning': 'Утреннее выполнение', 'adherence_evening': 'Вечернее выполнение',
    'adherence': 'Выполнение в источнике', 'report_schedule': 'Расписание самоотчёта',
    'missing_report_days': 'Дни без самоотчёта',
}
WARNING = ('Кандидаты могут содержать ошибки и пропуски. Не являются диагнозом, назначением или '
           'проверкой критичности. Просмотрите весь исходник; отсутствие кандидата не означает отсутствие риска.')


class ExtractionError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def text_input(value):
    if not isinstance(value, str) or not value.strip():
        raise ExtractionError('Нужен непустой текст.')
    try:
        size = len(value.encode('utf-8'))
    except UnicodeError:
        raise ExtractionError('Нужен корректный UTF-8.') from None
    if size > MAX_BYTES or any(ord(c) < 32 and c not in '\n\r\t' for c in value):
        raise ExtractionError('Текст: не более 24 000 байт UTF-8; управляющие символы запрещены.')
    return value


def upload_text(file):
    if not file.filename.lower().endswith('.txt'):
        raise ExtractionError('Поддерживается только .txt UTF-8. PDF, DOCX, сканы и архивы не поддерживаются.')
    raw = file.stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ExtractionError('Файл больше 24 000 байт.')
    try:
        return text_input(raw.decode('utf-8-sig'))
    except UnicodeError:
        raise ExtractionError('Файл должен быть текстом UTF-8; другие кодировки не определяются автоматически.') from None


def extract(text):
    text_input(text)
    if re.search(r'\d{101}', text):
        raise ExtractionError('Числовой фрагмент длиннее 100 цифр не поддерживается.')
    from .extraction_literals import extract_literals
    return extract_literals(text, FIELDS, VERSION, WARNING)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def save_import(db, user, patient_id, text, key):
    text_input(text)
    if not re.fullmatch(r'[a-f0-9]{32}', key):
        raise ExtractionError('Неверный ключ повтора.')
    result = extract(text)
    with transaction(db):
        relationship = decisions.doctor_relationship(db, user, patient_id)
        previous = db.execute('SELECT * FROM text_imports WHERE request_key=?', (key,)).fetchone()
        if previous:
            if (previous['patient_id'],previous['doctor_id'],previous['source_text']) != (patient_id,user['id'],text):
                raise ExtractionError('Этот ключ уже использован для другого текста.',409)
            return previous['id']
        iid = secrets.token_hex(16)
        db.execute('INSERT INTO text_imports VALUES (?,?,?,?,?,?,?,?,?)',
                   (iid,patient_id,relationship,user['id'],text,hashlib.sha256(text.encode()).hexdigest(),canonical(result),now(),key))
        access.audit(db,user['id'],'extraction.imported',iid)
        return iid


def history(db, patient_id):
    rows = []
    for r in db.execute('SELECT * FROM text_imports WHERE patient_id=? ORDER BY created_at DESC,id', (patient_id,)):
        item = dict(r)
        item['result'] = json.loads(item['result_json'])
        item['reviews'] = [dict(v) for v in db.execute('SELECT * FROM extraction_reviews WHERE import_id=? ORDER BY created_at,id', (r['id'],))]
        rows.append(item)
    return rows


def review(db, user, patient_id, iid, form):
    reason = form.get('reason','').strip()
    quote = form.get('quote','')
    field = form.get('field','')
    assertion = form.get('assertion','')
    disposition = form.get('disposition','')
    value = form.get('value','').strip()
    key = form.get('request_key','')
    if (not reason or len(reason)>1000 or len(value)>500 or len(quote)>2000 or field not in FIELDS
            or assertion not in ASSERTIONS or disposition not in ('accept','correct','reject','add')
            or not re.fullmatch(r'[a-f0-9]{32}',key)):
        raise ExtractionError('Проверьте поле, статус, действие, обоснование и длину ввода.')
    for s in (reason,value,quote):
        if any(ord(c)<32 and c not in '\n\r\t' for c in s):
            raise ExtractionError('Управляющие символы запрещены.')
    with transaction(db):
        relationship = decisions.doctor_relationship(db,user,patient_id)
        source = db.execute('SELECT * FROM text_imports WHERE id=? AND patient_id=? AND relationship_id=?', (iid,patient_id,relationship)).fetchone()
        if not source:
            raise ExtractionError('Импорт недоступен для сверки.',404)
        if not quote or quote not in source['source_text']:
            raise ExtractionError('Основание должно быть точной непустой цитатой из исходника.')
        cid = form.get('candidate_id','')
        original = next((c for c in json.loads(source['result_json'])['candidates'] if c['id']==cid), None)
        if disposition!='add' and (original is None or original['field']!=field):
            raise ExtractionError('Кандидат не найден; для нового факта выберите добавление.')
        if disposition=='accept' and (assertion != original['assertion'] or quote != original['quote'] or value != canonical(original['value'])):
            raise ExtractionError('Для подтверждения сохраните исходные статус, точную цитату и значение JSON. Для изменений выберите исправление.')
        if disposition=='add' and cid:
            raise ExtractionError('Добавление требует пустого номера кандидата.')
        payload = canonical({'candidate_id':cid,'field':field,'assertion':assertion,'value':value,
                             'quote':quote,'reason':reason,'disposition':disposition})
        previous = db.execute('SELECT * FROM extraction_reviews WHERE request_key=?',(key,)).fetchone()
        if previous:
            if (previous['import_id'],previous['doctor_id'],previous['payload_json'])!=(iid,user['id'],payload):
                raise ExtractionError('Этот ключ уже использован для другой сверки.',409)
            return previous['id']
        rid = secrets.token_hex(16)
        db.execute('INSERT INTO extraction_reviews VALUES (?,?,?,?,?,?)',(rid,iid,user['id'],payload,now(),key))
        access.audit(db,user['id'],'extraction.reviewed',rid)
        return rid
