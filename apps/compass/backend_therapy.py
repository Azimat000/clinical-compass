"""BE14 work in progress: read-only post-generation candidate inspection.

This is an internal development entry point, not a generator, HTTP endpoint or
admission boundary for treatment. No candidate is released by this version.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from . import backend_analyses as analyses, backend_care_plan as plans
from . import backend_medication_safety as safety, backend_risk_rules as risks
from . import backend_snapshot as history

VERSION = 'therapy-inspection-wip-v1'
FIELDS = {'product_id', 'form', 'strength_mg', 'unit', 'indication',
          'daily_dose_mg', 'times_per_day', 'phase'}
PHASES = {'initiation', 'maintenance', 'change', 'stop'}
INDICATIONS = {'F32': 'adult_depression', 'F33': 'adult_depression', 'F41.1': 'adult_gad'}
QUESTIONS = {
    'source': 'Подтвердить актуальность точного регистрационного документа.',
    'source_freshness': 'Повторно проверить источник: срок подтверждения истёк или ещё не наступил.',
    'excipient_coverage': 'Проверить полный состав вспомогательных веществ и их переносимость.',
    'coverage': 'Завершить проверку ограничений и взаимодействий по точной инструкции.',
    'allergies': 'Уточнить аллергии на препарат, действующее и вспомогательные вещества.',
    'allergies_complete': 'Подтвердить полноту сверки аллергий; пустой текст этого не доказывает.',
    'medications': 'Сверить точный состав назначенных, фактически принимаемых и недавно отменённых препаратов.',
    'medications_complete': 'Подтвердить полноту лекарственной сверки, включая безрецептурные средства.',
    'regimen_phase': 'Нужно отдельное проверенное основание начала, изменения или отмены; схема не вычисляется из диапазона доз.',
    'tablet_divisibility': 'Подтвердить возможность получить дозу целыми таблетками или доказанной равной делимостью.',
    'age': 'Уточнить непротиворечивый возраст на дату проверки.',
}


def release():
    return {'version': VERSION,
            'engine_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'safety_catalog_sha256': safety.digest(safety.release()),
            'safety_engine_sha256': hashlib.sha256(Path(safety.__file__).read_bytes()).hexdigest(),
            'care_plan_runtime': plans.release()}


def _candidates(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 3:
        raise analyses.AnalysisError('Нужны от одного до трёх структурированных кандидатов.', 400, 'therapy_candidates')
    for candidate in value:
        if (not isinstance(candidate, dict) or set(candidate) != FIELDS
                or any(not isinstance(candidate.get(k), str) or not 1 <= len(candidate[k]) <= 80
                       for k in ('product_id', 'form', 'unit', 'indication', 'phase'))
                or candidate['phase'] not in PHASES):
            raise analyses.AnalysisError('Некорректная структура лекарственного кандидата.', 400, 'therapy_candidate_schema')
    # Reject nonfinite values and oversized payloads before inspection. A wrong
    # but finite dose/unit is retained for a specific rejection by BE13.
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        if len(encoded.encode()) > 4096:
            raise ValueError()
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise analyses.AnalysisError('Некорректные значения лекарственного кандидата.', 400, 'therapy_candidate_schema') from None
    return json.loads(encoded)


def _patient(snapshot):
    """Only measured age can be projected today. No negative facts from prose.

    A future coded reconciliation must independently resolve each value AND its
    provenance. An arbitrary valid row reference alone cannot attest its meaning.
    """
    patient = {'mode': 'synthetic_only', 'synthetic': snapshot['patients'][0]['synthetic'] == 1}
    try:
        low, high = risks._ages(snapshot)
    except (ValueError, KeyError, TypeError):
        return patient
    if low != high:
        return patient
    refs = [r for r, meta in snapshot['patient_history']['sources'].items()
            if meta['table'] in ('patients', 'first_visit_versions')]
    if refs and all(history.resolve(snapshot, r) is not None for r in refs):
        patient['age'] = {'value': low, 'refs': refs}
    return patient


def _inspect(snapshot, candidates, *, at):
    """Pure mechanics over a trusted frozen snapshot; never use with HTTP data."""
    candidates = _candidates(candidates)
    if at.tzinfo is None:
        raise ValueError('timezone_required')
    if (snapshot.get('policy') != 'synthetic-inputs-v1'
            or snapshot['patients'][0]['synthetic'] != 1):
        raise analyses.AnalysisError('Разрешены только синтетические истории.', 409, 'synthetic_only')
    # BE12 enforces source withdrawal/expiry, diagnostic freshness and risk gates.
    outcome, care = plans.evaluate(snapshot)
    inp = snapshot['care_plan_input']
    preconditions = []
    if not inp['review'] or not inp['review_fresh'] or not inp['review'].get('diagnosis') or inp['rejected']:
        preconditions.append({'code': 'physician_diagnosis_required',
                              'question': 'Нужно свежее решение врача о диагнозе; гипотеза не заменяет его.'})
    if not care or care['status'] != 'physician_diagnosis_draft':
        preconditions.append({'code': 'care_context_incomplete',
                              'question': 'Уточнить диагностические критерии и риски до выбора лекарств.',
                              'details': outcome['errors'] if care is None else care['missing_data']})
    patient = _patient(snapshot)
    reviews = []
    for index, candidate in enumerate(candidates):
        report = safety.evaluate(candidate, patient, at=at)
        safety.verify(candidate, patient, report, at=at)
        extra = []
        if candidate['indication'] != INDICATIONS.get(inp['condition']):
            extra.append({'code': 'diagnosis_indication_mismatch', 'state': 'block',
                          'question': 'Показание кандидата не соответствует точному подтверждённому диагнозу.'})
        # Preserve the original phase. Never relabel start/change/stop maintenance
        # just to pass the limited independent dose checker.
        if candidate['phase'] != 'maintenance':
            extra.append({'code': 'phase_not_supported', 'state': 'unknown',
                          'question': QUESTIONS['regimen_phase']})
        extra.append({'code': 'reconciliation_not_available', 'state': 'unknown',
                      'question': 'Нужна структурированная сверка назначения, фактического приёма, ответа и переносимости. Рассказ и торговое название не превращаются в дозу или отсутствие противопоказания.'})
        questions = [{'code': c['code'], 'question': QUESTIONS.get(c['code'], c['reason']),
                      'input_refs': c['input_refs'], 'source': c['source']}
                     for c in report['checks'] if c['state'] == 'unknown']
        questions.extend({'code': c['code'], 'question': c['question']} for c in extra if c['state'] == 'unknown')
        blocked = any(c['state'] == 'block' for c in [*report['checks'], *extra])
        product = safety.release()['products'].get(candidate['product_id'])
        src = safety.release()['sources'].get(product['source_id']) if product else None
        reviews.append({'id': 'candidate-' + str(index + 1), 'candidate': candidate,
                        'disposition': 'rejected' if blocked else 'clarification_required',
                        'recommendable': False, 'safety': report, 'additional_checks': extra,
                        'questions': questions,
                        # A locator for an inspected number is not a validated regimen.
                        'dose_source': None if src is None else {
                            'url': src['pdf_url'], 'sha256': src['pdf_sha256'],
                            'pages': src['locators']['dose'], 'role': 'numeric_check_only'},
                        'regimen_basis': None})
    return {'version': VERSION, 'status': 'development_incomplete',
            'snapshot_sha256': history.digest(snapshot), 'runtime': release(),
            'checked_at': at.isoformat(),
            'diagnosis_review_id': inp['review']['id'] if inp['review'] else None,
            'condition': inp['condition'], 'preconditions': preconditions,
            'care_status': care['status'] if care else outcome['status'],
            'candidate_reviews': reviews, 'recommendations': [],
            'clinical_release': False, 'applied': False, 'patient_published': False,
            'limitation': 'Внутренняя проверка кандидатов. Генерация лечения и положительная приёмка BE14 не выполнены.'}


def inspect(db, user, patient_id, candidates):
    """Read-only development call; caller cannot supply patient facts or refs.

    Authorization precedes input validation. Capture, diagnosis and history reads
    share one transaction. There is deliberately no public route or queue hook.
    """
    own_transaction = not db.in_transaction
    if own_transaction:
        db.execute('BEGIN')
    try:
        relationship = analyses.authorize(db, user, patient_id)
        candidates = _candidates(candidates)
        snapshot = json.loads(analyses.capture(db, patient_id, relationship, operation='plan'))
        result = _inspect(snapshot, candidates, at=datetime.now(timezone.utc))
        if own_transaction:
            db.commit()
        return result
    except BaseException:
        if own_transaction:
            db.rollback()
        raise
