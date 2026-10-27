"""Reproducible BE14 dependency probe, not a live-model quality evaluation."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from apps.compass import backend_medication_safety as safety
from apps.compass import backend_therapy as therapy

at = datetime.now(timezone.utc)
catalog = safety.release()
patient = {'mode':'synthetic_only', 'synthetic':True}
def fact(key, value):
    patient[key] = {'value':value, 'refs':['synthetic:optimistic-mechanics:' + key]}
fact('age', 40)
for product in catalog['products'].values():
    for key in product['required_facts']:
        fact(key, False)
fact('allergies', [])
fact('allergies_complete', True)
fact('medications', [])
fact('medications_complete', True)
scenarios = []
for pid, strength, daily, times, indication in [
    ('elicea',10,10,1,'adult_depression'),
    ('aleval',50,50,1,'adult_depression'),
    ('aviandr',20,40,2,'adult_gad')]:
    base = dict(product_id=pid, form='film_coated_tablet', strength_mg=strength,
                unit='mg', indication=indication, daily_dose_mg=daily, times_per_day=times)
    for phase in sorted(therapy.PHASES):
        candidate = dict(base, phase=phase)
        report = safety.evaluate(candidate, patient, at=at)
        assert safety.verify(candidate, patient, report, at=at)
        assert report['state'] == 'unknown' and not report['eligible']
        codes = {c['code'] for c in report['checks'] if c['state']=='unknown'}
        assert {'source', 'excipient_coverage', 'coverage'} <= codes
        if phase != 'maintenance':
            assert 'regimen_phase' in codes
        scenarios.append({'product_id':pid, 'phase':phase, 'state':report['state'],
                          'eligible':report['eligible'], 'unknown_codes':sorted(codes),
                          'report_sha256':safety.digest(report)})
    for changed, expected in [({'unit':'ml'}, 'unit'), ({'daily_dose_mg':999}, 'dose')]:
        candidate = dict(base, phase='maintenance') | changed
        report = safety.evaluate(candidate, patient, at=at)
        assert report['state']=='block'
        assert next(c['state'] for c in report['checks'] if c['code']==expected)=='block'
        scenarios.append({'product_id':pid, 'case':expected, 'state':'block', 'eligible':False})
quality = {'version':therapy.VERSION, 'observed_at':at.isoformat(),
           'quality_status':'not_measured', 'real_model_runs':0,
           'clinical_validation':False, 'BE14_A01':'NOT_MET',
           'positive_regimen_success_rate':None,
           'probe':'independent checker only; not generation or recommendation quality',
           'optimistic_facts':'author supplied synthetic mechanics; no clinical attestation',
           'catalog_sha256':safety.digest(catalog), 'runtime':therapy.release(),
           'scenario_count':len(scenarios), 'scenarios':scenarios,
           'dependency_result':'0 of 12 product/phase combinations can receive independent pass',
           'remaining_work':['source/ingredient/interaction coverage', 'coded physician reconciliation',
                             'generation and post-generation integration', 'real positive and adversarial model runs']}
(ROOT/'evidence/BE14/therapy-quality.json').write_text(json.dumps(quality,ensure_ascii=False,indent=2)+'\n')
print('PASS: 18 mechanical probes; no full independent pass; live generation quality NOT measured.')
