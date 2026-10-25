"""Source-verified synthetic measurements; computed results are doctor-only."""
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo
import re
import secrets

from . import access, records, ages
from .db import now, transaction

DEFINITION_PATH = Path(__file__).with_name('resources') / 'dass42-ru-v1.json'
SCORING_VERSION = 'dass42-three-sums-v1'


class AssessmentError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def definition(form_id=None):
    path = DEFINITION_PATH
    if form_id and form_id != json.loads(path.read_text())['id']:
        path = next((p for p in sorted(path.parent.glob('*-ru-v*.json'))
                     if json.loads(p.read_text())['id'] == form_id), None)
        if path is None:
            raise AssessmentError('Версия анкеты недоступна.', 409)
    form = json.loads(path.read_text())
    keys = [n for group in form['subscales'].values() for n in group['items']]
    if (not form['items'] or len(form['options']) < 2
            or sorted(keys) != list(range(1, len(form['items']) + 1))):
        raise RuntimeError('Invalid assessment definition')
    return form


def definitions():
    return [definition()] + [definition(json.loads(p.read_text())['id'])
                            for p in sorted(DEFINITION_PATH.parent.glob('*-ru-v*.json'))
                            if p != DEFINITION_PATH]


def policy(form):
    # An assessment recall window is not an obligatory minimum repeat interval.
    return form.get('repeat_policy', {'mandatory_min_interval_days': None,
        'basis': 'В проверенных источниках обязательный минимальный интервал не установлен. '
                 'Врач может предложить анкету раньше; период оценки остаётся прежним.'})


def scoring_version(form):
    return form.get('scoring_version', SCORING_VERSION)


def scale_range(form, subscale):
    return (0, len(subscale['items']) * (len(form['options']) - 1) * subscale.get('multiplier', 1))


def install_form(db):
    """Publish the pinned measurement only for synthetic demo, without fake expert approval."""
    for form in definitions():
        _install_form(db, form)


def _install_form(db, form):
    text = canonical(form)
    digest = hashlib.sha256(text.encode()).hexdigest()
    with transaction(db):
        existing = db.execute('SELECT * FROM catalog_versions WHERE id=?', (form['id'],)).fetchone()
        if existing:
            release = db.execute('SELECT * FROM assessment_form_releases WHERE form_version_id=?', (form['id'],)).fetchone()
            source = db.execute('SELECT * FROM source_versions WHERE id=?', (existing['source_version_id'],)).fetchone()
            if (existing['definition_json'] != text or not release or release['definition_sha256'] != digest
                    or not source or source['sha256'] != form['source']['sha256']):
                raise RuntimeError('Published assessment version changed')
            return
        source_id = form['id'] + '-source'
        db.execute('INSERT INTO source_versions VALUES(?,?,?,?,?,?,?,?,?,?)',
                   (source_id, form.get('source_code', 'SRC19'), form['version'], form['source']['url'], form['source']['sha256'],
                    form['source']['checked_on'], canonical(form['population']), 'verified', 'verified', 'current'))
        db.execute('''INSERT INTO catalog_versions(id,kind,code,version,source_version_id,definition_json,
                    min_age,max_age,age_basis,blocker) VALUES(?,'scale',?,?,?,?,?,?,?,?)''',
                   (form['id'], form['code'], form['version'], source_id, text, form.get('min_age', 18), form.get('max_age', 120), form['population']['project_policy'],
                    'Clinical interpretation/real patient use not enabled; source-verified synthetic measurement only'))
        db.execute('INSERT INTO assessment_form_releases VALUES(?,?,?,?)',
                   (form['id'], digest, 'synthetic_demo', now()))


def available_form(db, form_id):
    form = definition(form_id)
    if form_id != form['id']:
        raise AssessmentError('Версия анкеты недоступна.', 409)
    row = db.execute('''SELECT c.definition_json,c.status,s.sha256,s.rights_status,s.validation_status,s.status source_status,
        r.definition_sha256 FROM assessment_form_releases r JOIN catalog_versions c ON c.id=r.form_version_id
        JOIN source_versions s ON s.id=c.source_version_id WHERE c.id=? AND r.scope='synthetic_demo' ''', (form_id,)).fetchone()
    digest = hashlib.sha256(canonical(form).encode()).hexdigest()
    if (not row or row['definition_json'] != canonical(form) or row['definition_sha256'] != digest
            or row['sha256'] != form['source']['sha256'] or row['status'] == 'retired' or row['source_status'] != 'current'
            or row['rights_status'] != 'verified' or row['validation_status'] != 'verified'):
        raise AssessmentError('Анкета временно недоступна: требуется проверка версии и источника.', 409)
    return form


