"""Source-bound synthetic examination/observation drafts, never care actions.

The source of a diagnosis is a physician receipt or a pinned unreviewed analysis.
No narrative is parsed again here, and model assertions never become prescriptions.
"""
import hashlib
import json
from pathlib import Path

from . import backend_analyses as analyses, backend_diagnosis_review as reviews
from . import backend_diagnosis_service as diagnostic, backend_snapshot as snapshots
from . import backend_sources as sources, backend_risk_rules as risks

VERSION = 'care-plan-v1'
ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / 'data/backend/care-plan-v1.json'
CONDITIONS = {'depressive_episode': 'F32', 'generalized_anxiety': 'F41.1'}
LIMITATION = 'Синтетический проект для врача; клиническая проверка не выполнена. Применение, направление и публикация пациенту не выполняются.'


def release():
    value = json.loads(CATALOG.read_text())
    if (value['version'] != VERSION or value['mode'] != 'synthetic_only'
            or value['clinical_review'] is not None):
        raise ValueError('care_plan_catalog_not_admitted')
    return {'version': VERSION, 'catalog_sha256': snapshots.digest(value),
            'engine_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'evidence_sha256': hashlib.sha256((ROOT / value['evidence']).read_bytes()).hexdigest()}


def references(snapshot):
    if 'care_plan_input' not in snapshot:
        return []
    runtime = snapshot['care_plan_input']['runtime']
    return [{'id': 'be12-' + key, 'version': VERSION,
             'sha256': snapshots.digest({'item': item, 'runtime': runtime})}
            for key, item in json.loads(CATALOG.read_text())['items'].items()]


def prepare(db, user, patient_id, raw):
    """Run under a read/write snapshot. Pin dependencies without a second queue."""
    state = reviews.view(db, user, patient_id)
    current = state['current']
    receipt = current['receipt'] if current else None
    fresh = bool(current and current['fresh'])
    chosen = None
    diagnostic_report = None
    diagnostic_run = None
    # Latest result only: a newer incomplete evaluation cannot silently fall back.
    row = db.execute('''SELECT r.id,s.payload_json FROM analysis_runs r
        JOIN analysis_input_snapshots s ON s.id=r.snapshot_id
        WHERE r.patient_id=? AND r.relationship_id=? AND r.operation='diagnosis'
        ORDER BY r.created_at DESC,r.id DESC LIMIT 1''',
        (patient_id, analyses.authorize(db, user, patient_id))).fetchone()
    if row:
        value = analyses._latest(db, row['id'])
        context = value.get('diagnosis_context')
        if (value['status'] in ('ready', 'insufficient_data', 'unsupported')
                and context and context['runtime_sha256'] == snapshots.digest(diagnostic.release())
                and reviews._clinical_digest(row['payload_json']) == reviews._clinical_digest(raw)):
            diagnostic_report = diagnostic.interpret(json.loads(row['payload_json']), context['raw'])
            diagnostic_run = {'id': row['id'], 'revision': value['revision'],
                              'snapshot_id': snapshots.digest(json.loads(row['payload_json']))}
    if fresh and receipt['diagnosis'] is not None:
        code = receipt['diagnosis']['code']
        if receipt['action'] == 'accept':
            code = CONDITIONS.get(receipt['hypothesis_id'])
        chosen = code if code in ('F32', 'F33', 'F41.1') else None
    # Rejection must not silently resurrect a rejected hypothesis.
    rejected = bool(fresh and receipt and receipt['action'] == 'reject')
    if chosen is None and not receipt and diagnostic_report:
        chosen = CONDITIONS.get(diagnostic_report['leading'])
        if chosen is None:
            # An incomplete branch supplies clarification only, never a diagnosis.
            candidates = [h for h in diagnostic_report['hypotheses'][:2]
                if any(f['state'] == 'present' for f in h['facts'])
                and h['duration']['assertion']['value'] is not None]
            if len(candidates) == 1:
                chosen = CONDITIONS[candidates[0]['kind']]
    episodes = []
    for row in db.execute('''SELECT e.id,e.origin,e.topic,v.revision,v.state,v.payload_json
        FROM backend_risk_episodes e JOIN backend_risk_episode_versions v ON v.episode_id=e.id
        WHERE e.patient_id=? AND e.relationship_id=? AND v.revision=(
            SELECT max(v2.revision) FROM backend_risk_episode_versions v2 WHERE v2.episode_id=e.id)
        ORDER BY e.id''', (patient_id, analyses.authorize(db, user, patient_id))):
        episodes.append(dict(row))
    return {'runtime': release(), 'review': receipt, 'review_fresh': fresh,
            'condition': chosen, 'rejected': rejected,
            'diagnostic_run': diagnostic_run, 'diagnostic_report': diagnostic_report,
            'episodes': episodes}


def _failure(code, text, state='insufficient_data'):
    return {'status': state, 'result': None, 'model': None,
            'errors': [{'code': code, 'message': text, 'retryable': False}]}


def evaluate(snapshot):
    """Deterministic physician-facing draft from exact frozen, checked inputs."""
    inp = snapshot.get('care_plan_input')
    if inp is None or inp['runtime'] != release():
        raise ValueError('care_plan_input_unavailable')
    if (snapshot['policy'] != 'synthetic-inputs-v1'
            or snapshot['patients'][0]['synthetic'] != 1):
        return _failure('synthetic_only', 'Реальный клинический выпуск закрыт.', 'unsupported'), None
    low, high = risks._ages(snapshot)
    if not 18 <= low <= high <= 120:
        return _failure('care_plan_age', 'Нужен сверенный взрослый возраст.'), None
    if snapshot['backend_sources'] != sources.capture():
        raise sources.SourceError(['source_snapshot_changed'])
    # Source withdrawal/expiry blocks ALL new drafts, including conditional ones.
    for entry in snapshot['backend_sources']['sources'].values():
        if entry['reasons']:
            raise sources.SourceError(entry['reasons'])
    condition = inp['condition']
    report = inp['diagnostic_report']
    receipt = inp['review']
    if receipt and not inp['review_fresh']:
        return _failure('diagnosis_review_stale', 'Сведения изменились после решения врача; требуется повторная оценка диагноза.'), None
    if inp['rejected']:
        return _failure('diagnosis_rejected', 'Гипотеза отклонена. Нужны новая диагностическая оценка или собственный диагноз врача.'), None
    if condition is None:
        if receipt:
            return _failure('diagnosis_scope', 'Код собственного диагноза не входит в F32/F33/F41.1; автоматическое сопоставление текста не выполняется.', 'unsupported'), None
        # Preserve concrete questions from incomplete diagnosis, never generic items.
        if report:
            questions = list(dict.fromkeys(q for h in report['hypotheses'][:2] for q in h['distinguishing_questions']))
            text = 'Уточнить до выбора плана: ' + '; '.join(questions)
        else:
            text = 'Нет актуального диагностического разбора. Нужны анализ текущих сведений и оценка врача, включая причины симптомов и безопасность.'
        return _failure('diagnosis_incomplete', text[:1000]), None
    kind = 'generalized_anxiety' if condition == 'F41.1' else 'depressive_episode'
    prefix = 'gad' if condition == 'F41.1' else 'dep'
    sid = 'KR457_3' if prefix == 'gad' else 'KR301_3'
    claim = 'be03-' + sid + ('-F03' if prefix == 'gad' else '-F04')
    sources.require(snapshot['backend_sources'], [claim], 'plan', age_min=low, age_max=high, condition=condition)
    catalogue = json.loads(CATALOG.read_text())['items']
    hypothesis = next((h for h in report['hypotheses'][:2] if h['kind'] == kind), None) if report else None
    facts = {f['id']: f for f in hypothesis['facts']} if hypothesis else {}
    missing = [f['question'] for f in facts.values() if f['state'] in ('unknown', 'conflicting')]
    if hypothesis:
        definitions = {c['id']: c['description'] for c in diagnostic.criteria.release()['conditions'][kind]['checks']}
        missing.extend('Уточнить критерий: ' + definitions[c['id']] for c in hypothesis['checks'] if c['check'] != 'met')
    if hypothesis and hypothesis['duration']['check'] != 'met':
        missing.append('Уточнить длительность и непрерывность симптомов.')
    rule = risks.evaluate(snapshot)
    rule_result = rule.get('result')
    patterns = rule_result['output']['patterns'] if rule_result else []
    open_episodes = [e for e in inp['episodes'] if e['state'] == 'open']
    dangers = [f['id'] for f in facts.values() if f['id'] in (
        'self_harm', 'mania_hypomania', 'psychosis_stupor',
        'organic_cause', 'somatic_cause', 'medication_cause', 'substance_cause',
        'major_functional_impairment', 'marked_symptom_intensity') and f['state'] in ('present', 'conflicting')]
    blocked = bool(dangers or (hypothesis and hypothesis['scope_blockers']))
    risk_context, _ = risks._context(snapshot)
    risk_context_mismatch = bool(risk_context and risk_context['condition'] != condition)
    risk_unknown = risk_context_mismatch or rule['status'] != 'ready' or bool(rule_result and any(
        e['state'] == 'insufficient_data' for e in rule_result['output']['rule_evaluations']))
    caution = bool(patterns or open_episodes or risk_unknown or blocked)
    if risk_context:
        missing.extend('Уточнить фактор риска: ' + name for name in risks.FLAGS
            if risk_context[name] in ('unknown', 'conflicting'))
    if risk_context_mismatch:
        missing.append('Диагноз и структурированный контекст риска расходятся; требуется сверка врача.')
    if risk_unknown:
        missing.append('Нужна актуальная структурированная оценка риска: ' + '; '.join(e['message'] for e in rule.get('errors', [])))
    if not hypothesis:
        missing.append('Нет актуального разбора критериев для выбранного диагноза: уточнить симптомы, длительность, функционирование и альтернативные причины.')
    reviewed = bool(receipt and inp['review_fresh'] and receipt['diagnosis'])
    conditional = not reviewed or bool(missing) or caution
    evidence_ids = {abs(i) for f in facts.values() for i in [*f['refs'], *f['uncertainty_refs']]}
    if hypothesis:
        evidence_ids.update(abs(i) for i in hypothesis['duration']['assertion']['refs'])
    evidence = [e for e in report['evidence'] if e['id'] in evidence_ids] if report else []
    refs = sorted({e['source_ref'] for e in evidence})
    if risk_context:
        _, context_ref = risks._context(snapshot)
        refs = sorted(set(refs + [context_ref]))
    refs = refs or ['profile:' + snapshot['patients'][0]['id']]
    if len(refs) > 50:
        return _failure('care_plan_evidence_limit', 'Слишком много оснований для безопасной публикации проекта.'), None
    items = []
    def add(key, reason, necessity='conditional', questions=None):
        c = catalogue[key]
        source = snapshot['backend_sources']['sources'][c['source_id']]['source']
        items.append({'id': 'be12-' + key, 'kind': c['kind'], 'text': c['text'], 'goal': c['goal'],
            'basis': reason, 'condition': condition,
            'diagnosis_review_id': receipt['id'] if receipt else None,
            'diagnosis_run_id': inp['diagnostic_run']['id'] if inp['diagnostic_run'] else None,
            'evidence_refs': refs, 'questions': questions or [], 'necessity': necessity,
            'source': {'id': c['source_id'], 'claim_id': 'be12-' + key,
                'pdf_sha256': source['sha256'], 'pdf_page': c['pdf_page'], 'section': c['section']},
            'timing': {'interval_days': None, 'selection': 'physician_required',
                'basis': 'Периодичность выбирает врач по состоянию, рискам и выбранному методу; общий числовой срок этим основанием не установлен.'}})
    if not reviewed:
        add(prefix + '-diagnosis', 'Гипотеза ещё не принята врачом; уточнить её критерии и альтернативы до выбора помощи.',
            'required_evaluation', missing or [f['question'] for f in facts.values() if f['state'] == 'present'])
    if caution:
        add(prefix + '-risk', 'Риск неизвестен либо имеются положительные/противоречивые признаки и открытые эпизоды. Отсутствие сигнала не доказывает безопасность.', 'required_evaluation')
    if patterns or open_episodes or blocked:
        add(prefix + '-route', 'Сигналы: ' + ', '.join([p['id'] for p in patterns] + dangers + [e['topic'] for e in open_episodes]), 'required_evaluation')
    if prefix == 'dep' and (not facts or facts.get('mania_hypomania', {}).get('state') != 'denied'):
        add('dep-mania', 'Мания/гипомания не исключены подтверждёнными сведениями.', questions=['Были ли мания, гипомания или смешанные эпизоды?'])
    causes = ('organic_cause', 'somatic_cause', 'medication_cause', 'substance_cause')
    if not facts or any(facts[k]['state'] != 'denied' for k in causes if k in facts):
        add(prefix + '-medical', 'Причины симптомов не исключены. Перечень анализов и инструментальных исследований автоматически не создаётся.', questions=missing)
    for f in facts.values():
        if f['state'] not in ('unknown', 'conflicting'):
            continue
        add(prefix + '-diagnosis', 'Критерий неизвестен или противоречив: ' + f['id'],
            'required_evaluation', [f['question']])
        # Exact criterion locator comes from the independently checked BE10 projection.
        item = items[-1]
        item['id'] = 'be12-' + prefix + '-clarify-' + f['id']
        item['text'] = f['question']
        item['source'].update(pdf_page=f['pdf_page'], section=f['section'])
    if not conditional:
        add(prefix + '-therapy', 'Есть свежее решение врача и непротиворечивые критерии; метод и возможность участия ещё согласуются.', 'recommended_discussion')
        add(prefix + '-education', 'Есть выбранный врачом диагноз; конкретные меры определяются при обсуждении.', 'recommended_discussion')
    # Conditional draft never prescribes treatment. Observation is physician reassessment.
    add(prefix + '-monitor', 'Оценка ответа и безопасности после уточнения диагноза/выбора помощи; изменения риска, состояния или переносимости требуют пересмотра.',
        'conditional' if conditional else 'recommended_discussion', questions=missing)
    detail = {'version': VERSION, 'status': 'conditional_clarification' if conditional else 'physician_diagnosis_draft',
        'condition': condition, 'diagnosis_review_id': receipt['id'] if receipt else None,
        'diagnosis_run_id': inp['diagnostic_run']['id'] if inp['diagnostic_run'] else None,
        'diagnosis_reviewed': reviewed, 'missing_data': list(dict.fromkeys(missing)),
        'risk_status': 'attention_required' if patterns or open_episodes or blocked else 'unknown' if risk_unknown else 'no_rule_match_not_safety',
        'risk_patterns': [p['id'] for p in patterns], 'open_episode_ids': [e['id'] for e in open_episodes],
        'items': items, 'review_conditions': ['Новые или противоречивые сведения.', 'Новый сигнал риска или ухудшение состояния.', 'Отсутствие ожидаемого ответа либо нежелательные явления.'],
        'clinical_ready': False, 'applied': False, 'patient_published': False, 'limitation': LIMITATION}
    result = {'summary': LIMITATION, 'facts': [{'id': 'case', 'text': 'Основания текущего проекта; состояние ' + condition, 'evidence_refs': refs}],
        'contradictions': [f['question'] for f in facts.values() if f['state'] == 'conflicting'],
        'missing_data': detail['missing_data'], 'output': {'diagnosis_run_id': detail['diagnosis_run_id'],
            'diagnosis_review_id': detail['diagnosis_review_id'], 'items': [
                {'id': i['id'], 'text': i['text'], 'fact_ids': ['case'], 'source_ids': [i['source']['claim_id']]} for i in items]}}
    return {'status': 'ready', 'result': result, 'errors': [], 'model': None}, detail


def execute(operation, snapshot, model=None):
    if operation != 'plan':
        raise ValueError('operation_unavailable')
    outcome, detail = evaluate(snapshot)
    context = {'version': VERSION, 'runtime_sha256': snapshots.digest(release()), 'report': detail}
    if 'therapy_input' in snapshot:
        from . import backend_therapy
        outcome, extension = backend_therapy.execute_extension(snapshot, outcome, detail, model=model)
        context['therapy'] = extension
    return {**outcome, 'care_plan_context': context}


def verify(snapshot, outcome, context):
    # Recompute publication from the recorded model JSON; never call the model
    # a second time inside the lease/database transaction.
    base, detail = evaluate(snapshot)
    expected_context = {'version': VERSION, 'runtime_sha256': snapshots.digest(release()), 'report': detail}
    if 'therapy_input' in snapshot:
        from . import backend_therapy
        extension = context.get('therapy')
        if extension is None:
            raise analyses.AnalysisError('Нет лекарственной проверки.', 409, 'therapy_result_mismatch')
        backend_therapy.verify_extension(snapshot, base, detail, extension, expected_outcome=outcome)
        expected_context['therapy'] = extension
    elif base != outcome:
        raise analyses.AnalysisError('Проект плана не совпадает с проверенными основаниями.', 409, 'care_plan_mismatch')
    if context != expected_context:
        raise analyses.AnalysisError('Контекст плана изменён.', 409, 'care_plan_mismatch')
