"""Internal structured criteria checks, never a clinical diagnosis or model result.

The caller's assignments of meaning to quotations remain UNREVIEWED assertions.
This module checks provenance and threshold logic, not clinical truth. It has no
DB writer, model adapter, HTTP route or queue integration.
"""
from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path

from . import backend_diagnoses as candidates, backend_risk_context as context
from . import backend_snapshot as snapshots, backend_sources as sources

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / 'data/backend/diagnosis-criteria-v1.json'
VERSION = 'diagnosis-criteria-v1'
STATES = ('present', 'denied', 'unknown', 'conflicting')
LIMITATION = ('Проверены структура, происхождение цитат и формальные пороги авторских '
              'утверждений. Клинический смысл утверждений не проверен независимо. '
              'Это не установленный диагноз, оценка безопасности или план лечения.')


class CriteriaError(ValueError):
    pass


def release():
    """Validate a trusted local catalogue and its exact scoped content review."""
    value = json.loads(CATALOG.read_text())
    if (set(value) != {'version', 'mode', 'clinical_review', 'authorship', 'evidence',
                      'content_review', 'conditions'}
            or value['version'] != VERSION or value['mode'] != 'synthetic_only'
            or value['clinical_review'] is not None
            or set(value['conditions']) != {'depressive_episode', 'generalized_anxiety'}):
        raise CriteriaError('invalid_criteria_catalog')
    review = json.loads((ROOT / value['content_review']).read_text())
    if (review['catalog_sha256'] != snapshots.digest(value)
            or review['representation'] != 'independently_authored_facts'
            or review['quoted_characters'] != 0
            or review['independent_clinical_review'] is not False):
        raise CriteriaError('criteria_content_review_mismatch')
    for condition in value['conditions'].values():
        if set(condition) != {'source_id', 'admission_claim', 'condition', 'branch',
                              'duration', 'facts', 'checks', 'unsupported_if', 'limitations'}:
            raise CriteriaError('invalid_condition')
        facts = condition['facts']
        if not facts or len(facts) > 80 or len(facts) != len(set(facts)):
            raise CriteriaError('invalid_facts')
        duration = condition['duration']
        if (set(duration) != {'unit', 'minimum', 'section', 'pdf_page'}
                or duration['unit'] not in ('days', 'months')
                or type(duration['minimum']) is not int or duration['minimum'] < 1):
            raise CriteriaError('invalid_duration')
        for fact in facts.values():
            if (set(fact) != {'question', 'section', 'pdf_page', 'origin'}
                    or fact['origin'] not in ('source_criterion', 'hac_scope_policy')
                    or not fact['question'] or type(fact['pdf_page']) is not int
                    or not 1 <= fact['pdf_page'] <= 200):
                raise CriteriaError('invalid_fact_locator')
        checks = condition['checks']
        if not checks or len({c['id'] for c in checks}) != len(checks):
            raise CriteriaError('invalid_checks')
        for check in checks:
            if (set(check) != {'id', 'facts', 'state', 'minimum', 'origin', 'description', 'section', 'pdf_page'}
                    or type(check['pdf_page']) is not int or not 1 <= check['pdf_page'] <= 200
                    or not check['section']
                    or not check['facts'] or len(set(check['facts'])) != len(check['facts'])
                    or set(check['facts']) - set(facts)
                    or check['state'] not in ('present', 'denied')
                    or type(check['minimum']) is not int
                    or not 1 <= check['minimum'] <= len(check['facts'])
                    or check['origin'] not in ('source_criterion', 'hac_scope_policy')):
                raise CriteriaError('invalid_threshold')
        if (set(condition['unsupported_if']) - set(facts)
                or any(not any(fid in c['facts'] for c in checks) for fid in facts)):
            raise CriteriaError('uncovered_fact')
    return {**value, 'catalog_sha256': snapshots.digest(value),
            'engine_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'evidence_sha256': hashlib.sha256((ROOT / value['evidence']).read_bytes()).hexdigest(),
            'content_review_sha256': hashlib.sha256((ROOT / value['content_review']).read_bytes()).hexdigest()}


def _threshold(values, expected, minimum):
    matched = sum(v == expected for v in values)
    unknown = sum(v in ('unknown', 'conflicting') for v in values)
    if matched >= minimum:
        return 'met'
    if matched + unknown < minimum:
        return 'not_met'
    return 'conflicting' if 'conflicting' in values else 'unknown'


def _evidence(items, indexed, day):
    if not isinstance(items, list) or len(items) > 8:
        raise CriteriaError('invalid_evidence')
    if any(not isinstance(e, dict) or set(e) != {'unit_id', 'quote'}
           or not isinstance(e['unit_id'], str) or not isinstance(e['quote'], str)
           or not 1 <= len(e['quote']) <= 4000 for e in items):
        raise CriteriaError('invalid_evidence')
    checked = candidates._evidence(items, indexed)
    for e in checked:
        m = e['metadata']
        if (not isinstance(e['value'], str) or not e['value'].strip()
                or not set(e['categories']) & {'visits', 'wellbeing', 'anamnesis'}
                or m['current_revision'] is not True or m['event_at'] is None
                or m['status'] != 'known' or m['context'] != 'current'):
            raise CriteriaError('inapplicable_evidence')
        # Record date never supplies symptom duration; it only checks provenance.
        if date.fromisoformat(m['event_at'][:10]) > date.fromisoformat(day):
            raise CriteriaError('future_evidence')
    return checked


