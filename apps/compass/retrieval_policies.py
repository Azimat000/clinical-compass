"""HAC constraints are project evidence, never Ministry or clinical evidence."""
import json
from datetime import timedelta

from .retrieval_corpus import CorpusError, digest, local_file, moment, sha

REGISTRY = 'data/retrieval/hac-policy-registry.json'
RECORD_PREFIX = 'data/retrieval/policy-evidence/'
SPEC = 'docs/architecture/retrieval-policy-evidence.md'
POLICY_ONLY = frozenset('''confirmed_course_and_dates unknown_or_conflicting_context
missing_data comparable_measurements time_overlap patient_and_physician_provenance
no_automatic_failure_threshold no_DASS_threshold course_and_dates absence_not_exclusion
no_causality_or_severity_inference no_class_substitution unknown_requires_review
not_comprehensive_pair_checker unknown_co_medication coverage_limits no_absence_of_risk_claim
explicit_patient_record course_linkage reasons_and_dates missing_not_missed
no_compensating_dose_from_search physician_confirmation no_automatic_taper independent_safety_path
no_urgency_from_RAG search_must_not_delay_existing_response missing_not_no_risk
explicit_unavailability no_model_or_network_fallback no_diagnosis_from_question uncertainty
no_cross_diagnosis_transfer physician_confirmed_plan no_unapproved_protocol no_invented_window
withdraw_affected_material complete_same_form overlapping_periods patient_no_computed_scores'''.split())
MIXED = frozenset('''no_diagnosis_from_score three_separate_scores_for_physician
no_diagnostic_or_medication_threshold age_boundary text_rights_separately'''.split())
POLICY_IDS = POLICY_ONLY | MIXED
INSTRUMENT_REQUIRED = {
    'exact_Russian_form_and_key': {'DASS42_RU_FORM', 'DASS42_EN_KEY', 'DASS42_RU_TRANSLATION'},
    'validation_population': {'DASS42_RU_VALIDATION_2025'},
    'text_rights_separately': {'DASS42_GUIDANCE', 'DASS42_DOWNLOAD_TERMS'},
    'recall_period': {'DASS42_RU_FORM'},
    'age_boundary': {'DASS42_RU_VALIDATION_2025', 'DASS42_GUIDANCE'},
    'three_separate_scores_for_physician': {'DASS42_EN_KEY'},
    'no_diagnostic_or_medication_threshold': {'DASS42_GUIDANCE'},
    'no_diagnosis_from_score': {'DASS42_GUIDANCE'},
}

CHECK_FILES = {'apps/tests/test_assessments.py', 'apps/tests/test_decisions.py',
               'apps/tests/test_retrieval_primary.py', 'tools/test_retrieval_policies.py'}
CODE_FILES = {'apps/compass/assessments.py', 'apps/compass/decisions.py',
              'apps/compass/retrieval_corpus.py', 'apps/compass/retrieval_primary.py',
              'tools/check_retrieval_coverage.py'}


def instrument_requirements(unit, aspect):
    """Same aspect spelling in FU08 refers to drug age, not DASS age."""
    if unit['kind'] != 'cell':
        return None
    domain = unit['requirement'].get('domain')
    if domain == 'D12' or (domain == 'D02' and aspect == 'no_diagnosis_from_score'):
        return INSTRUMENT_REQUIRED.get(aspect)
    return None


def aspect_mode(unit, aspect):
    # Dossiers and drug-specific age always require their own clinical sources.
    if unit['kind'] != 'cell':
        return 'clinical'
    if aspect in MIXED:
        return 'mixed' if instrument_requirements(unit, aspect) is not None else 'clinical'
    return 'policy' if aspect in POLICY_ONLY else 'clinical'


