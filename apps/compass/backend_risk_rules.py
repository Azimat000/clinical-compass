"""Source-bound structured review flags. Synthetic only; no model or care actions."""
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import secrets

from . import ages, backend_snapshot, backend_sources, decisions, records
from .db import now, transaction

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / 'data/backend/risk-rules-v1.json'
VERSION = 'backend-risk-rules-v1'
CONTEXT_VERSION = 'backend-risk-context-v1'
FLAGS = ('suicidal_ideation', 'suicidal_intent', 'suicidal_plan', 'suicidal_behavior',
         'suicide_risk', 'psychiatric_comorbidity', 'treatment_resistance',
         'psychopharmacotherapy', 'initial_antidepressant_phase', 'worsening_anxiety')
STATUSES = {'present', 'denied', 'unknown', 'conflicting'}
LIMITATION = ('Оценены только перечисленные структурированные правила. Анкеты, общий показатель '
              'самочувствия, свободный текст и его сочетания здесь не оценены (BE08); '
              'отсутствие совпадения не означает отсутствия риска. Клинический выпуск заблокирован.')


def release():
    value = json.loads(CATALOG.read_text())
    if (set(value) != {'version', 'mode', 'clinical_review', 'authorship', 'evidence', 'rules'}
            or value['version'] != VERSION or value['mode'] != 'synthetic_only'
            or value['clinical_review'] is not None
            or [r['id'] for r in value['rules']] != ['DEP-SUICIDE-FACT', 'GAD-PSY-REVIEW',
                                                    'GAD-ADVERSE-REVIEW', 'GAD-INITIAL-ANXIETY']):
        raise backend_sources.SourceError(['risk_catalog_invalid'])
    for rule in value['rules']:
        if (rule['attention'] != 'physician_review' or not rule['text']
                or rule['source_id'] not in ('KR301_3', 'KR457_3')
                or not 1 <= rule['pdf_page'] <= 200):
            raise backend_sources.SourceError(['risk_catalog_invalid'])
    return {**value, 'engine_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'evidence_sha256': hashlib.sha256((ROOT / value['evidence']).read_bytes()).hexdigest()}


def references(catalog):
    return [{'id': 'be07-' + r['id'], 'version': catalog['version'],
             'sha256': backend_snapshot.digest([catalog, r])} for r in catalog['rules']]


def _payload(value):
    expected = {'condition', 'severity', 'basis', 'supersedes_id', *FLAGS}
    if (not isinstance(value, dict) or set(value) != expected
            or value['condition'] not in {'F32', 'F33', 'F41.1', 'unknown', 'conflicting'}
            or value['severity'] not in {'severe', 'nonsevere', 'unknown', 'conflicting'}
            or any(value[k] not in STATUSES for k in FLAGS)
            or not isinstance(value['basis'], str) or not 1 <= len(value['basis'].strip()) <= 2000
            or (value['supersedes_id'] is not None and
                (not isinstance(value['supersedes_id'], str) or not re.fullmatch('[0-9a-f]{32}', value['supersedes_id'])))):
        raise ValueError('invalid_risk_context')
    return {**value, 'version': CONTEXT_VERSION,
            # Preserve safe interoperability with the older context reader.
            'gad_status': 'present' if value['condition'] == 'F41.1' else 'unknown',
            'aviandr_prescription': 'unknown', 'clinical_basis': value['basis']}


def record_context(db, user, patient_id, observed_on, value, request_key):
    """Internal physician boundary, no HTTP/UI. Append-only factual attestation.

    An explicit correction names supersedes_id. Independent same-day contexts
    are not silently resolved by choosing the latest one. This never diagnoses.
    """
    payload = _payload(value)
    if (not isinstance(request_key, str) or not re.fullmatch('[0-9a-f]{32}', request_key)
            or not isinstance(observed_on, str)
            or date.fromisoformat(observed_on).isoformat() != observed_on
            or not date(1900, 1, 1) <= date.fromisoformat(observed_on) <= records.today()):
        raise ValueError('invalid_risk_context')
    with transaction(db):
        relationship = decisions.doctor_relationship(db, user, patient_id)
        old = db.execute('SELECT * FROM clinical_contexts WHERE request_key=?', (request_key,)).fetchone()
        if old:
            if (old['patient_id'] != patient_id or old['actor_id'] != user['id']
                    or old['relationship_id'] != relationship or old['observed_on'] != observed_on
                    or old['payload_json'] != decisions.canonical(payload)):
                raise ValueError('context_request_conflict')
            return old['id']
        previous = payload['supersedes_id']
        if previous:
            parent = db.execute('SELECT * FROM clinical_contexts WHERE id=?', (previous,)).fetchone()
            if (not parent or parent['patient_id'] != patient_id or parent['relationship_id'] != relationship
                    or json.loads(parent['payload_json']).get('version') != CONTEXT_VERSION
                    or any(json.loads(r[0]).get('supersedes_id') == previous for r in
                           db.execute('SELECT payload_json FROM clinical_contexts WHERE patient_id=?', (patient_id,)))):
                raise ValueError('context_revision_conflict')
        cid = secrets.token_hex(16)
        db.execute('INSERT INTO clinical_contexts VALUES(?,?,?,?,?,?,?,?)',
                   (cid, patient_id, user['id'], relationship, observed_on, now(),
                    decisions.canonical(payload), request_key))
        from . import backend_jobs, events, access
        if backend_jobs.settings(db) is not None:
            events.enqueue(db, backend_jobs.TOPIC, patient_id,
                           {'relationship_id': relationship, 'doctor_id': user['id']})
        access.audit(db, user['id'], 'analysis.risk_context_recorded', cid)
        return cid


def _error(code, message, status='insufficient_data'):
    return {'status': status, 'errors': [{'code': code, 'message': message, 'retryable': False}]}


def _ages(snapshot):
    patient = snapshot['patients'][0]
    rows = [{'observed_on': patient['created_at'][:10], 'age': {
        'status': patient['age_status'], 'years': patient['age_years'], 'birth_date': patient['birth_date']}}]
    for row in snapshot.get('clinical_entries', []) + snapshot.get('first_visit_versions', []):
        payload = json.loads(row['payload_json'])
        rows.append({'observed_on': payload.get('age_observed_on', payload['observed_on']), 'age': payload['age']})
    possible, known = set(range(121)), False
    for row in rows:
        values = ages.possible_years(row, date.fromisoformat(snapshot['day']))
        if values is not None:
            possible &= values
            known = True
    if not known or not possible:
        raise ages.AgeError('age_unknown_or_conflicting')
    return min(possible), max(possible)


def _ref(snapshot, table, identity):
    matches = [ref for ref, meta in snapshot['patient_history']['sources'].items()
               if meta['table'] == table and meta['id'] == identity]
    if len(matches) != 1:
        raise ValueError('risk_evidence_unavailable')
    backend_snapshot.resolve(snapshot, matches[0])
    return matches[0]


def _context(snapshot):
    rows = [r for r in snapshot.get('clinical_contexts', []) if r['relationship_id'] == snapshot['relationship']]
    # Retain all original rows but exclude explicit corrected versions from use.
    superseded = {json.loads(r['payload_json']).get('supersedes_id') for r in rows}
    current = [r for r in rows if r['id'] not in superseded and r['observed_on'] == snapshot['day']]
    if len(current) != 1:
        return None, None
    row = current[0]
    payload = json.loads(row['payload_json'])
    if payload.get('version') == CONTEXT_VERSION:
        value = {k: payload[k] for k in {'condition', 'severity', 'basis', 'supersedes_id', *FLAGS}}
        if _payload(value) != payload:
            return None, None
    elif payload.get('gad_status') == 'present':
        # Previously recorded exact GAD facts remain usable. Missing new facts
        # are unknown, not denials. No free text is interpreted.
        payload = {**{k: 'unknown' for k in FLAGS}, **payload, 'condition': 'F41.1'}
    else:
        return None, None
    return payload, _ref(snapshot, 'clinical_contexts', row['id'])


def _or(values):
    # A definite positive remains visible even with another missing/conflicting
    # factor; uncertainty is separately returned and never clears that positive.
    if 'present' in values:
        return 'triggered'
    if all(v == 'denied' for v in values):
        return 'no_match'
    return 'insufficient_data'


def _adverse(snapshot):
    reports = []
    for row in snapshot.get('clinical_entries', []):
        p = json.loads(row['payload_json'])
        if row['observed_on'] != snapshot['day']:
            continue
        # Known structured status is a report of an event, not semantic parsing.
        fact = p['fields'].get('adverse_events', {'status': 'unknown'})
        value = {'known': 'present', 'denied': 'denied'}.get(fact['status'], fact['status'])
        if any('adverse' in i.get('responses', {}) for i in p.get('medication_feedback', [])):
            value = 'present'
        reports.append((value, _ref(snapshot, 'clinical_entries', row['id'])))
    if not reports:
        return 'insufficient_data', [], [], []
    values = [v for v, _ in reports]
    # Same-day positive/denial does not erase the report; state uncertainty.
    issues = ['НЯ: противоречие или неполные сведения требуют сверки.'] if (
        'conflicting' in values or 'unknown' in values or ('present' in values and 'denied' in values)) else []
    return _or(values), [ref for _, ref in reports], issues, values


def evaluate(snapshot):
    """Reproducible execution from frozen raw rows; no live DB or model input."""
    if snapshot.get('policy') != 'synthetic-inputs-v1' or snapshot['patients'][0]['synthetic'] != 1:
        return _error('clinical_release_blocked', 'Оценка допускается только на изолированной синтетике.', 'unsupported')
    if snapshot.get('backend_risk_rules') != release():
        return _error('risk_version_unavailable', 'Версия правил изменилась; нужен новый снимок.')
    try:
        low, high = _ages(snapshot)
    except (ages.AgeError, ValueError, KeyError):
        return _error('risk_age_unknown', 'Возраст неизвестен или противоречив; оценка не выполнена.')
    if high < 18 or low > 120:
        return _error('risk_age_unsupported', 'Возраст вне взрослой области правил.', 'unsupported')
    if low < 18:
        return _error('risk_age_unknown', 'Возраст пересекает границу взрослой области.')
    try:
        context, cref = _context(snapshot)
    except (KeyError, ValueError, TypeError):
        context, cref = None, None
    if context is None or context['condition'] in ('unknown', 'conflicting'):
        return _error('risk_context_unavailable', 'Нужен один непротиворечивый текущий структурированный контекст врача.')
    condition = context['condition']
    if condition not in ('F32', 'F33', 'F41.1'):
        return _error('risk_condition_unsupported', 'Область состояния не поддерживается.', 'unsupported')
    catalog = snapshot['backend_risk_rules']
    report = snapshot['backend_sources']
    evaluations, patterns, facts, missing, conflicts = [], [], [], [LIMITATION], []
    # Context and age evidence are inspectable frozen rows, never inferred labels.
    facts.append({'id': 'context', 'text': 'Структурированный контекст врача: ' + condition +
                  '; дата ' + snapshot['day'] + '.', 'evidence_refs': [cref]})
    age_refs = [_ref(snapshot, 'patients', snapshot['patients'][0]['id'])] + [
        _ref(snapshot, t, r['id']) for t in ('clinical_entries', 'first_visit_versions') for r in snapshot.get(t, [])]
    if len(age_refs) > 50:
        return _error('risk_evidence_limit', 'Слишком много возрастных оснований; оценка не опубликована.')
    facts.append({'id': 'age', 'text': f'Сверенный возраст на дату снимка: {low}–{high}.',
                  'evidence_refs': age_refs})
    for rule in catalog['rules']:
        rid = rule['id']
        state, reasons, refs, values, details = 'not_applicable', [], [cref], [], {}
        if condition in rule['conditions']:
            try:
                if report['claims'][rule['admission_claim']]['binding']['source_id'] != rule['source_id']:
                    raise backend_sources.SourceError(['risk_source_binding_mismatch'])
                backend_sources.require(report, [rule['admission_claim']], 'risk',
                                        age_min=low, age_max=high, condition=condition)
            except backend_sources.SourceError as exc:
                state, reasons = 'insufficient_data', exc.reasons
            else:
                if rid == 'DEP-SUICIDE-FACT':
                    details = {k: context[k] for k in (*FLAGS[:4], 'suicide_risk')}
                    values = list(details.values())
                    if context['suicide_risk'] == 'present':
                        reasons.append('legacy_clinician_recorded_suicide_risk')
                    state = _or(values)
                elif rid == 'GAD-PSY-REVIEW':
                    values = [context[k] for k in ('suicide_risk', 'psychiatric_comorbidity', 'treatment_resistance')]
                    details = {k: context[k] for k in ('suicide_risk', 'psychiatric_comorbidity', 'treatment_resistance', 'severity')}
                    severity = context['severity']
                    values.append({'severe': 'present', 'nonsevere': 'denied'}.get(severity, severity))
                    state = _or(values)
                elif rid == 'GAD-ADVERSE-REVIEW':
                    therapy = context['psychopharmacotherapy']
                    if therapy == 'denied':
                        state = 'not_applicable'
                    elif therapy != 'present':
                        state, reasons = 'insufficient_data', ['psychopharmacotherapy_unknown_or_conflicting']
                    else:
                        state, adverse_refs, issues, values = _adverse(snapshot)
                        refs += adverse_refs
                        conflicts += issues
                        details = {'psychopharmacotherapy': therapy, 'reported_adverse_statuses': values}
                elif rid == 'GAD-INITIAL-ANXIETY':
                    phase, change, therapy = (context[k] for k in (
                        'initial_antidepressant_phase', 'worsening_anxiety', 'psychopharmacotherapy'))
                    details = {'initial_antidepressant_phase': phase, 'worsening_anxiety': change, 'psychopharmacotherapy': therapy}
                    values = list(details.values())
                    if 'conflicting' in values or (therapy == 'denied' and phase == 'present'):
                        state, reasons = 'insufficient_data', ['therapy_phase_conflict']
                        conflicts.append(rid + ': начальная фаза указана при отрицании терапии либо сведения противоречивы.')
                    elif phase == 'denied' or change == 'denied':
                        state = 'no_match'
                    elif all(v == 'present' for v in values):
                        state = 'triggered'
                    else:
                        state = 'insufficient_data'
                if 'conflicting' in values:
                    conflicts.append(rid + ': врач указал противоречивые сведения.')
                if 'unknown' in values or 'conflicting' in values:
                    missing.append(rid + ': часть факторов не установлена; положительный фактор не отменён.')
                if state == 'insufficient_data' and not reasons:
                    reasons = ['required_structured_facts_unknown_or_conflicting']
        if state == 'insufficient_data':
            missing.append(rid + ': ' + ', '.join(reasons))
        fid = 'fact-' + rid
        # Do not truncate a large set of evidence to fit the contract.
        if len(refs) > 50:
            return _error('risk_evidence_limit', 'Слишком много структурированных оснований; оценка не опубликована.')
        if state in ('triggered', 'no_match'):
            facts.append({'id': fid, 'text': rid + ': ' + state + '; структурированные значения: ' +
                          decisions.canonical(details) + '; наблюдение ' + snapshot['day'] + '.', 'evidence_refs': refs})
        ev = {'rule_id': rid, 'version': VERSION, 'state': state,
              'attention': rule['attention'] if state == 'triggered' else 'undetermined',
              'source_ids': ['be07-' + rid], 'fact_ids': ['context', 'age'] + ([fid] if state in ('triggered', 'no_match') else []),
              'reasons': reasons, 'source_id': rule['source_id'], 'section': rule['section'],
              'pdf_page': rule['pdf_page']}
        evaluations.append(ev)
        if state == 'triggered':
            patterns.append({'id': rid, 'text': rule['text'], 'fact_ids': ev['fact_ids'], 'source_ids': ev['source_ids']})
    if not patterns and any(e['state'] == 'insufficient_data' for e in evaluations):
        return _error('risk_incomplete', 'Оценка структурированных правил неполна: ' + '; '.join(missing[1:])[:800])
    result = {'summary': ('Есть структурированные признаки для рассмотрения врачом.' if patterns else
                          'В пределах применимых структурированных правил совпадений не найдено; это не отсутствие риска.'),
              'facts': facts, 'contradictions': sorted(set(conflicts)), 'missing_data': sorted(set(missing)),
              'output': {'assessment': 'potential_risk' if patterns else 'no_pattern_found',
                         'patterns': patterns, 'rule_evaluations': evaluations}}
    return {'status': 'ready', 'result': result, 'model': None}


def execute(operation, snapshot):
    if operation != 'risk':
        from .backend_model import ModelError
        raise ModelError('operation_unavailable')
    return evaluate(snapshot)


def verify(snapshot, result):
    expected = evaluate(snapshot)
    if expected.get('status') != 'ready' or result != expected['result']:
        raise backend_sources.SourceError(['risk_result_not_reproducible'])
