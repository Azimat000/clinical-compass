"""Source-bound rules for synthetic demonstration; no diagnosis or clinical action."""
import hashlib
import json
from pathlib import Path
import secrets
from . import access, ages, events, records
from .db import now

ROOT = Path(__file__).resolve().parents[2]
RESOURCE = Path(__file__).with_name('resources') / 'clinical-rules-v1.json'
STATUSES = ('present', 'denied', 'unknown', 'conflicting')
SAFETY_FIELDS = ('taken', 'after_dose', 'current', 'rigidity', 'trismus', 'hyperhidrosis', 'hemoglobin')
TOPIC = 'clinical.critical.medication_safety.v1'


class RuleError(ValueError):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def release():
    data = json.loads(RESOURCE.read_text())
    if (data.get('version') != 'clinical-rules-v1' or data.get('mode') != 'synthetic_prototype'
            or data.get('clinical_validation') is not False or data.get('active_rules') != ['A02-v2']
            or data.get('inactive_rules') != ['A01', 'A03', 'A04', 'A05']):
        raise RuleError('Недопустимый выпуск правил.')
    for source in data['sources'].values():
        path = ROOT / source['path']
        if (not path.is_file() or path.stat().st_size != source['bytes']
                or hashlib.sha256(path.read_bytes()).hexdigest() != source['sha256']):
            raise RuleError('Источник правил изменён или недоступен.')
    return data


def fingerprint():
    data = release()
    return hashlib.sha256(canonical(data).encode() + Path(__file__).read_bytes()).hexdigest()


def _field(form, name, limit=40):
    if hasattr(form, 'getlist') and len(form.getlist(name)) > 1:
        raise RuleError('Повторяющееся поле формы.', 400)
    try:
        return records.text_field(form, name, limit)
    except records.RecordError as exc:
        raise RuleError(str(exc), 400) from None


def parse_safety(form):
    if 'safety_form_version' not in form:
        return None
    if _field(form, 'safety_form_version') != 'aviandr-safety-v1':
        raise RuleError('Обновите версию формы безопасности.', 400)
    result = {'version': 'aviandr-safety-v1'}
    for name in SAFETY_FIELDS:
        value = _field(form, 'safety_' + name) or 'unknown'
        if value not in STATUSES:
            raise RuleError('Недопустимый статус сведений о препарате.', 400)
        result[name] = value
    return result


def _doctor(db, user, patient_id):
    if user['role'] != 'doctor':
        raise RuleError('Доступно только ведущему врачу.', 403)
    patient = access.visible_patient(db, user, patient_id)
    active = db.execute("SELECT 1 FROM users WHERE id=? AND role='doctor' AND disabled=0", (user['id'],)).fetchone()
    if not patient or not active:
        raise RuleError('Карточка недоступна.', 404)
    return patient


def _relationship(db, patient_id):
    return db.execute('SELECT * FROM care_relationships WHERE patient_id=? AND ends_at IS NULL AND starts_at<=? ORDER BY starts_at DESC,id LIMIT 1',
                      (patient_id, now())).fetchone()


def _context(db, patient_id):
    row = db.execute('SELECT * FROM clinical_contexts WHERE patient_id=? ORDER BY rowid DESC LIMIT 1', (patient_id,)).fetchone()
    return {**dict(row), 'payload': json.loads(row['payload_json'])} if row else None


def _age(db, patient, minimum):
    state = ages.view(db, patient)
    try:
        allowed, known = set(range(121)), False
        for source in state['sources']:
            candidates = ages.possible_years(source, records.today())
            if candidates is not None:
                known = True
                allowed &= candidates
        if not known:
            return {'status': 'unknown', 'sources': state}
        if not allowed:
            return {'status': 'conflicting', 'sources': state}
    except (ages.AgeError, ValueError):
        return {'status': 'conflicting', 'sources': state}
    status = 'applicable' if min(allowed) >= minimum else ('not_applicable' if max(allowed) < minimum else 'unknown')
    return {'status': status, 'min_years': min(allowed), 'max_years': max(allowed), 'sources': state}


