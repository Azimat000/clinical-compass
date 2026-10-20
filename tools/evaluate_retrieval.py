#!/usr/bin/env python3
"""Offline retrieval benchmark; never imports the app, retrieves, or calls a network."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
CATEGORIES = (
    'depression', 'anxiety', 'adverse_events', 'adherence_effect', 'aviandr',
    'context_structure', 'age', 'diagnosis_stage', 'version_rights',
    'missing_evidence', 'conflict', 'injection',
)
SAFETY = ('role_bypass', 'source_bypass', 'applicability_bypass',
          'network_fallback', 'medical_writes', 'log_leak')
LINK_FIELDS = (
    'fragment_id', 'document_id', 'document_family', 'source_version',
    'source_sha256', 'page', 'section', 'start', 'end', 'quote',
    'required_context', 'admission_id', 'verified_at', 'review_due_at',
    'source_url', 'rights_id',
)
VERSIONS = dict(contract='retrieval-contract-1', corpus='fixture-corpus-1',
                index='fixture-index-1', retriever='fixture-export-1', policy='fixture-policy-1')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def document_digest(document):
    return hashlib.sha256(json.dumps(document, ensure_ascii=False,
                                     sort_keys=True).encode()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def validate_dataset(parts, documents, fragments, gates):
    """Validate labels as well as sizes; no search predictions are inspected here."""
    errors = []
    ids, families, doc_families = set(), {}, {}
    catalog = {f['fragment_id']: f for f in fragments}
    if len(catalog) != len(fragments):
        errors.append('duplicate_fragment_id')
    docs = {d['document_id']: d for d in documents}
    if len(docs) != len(documents):
        errors.append('duplicate_document_id')
    for f in fragments:
        try:
            d = docs[f['document_id']]
            page = d['pages'][f['page'] - 1]
            valid = (set(f) == set(LINK_FIELDS) and type(f['page']) is int and
                     f['page'] > 0 and type(f['start']) is int and
                     type(f['end']) is int and 0 <= f['start'] < f['end'] <= len(page) and
                     page[f['start']:f['end']] == f['quote'] and
                     f['source_sha256'] == document_digest(d) and
                     f['document_family'] == d['family'] and
                     f['source_version'] == d['version'] and
                     f['required_context'] and
                     all(isinstance(v, str) and v in page for v in f['required_context'].values()))
            if not valid:
                errors.append('invalid_reference:' + f['fragment_id'])
        except (KeyError, IndexError, TypeError):
            errors.append('malformed_reference:' + str(f.get('fragment_id')))
    for split, cases in parts.items():
        if len(cases) < (24 if split == 'safety' else 60):
            errors.append('insufficient_cases:' + split)
        families[split], doc_families[split] = set(), set()
        for c in cases:
            cid = c['id']
            if cid in ids:
                errors.append('duplicate_case:' + cid)
            ids.add(cid)
            families[split].add(c['family'])
            doc_families[split].update(c['document_families'])
            if (not c['query'].strip() or not c['categories'] or
                    set(c['categories']) - set(CATEGORIES) or c['clinical_review'] is not None or
                    c['provenance'] != 'Codex:synthetic_technical' or c['split'] != split):
                errors.append('invalid_annotation:' + cid)
            e = c['expected']
            if e['status'] == 'FOUND':
                if not e['sufficient_sets'] or any(not s for s in e['sufficient_sets']):
                    errors.append('no_sufficient_set:' + cid)
                for s in e['sufficient_sets']:
                    if len(s) != len(set(s)):
                        errors.append('duplicate_label:' + cid)
                    for fid in s:
                        if fid not in catalog:
                            errors.append('unknown_gold_fragment:' + cid)
                        elif catalog[fid]['document_family'] not in c['document_families']:
                            errors.append('wrong_gold_family:' + cid)
            elif e['status'] not in {'NO_EVIDENCE', 'NOT_APPLICABLE', 'CONFLICT',
                                      'UNAVAILABLE', 'ACCESS_DENIED'} or not e['reason_code'] or e['sufficient_sets']:
                errors.append('invalid_refusal:' + cid)
        if split != 'safety':
            found = [c for c in cases if c['expected']['status'] == 'FOUND']
            refusals = [c for c in cases if c['expected']['status'] in {'NO_EVIDENCE', 'NOT_APPLICABLE'}]
            conflicts = [c for c in cases if c['expected']['status'] == 'CONFLICT']
            if len(found) < 30 or len(refusals) < 20 or len(conflicts) < 5:
                errors.append('status_coverage:' + split)
            for direction in ('depression', 'anxiety'):
                if sum(c['direction'] == direction for c in found) < 10:
                    errors.append('direction_coverage:' + split + ':' + direction)
        if split == 'control':
            for cat in CATEGORIES:
                if sum(cat in c['categories'] for c in cases) < 5:
                    errors.append('category_coverage:' + cat)
    for a, b in (('development', 'control'), ('development', 'safety'), ('control', 'safety')):
        if families[a] & families[b] or doc_families[a] & doc_families[b]:
            errors.append('family_overlap:' + a + ':' + b)
    # These are project gates, not configurable tuning parameters.
    if gates['G02'] != {'recall_at_5_min': 0.95, 'mrr_at_5_min': 0.85, 'citation_errors_max': 0}:
        errors.append('changed_G02')
    return errors


def load_frozen(dataset_dir, manifest_path):
    manifest = read(manifest_path)
    for item in manifest['frozen_files']:
        target = ROOT / item['path']
        if not target.is_file() or digest(target) != item['sha256']:
            raise ValueError('Frozen file changed/missing: ' + item['path'])
    # The selected files themselves must be in the freeze (not a decoy manifest).
    pinned = {str((ROOT / f['path']).resolve()) for f in manifest['frozen_files']}
    names = ('development.json', 'control.json', 'safety.json', 'documents.json',
             'fragments.json', 'gates.json')
    if any(str((dataset_dir / name).resolve()) not in pinned for name in names):
        raise ValueError('Dataset is not bound to manifest')
    parts = {s: read(dataset_dir / (s + '.json')) for s in ('development', 'control', 'safety')}
    documents, fragments, gates = (read(dataset_dir / name) for name in names[3:])
    errors = validate_dataset(parts, documents, fragments, gates)
    if errors:
        raise ValueError('; '.join(errors))
    return parts, fragments, gates, manifest


def metrics(rows):
    answerable = [r for r in rows if r['answerable']]
    found = sum(r['rank'] is not None and r['rank'] <= 5 for r in answerable)
    reciprocal_sum = sum(1 / r['rank'] for r in answerable if r['rank'] is not None and r['rank'] <= 5)
    refusals = [r for r in rows if not r['answerable']]
    return dict(total=len(rows), answerable=len(answerable), found_at_5=found,
                recall_at_5=found / len(answerable) if answerable else None,
                reciprocal_rank_sum=reciprocal_sum,
                mrr_at_5=reciprocal_sum / len(answerable) if answerable else None,
                required_refusals=len(refusals),
                correct_refusals=sum(not r['errors'] for r in refusals),
                citation_errors=sum(e.startswith(('citation:', 'unknown_source:', 'duplicate_hit:'))
                                    for r in rows for e in r['errors']),
                error_count=sum(len(r['errors']) for r in rows))


def evaluate(cases, predictions, fragments, expected_versions=None):
    """Compute full-set ranks; validate *every* exposed citation, not only top five."""
    expected_versions = expected_versions or VERSIONS
    if not isinstance(predictions, list):
        raise ValueError('Predictions must be an array')
    lookup = {}
    case_ids = {c['id'] for c in cases}
    for p in predictions:
        if not isinstance(p, dict) or not isinstance(p.get('id'), str):
            raise ValueError('Prediction has no string id')
        if p['id'] in lookup or p['id'] not in case_ids:
            raise ValueError('Duplicate or unknown prediction id: ' + p['id'])
        lookup[p['id']] = p
    catalog = {f['fragment_id']: f for f in fragments}
    rows = []
    for c in cases:
        expected = c['expected']
        p = lookup.get(c['id'])
        errors, valid_ids, seen, returned = [], [], set(), []
        rank = None
        if p is None:
            errors.append('missing_prediction')
        else:
            allowed = {'id', 'status', 'reason_code', 'hits', 'versions', 'safety', 'http_status'}
            if set(p) - allowed or not {'id', 'status', 'reason_code', 'hits', 'versions', 'safety'} <= set(p):
                errors.append('schema')
            if p.get('status') != expected['status']:
                errors.append('status')
            if p.get('reason_code') != expected['reason_code']:
                errors.append('reason')
            if p.get('versions') != expected_versions:
                errors.append('versions')
            safe = p.get('safety')
            if not isinstance(safe, dict) or set(safe) != set(SAFETY):
                errors.append('safety_schema')
            else:
                errors.extend('safety:' + key for key in SAFETY if safe[key] is not False)
            if expected['status'] == 'ACCESS_DENIED' and p.get('http_status') != expected['http_status']:
                errors.append('http_status')
            hits = p.get('hits')
            if not isinstance(hits, list):
                errors.append('hits_schema')
                hits = []
            if expected['status'] != 'FOUND' and hits:
                errors.append('refusal_leak')
            for hit in hits:
                fid = hit.get('fragment_id') if isinstance(hit, dict) else None
                # Keep original positions: a malformed hit cannot improve ranking.
                valid_ids.append(None)
                if not isinstance(fid, str):
                    errors.append('citation:malformed')
                    continue
                returned.append(fid)
                if fid in seen:
                    errors.append('duplicate_hit:' + fid)
                    continue
                seen.add(fid)
                if fid not in catalog:
                    errors.append('unknown_source:' + fid)
                elif json.dumps(hit, sort_keys=True) != json.dumps(catalog[fid], sort_keys=True):
                    errors.append('citation:' + fid)
                elif p.get('versions') == expected_versions:
                    valid_ids[-1] = fid
            if p.get('status') == 'FOUND' and expected['status'] == 'FOUND':
                for k in range(1, min(5, len(valid_ids)) + 1):
                    if any(set(s) <= set(valid_ids[:k]) for s in expected['sufficient_sets']):
                        rank = k
                        break
        if expected['status'] == 'FOUND' and not any(
                set(s) <= (set(valid_ids) - {None}) for s in expected['sufficient_sets']):
            errors.append('incomplete_evidence')
        relevant = set().union(*(set(s) for s in expected['sufficient_sets']))
        valid = set(valid_ids) - {None}
        alternatives = [sorted(set(s) - valid) for s in expected['sufficient_sets']]
        rows.append(dict(id=c['id'], categories=c['categories'],
                         answerable=expected['status'] == 'FOUND', rank=rank, errors=errors,
                         fp=[fid for fid in returned if fid not in relevant or fid not in valid],
                         fn=min(alternatives, key=len) if alternatives else [],
                         fn_by_alternative=alternatives, expected_status=expected['status'],
                         actual_status=p.get('status') if p else None))
    overall = metrics(rows)
    g02 = ((overall['recall_at_5'] >= 0.95 and overall['mrr_at_5'] >= 0.85 and
            overall['citation_errors'] == 0) if overall['answerable'] else None)
    g03 = bool(rows) and not any(r['errors'] for r in rows)
    return dict(schema_version='retrieval-eval-1', scope='technical_only',
                release_approved=False, passed=(g02 is not False) and g03,
                rank_metrics_applicable=bool(overall['answerable']), gates={'G02': g02, 'G03': g03},
                not_measured=['G04', 'G05', 'G06', 'G07', 'G08', 'G09'], overall=overall,
                by_category={cat: metrics([r for r in rows if cat in r['categories']]) for cat in CATEGORIES},
                cases=rows)


def miniature():
    """Independent non-clinical microfixture; does not access development/control."""
    fragments = []
    for fid in ('a', 'b', 'distractor'):
        f = dict.fromkeys(LINK_FIELDS, 'micro')
        f.update(fragment_id=fid, page=1, start=0, end=3, quote='abc',
                 required_context={'exception': 'except xyz'})
        fragments.append(f)
    cases = [dict(id='mini-found', categories=['context_structure'],
                  expected=dict(status='FOUND', reason_code='evidence_found', sufficient_sets=[['a', 'b']])),
             dict(id='mini-refusal', categories=['age'],
                  expected=dict(status='NOT_APPLICABLE', reason_code='age_unknown', sufficient_sets=[]))]
    predictions = [dict(id=c['id'], status=c['expected']['status'],
                        reason_code=c['expected']['reason_code'],
                        versions=VERSIONS.copy(), safety=dict.fromkeys(SAFETY, False), hits=[])
                   for c in cases]
    predictions[0]['hits'] = copy.deepcopy(fragments[:2])
    return cases, predictions, fragments


def self_test():
    cases, good, fragments = miniature()
    perfect = evaluate(cases, good, fragments)
    assert perfect['gates']['G03'] and perfect['overall']['recall_at_5'] == 1
    assert perfect['overall']['mrr_at_5'] == 0.5  # two required parts
    probes = {}
    for name, mutate in (
        ('wrong_page', lambda p: p[0]['hits'][0].update(page=2)),
        ('wrong_version', lambda p: p[0]['hits'][0].update(source_version='old')),
        ('lost_context', lambda p: p[0]['hits'][0].update(required_context={})),
        ('unadmitted_source', lambda p: p[0]['hits'][0].update(fragment_id='foreign')),
        ('leak', lambda p: p[1].update(hits=[copy.deepcopy(fragments[0])])),
        ('wrong_refusal', lambda p: p[0].update(status='NO_EVIDENCE', reason_code='none', hits=[])),
        ('incomplete_set', lambda p: p[0].update(hits=p[0]['hits'][:1])),
        ('missing_row', lambda p: p.pop()),
        ('duplicate_hit', lambda p: p[0]['hits'].append(copy.deepcopy(p[0]['hits'][0]))),
        ('network_fallback', lambda p: p[0]['safety'].update(network_fallback=True)),
    ):
        p = copy.deepcopy(good)
        mutate(p)
        result = evaluate(cases, p, fragments)
        assert not result['passed'], name
        probes[name] = {'rejected': True, 'gates': result['gates'],
                        'errors': {r['id']: r['errors'] for r in result['cases']}}
    # Single sufficient fragment is a truly passing control for gate probes.
    single = copy.deepcopy(cases)
    single[0]['expected']['sufficient_sets'] = [['a']]
    p = copy.deepcopy(good)
    p[0]['hits'] = p[0]['hits'][:1]
    assert evaluate(single, p, fragments)['passed']
    for name in ('page', 'leak', 'refusal'):
        broken = copy.deepcopy(p)
        if name == 'page':
            broken[0]['hits'][0]['page'] = 99
        elif name == 'leak':
            broken[0]['safety']['log_leak'] = True
        else:
            broken[0].update(status='NO_EVIDENCE', hits=[], reason_code='none')
        assert not evaluate(single, broken, fragments)['passed']
    return dict(status='PASS', positive_control=True, multipart_mrr=0.5, probes=probes,
                scope='microfixture_only; no retrieval/control run')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument('--validate', action='store_true')
    actions.add_argument('--self-test', action='store_true')
    actions.add_argument('--predictions', type=Path)
    parser.add_argument('--dataset-dir', type=Path, default=ROOT / 'data/synthetic/retrieval')
    parser.add_argument('--manifest', type=Path, default=ROOT / 'evidence/S17J01/dataset-manifest.json')
    parser.add_argument('--split', choices=['development', 'control', 'safety'], default='development')
    parser.add_argument('--control-run-id')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        if args.self_test:
            result = self_test()
        else:
            parts, fragments, gates, manifest = load_frozen(args.dataset_dir, args.manifest)
            if args.validate:
                result = {'status': 'PASS', 'sizes': {s: len(v) for s, v in parts.items()},
                          'scope': 'structural validation only; no retrieval run'}
            else:
                if args.split == 'control' and not args.control_run_id:
                    raise ValueError('Control requires --control-run-id and an access-log entry')
                result = evaluate(parts[args.split], read(args.predictions), fragments,
                                  gates['export_versions'])
                result.update(split=args.split, control_run_id=args.control_run_id,
                              predictions_sha256=digest(args.predictions),
                              manifest_sha256=digest(args.manifest),
                              evaluator_sha256=digest(__file__), corpus_kind=manifest['corpus_kind'])
        output = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
        if args.output:
            args.output.write_text(output)
        else:
            print(output, end='')
        return 0 if result.get('status') == 'PASS' or result.get('passed') else 1
    except (ValueError, KeyError, TypeError, OSError, IndexError) as exc:
        print('ERROR: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
