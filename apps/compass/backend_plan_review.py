"""Explicit synthetic physician plan reviews using the existing decision ledger.

The review table only binds provenance to an immutable proposal. Confirmations,
the current action, medication schedules and patient outcomes have one home.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import secrets

from . import access, backend_analyses as analyses, backend_care_plan as plans
from . import backend_therapy as therapy, backend_medication_regimens as regimens
from . import decisions, medications, records, routing
from .db import now, transaction

VERSION = 'plan-review-v1'
text = lambda n: {'type': 'string', 'minLength': 1, 'maxLength': n}
nullable = lambda s: {'oneOf': [s, {'type': 'null'}]}
def obj(properties):
    return {'type': 'object', 'additionalProperties': False,
            'properties': properties, 'required': list(properties)}

MEDICATION = obj({'recommendation_id': text(64), 'candidate': therapy.RAW_SCHEMA['properties']['candidates']['items'],
    'start': text(10), 'days': {'type': 'integer', 'minimum': 1, 'maximum': 366},
    'times': {'type': 'array', 'minItems': 1, 'maxItems': 4,
              'items': {**text(5), 'pattern': '(?:[01][0-9]|2[0-3]):[0-5][0-9]'}}})
ROUTE = obj({k: text(2000) for k in ('category', 'urgency', 'severity_status',
    'population_status', 'specialty', 'severity', 'population', 'evidence', 'unavailable', 'age_years')})
SCHEMA = obj({'request_key': {**text(32), 'pattern': '[0-9a-f]{32}'},
    'analysis_revision': {'type': 'integer', 'minimum': 1},
    'snapshot_id': {**text(64), 'pattern': '[0-9a-f]{64}'},
    'expected_version': {'type': 'integer', 'minimum': 0},
    'parent_id': nullable(text(64)),
    'items': {'type': 'array', 'minItems': 1, 'maxItems': 30,
              'items': obj({'id': text(100), 'due_on': nullable(text(10))})},
    'medication': nullable(MEDICATION), 'routing': nullable(ROUTE),
    'basis': text(4000), 'uncertainties': text(4000), 'reviewed': {'const': True, 'type': 'boolean'}})
CONFIRM_SCHEMA = obj({'version': {'type': 'integer', 'minimum': 1},
    'decision': {'enum': ['approved', 'rejected']}, 'rationale': text(4000),
    'reviewed': {'type': 'boolean', 'const': True}})


def runtime():
    from . import backend_snapshot
    return hashlib.sha256(Path(__file__).read_bytes() + Path(decisions.__file__).read_bytes()
                          + Path(backend_snapshot.__file__).read_bytes()).hexdigest()


def available(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='backend_plan_reviews'").fetchone():
        raise analyses.AnalysisError('Нужна миграция отдельной синтетической копии.', 409, 'plan_review_unavailable')


def head(db, patient_id):
    return db.execute('SELECT * FROM backend_plan_reviews WHERE patient_id=? ORDER BY version DESC LIMIT 1',
                      (patient_id,)).fetchone()


def _day(value):
    try:
        day = date.fromisoformat(value)
        if day.isoformat() != value or not records.today() <= day <= records.today() + timedelta(days=366):
            raise ValueError()
        return day
    except (ValueError, TypeError):
        raise analyses.AnalysisError('Нужна явная дата врача от сегодня до года вперёд.') from None


def project(db, user, patient_id, run_id, body):
    """Recompute source, risk, diagnosis and medication checks inside the write lock."""
    value = analyses.read(db, user, patient_id, run_id)
    if (value['operation'] != 'plan' or value['status'] != 'ready'
            or value['revision'] != body['analysis_revision'] or value['snapshot_id'] != body['snapshot_id']
            or not value.get('care_plan_context')):
        raise analyses.AnalysisError('Проект или его точные входы устарели.', 409, 'plan_unavailable')
    frozen = json.loads(db.execute('SELECT payload_json FROM analysis_input_snapshots WHERE id=?',
                                  (value['snapshot_id'],)).fetchone()[0])
    context = value['care_plan_context']
    plans.verify(frozen, {k: value[k] for k in ('status', 'result', 'errors', 'model')}, context)
    report = context['report']
    if not report or not report['diagnosis_reviewed']:
        raise analyses.AnalysisError('Сначала требуется отдельное актуальное решение врача по диагнозу.', 409)
    indexed = {i['id']: i for i in report['items']}
    ids = [i['id'] for i in body['items']]
    if len(set(ids)) != len(ids) or set(ids) - indexed.keys():
        raise analyses.AnalysisError('Выберите точные неповторяющиеся пункты проекта.')
    required = {i['id'] for i in report['items'] if i['necessity'] == 'required_evaluation'}
    if not required.issubset(ids):
        raise analyses.AnalysisError('Обязательное уточнение риска или диагноза нельзя убрать.', 409)
    items = []
    for selection in body['items']:
        if selection['due_on'] is not None:
            _day(selection['due_on'])
        items.append({**indexed[selection['id']], 'due_on': selection['due_on']})
    route = None
    needs_route = any(i['kind'] == 'routing' for i in items)
    if needs_route != (body['routing'] is not None):
        raise analyses.AnalysisError('Для пункта направления нужна отдельная оценка маршрута врачом.')
    if needs_route:
        route = routing.review({'routing_reference': routing.reference()['version'],
                                **{'route_' + k: v for k, v in body['routing'].items()}})
        routing.confirmable(db, patient_id, {'routing_review': route})
    result = {'kind': 'plan_change', 'mode': 'physician_reviewed_synthetic', 'automatic': False,
        'content': '\n'.join(i['text'] for i in items), 'basis': decisions.checked_text(body, 'basis'),
        'uncertainties': decisions.checked_text(body, 'uncertainties'), 'plan_items': items,
        'backend_plan_review': {'version': VERSION, 'run_id': run_id,
            'analysis_revision': body['analysis_revision'], 'snapshot_id': body['snapshot_id']}}
    if route:
        result['routing_review'] = route
        result['content'] += '\nНаправление: ' + route['specialty'] + '; ' + route['urgency']
    med = body['medication']
    if med is not None:
        extension = context.get('therapy')
        options = extension['report']['recommendations'] if extension else []
        chosen = next((r for r in options if r['id'] == med['recommendation_id']), None)
        if (chosen is None or med['candidate']['product_id'] != chosen['candidate']['product_id']
                or report['status'] != 'physician_diagnosis_draft'):
            raise analyses.AnalysisError('Нужен один проверенный вариант лечения без неуточнённых рисков.', 409)
        patient, _ = therapy.patient_context(frozen)
        candidate = med['candidate']
        check = regimens.evaluate(candidate, patient)
        regimens.verify(candidate, patient, check)
        if (not check['synthetic_eligible'] or candidate['indication'] != therapy.INDICATIONS[report['condition']]):
            raise analyses.AnalysisError('Редакция не прошла независимую лекарственную проверку.', 409, 'medication_blocked')
        if len(med['times']) != candidate['times_per_day'] or len(set(med['times'])) != len(med['times']):
            raise analyses.AnalysisError('Время приёмов должно соответствовать проверенной кратности.')
        _day(med['start'])
        quarters = Decimal(str(candidate['daily_dose_mg'])) * 4 / Decimal(str(candidate['strength_mg'])) / candidate['times_per_day']
        if quarters != int(quarters) or not 1 <= quarters <= medications.MAX_QUARTERS:
            raise analyses.AnalysisError('Доза не представима проверенным числом таблеток.', 409)
        product = regimens.release()['products'][candidate['product_id']]
        form = {'med_change': 'replace', 'med_reviewed': 'yes',
                'med_0_name': f"{product['name']} {candidate['strength_mg']} мг",
                'med_0_start': med['start'], 'med_0_days': str(med['days'])}
        for n, clock in enumerate(med['times']):
            form.update({f'med_0_{n}_time': clock, f'med_0_{n}_qty': str(int(quarters))})
        result['medications'] = medications.parse(form, 'plan_change')
        result['medication_context'] = product['administration']
        result['content'] += (f"\n{form['med_0_name']}: {candidate['daily_dose_mg']} мг/сут; "
            f"{', '.join(med['times'])}; начало {med['start']}, {med['days']} дн. {product['administration']}")
        result['selected_medication'] = {'candidate': candidate, 'source': chosen['source'],
            'duration_selection': 'physician_authored', 'clinical_release': False}
    return result


def create(db, user, patient_id, run_id, body):
    analyses.validate_schema(body, SCHEMA)
    with transaction(db):
        relationship = analyses.authorize(db, user, patient_id)
        available(db)
        encoded = decisions.canonical(body)
        old = db.execute('SELECT * FROM backend_plan_reviews WHERE actor_id=? AND patient_id=? AND request_key=?',
                         (user['id'], patient_id, body['request_key'])).fetchone()
        if old:
            if old['request_json'] != encoded or old['run_id'] != run_id or old['relationship_id'] != relationship:
                raise analyses.AnalysisError('Повтор содержит другую редакцию.', 409, 'idempotency_conflict')
            return receipt(db, user, patient_id, old['proposal_id'])
        latest = head(db, patient_id)
        if (body['expected_version'] != (latest['version'] if latest else 0)
                or body['parent_id'] != (latest['proposal_id'] if latest else None)):
            raise analyses.AnalysisError('Уже существует новая редакция.', 409, 'revision_conflict')
        payload = project(db, user, patient_id, run_id, body)
        pid, stamp = secrets.token_hex(16), now()
        version = db.execute('SELECT coalesce(max(version),0)+1 FROM proposals WHERE patient_id=?', (patient_id,)).fetchone()[0]
        db.execute("INSERT INTO proposals(id,patient_id,kind,version,payload_json,input_snapshot_json,created_at,status) VALUES(?,?,'plan_change',?,?,?,?,'draft')",
            (pid, patient_id, version, decisions.canonical(payload), decisions.snapshot(db, patient_id, relationship), stamp))
        retry = hashlib.sha256(f"be15:{user['id']}:{patient_id}:{body['request_key']}".encode()).hexdigest()
        db.execute('INSERT INTO decision_drafts VALUES(?,?,?,?,?,?)',
            (pid, user['id'], relationship, retry, body['parent_id'], decisions.canonical(decisions.reference())))
        db.execute('INSERT INTO backend_plan_reviews VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            (pid, patient_id, relationship, user['id'], body['expected_version']+1, run_id,
             body['analysis_revision'], body['request_key'], encoded, runtime(), stamp))
        access.audit(db, user['id'], 'plan.review_drafted', pid)
        return receipt(db, user, patient_id, pid)


def receipt(db, user, patient_id, proposal_id):
    relationship = analyses.authorize(db, user, patient_id)
    available(db)
    row = db.execute('''SELECT r.*,p.version proposal_version,p.payload_json,c.decision,c.id confirmation_id
        FROM backend_plan_reviews r JOIN proposals p ON p.id=r.proposal_id
        LEFT JOIN doctor_confirmations c ON c.proposal_id=p.id
        WHERE r.proposal_id=? AND r.patient_id=? AND r.relationship_id=?''',
        (proposal_id, patient_id, relationship)).fetchone()
    if not row:
        raise analyses.AnalysisError('Редакция недоступна.', 404, 'not_found')
    return {'proposal_id': proposal_id, 'proposal_version': row['proposal_version'],
        'review_version': row['version'], 'decision': row['decision'], 'confirmation_id': row['confirmation_id'],
        'payload': json.loads(row['payload_json']), 'clinical_release': 'blocked', 'synthetic_only': True}


def validate_confirmation(db, user, patient_id, proposal):
    """Called by the ONLY decision confirmer, including legacy direct callers."""
    payload = json.loads(proposal['payload_json'])
    exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='backend_plan_reviews'").fetchone()
    row = db.execute('SELECT * FROM backend_plan_reviews WHERE proposal_id=?', (proposal['id'],)).fetchone() if exists else None
    if row is None:
        if 'backend_plan_review' in payload:
            raise analyses.AnalysisError('Отсутствует происхождение проекта.', 409)
        return
    if row['runtime_sha256'] != runtime() or head(db, patient_id)['proposal_id'] != proposal['id']:
        raise analyses.AnalysisError('Механизм или редакция плана изменились.', 409, 'revision_conflict')
    body = json.loads(row['request_json'])
    if project(db, user, patient_id, row['run_id'], body) != payload:
        raise analyses.AnalysisError('Содержимое расходится с повторной проверкой.', 409)


def materialize(db, user, patient_id, proposal, confirmation_id):
    """Inside decisions.confirm's transaction; no separate medication/care engine."""
    payload = json.loads(proposal['payload_json'])
    if 'backend_plan_review' not in payload:
        return
    action = db.execute('SELECT id FROM care_actions WHERE confirmation_id=?', (confirmation_id,)).fetchone()[0]
    relationship = decisions.doctor_relationship(db, user, patient_id)
    stamp = now()
    for item in payload['plan_items']:
        if item['due_on'] is None:
            continue
        db.execute('INSERT INTO adherence_tasks VALUES(?,?,?,?,?,?,?,?,?)',
            (secrets.token_hex(16), patient_id, relationship, action, item['text'],
             datetime.fromisoformat(item['due_on']+'T00:00:00+03:00').astimezone(timezone.utc).isoformat(timespec='microseconds'),
             stamp, user['id'], secrets.token_hex(16)))
    route = payload.get('routing_review')
    if route:
        db.execute('INSERT INTO referrals VALUES(?,?,?,?,?,?,?)',
            (secrets.token_hex(16), patient_id, proposal['id'], route['category'], route['severity'], route['specialty'], action))
    access.audit(db, user['id'], 'plan.applied_synthetic', proposal['id'])


def confirm(db, user, patient_id, proposal_id, body):
    analyses.validate_schema(body, CONFIRM_SCHEMA)
    receipt(db, user, patient_id, proposal_id)
    try:
        decisions.confirm(db, user, patient_id, proposal_id,
            {**body, 'version': str(body['version']), 'reviewed': 'yes'})
    except decisions.DecisionError as exc:
        raise analyses.AnalysisError(str(exc), exc.status, 'plan_confirmation_refused') from None
    return receipt(db, user, patient_id, proposal_id)