def evaluate_safety(db, user, patient_id, entry_id, payload):
    if 'medication_safety' not in payload:
        return None
    if not db.in_transaction:
        raise RuntimeError('Safety evaluation must share the record transaction')
    source_release = release()
    safety = payload['medication_safety']
    # Validate the internal contract too; direct callers cannot bypass the form parser.
    if not isinstance(safety, dict) or safety != parse_safety({'safety_form_version': safety.get('version'),
                    **{'safety_' + k: safety.get(k, 'unknown') for k in SAFETY_FIELDS}}):
        raise RuleError('Недопустимый снимок сведений.', 400)
    entry = db.execute('SELECT * FROM clinical_entries WHERE id=? AND patient_id=? AND actor_id=? AND kind=\'self_report\'',
                       (entry_id, patient_id, user['id'])).fetchone()
    if not entry or user['role'] != 'patient' or json.loads(entry['payload_json']) != payload:
        raise RuleError('Нет исходного самоотчёта.', 403)
    old = db.execute('SELECT id FROM clinical_rule_evaluations WHERE entry_id=?', (entry_id,)).fetchone()
    if old:
        return old['id']
    patient = db.execute('SELECT * FROM patients WHERE id=?', (patient_id,)).fetchone()
    context = _context(db, patient_id)
    age = _age(db, patient, 19)
    current = bool(context and context['observed_on'] == records.today().isoformat())
    rx = context['payload']['aviandr_prescription'] if current else 'unknown'
    facts = [safety[k] for k in SAFETY_FIELDS[:3]]
    reactions = [safety[k] for k in SAFETY_FIELDS[3:]]
    if patient['synthetic'] != 1 or age['status'] == 'not_applicable':
        result = 'not_applicable'
    elif age['status'] != 'applicable':
        result = age['status']
    elif not current or payload['observed_on'] != records.today().isoformat():
        result = 'unknown'
    elif 'denied' in facts or rx == 'denied' or all(v == 'denied' for v in reactions):
        result = 'no_match'
    elif 'conflicting' in facts or rx == 'conflicting':
        result = 'conflicting'
    elif rx != 'active' or 'unknown' in facts:
        result = 'unknown'
    elif 'present' in reactions:
        result = 'triggered'
    elif 'conflicting' in reactions:
        result = 'conflicting'
    else:
        result = 'unknown'
    evidence = {'inputs': payload, 'context': context, 'age_applicability': age, 'source': source_release['sources']['aviandr'],
                'release': source_release, 'release_fingerprint': fingerprint(),
                'uncertainty': 'conflicting' in reactions or 'unknown' in reactions,
                'interpretation': 'Совпадение с текстом инструкции; не оценка причинности, угрозы жизни или безопасности.'}
    evaluation_id = secrets.token_hex(16)
    db.execute('INSERT INTO clinical_rule_evaluations VALUES(?,?,?,?,?,?,?,?)',
               (evaluation_id, patient_id, entry_id, context['id'] if context else None, 'A02-v2', result, now(), canonical(evidence)))
    if result == 'triggered':
        relationship = _relationship(db, patient_id)
        critical_id = secrets.token_hex(16)
        outbox_id = events.enqueue(db, TOPIC, critical_id, {'event_id': critical_id, 'patient_id': patient_id})
        db.execute('INSERT INTO critical_events VALUES(?,?,?,?,?,?,?,?,?,?)',
                   (critical_id, patient_id, evaluation_id, 'A02-v2', source_release['sources']['aviandr']['sha256'],
                    relationship['id'] if relationship else None, relationship['doctor_id'] if relationship else None,
                    now(), 'pending_s10' if relationship else 'unassigned', outbox_id))
    return evaluation_id


def recommendation(db, user, patient_id):
    patient = _doctor(db, user, patient_id)
    ref = release()
    context = _context(db, patient_id)
    age = _age(db, patient, 18)
    advice = {'category': 'unknown', 'urgency': 'unknown', 'context_id': context['id'] if context else None,
              'reason': 'Недостаточно согласованных текущих врачебных сведений или не установлена применимость.',
              'source_url': ref['sources']['gtr']['url'], 'source_section': '§5, стр. 38',
              'age_years': age.get('min_years'), 'age_applicability': age, 'basis': '',
              'alternative': None, 'release_fingerprint': fingerprint()}
    if patient['synthetic'] != 1 or age['status'] != 'applicable' or not context or context['observed_on'] != records.today().isoformat():
        return advice
    p = context['payload']
    advice['basis'] = p['clinical_basis']
    if p['gad_status'] != 'present':
        return advice
    flags = [p[k] for k in ('suicide_risk', 'psychiatric_comorbidity', 'treatment_resistance')]
    if p['severity'] == 'severe' or 'present' in flags:
        advice.update(category='mandatory', reason='При документированном ГТР и указанном факторе §5 рекомендует диспансерное наблюдение психиатром.')
    elif p['severity'] == 'nonsevere' and all(v == 'denied' for v in flags):
        advice.update(category='desirable', alternative='psychotherapist', reason='§5 рекомендует наблюдение психотерапевтом или психиатром всем пациентам с ГТР.')
    return advice
