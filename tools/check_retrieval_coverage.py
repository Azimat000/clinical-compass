#!/usr/bin/env python3
"""COVERAGE-1: frozen denominators and evidence integrity, not medical approval."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from apps.compass.retrieval_corpus import (CorpusError, digest, eligible_sources,
    local_file, moment, reference_reasons, sha)
from apps.compass.retrieval_packages import package_registry
from apps.compass.retrieval_policies import (aspect_mode, validate_policy_reference, instrument_requirements)
from apps.compass.retrieval_primary import TYPES as PRIMARY_TYPES

MATRIX = 'data/retrieval/coverage-matrix.json'
MEDICATIONS = 'data/retrieval/planned-medications.json'
FREEZE = 'data/retrieval/coverage-freeze.json'
EVIDENCE = 'data/retrieval/coverage-evidence.json'
DIRECTIONS = {'depression', 'generalized_anxiety_disorder'}
DOMAINS = {f'D{i:02}' for i in range(1, 13)}
FU = {f'FU{i:02}' for i in range(1, 9)}


def read(root, relative):
    return json.loads(local_file(root, relative, {relative}))


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def unique(rows, key='id'):
    if not isinstance(rows, list) or not rows:
        raise CorpusError('empty_denominator')
    values = [r[key] for r in rows]
    if not all(nonempty(v) for v in values) or len(values) != len(set(values)):
        raise CorpusError('duplicate_or_invalid_identity')
    return values


def scope(root):
    frozen, matrix, meds = read(root, FREEZE), read(root, MATRIX), read(root, MEDICATIONS)
    if frozen['schema_version'] != 1 or set(frozen['files']) != {MATRIX, MEDICATIONS}:
        raise CorpusError('freeze_schema')
    for path, expected in frozen['files'].items():
        if sha(local_file(root, path, {path})) != expected:
            raise CorpusError('frozen_scope_changed:' + path)
    if matrix['schema_version'] != 1 or meds['schema_version'] != 1:
        raise CorpusError('scope_schema')
    if set(matrix['directions']) != DIRECTIONS or set(matrix['fu_ids']) != FU or set(unique(matrix['domains'])) != DOMAINS:
        raise CorpusError('scope_incomplete')
    cells, medications = matrix['cells'], meds['medications']
    unique(cells); unique(medications); unique(matrix['mandatory_refusals'])
    seen_fu, seen_domain_direction = set(), set()
    units = {}
    for cell in cells:
        if cell['required'] is not True or cell['domain'] not in DOMAINS or cell['direction'] not in DIRECTIONS:
            raise CorpusError('cell_scope_invalid')
        if not all(nonempty(cell[k]) for k in ('question', 'stage', 'population', 'sufficient_bundle')):
            raise CorpusError('cell_context_missing')
        if not isinstance(cell['fu_ids'], list) or not cell['fu_ids'] or not set(cell['fu_ids']) <= FU:
            raise CorpusError('cell_fu_invalid')
        seen_fu.update(cell['fu_ids']); seen_domain_direction.add((cell['domain'], cell['direction']))
        aspects = cell['required_aspects']
        if not isinstance(aspects, list) or not aspects or len(set(aspects)) != len(aspects) or not all(nonempty(a) for a in aspects):
            raise CorpusError('empty_sufficient_bundle')
        units[cell['id']] = {'kind': 'cell', 'aspects': aspects, 'requirement': cell}
    if seen_fu != FU or seen_domain_direction != {(d, direction) for d in DOMAINS for direction in DIRECTIONS}:
        raise CorpusError('domain_direction_or_fu_gap')
    sections = meds['required_sections']
    if not isinstance(sections, list) or not sections or len(set(sections)) != len(sections) or set(sections) != set(meds['section_aspects']):
        raise CorpusError('dossier_sections_missing')
    for med in medications:
        if med['required'] is not True or not nonempty(med['inn']) or med['required_sections'] != sections or not med['selection_basis']:
            raise CorpusError('medication_scope_invalid')
        targets = med['registration_targets']
        if not isinstance(targets, list) or not targets:
            raise CorpusError('medication_research_target_missing')
        for target in targets:
            if not isinstance(target, dict) or not all(nonempty(target[k]) for k in ('trade_name', 'registration', 'form', 'route', 'official_url', 'status')):
                raise CorpusError('medication_research_target_invalid')
            if not isinstance(target['strengths'], list) or not target['strengths'] or not all(nonempty(v) for v in target['strengths']):
                raise CorpusError('medication_research_strengths_missing')
            url = urlsplit(target['official_url'])
            if url.scheme != 'https' or url.hostname not in {'grls.rosminzdrav.ru', 'grls.rosminzdrav.gov.ru', 'pots.minzdrav.gov.ru'} or url.username or url.password:
                raise CorpusError('medication_research_official_link_missing')
        for selection in med['selection_basis']:
            if not nonempty(selection['document_id']) or not nonempty(selection['section']) or not selection['pdf_pages'] or not all(type(p) is int and p > 0 for p in selection['pdf_pages']):
                raise CorpusError('medication_selection_missing')
        for section in sections:
            aspects = meds['section_aspects'][section]
            if not aspects or not all(nonempty(a) for a in aspects) or len(set(aspects)) != len(aspects):
                raise CorpusError('empty_sufficient_bundle')
            unit_id = med['id'] + '/' + section
            if unit_id in units:
                raise CorpusError('unit_collision')
            units[unit_id] = {'kind': 'dossier', 'aspects': aspects, 'medication': med,
                             'requirement': {'medication': med, 'section': section, 'aspects': aspects}}
    counts = {'required_cells': len(cells), 'required_medications': len(medications),
              'required_dossier_sections': len(medications) * len(sections),
              'required_refusals': len(matrix['mandatory_refusals'])}
    if any(type(frozen[k]) is not int or frozen[k] <= 0 or frozen[k] != v for k, v in counts.items()):
        raise CorpusError('frozen_denominator_mismatch')
    if any(r['required'] is not True or not nonempty(r['trigger']) or not nonempty(r['expected_reason']) for r in matrix['mandatory_refusals']):
        raise CorpusError('refusal_scope_invalid')
    return frozen, matrix, meds, units


def card_catalog(snapshot, registry, at, root):
    eligibility = eligible_sources(snapshot, registry, at.isoformat(), evidence_root=root)
    catalog = {}
    for item in eligibility['admitted']:
        if item.get('representation') != 'reviewed_cards':
            continue  # Full-text reference adapter is not yet accepted in J03.
        data = (Path(snapshot) / (item['artifact_sha256'] + '.json')).read_bytes()
        if reference_reasons(item, data):
            raise CorpusError('reference_changed')
        for fragment in json.loads(data)['fragments']:
            catalog[(item['document_id'], fragment['fragment_id'])] = (item, fragment)
    return catalog, eligibility


def validate_review(root, unit_id, unit, pointer, catalog, frozen, at):
    """A human-authored attestation is required; hashes do not prove its truth."""
    if not isinstance(pointer, dict) or set(pointer) != {'review_path', 'review_sha256'}:
        raise CorpusError('review_pointer_invalid')
    data = local_file(root, pointer['review_path'], {pointer['review_path']})
    if sha(data) != pointer['review_sha256']:
        raise CorpusError('review_integrity')
    review = json.loads(data)
    fields = {'schema_version', 'scope_version', 'unit_id', 'requirement_sha256', 'verdict',
              'reviewer', 'origin', 'sufficiency_explanation', 'checked_at', 'review_due_at', 'aspects'}
    if unit['kind'] == 'dossier':
        fields.add('medication_identity')
        if unit_id.endswith('/safety_updates_and_version_status'):
            fields.add('safety_check')
    if not isinstance(review, dict) or set(review) != fields or review['schema_version'] not in (1, 2):
        raise CorpusError('review_schema')
    if review['scope_version'] != frozen['scope_version'] or review['unit_id'] != unit_id or review['requirement_sha256'] != digest(unit['requirement']):
        raise CorpusError('review_requirement_mismatch')
    if review['verdict'] != 'sufficient' or not all(nonempty(review[k]) for k in ('reviewer', 'origin', 'sufficiency_explanation')):
        raise CorpusError('sufficiency_not_reviewed')
    if not moment(review['checked_at']) <= at < moment(review['review_due_at']):
        raise CorpusError('sufficiency_review_expired')
    if not isinstance(review['aspects'], dict) or set(review['aspects']) != set(unit['aspects']):
        raise CorpusError('sufficient_aspects_missing')
    identity = None
    if unit['kind'] == 'dossier':
        identity = review['medication_identity']
        required_identity = {'inn', 'trade_name', 'form', 'strength', 'route', 'registration', 'official_url'}
        if not isinstance(identity, dict) or set(identity) != required_identity or not all(nonempty(v) for v in identity.values()) or identity['inn'] != unit['medication']['inn']:
            raise CorpusError('medication_identity_unverified')
        url = urlsplit(identity['official_url'])
        if url.scheme != 'https' or url.hostname not in {'grls.rosminzdrav.ru', 'grls.rosminzdrav.gov.ru'} or url.username or url.password:
            raise CorpusError('medication_official_identity_missing')
        targets = unit['medication']['registration_targets']
        if targets and not any(all(identity[k] == t[k] for k in ('registration', 'form', 'trade_name')) and identity['strength'] in t['strengths'] and identity['route'] == t['route'] for t in targets):
            raise CorpusError('medication_target_mismatch')
    professional_source = False
    for aspect, evidence in review['aspects'].items():
        mode = aspect_mode(unit, aspect)
        if review['schema_version'] == 1:
            if mode != 'clinical':
                raise CorpusError('separate_policy_evidence_required')
            refs, policies = evidence, []
        else:
            if not isinstance(evidence, dict) or set(evidence) != {'source_references', 'policy_references'}:
                raise CorpusError('aspect_evidence_schema')
            refs, policies = evidence['source_references'], evidence['policy_references']
        if not isinstance(refs, list) or not isinstance(policies, list):
            raise CorpusError('aspect_reference_missing')
        if mode == 'clinical' and (not refs or policies):
            raise CorpusError('policy_cannot_replace_clinical_source')
        if mode == 'policy' and (refs or not policies):
            raise CorpusError('policy_must_have_separate_origin')
        if mode == 'mixed' and (not refs or not policies):
            raise CorpusError('mixed_evidence_requires_both_origins')
        for policy in policies:
            validate_policy_reference(root, policy, unit_id, unit, aspect, frozen, at)
        seen_sources = set()
        for ref in refs:
            if not isinstance(ref, dict) or set(ref) != {'document_id', 'fragment_id', 'page', 'section', 'source_version', 'source_sha256', 'artifact_sha256', 'fragment_sha256'}:
                raise CorpusError('reference_schema')
            pair = catalog.get((ref['document_id'], ref['fragment_id']))
            if pair is None:
                raise CorpusError('reference_not_admitted')
            item, fragment = pair
            if ref['source_sha256'] != item['sha256'] or ref['artifact_sha256'] != item['artifact_sha256'] or ref['source_version'] != item['source_version'] or ref['fragment_sha256'] != digest(fragment) or ref['page'] != fragment['page'] or ref['section'] != fragment['section']:
                raise CorpusError('reference_coordinates_or_version_mismatch')
            if item['document_type'] in PRIMARY_TYPES and instrument_requirements(unit, aspect) is None:
                raise CorpusError('primary_source_scope_mismatch')
            if identity is not None and (item.get('medication_identity') != identity or item['document_type'] not in {'patient_leaflet', 'medication_instruction', 'sm_pc', 'safety_update'}):
                raise CorpusError('dossier_source_identity_mismatch')
            professional_source |= item['document_type'] in {'medication_instruction', 'sm_pc'}
            seen_sources.add(item['document_id'])
        required_primary = instrument_requirements(unit, aspect)
        if required_primary is not None and not required_primary <= seen_sources:
            raise CorpusError('exact_instrument_primary_source_missing')
    if identity is not None and not professional_source:
        raise CorpusError('professional_dossier_source_missing')
    if unit_id.endswith('/safety_updates_and_version_status'):
        safety = review['safety_check']
        if not isinstance(safety, dict) or set(safety) != {'checked_sources', 'scope', 'result', 'checked_at', 'review_due_at'}:
            raise CorpusError('safety_check_missing')
        if not isinstance(safety['checked_sources'], list) or not safety['checked_sources']:
            raise CorpusError('safety_check_incomplete')
        urls = [urlsplit(u) for u in safety['checked_sources']]
        hosts = {u.hostname for u in urls if u.scheme == 'https' and not u.username and not u.password}
        if 'grls.rosminzdrav.gov.ru' in hosts:
            hosts.add('grls.rosminzdrav.ru')
        if not {'grls.rosminzdrav.ru', 'roszdravnadzor.gov.ru'} <= hosts or not nonempty(safety['scope']) or not nonempty(safety['result']) or not moment(safety['checked_at']) <= at < moment(safety['review_due_at']):
            raise CorpusError('safety_check_incomplete')
    return review


def assess(root, snapshot, at, package_ids=None):
    report = {'gate': 'COVERAGE-1', 'evaluated_at': at, 'status': 'NOT_READY',
              'clinical_approval': 'NOT_ASSESSED_BY_THIS_TOOL', 'errors': [], 'gaps': [],
              'limitation': 'Checks structure, exact admission and reviewer evidence. Does not establish medical completeness or independent clinical approval.'}
    try:
        at = moment(at)
        report['evaluated_at'] = at.isoformat()
        frozen, matrix, meds, units = scope(root)
        report['scope_version'] = frozen['scope_version']
        report['scope_sha256'] = digest(frozen)
        report['counts'] = {'cells': {'complete': 0, 'required': frozen['required_cells']},
                            'dossier_sections': {'complete': 0, 'required': frozen['required_dossier_sections']},
                            'medications': {'complete': 0, 'required': frozen['required_medications']},
                            'refusal_definitions': {'complete': len(matrix['mandatory_refusals']), 'required': frozen['required_refusals']}}
        report['refusal_behavior'] = 'NOT_TESTED; J03/J04/J06 gates remain required'
        evidence = read(root, EVIDENCE)
        if not isinstance(evidence, dict) or set(evidence) != {'schema_version', 'scope_version', 'units', 'clinical_approval'} or evidence['schema_version'] != 1 or evidence['scope_version'] != frozen['scope_version'] or not isinstance(evidence['units'], dict):
            raise CorpusError('coverage_evidence_schema')
        if set(evidence['units']) - set(units):
            raise CorpusError('evidence_unknown_unit')
        registry, _, _ = package_registry(root, package_ids)
        if snapshot is None:
            catalog = {}
            report['errors'].append('snapshot_required')
        else:
            catalog, eligibility = card_catalog(snapshot, registry, at, root)
            report['corpus_version'] = eligibility['corpus_version']
            report['refused_sources'] = eligibility['refused']
        completed, identities = set(), {}
        for unit_id, unit in units.items():
            try:
                if unit_id not in evidence['units']:
                    raise CorpusError('sufficiency_evidence_missing')
                review = validate_review(root, unit_id, unit, evidence['units'][unit_id], catalog, frozen, at)
                completed.add(unit_id)
                if unit['kind'] == 'dossier':
                    identities.setdefault(unit['medication']['id'], set()).add(digest(review['medication_identity']))
            except (CorpusError, OSError, ValueError, KeyError, TypeError) as exc:
                report['gaps'].append({'unit_id': unit_id, 'kind': unit['kind'], 'reason': str(exc)})
        for med in meds['medications']:
            if len(identities.get(med['id'], set())) > 1:
                for section in meds['required_sections']:
                    unit_id = med['id'] + '/' + section
                    if unit_id in completed:
                        completed.remove(unit_id)
                        report['gaps'].append({'unit_id': unit_id, 'kind': 'dossier', 'reason': 'dossier_identity_conflict'})
            if all(med['id'] + '/' + s in completed for s in meds['required_sections']):
                report['counts']['medications']['complete'] += 1
        report['counts']['cells']['complete'] = sum(units[u]['kind'] == 'cell' for u in completed)
        report['counts']['dossier_sections']['complete'] = sum(units[u]['kind'] == 'dossier' for u in completed)
        if not report['errors'] and not report['gaps'] and all(c['required'] > 0 and c['complete'] == c['required'] for c in report['counts'].values()):
            report['status'] = 'READY'
    except (CorpusError, OSError, ValueError, KeyError, TypeError) as exc:
        report['errors'].append(str(exc))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path)
    parser.add_argument('--at', help='Reproducible audit timestamp; default actual UTC')
    parser.add_argument('--package', action='append')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = assess(ROOT, args.snapshot, args.at or datetime.now(timezone.utc).isoformat(), args.package)
    text = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.write_text(text)
    else:
        print(text, end='')
    return 0 if report['status'] == 'READY' else 1


if __name__ == '__main__':
    raise SystemExit(main())
