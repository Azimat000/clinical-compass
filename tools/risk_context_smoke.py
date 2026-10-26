#!/usr/bin/env python3
"""BE08A frozen author-created smoke corpus; never reads the service database."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from apps.compass import backend_risk_context as context, backend_risk_rules as rules
from apps.compass import backend_snapshot as snapshots
from apps.compass.backend_model import Budget, Config, DeepSeek, ModelError


def snapshot(case):
    rows, entries, sources = [], [], {}
    for i, doc in enumerate(case['documents']):
        row = {'id': str(i), 'value': doc['value']}
        rows.append(row)
        ref = 's2_' + snapshots.digest(['evidence_documents', str(i), row])
        sources[ref] = {'table': 'evidence_documents', 'key': 'id', 'id': str(i), 'sha256': snapshots.digest(row)}
        entries.append({'category': doc['category'], 'recorded_at': '2026-10-26T18:00:00Z',
            'current_revision': True, 'state': 'recorded', 'author_id': 'fictional-author',
            'fields': [{'source_ref': ref, 'path': '/value', 'value': doc['value'],
                'event_at': doc['event_at'], 'context': 'current', 'status': 'known', 'code': doc['code']}]})
    return {'policy': 'synthetic-inputs-v1', 'day': '2026-10-26', 'relationship': 'synthetic',
        'patients': [{'id': 'fictional', 'synthetic': 1, 'age_status': 'known', 'age_years': 35,
                      'birth_date': None, 'created_at': '2026-10-26T18:00:00Z'}],
        'backend_risk_rules': rules.release(), 'clinical_contexts': [],
        'evidence_documents': rows, 'patient_history': {'version': snapshots.VERSION,
            'complete': True, 'truncated': False, 'entries': entries, 'sources': sources}}


def metrics(cases):
    counts = {'tp': 0, 'fp': 0, 'fn': 0}
    for case in cases:
        expected = set(case['expected_topics'])
        actual = {c['topic'] for c in case['result']['model_candidates']}
        for name, values in [('tp', expected & actual), ('fp', actual - expected), ('fn', expected - actual)]:
            counts[name] += len(values)
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise SystemExit('Refusing to overwrite evidence')
    folder = ROOT / 'data/fictional/backend-risk-context'
    policy = json.loads((folder / 'policy.json').read_text())
    raw = (folder / 'smoke.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != policy['corpus_sha256']:
        raise SystemExit('Frozen corpus mismatch')
    key = ROOT / 'var/deepseek-api-key'
    if key.stat().st_mode & 0o077:
        raise SystemExit('Key mode must be 0600')
    os.environ['DEEPSEEK_API_KEY'] = key.read_text().strip()
    ledger = ROOT / 'var/deepseek-budget.sqlite3'
    budget = Budget(ledger)
    model = DeepSeek(Config(model='deepseek-flash', timeout=60, max_input_bytes=16000,
                            max_output_tokens=768), budget)
    report = {'started_at': datetime.now(timezone.utc).isoformat(), 'synthetic': True,
              'test_double': False, 'policy': policy, 'prompt_sha256': context.PROMPT_SHA256,
              'candidate_version': context.VERSION, 'cases': [], 'complete': False}
    def save():
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    save()
    for case in json.loads(raw)['cases']:
        frozen = snapshot(case)
        result = context.analyze_snapshot(frozen, model, synthetic=True)
        report['cases'].append({'id': case['id'], 'expected_topics': case['expected_topics'],
                                'snapshot_sha256': snapshots.digest(frozen), 'result': result})
        save()
        print(case['id'], result['model_evaluation'], flush=True)
    # Genuine adapter failure before reservation/network; never fake an API timeout.
    limited = DeepSeek(Config(model='deepseek-flash', max_input_bytes=1), budget)
    failure = context.analyze_snapshot(snapshot(json.loads(raw)['cases'][0]), limited, synthetic=True)
    report['real_adapter_failure'] = failure
    report['candidate_metrics'] = metrics(report['cases'])
    report['rule_metrics'] = {'measured': False, 'reason': 'This is candidate smoke, BE07 rules tested separately; full BE08B required.'}
    with sqlite3.connect(ledger) as db:
        report['ledger_micro_usd'] = db.execute('SELECT sum(micro_usd) FROM calls').fetchone()[0]
    report['pass'] = (all(c['result']['model_evaluation'] == 'candidates_only' for c in report['cases'])
                      and failure['errors'] == [{'code': 'context_limit', 'stage': 'model_candidate_evaluation'}])
    report.update(complete=True, finished_at=datetime.now(timezone.utc).isoformat())
    save()
    print(json.dumps({'pass': report['pass'], 'metrics': report['candidate_metrics'],
                      'ledger_micro_usd': report['ledger_micro_usd']}))
    return 0 if report['pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
