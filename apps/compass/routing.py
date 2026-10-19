"""Explicit physician routing in synthetic cases; no automatic clinical classification."""
import hashlib
import json
from pathlib import Path

PATH = Path(__file__).with_name('resources') / 'routing-reference-v1.json'
CATEGORIES = {'unknown': 'Не определена', 'mandatory': 'Обязательно', 'desirable': 'Желательно'}
URGENCIES = {'unknown': 'Не определена', 'emergency': 'Экстренно', 'urgent': 'Срочно', 'planned': 'Планово'}
STATUSES = {'unknown': 'Неизвестно', 'known': 'Данные представлены', 'conflicting': 'Противоречие'}


def reference():
    value = json.loads(PATH.read_text())
    if value['mode'] != 'manual_reference' or value['active_rules'] is not False:
        raise RuntimeError('Unreviewed routing release')
    return value


def fingerprint():
    return hashlib.sha256(PATH.read_bytes()).hexdigest()


def review(form):
    from .decisions import DecisionError, checked_text
    ref = reference()
    if form.get('routing_reference') != ref['version']:
        raise DecisionError('Справка маршрутизации изменилась. Обновите форму.', 409)
    value = {'reference': ref, 'fingerprint': fingerprint(), 'target': 'psychiatrist',
             'automatic': False, 'clinical_protocol_approved': False}
    for key, choices in [('category', CATEGORIES), ('urgency', URGENCIES),
                         ('severity_status', STATUSES), ('population_status', STATUSES)]:
        code = form.get('route_' + key, 'unknown')
        if code not in choices:
            raise DecisionError('Недопустимое поле маршрутизации: ' + key)
        value[key] = code
    for name in ('specialty', 'severity', 'population', 'evidence', 'unavailable'):
        value[name] = checked_text(form, 'route_' + name, 2000)
    raw_age = checked_text(form, 'route_age_years', 3, False)
    try:
        value['age_years'] = int(raw_age) if raw_age else None
        if value['age_years'] is not None and not 0 <= value['age_years'] <= 120:
            raise ValueError()
    except ValueError:
        raise DecisionError('Проверьте возраст для применимости маршрута.') from None
    return value


def confirmable(db, patient_id, payload):
    from .decisions import DecisionError
    ref = payload.get('routing_review')
    if not ref or ref.get('fingerprint') != fingerprint():
        raise DecisionError('Нужен новый проект с текущей формой маршрутизации.', 409)
    reference()
    if ref['population_status'] != 'known' or ref.get('age_years') is None or ref['age_years'] < 18:
        raise DecisionError('Для справки взрослых нужны проверенный возраст от 18 лет и применимость. Неизвестность не означает отсутствие риска.', 409)
    from . import ages
    patient = db.execute('SELECT * FROM patients WHERE id=?', (patient_id,)).fetchone()
    try:
        ages.verify(db, patient, ref['age_years'])
    except ages.AgeError as error:
        raise DecisionError(str(error), 409) from None
    if ref['category'] == 'unknown' or ref['urgency'] == 'unknown':
        raise DecisionError('Врач должен определить категорию и срочность направления отдельно.', 409)


def summaries(db, user, patient_id):
    from . import access, decisions
    if access.visible_patient(db, user, patient_id) is None:
        return []
    items = decisions.history(db, user, patient_id)
    return [i for i in items if i['kind'] == 'referral'][:3]
