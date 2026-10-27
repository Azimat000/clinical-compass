"""Small source-bound catalogue. Offline checks; no search, signatures or clinical release.

Administrator files are trusted configuration, never model/HTTP input. Reuse the
existing admission/rights/receipt gates without importing the optional RAG corpus.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from .retrieval_corpus import (CorpusError, admission_reasons, digest, local_file,
                               moment, reference_reasons, sha)

ROOT = Path(__file__).resolve().parents[2]
CATALOG = 'data/backend/source-catalog-v1.json'
REGISTRY = 'data/retrieval/source-registry.json'
OPERATIONS = {'risk', 'diagnosis', 'plan'}


class SourceError(ValueError):
    def __init__(self, reasons):
        self.reasons = sorted(set(reasons))
        super().__init__('; '.join(self.reasons))


def clock():
    return datetime.now(timezone.utc)


def _json(root, path):
    return json.loads(local_file(root, path, {path}))


def _fields(value, fields):
    if not isinstance(value, dict) or set(value) != set(fields.split()):
        raise SourceError(['catalog_schema'])


def capture(*, root=None, at=None):
    """Freeze metadata, exact claims and current reasons, never the full PDF text."""
    root, at = root or ROOT, at or clock()
    try:
        catalog = _json(root, CATALOG)
        _fields(catalog, 'version mode clinical_review sources claims')
        if (catalog['version'] != 'backend-sources-v1' or catalog['mode'] != 'synthetic_only'
                or catalog['clinical_review'] is not None):
            raise SourceError(['clinical_release_unavailable'])
        registry = _json(root, REGISTRY)
        items = {i['document_id']: i for i in registry['sources']}
        if len(items) != len(registry['sources']):
            raise SourceError(['duplicate_source'])
        report = {'version': catalog['version'], 'mode': 'synthetic_only',
                  'clinical_review': None, 'catalog_sha256': digest(catalog),
                  'engine_sha256': digest({name: sha(Path(__file__).with_name(name).read_bytes())
                      for name in ('backend_sources.py', 'retrieval_corpus.py', 'retrieval_primary.py')}),
                  'sources': {}, 'claims': {}}
        for pin in catalog['sources']:
            _fields(pin, 'id registry_sha256 age_min age_max conditions status verification')
            sid = pin['id']
            if sid in report['sources']:
                raise SourceError(['duplicate_source'])
            if (type(pin['age_min']) is not int or type(pin['age_max']) is not int
                    or not 18 <= pin['age_min'] <= pin['age_max'] <= 120
                    or not isinstance(pin['conditions'], list) or not pin['conditions']
                    or not all(isinstance(c, str) and c for c in pin['conditions'])):
                raise SourceError(['invalid_applicability'])
            proof = pin['verification']
            _fields(proof, 'path sha256 checked_at review_due_at current_status')
            reasons = []
            item = items.get(sid)
            entry = {'pin': deepcopy(pin), 'source': deepcopy(item), 'reasons': reasons}
            report['sources'][sid] = entry
            if pin['status'] != 'registered':
                reasons.append('source_' + str(pin['status']))
            if proof['current_status'] != 'current':
                reasons.append('current_status_unconfirmed_or_withdrawn')
            if not (moment(proof['checked_at']) <= at < moment(proof['review_due_at'])
                    <= moment(proof['checked_at']) + timedelta(days=1)):
                reasons.append('current_status_review_expired')
            try:
                if sha(local_file(root, proof['path'], {proof['path']})) != proof['sha256']:
                    reasons.append('current_status_evidence_changed')
            except (OSError, CorpusError):
                reasons.append('current_status_evidence_missing')
            if item is None:
                reasons.append('source_removed')
                continue
            if digest(item) != pin['registry_sha256']:
                reasons.append('source_metadata_changed')
            # Preserve the original provenance/rights gates too. Only its old
            # freshness deadline is superseded by the new scoped receipt.
            reasons.extend(r for r in admission_reasons(item, at, evidence_root=root)
                           if r != 'review_expired_or_invalid')
            # New scoped status/unchanged-byte receipt; preserve the historical
            # registry and its old deadlines. Rights remain pinned and unchanged.
            effective = deepcopy(item)
            effective['verified_at'] = proof['checked_at']
            effective['review_due_at'] = proof['review_due_at']
            effective['verification'].update(checked_at=proof['checked_at'],
                evidence=[proof['path']], evidence_sha256=proof['sha256'])
            entry['effective_verification'] = deepcopy(effective['verification'])
            entry['effective_review_due_at'] = proof['review_due_at']
            reasons.extend(admission_reasons(effective, at, evidence_root=root))
            for field, hash_field in [('path', 'sha256'), ('artifact_path', 'artifact_sha256')]:
                try:
                    data = local_file(root, item[field], {item[field]})
                    if sha(data) != item[hash_field]:
                        reasons.append('source_bytes_changed:' + field)
                    if field == 'artifact_path':
                        reasons.extend(reference_reasons(item, data))
                except (OSError, CorpusError, KeyError):
                    reasons.append('source_missing:' + field)
            reasons[:] = sorted(set(reasons))
        if not report['sources']:
            raise SourceError(['empty_catalog'])
        for claim in catalog['claims']:
            _fields(claim, 'id source_id fragment_id operation text_sha256 section page')
            if (claim['id'] in report['claims'] or claim['operation'] not in OPERATIONS
                    or claim['source_id'] not in report['sources']):
                raise SourceError(['invalid_claim_binding'])
            source = report['sources'][claim['source_id']]
            reasons = list(source['reasons'])
            text = None
            try:
                item = source['source']
                cards = _json(root, item['artifact_path'])
                fragments = [f for f in cards['fragments'] if f['fragment_id'] == claim['fragment_id']]
                if len(fragments) != 1:
                    raise SourceError(['claim_fragment_missing'])
                fragment = fragments[0]
                text = fragment['paraphrase']
                if (sha(text.encode()) != claim['text_sha256'] or fragment['page'] != claim['page']
                        or fragment['section'] != claim['section']):
                    reasons.append('claim_text_or_locator_changed')
            except (OSError, CorpusError, SourceError, TypeError, KeyError):
                reasons.append('claim_fragment_missing')
            report['claims'][claim['id']] = {'binding': deepcopy(claim), 'text': text,
                                            'reasons': sorted(set(reasons))}
        if not report['claims']:
            raise SourceError(['empty_claims'])
        return report
    except SourceError:
        raise
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        raise SourceError(['source_catalog_unavailable_or_invalid']) from None


def references(report):
    return [{'id': cid, 'version': report['version'],
             'sha256': digest({'claim': c, 'source': report['sources'][c['binding']['source_id']]})}
            for cid, c in report['claims'].items()]


def require(report, claim_ids, operation, *, age_min, age_max, condition, mode='synthetic_only'):
    """Trusted structured context, not extracted narrative. Unknowns fail closed."""
    reasons = []
    if mode != 'synthetic_only' or report.get('mode') != 'synthetic_only' or report.get('clinical_review') is not None:
        raise SourceError(['clinical_release_unavailable'])
    if not claim_ids:
        raise SourceError(['claim_required'])
    for cid in claim_ids:
        claim = report['claims'].get(cid)
        if claim is None:
            reasons.append('claim_not_registered')
            continue
        reasons.extend(claim['reasons'])
        binding = claim['binding']
        if binding['operation'] != operation:
            reasons.append('claim_operation_mismatch')
        pin = report['sources'][binding['source_id']]['pin']
        if (type(age_min) is not int or type(age_max) is not int or age_min > age_max
                or age_min < pin['age_min'] or age_max > pin['age_max']):
            reasons.append('source_age_unknown_or_inapplicable')
        if condition not in pin['conditions']:
            reasons.append('source_indication_unknown_or_inapplicable')
    if reasons:
        raise SourceError(reasons)


def check_result(frozen, operation, result, *, root=None, context=None, snapshot=None):
    """Final server check. No arbitrary assertion can borrow a valid citation.

    v1 permits only exact registered authored statements. Patient-specific clinical
    rules and supported generated claims are added in BE07/10/12/13/14.
    """
    context = context or {}
    current = capture(root=root)
    if frozen != current:
        raise SourceError(['source_snapshot_changed'])
    if operation == 'risk' and snapshot is not None and 'rule_evaluations' in result['output']:
        from . import backend_risk_rules
        backend_risk_rules.verify(snapshot, result)
        return current
    if operation == 'diagnosis' and snapshot is not None and context.get('diagnosis_context') is not None:
        from . import backend_diagnosis_service as diagnostic
        saved = context['diagnosis_context']
        report = diagnostic.interpret(snapshot, saved['raw'])
        expected, _ = diagnostic.publication(snapshot, {'context': report})
        if diagnostic.projection(report) != saved or expected['status'] != 'ready' or expected['result'] != result:
            raise SourceError(['diagnosis_result_mismatch'])
        return current
    if operation == 'plan' and context.get('care_plan_context') is not None:
        from . import backend_care_plan
        saved = context['care_plan_context']
        expected, detail = backend_care_plan.evaluate(snapshot)
        if 'therapy_input' in snapshot:
            from . import backend_therapy
            extension = saved.get('therapy')
            if extension is None:
                raise SourceError(['therapy_check_missing'])
            expected, _ = backend_therapy.enrich(snapshot, expected, detail, extension['raw'],
                checked_at=extension['checked_at'], metadata=extension['model_metadata'])
        if expected.get('result') != result:
            raise SourceError(['care_plan_result_mismatch'])
        return current
    output = result['output']
    findings = (output['patterns'] if operation == 'risk' else
                [output['leading'], *output['alternatives']] if operation == 'diagnosis' else output['items'])
    if not findings:
        raise SourceError(['negative_risk_rule_not_implemented'])
    for finding in findings:
        ids = finding['source_ids']
        if not ids:
            raise SourceError(['claim_required'])
        # Patient context is deliberately not inferred here; functions supplying
        # patient-specific conclusions must add their own checked applicability.
        for cid in ids:
            claim = current['claims'].get(cid)
            if claim is None:
                raise SourceError(['claim_not_registered'])
            require(current, [cid], operation, age_min=context.get('age_min'),
                    age_max=context.get('age_max'), condition=context.get('condition'))
            if finding['text'] != claim['text']:
                raise SourceError(['claim_text_mismatch'])
    return current
