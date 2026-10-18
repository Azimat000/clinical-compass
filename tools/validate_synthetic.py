#!/usr/bin/env python3
"""Validate frozen synthetic fixtures; this does not validate clinical rules."""
import argparse
from collections import Counter
from datetime import date
from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
ASSERTIONS = {
    'present', 'negated', 'considered', 'suspected', 'unknown', 'patient_reported',
    'conflicting', 'historical', 'stopped', 'listed', 'third_party', 'incomplete',
    'invalid', 'cancelled_proposal', 'not_due',
}
SCENARIOS = {
    'consideration', 'restriction', 'depressive_symptoms', 'deterioration',
    'adverse_and_missed', 'incomplete_conflicting',
}
SENSITIVE = re.compile(r'\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b|(?:\+7|8)[ ()-]*\d{3}[ ()-]*\d{3}[ -]*\d{2}[ -]*\d{2}')


def validate(root=ROOT):
    errors = []

    def check(condition, message):
        if not condition:
            errors.append(message)

    def load(path):
        return json.loads((root / path).read_text())

    def provenance(obj, label):
        p = obj['provenance']
        check(p['synthetic'] is True and bool(p['origin']), f'{label}: provenance')
        check(p['clinical_review_status'] == 'not_reviewed', f'{label}: review status')
        check(p['clinical_reviewer'] is None and p['clinical_gold'] is False,
              f'{label}: unsupported clinical gold/reviewer')
        check(p['active'] is False, f'{label}: active content')

    manifest = load('data/synthetic/manifest.json')
    provenance(manifest, 'manifest')
    check(manifest['dataset_version'] == 'S03-v1', 'unexpected dataset version')
    expected_paths = {
        'data/synthetic/cases.json',
        'data/synthetic/extraction-development.json',
        'data/synthetic/extraction-holdout.json',
    }
    check({f['path'] for f in manifest['files']} == expected_paths, 'manifest file set')
    for f in manifest['files']:
        check(f['path'] in expected_paths, 'unexpected manifest path')
        if f['path'] in expected_paths:
            actual = hashlib.sha256((root / f['path']).read_bytes()).hexdigest()
            check(actual == f['sha256'], f"{f['path']}: frozen checksum mismatch")
    policy = manifest['holdout_policy']
    check(policy['group_key'] == 'profile_id' and policy['selected_before_extractor'] is True,
          'holdout selection')
    check(policy['development_use_prohibited'] is True, 'holdout tuning prohibited')
    check(policy['clinical_blind_independence'] is False and
          policy['already_inspected_by_dataset_author'] is True, 'holdout limits')

    cases = load('data/synthetic/cases.json')
    provenance(cases, 'cases')
    check(len(cases['cases']) == 6, 'six demonstration cases required')
    check({c['scenario_type'] for c in cases['cases']} == SCENARIOS, 'six scenario types')
    ids, profiles, facts_seen = set(), set(), set()
    for c in cases['cases']:
        provenance(c, c['id'])
        check(c['id'] not in ids and c['profile_id'] not in profiles, 'duplicate demo profile')
        ids.add(c['id'])
        profiles.add(c['profile_id'])
        check(bool(c['profile']), f"{c['id']}: empty profile")
        check(c['clinical_expectation'] is None, f"{c['id']}: clinical expectation")
        check(c['aviandr_consideration']['eligibility'] is None, f"{c['id']}: eligibility")
        for key in ['aviandr_consideration', 'treatment_recommendations', 'routing']:
            check(bool(c[key]['draft']) and c[key]['clinical_review_status'] == 'not_reviewed',
                  f"{c['id']}: draft {key}")
        for key in ['treatment_recommendations', 'routing']:
            check(c[key]['active'] is False and c[key]['requires_physician_confirmation'] is True,
                  f"{c['id']}: action gate")
        check(c['routing']['category'] is None and c['routing']['urgency'] is None,
              f"{c['id']}: unapproved routing")
        check('B04' in c['activation_blockers'], f"{c['id']}: expert blocker missing")

    records, signatures, splits = [], {}, {}
    for split, count in [('development', 24), ('holdout', 12)]:
        data = load(f'data/synthetic/extraction-{split}.json')
        provenance(data, split)
        check(data['split'] == split, f'{split}: partition metadata')
        check(len(data['records']) == count, f'{split}: record count')
        check(data['dataset_version'] == manifest['dataset_version'], 'dataset version drift')
        splits[split] = set()
        for r in data['records']:
            label = r['id']
            provenance(r, label)
            check(label not in ids and r['profile_id'] not in profiles, f'{label}: reused profile')
            ids.add(label)
            profiles.add(r['profile_id'])
            splits[split].add(r['profile_id'])
            check(r['split'] == split and bool(r['template']), f'{label}: split/template')
            check(r['clinical_expectation'] is None, f'{label}: clinical gold')
            check(not SENSITIVE.search(r['text']), f'{label}: contact-like pattern')
            check(len(r['text']) >= 60 and bool(r['facts']), f'{label}: insufficient text/labels')
            check(bool(r['critical_missing_fields']), f'{label}: missing-field labels')
            target = set(r['target_fields'])
            check(target == {f['field'] for f in r['facts']} | set(r['critical_missing_fields']),
                  f'{label}: target field scope')
            present_fields = {f['field'] for f in r['facts']}
            check(not present_fields.intersection(r['critical_missing_fields']),
                  f'{label}: missing and present field collision')
            for f in r['facts']:
                check(f['id'] not in facts_seen, f'{label}: duplicate fact ID')
                facts_seen.add(f['id'])
                a, b = f['span']['start'], f['span']['end']
                check(0 <= a < b <= len(r['text']) and r['text'][a:b] == f['quote'],
                      f"{f['id']}: source span mismatch")
                check(f['assertion'] in ASSERTIONS, f"{f['id']}: assertion")
                if f['assertion'] in {'unknown', 'invalid', 'not_due'}:
                    check(f['value'] is None, f"{f['id']}: unknown not null")
                if f['field'] in {'event_date', 'received_date', 'medication_start'} and f['value']:
                    try:
                        date.fromisoformat(f['value'])
                    except ValueError:
                        check(False, f"{f['id']}: normalized date")
                if f['field'] == 'age_years' and f['value'] is not None:
                    check(type(f['value']) is int and 0 <= f['value'] <= 120,
                          f"{f['id']}: age format")
                if f['field'] == 'dose' and isinstance(f['value'], dict):
                    check(f['value']['unit'] in {'mg', 'g', 'ml', 'tablet', None},
                          f"{f['id']}: dose unit")
            # Exclude age, dates and wording: a changed date/age cannot create a new profile.
            core = sorted([
                (f['field'], f['assertion'], json.dumps(f['value'], sort_keys=True, ensure_ascii=False))
                for f in r['facts']
                if f['field'] not in {'age_years', 'event_date', 'received_date', 'medication_start'}
            ])
            signature = json.dumps([core, sorted(r['critical_missing_fields'])], ensure_ascii=False)
            check(signature not in signatures, f'{label}: duplicate clinical input profile')
            signatures[signature] = label
            records.append(r)
    check(not splits['development'] & splits['holdout'], 'profile leakage across partitions')

    max_similarity, nearest = 0, None
    for a in records[:24]:
        for b in records[24:]:
            ratio = SequenceMatcher(None, a['text'].casefold(), b['text'].casefold()).ratio()
            if ratio > max_similarity:
                max_similarity, nearest = ratio, [a['id'], b['id']]
            check(ratio < .85, f"near duplicate across partitions: {a['id']}/{b['id']}")
    assertions = Counter(f['assertion'] for r in records for f in r['facts'])
    units = Counter(f['value']['unit'] for r in records for f in r['facts']
                    if f['field'] == 'dose' and isinstance(f['value'], dict))
    for required in ['negated', 'unknown', 'conflicting', 'invalid', 'historical', 'third_party']:
        check(assertions[required] > 0, f'missing challenge: {required}')
    check({'mg', 'g', 'ml', 'tablet'} <= set(units), 'unit diversity')
    for split in splits:
        part = [r for r in records if r['split'] == split]
        check(any(f['assertion'] == 'negated' for r in part for f in r['facts']), f'{split}: negations')
        check(any(f['field'] == 'dose' for r in part for f in r['facts']), f'{split}: prescriptions')
        check(any(f['field'] == 'event_date' for r in part for f in r['facts']), f'{split}: dates')
        check(len({r['template'] for r in part}) >= 6, f'{split}: template diversity')
    expected_counts = {'demonstration': 6, 'development': 24, 'holdout': 12}
    check(manifest['counts'] == expected_counts, 'manifest counts')
    result = {
        'status': 'PASS' if not errors else 'FAIL', 'errors': errors,
        'counts': expected_counts, 'unique_profiles_including_demo': len(profiles),
        'fact_count': len(facts_seen), 'template_count': len({r['template'] for r in records}),
        'assertion_counts': dict(assertions), 'dose_units': {str(k): v for k, v in units.items()},
        'max_cross_split_text_similarity': round(max_similarity, 4), 'nearest_pair': nearest,
        'scope': 'Structural/textual fixture integrity only; no extraction or clinical performance measured.',
        'privacy_limit': 'Contact pattern scan supplements authored provenance; it does not prove anonymization.',
    }
    return errors, result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        errors, result = validate(args.root)
    except (KeyError, TypeError, ValueError, OSError) as exc:
        print(json.dumps({'status': 'FAIL', 'error': str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return bool(errors)


if __name__ == '__main__':
    raise SystemExit(main())
