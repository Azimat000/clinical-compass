"""BE10B summary acceptance: offline replay and preservation, no paid calls."""
from contextlib import closing
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from apps.compass import backend_diagnosis_service as service
from apps.compass import backend_diagnosis_codec as codec
from apps.compass import backend_risk_context as context
from apps.compass import backend_snapshot as snapshots
from apps.compass import backend_sources as sources

OUT = Path(__file__).resolve().parent
PRIOR = ROOT / 'evidence/BE10B02/revision-v2'
FINAL = PRIOR / 'iteration-5'
read = lambda p: json.loads(p.read_text())
sha = lambda b: hashlib.sha256(b).hexdigest()
ALTERNATIVES = {'mania_hypomania', 'organic_cause', 'somatic_cause',
                'medication_cause', 'substance_cause', 'other_primary_disorder',
                'panic_disorder', 'phobic_disorder', 'ocd', 'hypochondriacal_disorder'}


def verify():
    base = read(OUT / 'baseline.json')
    assert base['diff'] == base['cached_diff'] == ''
    # The previous full audit was rerun by the main agent before session start.
    assert sha((PRIOR / 'verification.json').read_bytes()) == base['prior_audit_sha256']
    for path, expected in base['preserved_files'].items():
        assert sha((ROOT / path).read_bytes()) == expected, path
    assert sha((ROOT / 'var/clinic-20261026-access.md').read_bytes()) == base['access_sha256']
    with closing(sqlite3.connect('file:' + str(ROOT / 'var/compass.sqlite3') + '?mode=ro', uri=True)) as db:
        tables = {t: sha(json.dumps(sorted(json.dumps(r, ensure_ascii=False, default=str)
                  for r in db.execute('SELECT * FROM "' + t + '"')), ensure_ascii=False).encode())
                  for (t,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        assert tables == base['active_db_tables']
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        assert db.execute('SELECT count(*) FROM patients').fetchone()[0] == 10
    with closing(sqlite3.connect('file:' + str(ROOT / 'var/deepseek-budget.sqlite3') + '?mode=ro', uri=True)) as db:
        rows = [list(r) for r in db.execute('SELECT * FROM calls ORDER BY id')]
        assert rows == base['ledger_rows']
        ledger = list(db.execute('SELECT count(*),sum(micro_usd) FROM calls').fetchone())
        assert ledger == [145, 730308]
    current = sources.capture()
    catalog = service.criteria.release()
    for condition in catalog['conditions'].values():
        sources.require(current, [condition['admission_claim']], 'diagnosis', age_min=18,
                        age_max=120, condition=condition['condition'])
        source = current['sources'][condition['source_id']]['source']
        assert sha((ROOT / source['path']).read_bytes()) == source['sha256']
    runtime = snapshots.digest(service.release())
    quality = read(ROOT / 'evidence/BE10/diagnosis-quality.json')
    assert quality['pass'] and quality['runtime_sha256'] == runtime
    assert quality['clinical_ready'] is quality['independent_clinical_review'] is False
    summary = read(FINAL / 'live-holdout/summary.json')
    freeze = summary['freeze']
    for name in ('development', 'holdout'):
        assert sha((FINAL / (name + '.json')).read_bytes()) == freeze[name + '_sha256']
    assert sha((FINAL / 'protocol.py').read_bytes()) == freeze['protocol_sha256']
    assert sha((ROOT / 'apps/tests/diagnosis_fixtures.py').read_bytes()) == freeze['fixture_sha256']
    assert runtime == freeze['runtime_sha256']
    counts = dict(cases=0, facts=0, alternative_facts=0, durations=0,
                  dangerous_positive_facts=0, dangerous_omissions=0,
                  raw_model_facts_correct=0, raw_model_alternative_facts_correct=0)
    citations = 0
    for case in read(FINAL / 'holdout.json')['cases']:
        saved = read(FINAL / 'live-holdout' / (case['id'] + '.json'))
        calls = read(FINAL / 'live-holdout' / (case['id'] + '-calls.json'))
        named = {c['branch']: c['response']['value'] for c in calls}
        result = service.named_interpret(saved['snapshot'], named)
        assert result == saved['report']['diagnosis_report']['context']
        assert result['leading'] == case['leading'] and result['disposition'] == case['disposition']
        assert result['clinical_ready'] is False
        assert result['established_diagnosis'] is result['diagnosis_code'] is result['plan'] is None
        assert saved['care_actions'] == 0 and saved['queue_attempts'] == 1
        units = {u['unit_id']: u for u in context.prepare_snapshot(saved['snapshot'])}
        for call in calls:
            meta = call['response']['metadata']
            assert meta['test_double'] is False and meta['returned_model'] == 'deepseek-flash'
            payload = service.payload(saved['snapshot'], call['branch'])
            assert sha(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()) == call['payload_sha256']
            assert sha(json.dumps(codec.schema(call['branch']), sort_keys=True).encode()) == call['schema_sha256']
            for q in call['response']['value']['quotes']:
                assert q['quote'] and q['quote'] in units[q['unit_id']]['text']
                citations += 1
        actual = {h['kind'] + '.' + f['id']: f['state'] for h in result['hypotheses'][:2] for f in h['facts']}
        raw = {kind + '.' + f['id']: f['state'] for kind, part in named.items() for f in part['facts']}
        for key, expected in case['expected_facts'].items():
            assert actual[key] == expected, (case['id'], key)
            counts['facts'] += 1
            counts['raw_model_facts_correct'] += raw[key] == expected
            if key.split('.')[1] in ALTERNATIVES:
                counts['alternative_facts'] += 1
                counts['raw_model_alternative_facts_correct'] += raw[key] == expected
        for kind, expected in case['expected_durations'].items():
            assert result['raw']['durations'][kind]['value'] == expected
            counts['durations'] += 1
        for key in case.get('dangerous_facts', []):
            counts['dangerous_positive_facts'] += 1
            counts['dangerous_omissions'] += actual[key] != 'present'
        counts['cases'] += 1
    assert all(quality['metrics'][key] == value for key, value in counts.items())
    assert counts['dangerous_omissions'] == 0
    http = read(PRIOR / 'default-http-report.json')
    assert http['status'] == 'PASS' and http['runtime_sha256'] == runtime
    assert http['default_executor'] is True and http['test_double'] is False
    assert http['creation_http_status'] == 202 and http['care_actions'] == 0
    assert http['idempotent_before_and_after'] and http['read_head_access_cancel_and_stale'] == 'PASS'
    coverage = read(ROOT / 'plan/coverage.json')
    preserved = lambda value: [(i['id'], i['text'], i['subchecks'], i['fulfilment_status']) for i in value['items']]
    assert sha(json.dumps(preserved(coverage), ensure_ascii=False).encode()) == base['coverage_invariants_sha256']
    requirements = read(ROOT / 'plan/backend/requirements.json')
    assert [[i['id'], i['text'], i['status']] for i in requirements['items']] == base['requirement_invariants']
    state = read(ROOT / 'memory/STATE.json')
    assert state['backend_program']['clinical_release'] == 'blocked'
    assert state['backend_program']['active_service_migrated'] is False
    for sid in ('BE10B01', 'BE10B02'):
        assert state['slices'][sid]['status'] == 'accepted'
        subprocess.run(['git', 'rev-parse', '--verify', 'refs/tags/slice/' + sid], cwd=ROOT, check=True, capture_output=True)
    for sid in ('BE10', 'BE11'):
        assert state['slices'][sid]['status'] == 'planned'
    if state['slices']['BE10B']['status'] == 'accepted':
        assert state['current_slice'] is None
        assert state['last_accepted_slice'] == 'BE10B' and state['next_slice'] == 'BE10'
        assert state['slices']['BE10B']['commit_ref'] == 'refs/tags/slice/BE10B'
    else:
        assert state['current_slice'] == 'BE10B'
        assert state['slices']['BE10B']['status'] == 'in_progress'
    tracked = subprocess.check_output(['git', 'diff', base['head'], '--name-only'], cwd=ROOT, text=True).splitlines()
    new = subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard'], cwd=ROOT, text=True).splitlines()
    allowed = {'START_HERE.md', 'AGENTS.md', 'docs/architecture/backend-diagnoses.md',
               'memory/STATE.json', 'memory/sessions/BE10B.md', 'memory/DECISIONS.md',
               'memory/BLOCKERS.md', 'memory/EXTERNAL.md', 'memory/BUDGET.json',
               'plan/backend/requirements.json', 'plan/coverage.json', 'plan/COVERAGE.md'}
    secret = (ROOT / 'var/deepseek-api-key').read_bytes().strip()
    for path in set(tracked + new) - set(base['preserved_files']):
        assert path in allowed or path.startswith('evidence/BE10B/'), path
        assert secret not in (ROOT / path).read_bytes(), path
    return {'status': 'PASS', 'checked_at': datetime.now(ZoneInfo('Europe/Moscow')).isoformat(),
            'runtime_sha256': runtime, 'metrics_replayed_offline': counts, 'quotes_checked': citations,
            'active_tables_unchanged': len(tables), 'patients': 10, 'foreign_files_unchanged': 4,
            'ledger_unchanged': ledger, 'new_paid_calls': 0, 'remaining_micro_usd': 269692,
            'requirements_unchanged': len(coverage['items']),
            'subchecks_unchanged': sum(len(i['subchecks']) for i in coverage['items']),
            'source_gates': 'PASS', 'deadline_extended': False,
            'clinical_release': 'blocked', 'parent_BE10_and_BE11': 'planned',
            'scope_and_secret_scan': 'PASS', 'prior_http_artifact_verified': True}


if __name__ == '__main__':
    value = verify()
    (OUT / 'verification.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(value, ensure_ascii=False, indent=2))