def _assertions(value, condition, indexed, day):
    if (not isinstance(value, dict) or set(value) != {'kind', 'facts', 'duration'}
            or not isinstance(value['facts'], dict)
            or set(value['facts']) != set(condition['facts'])):
        raise CriteriaError('incomplete_or_unknown_facts')
    facts = {}
    for fid, fact in value['facts'].items():
        if (not isinstance(fact, dict) or set(fact) != {'state', 'evidence'}
                or fact['state'] not in STATES):
            raise CriteriaError('invalid_assertion')
        evidence = _evidence(fact['evidence'], indexed, day)
        if ((fact['state'] == 'unknown') != (not evidence)
                or fact['state'] == 'conflicting' and len(evidence) < 2):
            raise CriteriaError('assertion_evidence_mismatch')
        facts[fid] = {**deepcopy(fact), 'evidence': evidence,
                      'basis': deepcopy(condition['facts'][fid]),
                      'interpretation': 'assertion_unreviewed'}
    duration = value['duration']
    if (not isinstance(duration, dict) or set(duration) != {'state', 'unit', 'value', 'evidence'}
            or duration['state'] not in ('known', 'unknown', 'conflicting')
            or duration['unit'] != condition['duration']['unit']):
        raise CriteriaError('invalid_duration_assertion')
    evidence = _evidence(duration['evidence'], indexed, day)
    if duration['state'] == 'known':
        if type(duration['value']) is not int or not 0 <= duration['value'] <= 50000 or not evidence:
            raise CriteriaError('invalid_duration_assertion')
        state = 'met' if duration['value'] >= condition['duration']['minimum'] else 'not_met'
    else:
        if (duration['value'] is not None or (duration['state'] == 'unknown') != (not evidence)
                or duration['state'] == 'conflicting' and len(evidence) < 2):
            raise CriteriaError('invalid_duration_assertion')
        state = duration['state']
    return facts, {**deepcopy(duration), 'evidence': evidence, 'check': state,
                   'basis': deepcopy(condition['duration']), 'interpretation': 'assertion_unreviewed'}


def evaluate(snapshot, assertions, *, synthetic=False):
    """Pure structured check. No default adapter, side effects or diagnosis fields.

    `present` / `denied` are explicit authored assertions with current quotations;
    matching a quote does not verify the assertion's clinical interpretation.
    """
    if synthetic is not True:
        raise CriteriaError('synthetic_only')
    frozen = deepcopy(snapshot)
    report = {'version': VERSION, 'status': 'not_evaluated', 'clinical_ready': False,
              'established_diagnosis': None, 'diagnosis_code': None, 'plan': None,
              'snapshot_sha256': snapshots.digest(frozen), 'catalog': None,
              'assessment': None, 'errors': [], 'limitation': LIMITATION}
    try:
        catalog = release()
        if not isinstance(assertions, dict) or assertions.get('kind') not in catalog['conditions']:
            raise CriteriaError('unsupported_kind')
        condition = catalog['conditions'][assertions['kind']]
        # Reuse the exact source/status/rights/age gate without changing BE10A.
        applicability = candidates._gate(frozen, {'domains': [condition]})
        units = context.prepare_snapshot(frozen)
        facts, duration = _assertions(assertions, condition, {u['unit_id']: u for u in units}, frozen['day'])
        checks = [{**deepcopy(c), 'check': _threshold(
            [facts[f]['state'] for f in c['facts']], c['state'], c['minimum'])}
            for c in condition['checks']]
        blocked = [f for f in condition['unsupported_if'] if facts[f]['state'] == 'present']
        # Conservative narrow scope policy. Conflicting or missing assertions
        # prevent a supported result even if a symptom count is already sufficient.
        unresolved = [f for f, a in facts.items() if a['state'] in ('unknown', 'conflicting')]
        states = [c['check'] for c in checks] + [duration['check']]
        if blocked:
            outcome = 'unsupported'
        elif 'not_met' in states:
            outcome = 'criteria_not_demonstrated'
        elif unresolved or any(s in ('unknown', 'conflicting') for s in states):
            outcome = 'insufficient_data'
        else:
            outcome = 'criteria_supported_unreviewed'
        questions = [facts[f]['basis']['question'] for f in unresolved]
        if duration['check'] in ('unknown', 'conflicting'):
            questions.append('Уточнить длительность одного текущего эпизода; дата записи её не устанавливает.')
        # Guard local source/catalog changes during validation as in BE10A.
        if catalog != release() or frozen.get('backend_sources') != sources.capture():
            raise CriteriaError('sources_or_criteria_changed')
        report.update(status='unreviewed', catalog=catalog, assessment={
            'kind': assertions['kind'], 'outcome': outcome, 'branch': condition['branch'],
            'facts': facts, 'duration': duration, 'checks': checks,
            'scope_blockers': blocked, 'unresolved_facts': unresolved,
            'distinguishing_questions': questions, 'applicability': applicability,
            'interpretation': 'structured_assertions_unreviewed'})
    except Exception as exc:
        # No provider body, clinical text, path or secret may enter an error.
        known = {'unsupported_kind', 'incomplete_or_unknown_facts', 'invalid_assertion',
                 'invalid_evidence', 'inapplicable_evidence', 'future_evidence',
                 'assertion_evidence_mismatch', 'invalid_duration_assertion',
                 'sources_or_criteria_changed', 'synthetic_only'}
        report['errors'] = [{'code': str(exc) if isinstance(exc, CriteriaError)
                            and str(exc) in known else 'criteria_input_or_source_invalid'}]
    return report
