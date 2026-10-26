#!/usr/bin/env python3
"""Frozen synthetic BE05 evaluation. Never reads the service or patient database."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from apps.compass.backend_extraction import KINDS, PROMPT_SHA256, ExtractionError, extract_documents
from apps.compass.backend_model import Budget, Config, DeepSeek, ModelError


def score(cases, policy):
    counts = {k: {'tp': 0, 'fp': 0, 'fn': 0} for k in KINDS}
    errors = []
    for case in cases:
        expected = Counter((f['kind'], f['quote']) for f in case['expected'])
        actual = Counter((f['kind'], f['quote']) for f in case.get('result', {}).get('facts', []))
        for key, count in (expected & actual).items():
            counts[key[0]]['tp'] += count
        for direction, difference in [('fp', actual - expected), ('fn', expected - actual)]:
            for (kind, quote), count in difference.items():
                counts[kind][direction] += count
                errors.append({'case': case['id'], 'direction': direction,
                               'kind': kind, 'quote': quote, 'count': count})
    for value in counts.values():
        tp, fp, fn = (value[k] for k in ('tp', 'fp', 'fn'))
        value['precision'] = tp / (tp + fp) if tp + fp else (0 if fn else None)
        value['recall'] = tp / (tp + fn) if tp + fn else None
        value['pass'] = (value['precision'] is not None and value['recall'] is not None
            and value['precision'] >= policy['thresholds']['each_kind_precision']
            and value['recall'] >= policy['thresholds']['each_kind_recall'])
    return counts, errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--split', choices=['development', 'holdout', 'holdout-v2'], required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise SystemExit('Refusing to overwrite existing evaluation evidence')
    folder = ROOT / 'data/fictional/backend-extraction'
    policy = json.loads((folder / ('policy-v2.json' if args.split == 'holdout-v2' else 'policy.json')).read_text())
    for filename, expected_hash in policy['corpus_sha256'].items():
        if hashlib.sha256((folder / filename).read_bytes()).hexdigest() != expected_hash:
            raise SystemExit('Frozen corpus hash mismatch')
    key = ROOT / 'var/deepseek-api-key'
    if key.stat().st_mode & 0o077:
        raise SystemExit('Credential must have mode 0600')
    os.environ['DEEPSEEK_API_KEY'] = key.read_text().strip()
    model = DeepSeek(Config(model='deepseek-flash', timeout=60, max_input_bytes=16000,
                            max_output_tokens=1024), Budget(ROOT / 'var/deepseek-budget.sqlite3'))
    report = {'split': args.split, 'started_at': datetime.now(timezone.utc).isoformat(),
              'synthetic': True, 'test_double': False, 'policy': policy,
              'prompt_sha256_before_run': PROMPT_SHA256, 'cases': [], 'complete': False}
    def save():
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    for case in json.loads((folder / (args.split + '.json')).read_text())['cases']:
        doc = {'source_ref': 'synthetic_' + case['id'], 'path': '/text', 'text': case['text'],
               'event_at': '2026-10-26', 'recorded_at': '2026-10-26T17:00:00Z',
               'category': 'anamnesis' if 'family' in case['tags'] else 'wellbeing'}
        record = {'id': case['id'], 'tags': case['tags'], 'expected': case['expected']}
        try:
            record['result'] = extract_documents([doc], model, synthetic=True)
            facts = record['result']['facts']
            record['unsupported_final_spans'] = sum(
                doc['text'][f['start']:f['end']] != f['quote'] or
                doc['text'][f['context_start']:f['context_end']] != f['context_quote']
                for f in facts)
        except (ModelError, ExtractionError) as exc:
            record['error_code'] = str(exc)
        report['cases'].append(record)
        save()
        print(case['id'], record.get('error_code', 'received'), flush=True)
    metrics, errors = score(report['cases'], policy)
    report.update(complete=True, metrics_by_kind=metrics, errors=errors,
        failed_calls=sum('error_code' in c for c in report['cases']),
        unsupported_final_spans=sum(c.get('unsupported_final_spans', 0) for c in report['cases']),
        finished_at=datetime.now(timezone.utc).isoformat())
    report['pass'] = (all(v['pass'] for v in metrics.values()) and report['failed_calls'] == 0
                      and report['unsupported_final_spans'] == 0)
    report['billing'] = {key: sum(c.get('result', {}).get('metadata', {}).get(key, 0)
                                for c in report['cases']) for key in
        ('cost_ceiling_micro_usd', 'estimated_peak_cost_nano_usd', 'estimated_offpeak_cost_nano_usd')}
    save()
    print(json.dumps({'pass': report['pass'], 'metrics': metrics, 'errors': errors}, ensure_ascii=False))
    return 0 if report['pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
