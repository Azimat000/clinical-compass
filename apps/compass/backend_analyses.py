"""Versioned internal analysis records. No inference, delivery or clinical actions."""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import secrets

from . import access, ages, clinical_rules, decisions, records
from .db import now, transaction

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / 'docs/architecture/backend-api.json'
SCOPE_PATH = ROOT / 'docs/architecture/backend-scope.json'
TRANSITIONS = {'queued': {'running', 'insufficient_data', 'unsupported', 'failed', 'stale'},
               'running': {'ready', 'insufficient_data', 'unsupported', 'failed', 'stale'},
               **{s: {'stale'} for s in ('ready', 'insufficient_data', 'unsupported', 'failed')}, 'stale': set()}
RELEASE = {'status': 'blocked', 'version': 'be01-contract-only-v1',
           'blockers': ['BE03', 'BE04', 'BE18', 'BE19', 'B04', 'E02', 'E06']}


class AnalysisError(ValueError):
    def __init__(self, message, status=400, code='invalid_contract'):
        super().__init__(message)
        self.status, self.code = status, code


def specification():
    return json.loads(CONTRACT_PATH.read_text())


def validate_schema(value, schema, spec=None):
    """Strict validator for the finite JSON Schema subset used by this contract.

    Unknown schema keywords fail closed so changing the spec cannot skip checks.
    This is not a general OpenAPI/JSON Schema implementation.
    """
    spec = spec or specification()
    if '$ref' in schema:
        prefix = '#/components/schemas/'
        if not schema['$ref'].startswith(prefix):
            raise RuntimeError('External schema reference is not supported')
        return validate_schema(value, spec['components']['schemas'][schema['$ref'][len(prefix):]], spec)
    permitted = {'type', 'const', 'enum', 'oneOf', 'properties', 'required', 'additionalProperties',
                 'items', 'minItems', 'maxItems', 'minLength', 'maxLength', 'pattern', 'minimum', 'format'}
    if set(schema) - permitted:
        raise RuntimeError('Unsupported contract keyword')
    if 'oneOf' in schema:
        matches = 0
        for branch in schema['oneOf']:
            try:
                validate_schema(value, branch, spec)
                matches += 1
            except AnalysisError:
                pass
        if matches != 1:
            raise AnalysisError('Значение не соответствует формату ответа.')
    if 'const' in schema and (type(value) is not type(schema['const']) or value != schema['const']):
        raise AnalysisError('Неверная версия или состояние выпуска.')
    if 'enum' in schema and value not in schema['enum']:
        raise AnalysisError('Неизвестное значение перечисления.')
    types = {'object': dict, 'array': list, 'string': str, 'integer': int, 'boolean': bool, 'null': type(None)}
    kind = schema.get('type')
    if kind and type(value) is not types[kind]:
        raise AnalysisError('Неверный тип значения.')
    if kind == 'object':
        if set(schema['required']) - set(value) or (schema['additionalProperties'] is False and set(value) - set(schema['properties'])):
            raise AnalysisError('Неполный набор полей или неизвестное поле.')
        for name, item in value.items():
            validate_schema(item, schema['properties'][name], spec)
    if kind in ('array', 'string'):
        low, high = ('minItems', 'maxItems') if kind == 'array' else ('minLength', 'maxLength')
        if len(value) < schema.get(low, 0) or len(value) > schema.get(high, float('inf')):
            raise AnalysisError('Превышен предел длины или отсутствует значение.')
    if kind == 'array':
        for item in value:
            validate_schema(item, schema['items'], spec)
    if kind == 'string':
        if (schema.get('minLength', 0) > 0 and not value.strip()) or '\x00' in value or ('pattern' in schema and re.fullmatch(schema['pattern'], value) is None):
            raise AnalysisError('Недопустимое текстовое значение.')
        if schema.get('format') == 'date-time':
            try:
                if datetime.fromisoformat(value).utcoffset() is None:
                    raise ValueError()
            except ValueError:
                raise AnalysisError('Дата должна содержать часовой пояс.') from None
    if kind == 'integer' and value < schema.get('minimum', -float('inf')):
        raise AnalysisError('Неверный номер версии.')


def validate(name, value):
    spec = specification()
    validate_schema(value, spec['components']['schemas'][name], spec)