def validate_policy_reference(root, ref, unit_id, unit, aspect, frozen, at):
    if not isinstance(ref, dict) or set(ref) != {'policy_id', 'record_sha256'} or ref['policy_id'] != aspect or aspect not in POLICY_IDS or aspect_mode(unit, aspect) == 'clinical':
        raise CorpusError('policy_cannot_replace_clinical_source')
    registry = json.loads(local_file(root, REGISTRY, {REGISTRY}))
    if set(registry) != {'schema_version', 'scope_version', 'policies'} or registry['schema_version'] != 1 or registry['scope_version'] != frozen['scope_version'] or not isinstance(registry['policies'], list):
        raise CorpusError('policy_registry_schema')
    ids = [row['policy_id'] for row in registry['policies']]
    if len(ids) != len(set(ids)) or any(i not in POLICY_IDS for i in ids):
        raise CorpusError('policy_registry_identity')
    pins = [row for row in registry['policies'] if row['policy_id'] == aspect]
    if len(pins) != 1 or set(pins[0]) != {'policy_id', 'record_path', 'record_sha256', 'status'}:
        raise CorpusError('policy_not_registered')
    pin = pins[0]
    expected_path = RECORD_PREFIX + aspect + '.json'
    if pin['status'] != 'approved' or pin['record_path'] != expected_path or pin['record_sha256'] != ref['record_sha256']:
        raise CorpusError('policy_changed_or_revoked')
    data = local_file(root, expected_path, {expected_path})
    if sha(data) != pin['record_sha256']:
        raise CorpusError('policy_record_integrity')
    record = json.loads(data)
    fields = {'schema_version', 'policy_id', 'scope_version', 'statement', 'origin', 'reviewer',
              'checked_at', 'review_due_at', 'assurance', 'bindings', 'support', 'verification'}
    if set(record) != fields or record['schema_version'] != 1 or record['scope_version'] != frozen['scope_version'] or record['policy_id'] != aspect:
        raise CorpusError('policy_record_schema')
    if record['origin'] != 'HAC_PROJECT_POLICY' or not all(isinstance(record[k], str) and record[k].strip() for k in ['statement', 'origin', 'reviewer']):
        raise CorpusError('policy_origin_missing')
    if not moment(record['checked_at']) <= at < moment(record['review_due_at']):
        raise CorpusError('policy_review_expired')
    if record['assurance'] not in {'documented_constraint', 'tested_existing_control'}:
        raise CorpusError('policy_assurance_unknown')
    expected_binding = {'unit_id': unit_id, 'aspect': aspect, 'requirement_sha256': digest(unit['requirement'])}
    if not isinstance(record['bindings'], list) or expected_binding not in record['bindings'] or not all(set(b) == set(expected_binding) for b in record['bindings']):
        raise CorpusError('policy_requirement_mismatch')
    if not isinstance(record['support'], list) or not record['support']:
        raise CorpusError('policy_support_missing')
    spec_found = False
    code_found = False
    for proof in record['support']:
        if set(proof) != {'path', 'sha256', 'locator'} or not isinstance(proof['locator'], str) or not proof['locator']:
            raise CorpusError('policy_support_schema')
        path = proof['path']
        if path not in CODE_FILES | {SPEC}:
            raise CorpusError('policy_support_path')
        body = local_file(root, path, {path})
        if sha(body) != proof['sha256'] or proof['locator'].encode() not in body:
            raise CorpusError('policy_support_changed')
        if path == SPEC:
            section = body.split(proof['locator'].encode(), 1)[1].split(b'\n## policy:', 1)[0]
            if record['statement'].encode() not in section:
                raise CorpusError('policy_statement_not_in_spec')
        spec_found |= path == SPEC
        code_found |= path in CODE_FILES
    if not spec_found:
        raise CorpusError('policy_spec_missing')
    verification = record['verification']
    if record['assurance'] == 'documented_constraint':
        if verification is not None:
            raise CorpusError('declared_policy_not_runtime_test')
    else:
        if not code_found or not isinstance(verification, dict) or set(verification) != {'test_path', 'test_sha256', 'test_name', 'run_path', 'run_sha256'}:
            raise CorpusError('policy_test_evidence_missing')
        if verification['test_path'] not in CHECK_FILES:
            raise CorpusError('policy_test_path')
        body = local_file(root, verification['test_path'], {verification['test_path']})
        if sha(body) != verification['test_sha256'] or ('def ' + verification['test_name'] + '(').encode() not in body:
            raise CorpusError('policy_test_changed')
        run_path = verification['run_path']
        if run_path != 'evidence/S17J02B02/policy-control-tests.json':
            raise CorpusError('policy_test_run_path')
        data = local_file(root, run_path, {run_path})
        if sha(data) != verification['run_sha256']:
            raise CorpusError('policy_test_run_changed')
        run = json.loads(data)
        if run.get('exit_code') != 0 or run.get('status') != 'PASS' or not isinstance(run.get('command'), str) or not run['command'].strip():
            raise CorpusError('policy_test_run_failed')
        selected = verification['test_path'] + '::' + verification['test_name']
        if selected not in run.get('tests', []):
            raise CorpusError('policy_test_not_run')
        log_path = run['log_path']
        if log_path != 'evidence/S17J02B02/policy-control-tests.log' or sha(local_file(root, log_path, {log_path})) != run['log_sha256']:
            raise CorpusError('policy_test_log_changed')
        if not moment(record['checked_at']) - timedelta(days=1) <= moment(run['checked_at']) <= moment(record['checked_at']):
            raise CorpusError('policy_test_date')
    return record