def score_answers(answers, form):
    """Exact integer arithmetic; never impute, diagnose or apply clinical thresholds."""
    count, maximum = len(form['items']), len(form['options']) - 1
    if len(answers) != count or any(a is not None and (type(a) is not int or not 0 <= a <= maximum) for a in answers):
        raise AssessmentError(f'Нужны {count} ответов: целые значения от 0 до {maximum} либо пропуски.')
    if any(a is None for a in answers):
        return None
    return {code: sum(answers[n - 1] for n in group['items']) * group.get('multiplier', 1)
            for code, group in form['subscales'].items()}


def parse_answers(values, form=None):
    form = form or definition()
    count, maximum = len(form['items']), len(form['options']) - 1
    allowed = {f'answer_{i}' for i in range(1, count + 1)}
    if any(k.startswith('answer_') and k not in allowed for k in values):
        raise AssessmentError('Обнаружен неизвестный пункт анкеты.')
    answers = []
    for i in range(1, count + 1):
        key = f'answer_{i}'
        if hasattr(values, 'getlist') and len(values.getlist(key)) > 1:
            raise AssessmentError('Для каждого пункта допустим только один ответ.')
        value = values.get(key, '')
        if value not in [''] + [str(n) for n in range(maximum + 1)]:
            raise AssessmentError(f'Проверьте ответы: допустимы целые значения от 0 до {maximum} или пропуск.')
        answers.append(None if value == '' else int(value))
    return answers


def request_age_current(db, task):
    patient = db.execute('SELECT * FROM patients WHERE id=?', (task['patient_id'],)).fetchone()
    try:
        return json.loads(task['age_snapshot_json']).get('verification_token') == ages.verify(db, patient, task['age_years'])
    except ages.AgeError:
        return False


def repeat_state(db, patient_id, form, include_pending=True):
    """Patient/instrument scope survives doctor or version changes; server receipt is the anchor."""
    rule = policy(form)
    last = db.execute('''SELECT r.recorded_at FROM assessment_results r
        JOIN assessments a ON a.id=r.assessment_id JOIN catalog_versions c ON c.id=a.scale_version_id
        WHERE a.patient_id=? AND c.code=? ORDER BY r.recorded_at DESC LIMIT 1''', (patient_id, form['code'])).fetchone()
    state = {'allowed': True, 'message': '', 'next_at': None, 'last_at': None, 'pending_id': None}
    if last:
        state['last_at'] = last['recorded_at']
    interval = rule['mandatory_min_interval_days']
    if last and interval is not None:
        due = datetime.fromisoformat(last['recorded_at']) + timedelta(days=interval)
        state.update(next_at=due.isoformat(), last_at=last['recorded_at'])
        if datetime.fromisoformat(now()) < due:
            label = due.astimezone(ZoneInfo('Europe/Moscow')).strftime('%d.%m.%Y %H:%M:%S') + ' МСК'
            state.update(allowed=False, message=f"{form['code']}: повтор доступен с {label}. "
                         f"После отправки должно пройти {interval} суток. {rule['basis']}")
    if include_pending:
        tasks = db.execute('''SELECT q.* FROM assessment_requests q
            JOIN catalog_versions c ON c.id=q.form_version_id
            JOIN care_relationships r ON r.id=q.relationship_id JOIN users d ON d.id=r.doctor_id
            WHERE q.patient_id=? AND c.code=? AND q.expires_at>? AND q.age_on=?
            AND r.ends_at IS NULL AND d.disabled=0 AND r.starts_at<=?
            AND NOT EXISTS(SELECT 1 FROM assessment_results a WHERE a.request_id=q.id)
            ORDER BY q.requested_at DESC''', (patient_id, form['code'], now(), records.today().isoformat(), now())).fetchall()
        task = next((q for q in tasks if request_age_current(db, q)), None)
        if task:
            state.update(allowed=False, pending_id=task['id'], message=f"{form['code']} уже предложена и ждёт ответа пациента. Дождитесь ответа или окончания срока предложения.")
    return state


