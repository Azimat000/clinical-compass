"""Independent main-agent checks: actual engine scenarios and live preservation."""
from contextlib import closing
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from apps.compass import backend_medication_safety as safety

OUT = Path(__file__).resolve().parent
sha = lambda value: hashlib.sha256(value).hexdigest()


def preservation():
    base = json.loads((OUT / 'baseline.json').read_text())
    for name, expected in base['preserved_files'].items():
        assert sha((ROOT / name).read_bytes()) == expected, name
    assert sha((ROOT / 'var/clinic-20261026-access.md').read_bytes()) == base['access_sha256']
    assert sha((ROOT / 'var/deepseek-budget.sqlite3').read_bytes()) == base['ledger_sha256']
    with closing(sqlite3.connect('file:' + str(ROOT / 'var/compass.sqlite3') + '?mode=ro', uri=True)) as db:
        current = {row[0]: sha(json.dumps(db.execute('SELECT * FROM "' + row[0] + '"').fetchall(),
            sort_keys=True, default=str).encode())
            for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert current == base['active_db_tables'], 'live database changed'
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
    coverage = json.loads((ROOT / 'plan/coverage.json').read_text())
    stripped = [{k: v for k, v in item.items() if k != 'actual_evidence'} for item in coverage['items']]
    assert sha(json.dumps(stripped, ensure_ascii=False, sort_keys=True).encode()) == base['coverage_invariants_sha256']
    return {'pass': True, 'live_tables_unchanged': len(current), 'foreign_files_unchanged': 4,
            'credentials_unchanged': True, 'ledger_unchanged': True,
            'requirements': len(coverage['items']),
            'subchecks': sum(len(i['subchecks']) for i in coverage['items'])}


def scenarios():
    catalog = safety.release()
    cases = []
    for pid, p in catalog['products'].items():
        candidate = {'product_id': pid, 'form': p['form'], 'strength_mg': p['strengths_mg'][0],
            'unit': 'mg', 'indication': p['indications'][0], 'daily_dose_mg': p['daily_mg'][0],
            'times_per_day': p['times_per_day'], 'phase': 'maintenance'}
        patient = {'mode': 'synthetic_only', 'synthetic': True}
        for key, value in {'age': 40, 'allergies': [], 'allergies_complete': True,
                           'medications': [], 'medications_complete': True,
                           **{key: False for key in p['required_facts']}}.items():
            patient[key] = {'value': value, 'refs': ['synthetic:case:' + key]}
        variants = [('complete_partial_coverage', None, None, 'coverage', 'unknown'),
            ('duplicate_trade_name', 'medications', [{'ingredient': p['ingredient'],
                'name': 'Другое торговое название', 'state': 'current', 'refs': ['synthetic:other']}], 'medication_0', 'block'),
            ('unsupported_interaction', 'medications', [{'ingredient': 'not_in_catalog',
                'state': 'current', 'refs': ['synthetic:other']}], 'medication_0', 'unknown'),
            ('missing_age', 'age', None, 'age', 'unknown'),
            ('allergy', 'allergies', [p['ingredient']], 'allergies', 'block')]
        for label, key, new, gate, expected in variants:
            inp = deepcopy(patient)
            if key:
                inp[key]['value'] = new
            report = safety.evaluate(candidate, inp)
            actual = next(c for c in report['checks'] if c['code'] == gate)
            assert actual['state'] == expected, (pid, label, actual)
            assert not report['eligible'] and not report['applied'] and not report['clinical_release']
            assert safety.verify(candidate, inp, report)
            for c in report['checks']:
                assert c['state'] in ('pass', 'block', 'unknown')
                if c['source']:
                    assert c['source']['pages']
                    assert c['source']['pdf_sha256'] == catalog['sources'][p['source_id']]['pdf_sha256']
            forged = deepcopy(report)
            forged['checks'][0]['reason'] = 'Подменённый текст'
            try:
                safety.verify(candidate, inp, forged)
            except ValueError:
                pass
            else:
                raise AssertionError('forged result accepted')
            cases.append({'product': pid, 'case': label, 'expected_gate': gate,
                          'expected_state': expected, 'pass': True, 'report': report})
    (OUT / 'scenarios.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2) + '\n')
    return {'pass': True, 'count': len(cases), 'scope': 'actual internal engine; no HTTP route, model or clinical accuracy claim'}


if __name__ == '__main__':
    catalog = safety.release()
    result = {'status': 'PASS', 'catalog_sha256': safety.digest(catalog),
        'engine_sha256': sha(Path(safety.__file__).read_bytes()), 'scenarios': scenarios(),
        'preservation': preservation(), 'model_calls': 0, 'clinical_ready': False}
    (OUT / 'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