def parse_request(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise AnalysisError('Повторяющееся поле JSON.')
            result[key] = value
        return result
    try:
        value = json.loads(raw, object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError, RecursionError):
        raise AnalysisError('Некорректный JSON.') from None
    validate('CreateAnalysis', value)
    return value


def authorize(db, user, patient_id):
    try:
        return decisions.doctor_relationship(db, user, patient_id)
    except decisions.DecisionError as exc:
        raise AnalysisError(str(exc), exc.status, 'access_denied') from None


def age_scope(db, patient_id):
    patient = db.execute('SELECT * FROM patients WHERE id=?', (patient_id,)).fetchone()
    candidates = set(range(121))
    known = False
    try:
        for source in ages.view(db, patient)['sources']:
            values = ages.possible_years(source, records.today())
            if values is not None:
                known = True
                candidates &= values
    except ages.AgeError:
        return 'insufficient_data', 'Возрастные сведения противоречивы или некорректны.'
    if not known or not candidates or (min(candidates) < 18 <= max(candidates)):
        return 'insufficient_data', 'Нужен непротиворечивый возраст для определения применимости.'
    if max(candidates) < 18:
        return 'unsupported', 'Первая версия анализа не поддерживает лиц младше 18 лет.'
    return None, None


def capture(db, patient_id, relationship_id):
    # Reuse conservative existing snapshot; BE02 will add normalized facts, not a second care plan.
    try:
        value = json.loads(decisions.snapshot(db, patient_id, relationship_id))
        value['backend_contract'] = {
            'contract_version': '1.0',
            'schema_sha256': hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest(),
            'scope_sha256': hashlib.sha256(SCOPE_PATH.read_bytes()).hexdigest()}
        snapshot = decisions.canonical(value)
        if len(snapshot.encode()) > 4194304:
            raise AnalysisError('Входной снимок превышает 4 МиБ.', 409, 'snapshot_too_large')
        return snapshot
    except clinical_rules.RuleError:
        raise AnalysisError('Источниковая зависимость недоступна.', 409, 'source_unavailable') from None


def source_refs(snapshot):
    return [{'id': r['id'], 'version': r['version'], 'sha256': r['sha256']}
            for r in json.loads(snapshot)['source_versions']]


def validate_analysis(value):
    validate('Analysis', value)
    state, result = value['status'], value['result']
    if state == 'ready' and (result is None or value['errors']):
        raise AnalysisError('Готовый результат требует содержимого и не допускает ошибок.')
    if state not in ('ready', 'stale') and result is not None:
        raise AnalysisError('Незавершённый анализ не содержит клинического результата.')
    if state in ('failed', 'unsupported', 'insufficient_data') and not value['errors']:
        raise AnalysisError('Необходимо конкретное объяснение отсутствия результата.')
    if (state == 'stale') != (value['stale_reason'] is not None):
        raise AnalysisError('Устаревание требует отдельного объяснения.')
    if result is None:
        return
    operation = value['operation']
    output = result['output']
    validate({'risk': 'RiskOutput', 'diagnosis': 'DiagnosisOutput', 'plan': 'PlanOutput'}[operation], output)
    facts = result['facts']
    if len({f['id'] for f in facts}) != len(facts) or any(not f['evidence_refs'] for f in facts):
        raise AnalysisError('Факты требуют уникальных номеров и ссылок на входы.')
    if operation == 'risk':
        findings = output['patterns']
        if bool(findings) != (output['assessment'] == 'potential_risk'):
            raise AnalysisError('Оценка риска расходится с перечнем паттернов.')
    elif operation == 'diagnosis':
        findings = [output['leading'], *output['alternatives']]
    else:
        findings = output['items']
        if not findings:
            raise AnalysisError('План не может быть пустым.')
    fact_ids = {f['id'] for f in facts}
    source_ids = {s['id'] for s in value['sources']}
    if len({f['id'] for f in findings}) != len(findings):
        raise AnalysisError('Повторяющийся номер вывода.')
    for finding in findings:
        if (not finding['fact_ids'] or not finding['source_ids']
                or set(finding['fact_ids']) - fact_ids or set(finding['source_ids']) - source_ids):
            raise AnalysisError('Вывод должен ссылаться на известные факты и источники.')


def _append(db, value):
    validate_analysis(value)
    if len(decisions.canonical(value).encode()) > 65536:
        raise AnalysisError('Ответ превышает 65 536 байт.')
    db.execute('INSERT INTO analysis_result_versions VALUES(?,?,?,?,?)',
               (value['run_id'], value['revision'], value['status'], decisions.canonical(value), value['updated_at']))


def _latest(db, run_id):
    row = db.execute('SELECT payload_json FROM analysis_result_versions WHERE run_id=? ORDER BY revision DESC LIMIT 1', (run_id,)).fetchone()
    if row is None:
        raise AnalysisError('Анализ недоступен.', 404, 'not_found')
    value = json.loads(row['payload_json'])
    validate_analysis(value)
    return value


def create(db, user, patient_id, body):
    validate('CreateAnalysis', body)
    with transaction(db):
        relationship = authorize(db, user, patient_id)
        old = db.execute('SELECT * FROM analysis_runs WHERE actor_id=? AND patient_id=? AND request_key=?',
                         (user['id'], patient_id, body['request_key'])).fetchone()
        if old:
            if old['operation'] != body['operation']:
                raise AnalysisError('Ключ уже использован для другой операции.', 409, 'idempotency_conflict')
            return read(db, user, patient_id, old['id'])
        snapshot = capture(db, patient_id, relationship)
        snapshot_id = hashlib.sha256(snapshot.encode()).hexdigest()
        stamp, run_id = now(), secrets.token_hex(16)
        db.execute('INSERT OR IGNORE INTO analysis_input_snapshots VALUES(?,?,?,?)', (snapshot_id, patient_id, snapshot, stamp))
        db.execute('INSERT INTO analysis_runs VALUES(?,?,?,?,?,?,?,?)',
                   (run_id, patient_id, snapshot_id, user['id'], relationship, body['operation'], body['request_key'], stamp))
        value = {'contract_version': '1.0', 'operation': body['operation'], 'patient_id': patient_id,
                 'snapshot_id': snapshot_id, 'run_id': run_id, 'revision': 1, 'status': 'queued',
                 'release': deepcopy(RELEASE), 'scope_version': 'backend-scope-v1', 'sources': source_refs(snapshot),
                 'result': None, 'errors': [], 'model': None, 'created_at': stamp, 'updated_at': stamp, 'stale_reason': None}
        _append(db, value)
        state, reason = age_scope(db, patient_id)
        if state:
            value.update(status=state, revision=2, updated_at=now(),
                         errors=[{'code': 'age_scope', 'message': reason, 'retryable': False}])
            _append(db, value)
        access.audit(db, user['id'], 'analysis.requested', run_id)
        return value


def read(db, user, patient_id, run_id):
    if db.in_transaction:
        return _read_in_snapshot(db, user, patient_id, run_id)
    db.execute('BEGIN')
    try:
        value = _read_in_snapshot(db, user, patient_id, run_id)
        db.commit()
        return value
    except BaseException:
        db.rollback()
        raise


def _read_in_snapshot(db, user, patient_id, run_id):
    relationship = authorize(db, user, patient_id)
    run = db.execute('SELECT * FROM analysis_runs WHERE id=? AND patient_id=? AND relationship_id=?',
                     (run_id, patient_id, relationship)).fetchone()
    if run is None:
        raise AnalysisError('Анализ недоступен.', 404, 'not_found')
    value = _latest(db, run_id)
    if value['status'] != 'stale' and run['snapshot_id'] != hashlib.sha256(capture(db, patient_id, relationship).encode()).hexdigest():
        # Pure read projection: original versions remain intact; no clinical claim remains current.
        value.update(status='stale', stale_reason='Сведения, источники, связь или дата изменились; нужен новый запуск.')
    validate_analysis(value)
    return value


def advance(db, user, patient_id, run_id, expected_revision, status, *, result=None, errors=None, model=None, stale_reason=None):
    """Internal worker boundary, deliberately absent from HTTP. Never applies a plan."""
    if type(expected_revision) is not int:
        raise AnalysisError('Нужна точная версия.', 409, 'revision_conflict')
    with transaction(db):
        authorize(db, user, patient_id)
        current = read(db, user, patient_id, run_id)
        if current['status'] == 'stale' or current['revision'] != expected_revision:
            raise AnalysisError('Запуск устарел или изменён.', 409, 'revision_conflict')
        if status not in TRANSITIONS[current['status']]:
            raise AnalysisError('Недопустимый переход состояния.', 409, 'invalid_transition')
        if status == 'ready':
            state, _ = age_scope(db, patient_id)
            if state:
                raise AnalysisError('Применимость не установлена.', 409, 'scope_unavailable')
        if status == 'ready' and result is not None:
            # Evidence references are existing stored rows, never arbitrary model strings.
            validate('Result', result)
            raw = db.execute('SELECT payload_json FROM analysis_input_snapshots WHERE id=?', (current['snapshot_id'],)).fetchone()[0]
            snapshot = json.loads(raw)
            known_refs = {'profile:' + patient_id}
            for table, rows in snapshot.items():
                if isinstance(rows, list):
                    known_refs.update(table + ':' + str(row['id']) for row in rows if isinstance(row, dict) and 'id' in row)
            for fact in result['facts']:
                if set(fact['evidence_refs']) - known_refs:
                    raise AnalysisError('Факт ссылается на отсутствующую входную запись.')
            if current['operation'] == 'plan':
                validate('PlanOutput', result['output'])
                diagnosis = read(db, user, patient_id, result['output']['diagnosis_run_id'])
                if (diagnosis['operation'] != 'diagnosis' or diagnosis['status'] != 'ready'
                        or diagnosis['snapshot_id'] != current['snapshot_id']):
                    raise AnalysisError('Нужна актуальная точная версия диагностического анализа.', 409, 'diagnosis_unavailable')
        value = {**current, 'status': status, 'revision': expected_revision + 1, 'updated_at': now(),
                 'result': result, 'errors': errors if errors is not None else [], 'model': model, 'stale_reason': stale_reason}
        _append(db, value)
        access.audit(db, user['id'], 'analysis.' + status, run_id)
        return value