def catalogue(db, user, patient_id):
    if user['role'] != 'doctor' or access.visible_patient(db, user, patient_id) is None:
        return []
    result = []
    for form in definitions():
        state = repeat_state(db, patient_id, form)
        try:
            available_form(db, form['id'])
        except AssessmentError as error:
            state.update(allowed=False, message=str(error))
        result.append({'form': form, 'policy': policy(form), **state})
    return result


def checked_age(db, patient, values, form=None):
    try:
        age = records.validate({**values, 'observed_on': records.today().isoformat()})['age']
        basis = records.text_field(values, 'age_basis', 1000)
    except records.RecordError as error:
        raise AssessmentError(str(error)) from None
    years = age['years'] if age['years'] is not None else age['calculated_years']
    if age['status'] != 'known' or years is None or not 18 <= years <= 120 or not basis:
        raise AssessmentError('Укажите возраст от 18 лет и источник сведений. Неизвестный возраст не даёт допуск.')
    try:
        token = ages.verify(db, patient, years)
    except ages.AgeError as error:
        raise AssessmentError(str(error), error.status) from None
    age['verification_token'] = token
    if form and not form.get('min_age', 18) <= years <= form.get('max_age', 120):
        raise AssessmentError(f"{form['code']}: в этом выпуске доступен возраст от {form.get('min_age', 18)} до {form.get('max_age', 120)} лет. Применимость вне изученной группы не подтверждена.", 409)
    return years, basis, age


def assign(db, user, patient_id, values):
    if user['role'] != 'doctor':
        raise AssessmentError('Предложить анкету может только ведущий врач.', 403)
    retry = values.get('assignment_key', '')
    if not re.fullmatch(r'[0-9a-f]{32}', retry):
        raise AssessmentError('Обновите форму перед отправкой.')
    with transaction(db):
        patient = access.visible_patient(db, user, patient_id)
        if patient is None:
            raise AssessmentError('Карточка недоступна.', 404)
        if patient['synthetic'] != 1:
            raise AssessmentError('Доступен только синтетический демонстрационный режим.', 409)
        form = available_form(db, values.get('form_version_id', ''))
        years, basis, age = checked_age(db, patient, values, form)
        payload = canonical({'form_version_id': form['id'], 'age': age, 'age_basis': basis})
        key = hashlib.sha256(f'{user["id"]}:{patient_id}:{retry}'.encode()).hexdigest()
        old = db.execute('SELECT id,payload_json FROM assessment_requests WHERE request_key=?', (key,)).fetchone()
        if old:
            if old['payload_json'] != payload:
                raise AssessmentError('Эта отправка уже сохранена с другим содержимым.', 409)
            return old['id']
        repeat = repeat_state(db, patient_id, form)
        if not repeat['allowed']:
            raise AssessmentError(repeat['message'], 409)
        relationship = db.execute('''SELECT id FROM care_relationships WHERE patient_id=? AND doctor_id=?
            AND ends_at IS NULL AND starts_at<=?''', (patient_id, user['id'], now())).fetchone()
        if not relationship:
            raise AssessmentError('Действующая связь с пациентом не найдена.', 409)
        # The defined group is always bound to a concrete patient/doctor relationship.
        request_id, stamp = secrets.token_hex(16), now()
        expires = (datetime.fromisoformat(stamp) + timedelta(hours=24)).isoformat(timespec='microseconds')
        db.execute('INSERT INTO assessment_requests VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   (request_id, patient_id, relationship['id'], form['id'], user['id'], stamp, expires,
                    records.today().isoformat(), years, basis, canonical(age), key, payload))
        access.audit(db, user['id'], 'assessment.requested', request_id)
        return request_id


