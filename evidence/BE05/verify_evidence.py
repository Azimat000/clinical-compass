"""Independent local acceptance checks; no network or clinical database access."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess

ROOT = Path(__file__).resolve().parents[2]
reports = []
for report_file, corpus, policy_file, prompt_version in (
    ('development-run.json', 'development.json', 'policy.json', 'v1'),
    ('extraction-quality.json', 'holdout.json', 'policy.json', 'v1'),
    ('extraction-quality-v2.json', 'holdout-v2.json', 'policy-v2.json', 'v2')):
    report = json.loads((ROOT/'evidence/BE05'/report_file).read_text())
    policy = json.loads((ROOT/'data/fictional/backend-extraction'/policy_file).read_text())
    for filename, sha in policy['corpus_sha256'].items():
        assert hashlib.sha256((ROOT/'data/fictional/backend-extraction'/filename).read_bytes()).hexdigest() == sha
    cases = json.loads((ROOT/'data/fictional/backend-extraction'/corpus).read_text())['cases']
    prompts = json.loads((ROOT/'evidence/BE05/prompts.json').read_text())
    prompt_hash = hashlib.sha256(prompts[prompt_version].encode()).hexdigest()
    assert report['prompt_sha256_before_run'] == prompt_hash
    assert len(report['cases']) == len(cases) and report['complete']
    matched, predicted, expected = Counter(), Counter(), Counter()
    for raw, measured in zip(cases, report['cases']):
        assert raw['id'] == measured['id'] and raw['expected'] == measured['expected']
        result = measured['result']
        assert result['clinical_ready'] is False
        meta = result['metadata']
        assert meta['test_double'] is False and meta['returned_model'] == 'deepseek-flash'
        assert meta['extraction_prompt_sha256'] == prompt_hash
        got = Counter((f['kind'], f['quote']) for f in result['facts'])
        gold = Counter((f['kind'], f['quote']) for f in raw['expected'])
        for key, n in (got & gold).items(): matched[key[0]] += n
        for key, n in got.items(): predicted[key[0]] += n
        for key, n in gold.items(): expected[key[0]] += n
        for f in result['facts']:
            assert raw['text'][f['start']:f['end']] == f['quote']
            assert raw['text'][f['context_start']:f['context_end']] == f['context_quote']
            assert f['source_ref'] == 'synthetic_' + raw['id'] and f['path'] == '/text'
            assert f['field_sha256'] == hashlib.sha256(raw['text'].encode()).hexdigest()
            assert f['event_at'] == '2026-10-26' and f['recorded_at'] == '2026-10-26T17:00:00Z'
    if report_file == 'extraction-quality-v2.json':
        assert report['pass'] and not report['errors']
        for kind in policy['kinds']:
            assert predicted[kind] > 0 and expected[kind] > 0
            precision, recall = matched[kind]/predicted[kind], matched[kind]/expected[kind]
            assert precision == report['metrics_by_kind'][kind]['precision']
            assert recall == report['metrics_by_kind'][kind]['recall']
            assert precision >= .9 and recall >= .8
    elif report_file == 'extraction-quality.json':
        assert report['pass'] is False and len(report['errors']) == 14
    reports.append({'file': report_file, 'calls': len(cases), 'pass': report['pass'],
                    'matched': sum(matched.values()), 'predicted': sum(predicted.values()),
                    'expected': sum(expected.values())})
baseline = json.loads((ROOT/'evidence/BE05/baseline.json').read_text())
for name, sha in baseline['preserved'].items():
    assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == sha
with sqlite3.connect(f'file:{ROOT}/var/deepseek-budget.sqlite3?mode=ro', uri=True) as db:
    ledger = db.execute('select sum(micro_usd),count(*) from calls').fetchone()
    assert ledger[0] <= 50000
print(json.dumps({'status': 'PASS', 'reports': reports, 'preserved_files': len(baseline['preserved']),
                  'ledger_micro_usd': ledger[0], 'ledger_calls': ledger[1]}, indent=2))
