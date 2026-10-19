"""Literal, conservative candidates. No clinical rules or automatic chart writes."""
import hashlib
import json
import re
import secrets
from datetime import date
from . import access, decisions
from .db import now, transaction

VERSION = 'literal-v1'
MAX_BYTES = 24000
ASSERTIONS = ('present', 'negated', 'unknown', 'conflicting', 'suspected', 'considered',
              'historical', 'patient_reported', 'stopped', 'listed', 'incomplete', 'invalid', 'third_party')
ASSERTION_LABELS = dict(zip(ASSERTIONS, ('Указано', 'Явно отрицается', 'Неизвестно', 'Противоречие', 'Предположение', 'Обсуждается', 'В прошлом', 'Со слов пациента', 'Отменено в источнике', 'В списке', 'Неполно', 'Некорректно', 'О другом человеке')))
FIELDS = {
    'age_years': 'Возраст', 'event_date': 'Дата записи/события', 'diagnosis': 'Диагноз в источнике',
    'medication': 'Упоминание препарата', 'dose': 'Доза в источнике',
    'frequency_per_day': 'Кратность в сутки', 'medication_allergy': 'Лекарственная аллергия',
    'pregnancy_status': 'Беременность', 'lactation_status': 'Грудное вскармливание',
    'symptom': 'Жалоба/симптом', 'self_harm_report': 'Высказывание о самоповреждении',
    'concomitant_medications': 'Сопутствующие лекарства', 'medication_start': 'Начало приёма',
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
    candidates = []

    def add(field, assertion, value, start, end):
        item = {'field': field, 'assertion': assertion, 'value': value,
                'quote': text[start:end], 'span': {'start': start, 'end': end}}
        if item not in candidates:
            candidates.append(item)

    def scan(pattern, field, transform, flags=re.I):
        for m in re.finditer(pattern, text, flags):
            assertion, value = transform(m)
            add(field, assertion, value, m.start(), m.end())

    def clause(m):
        # Periods in decimal numbers/ICD/date are not sentence boundaries.
        prefix = text[:m.start()]
        suffix = text[m.end():]
        left = list(re.finditer(r'[;\n]|\.(?=\s|$)', prefix))
        right = re.search(r'[;\n]|\.(?=\s|$)', suffix)
        return text[left[-1].end() if left else 0:m.end() + (right.start() if right else len(suffix))].lower()

    scan(r'\b(\d{1,3})\s*(?:лет|года?|л\.)\b', 'age_years', lambda m: ('present', int(m[1])))
    scan(r'возраст\s*[:—-]?\s*(?:неизвестен|не заполнен|не указан)', 'age_years', lambda m: ('unknown', None))
    scan(r'сколько лет\?\s*—\s*(\d{1,3})', 'age_years', lambda m: ('present', int(m[1])))

    def numeric_date(m):
        parts = re.split(r'[./-]', m[0])
        y, mo, d = map(int, parts if len(parts[0]) == 4 else parts[::-1])
        try:
            return 'present', date(y, mo, d).isoformat()
        except ValueError:
            return 'invalid', None
    scan(r'\b(?:\d{4}-\d{2}-\d{2}|\d{2}[./]\d{2}[./]\d{4})\b', 'event_date', numeric_date)
    months = {'января':1,'февраля':2,'марта':3,'апреля':4,'мая':5,'июня':6,'июля':7,'августа':8,'сентября':9,'октября':10,'ноября':11,'декабря':12}
    def word_date(m):
        try:
            return 'present', date(int(m[3]), months[m[2].lower()], int(m[1])).isoformat()
        except ValueError:
            return 'invalid', None
    scan(r'\b(\d{1,2})\s+('+'|'.join(months)+r')\s+(\d{4})(?:\s+года)?', 'event_date', word_date)

    def state(m):
        c = clause(m)
        if re.search(r'неизвест|не помнит|нет подтверждения|не уверен', c):
            return 'unknown'
        if re.search(r'не принимает|не назначал|не упомина|не начинал|отрица|не подтвержд', c):
            return 'negated'
        if re.search(r'отмен[её]н', c):
            return 'stopped'
        if re.search(r'обсужд|рассмотр|вопрос врачу', c):
            return 'considered'
        if re.search(r'ранее|архив|старой|до этого|в прошлом', c):
            return 'historical'
        if re.search(r'подозрев|уточнен|\?', c):
            return 'suspected'
        if re.search(r'со слов|самоотч[её]т|пациент', c):
            return 'patient_reported'
        return 'listed'

    def diagnosis(m):
        s = state(m)
        return (s if s in ('historical', 'suspected', 'unknown', 'negated') else 'present'), m[0].upper() if re.fullmatch(r'[fF]\d{2}(?:\.\d)?', m[0]) else m[0]
    scan(r'\b[Ff]\d{2}(?:\.\d)?\b', 'diagnosis', diagnosis)
    # Named diagnoses only when no code follows in the same clause; no diagnosis from symptoms.
    for m in re.finditer(r'\b(?:ГТР|генерализованное тревожное расстройство|депрессивный эпизод)\b', text, re.I):
        if not re.search(r'\bf\d{2}', clause(m)):
            s, v = diagnosis(m)
            add('diagnosis', s, v, m.start(), m.end())
    scan(r'(?:диагноз\s+(?:не установлен|отсутствует|не вписан)|без установленного диагноза|врачебного диагноза нет)', 'diagnosis', lambda m: ('unknown', None))
    scan(r'\b(?:Авиандр[а]?|препарат\s+[XYZ])\b', 'medication',
         lambda m: (state(m), None if state(m) == 'unknown' else ('Авиандр' if m[0].lower().startswith('авиандр') else 'препарат '+m[0][-1].upper())))

    def dose(m):
        value = float(m[1].replace(',', '.'))
        unit = {'мг':'mg','г':'g','мл':'ml'}[m[2].lower()]
        return ('historical' if state(m) == 'historical' else 'present'), {'value':value, 'unit':unit}
    scan(r'\b(\d+(?:[.,]\d+)?)\s*(мг|мл|г)\b', 'dose', dose)
    scan(r'доз[ау]\s+(?:не помнит|неизвестна)|доза неизвестна', 'dose', lambda m: ('unknown', None))
    scan(r'\b(\d+)\s*раз[а]?\s*(?:в сутки|в день)', 'frequency_per_day', lambda m: ('present', int(m[1])))
    scan(r'один раз в день', 'frequency_per_day', lambda m: ('present', 1))

    def risk(m):
        c = clause(m)
        if re.search(r'неизвест|не заполн|нет сведений|отсутствуют сведения|не сообщает', c):
            return 'unknown', None
        if 'противореч' in c:
            return 'conflicting', None
        if re.search(r'отрица|:\s*нет\b|не беремен', c) and 'не отрица' not in c:
            return 'negated', False
        if re.search(r'подтвержд|:\s*да\b|есть|имеется', c):
            return ('patient_reported' if 'со слов' in c else 'present'), True
        return 'unknown', None
    for field, pattern in (
        ('medication_allergy', r'(?:лекарственная аллергия|аллерги[юяи]\s+на лекарства|сведения об аллергии)'),
        ('pregnancy_status', r'беременность|беременна'),
        ('lactation_status', r'грудно(?:м|е) вскармливани[еи]'),
    ):
        scan(pattern, field, risk)
    # A deliberately small literal vocabulary; unknown variants remain for manual review.
    for pattern, value in [(r'сердцебиение', 'сердцебиение'), (r'сплю хуже|бессонница', 'нарушение сна'),
                           (r'подавленного настроения','сниженное настроение'), (r'усталость','усталость'),
                           (r'тошнота','тошнота'), (r'сыпь','сыпь'), (r'от[её]к губ','отёк губ')]:
        scan(pattern, 'symptom', lambda m, v=value: (('negated' if state(m)=='negated' else 'historical' if state(m)=='historical' else 'present'), v))
    # High-risk wording is flagged as unresolved, never used to assert an emergency or its absence.
    scan(r'причинить себе вред|суицид\w*|самоповрежден\w*', 'self_harm_report', lambda m: ('unknown', None))

    # Multiple incompatible literal values are retained and visibly marked, never silently chosen.
    for field in ('age_years', 'dose'):
        items = [c for c in candidates if c['field'] == field and c['assertion']=='present']
        if len({json.dumps(c['value'], sort_keys=True) for c in items}) > 1:
            for c in items:
                c['assertion'] = 'conflicting'
    candidates.sort(key=lambda c: (c['span']['start'], c['field']))
    for i, c in enumerate(candidates):
        c['id'] = str(i)
    missing = [f for f in FIELDS if not any(c['field']==f for c in candidates)]
    return {'version':VERSION, 'candidates':candidates, 'unextracted_fields':missing, 'warning':WARNING}


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