def with_deadline(task):
    """Display the same earlier boundary enforced by submit: expiry or Moscow midnight."""
    task = dict(task)
    zone = ZoneInfo('Europe/Moscow')
    midnight = (datetime.fromisoformat(task['age_on']) + timedelta(days=1)).replace(tzinfo=zone)
    deadline = min(datetime.fromisoformat(task['expires_at']), midnight).astimezone(zone)
    task['deadline_iso'] = deadline.isoformat()
    if 'form_version_id' in task:
        form = definition(task['form_version_id'])
        task.update(code=form['code'], item_count=len(form['items']), title=form['title'])
    if deadline.hour == 0 and deadline.minute == 0:
        # «00:00 завтрашнего дня» читается как начало суток; пациенту пишем конец сегодняшних.
        task['deadline_label'] = (deadline - timedelta(days=1)).strftime('%d.%m.%Y') + ' 24:00 МСК'
    else:
        task['deadline_label'] = deadline.strftime('%d.%m.%Y %H:%M') + ' МСК'
    return task


def visible_request(db, user, request_id, read_completed=False):
    task = db.execute('SELECT * FROM assessment_requests WHERE id=?', (request_id,)).fetchone()
    if task is None or access.visible_patient(db, user, task['patient_id']) is None:
        raise AssessmentError('Анкета недоступна.', 404)
    if read_completed and db.execute('SELECT 1 FROM assessment_results WHERE request_id=?', (request_id,)).fetchone():
        return with_deadline(task)
    # A new doctor-patient relationship must never inherit an outstanding invitation.
    relationship = db.execute('''SELECT r.* FROM care_relationships r JOIN users d ON d.id=r.doctor_id
        WHERE r.id=? AND r.ends_at IS NULL AND r.starts_at<=? AND d.disabled=0''', (task['relationship_id'], now())).fetchone()
    if not relationship or (user['role'] == 'doctor' and relationship['doctor_id'] != user['id']):
        raise AssessmentError('Связь для этой анкеты больше не действует.', 409)
    return with_deadline(task)


def submit(db, user, request_id, values):
    with transaction(db):
        task = visible_request(db, user, request_id)
        if task['expires_at'] <= now() or task['age_on'] != records.today().isoformat():
            raise AssessmentError('Срок предложения истёк. Врач может предложить новую анкету.', 409)
        form = available_form(db, task['form_version_id'])
        if values.get('form_version_id') != form['id']:
            raise AssessmentError('Версия анкеты не совпадает с предложенной.', 409)
        patient = access.visible_patient(db, user, task['patient_id'])
        _, _, current_age = checked_age(db, patient, {'age_status': 'known', 'age_years': str(task['age_years']), 'age_basis': task['age_basis']}, form)
        if json.loads(task['age_snapshot_json']).get('verification_token') != current_age['verification_token']:
            raise AssessmentError('Сведения о возрасте изменились. Врач должен предложить новую анкету.', 409)
        answers = parse_answers(values, form)
        scores = score_answers(answers, form)
        encoded = canonical(answers)
        old = db.execute('''SELECT a.id,a.answers_json FROM assessments a JOIN assessment_results r
            ON r.assessment_id=a.id WHERE r.request_id=?''', (request_id,)).fetchone()
        if old:
            if old['answers_json'] != encoded:
                raise AssessmentError('Эта анкета уже отправлена с другими ответами. Прежняя запись сохранена.', 409)
            return old['id']
        repeat = repeat_state(db, task['patient_id'], form, include_pending=False)
        if not repeat['allowed']:
            raise AssessmentError(repeat['message'], 409)
        assessment_id, stamp = secrets.token_hex(16), now()
        db.execute('INSERT INTO assessments VALUES(?,?,?,?,?,?,?,?,?)',
                   (assessment_id, task['patient_id'], form['id'], task['requested_by'], stamp,
                    encoded, None, 'complete' if scores is not None else 'incomplete', scoring_version(form)))
        db.execute('INSERT INTO assessment_results VALUES(?,?,?,?,?,?)',
                   (assessment_id, request_id, user['id'], records.today().isoformat(), stamp,
                    canonical(scores) if scores is not None else None))
        access.audit(db, user['id'], 'assessment.received', assessment_id)
        return assessment_id


def history(db, user, patient_id):
    """Explicit separate projections; patient responses contain no answers or computed data."""
    if access.visible_patient(db, user, patient_id) is None:
        raise AssessmentError('Карточка недоступна.', 404)
    if user['role'] == 'patient':
        return [dict(r) for r in db.execute('''SELECT q.id request_id,q.requested_at,r.recorded_at,
            q.form_version_id FROM assessment_requests q JOIN assessment_results r ON r.request_id=q.id
            WHERE q.patient_id=? ORDER BY r.recorded_at DESC''', (patient_id,))]
    rows = db.execute('''SELECT a.*,r.actor_id,r.observed_on,r.recorded_at,r.scores_json,q.age_years,q.age_basis,
        q.age_on,u.display_name,c.definition_json,s.sha256 source_sha256,s.url source_url
        FROM assessments a JOIN assessment_results r ON r.assessment_id=a.id
        JOIN assessment_requests q ON q.id=r.request_id JOIN users u ON u.id=r.actor_id
        JOIN catalog_versions c ON c.id=a.scale_version_id JOIN source_versions s ON s.id=c.source_version_id
        WHERE a.patient_id=? ORDER BY r.observed_on DESC,r.recorded_at DESC,a.id DESC''', (patient_id,)).fetchall()
    return [{**dict(r), 'answers': json.loads(r['answers_json']),
             'scores': json.loads(r['scores_json']) if r['scores_json'] else None,
             'form': json.loads(r['definition_json'])} for r in rows]


def pending(db, user, patient_id):
    if access.visible_patient(db, user, patient_id) is None:
        return []
    columns = ('id', 'requested_at', 'form_version_id', 'expires_at', 'age_on')
    return [with_deadline({k: r[k] for k in columns}) for r in db.execute('''SELECT q.* FROM assessment_requests q
        JOIN care_relationships r ON r.id=q.relationship_id JOIN users d ON d.id=r.doctor_id
        WHERE q.patient_id=? AND q.expires_at>? AND q.age_on=? AND r.ends_at IS NULL AND d.disabled=0
        AND NOT EXISTS(SELECT 1 FROM assessment_results a WHERE a.request_id=q.id)
        ORDER BY q.requested_at DESC''', (patient_id, now(), records.today().isoformat())) if request_age_current(db, r)]


def trends(results):
    """Exact-version small multiples, real calendar spacing and explicit breaks for missing data."""
    groups = {}
    for result in sorted(results, key=lambda r: (r['observed_on'], r['recorded_at'], r['id'])):
        key = (result['scale_version_id'], result['scoring_version'], result['source_sha256'])
        group = groups.setdefault(key, {'form': result['form'], 'version': key[0], 'source_sha256': key[2], 'rows': []})
        group['rows'].append(result)
    for group in groups.values():
        rows = group['rows'][-30:]
        days = [datetime.fromisoformat(r['observed_on']).toordinal() for r in rows]
        span = max(days) - min(days)
        series = []
        for code, subscale in group['form']['subscales'].items():
            low, high = scale_range(group['form'], subscale)
            points, segments, segment = [], [], []
            for index, row in enumerate(rows):
                if row['scores'] is None:
                    if segment: segments.append(segment)
                    segment = []
                    continue
                value = row['scores'][code]
                point = {'x': round(42 + (days[index] - min(days)) * 488 / span, 2) if span else 286,
                         'y': round(156 - (value - low) * 126 / (high - low), 2),
                         'value': value, 'date': row['observed_on'], 'id': row['id']}
                points.append(point)
                segment.append(point)
            if segment: segments.append(segment)
            previous = points[-2] if len(points) > 1 else None
            latest = points[-1] if points else None
            series.append({'name': subscale['label'], 'code': code, 'points': points, 'segments': segments,
                           'maximum': high, 'middle': high / 2 if high % 2 else high // 2, 'latest': latest, 'previous': previous,
                           'delta': latest['value'] - previous['value'] if previous else None})
        group.update(series=series, shown=len(rows), total=len(group['rows']),
                     first_date=rows[0]['observed_on'], last_date=rows[-1]['observed_on'],
                     missing=sum(r['scores'] is None for r in rows))
    return list(groups.values())
