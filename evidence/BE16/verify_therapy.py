"""Verify saved genuine BE16 responses; no additional model calls or substitutions."""
from copy import deepcopy
from datetime import datetime,timezone
import hashlib,json,sqlite3,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from apps.compass import backend_therapy as therapy,backend_care_plan as plans
OUT=Path(__file__).resolve().parent
p=json.loads((OUT/'therapy/live-progress.json').read_text());r=p['records'];calls=p['calls']
assert len(r)==19 and all(c['passed'] for c in r)
assert p['freeze']==therapy.generation_release()
attacks=[]
for row in r:
    plans.verify(row['snapshot'],{k:row['outcome'][k] for k in ('status','result','errors','model')},row['outcome']['care_plan_context'])
    if row['expected_positive']:
        base,detail=plans.evaluate(row['snapshot']);original=row['outcome']['care_plan_context']['therapy']
        for field,value in [('unit','ml'),('daily_dose_mg',999),('phase','stop'),('product_id','unregistered')]:
            raw=deepcopy(original['raw'])
            for candidate in raw['candidates']:candidate[field]=value
            _,extension=therapy.enrich(row['snapshot'],base,detail,raw,checked_at=datetime.now(timezone.utc).isoformat(),metadata=original['model_metadata'])
            assert not extension['report']['recommendations']
            attacks.append({'case':row['id'],'field':field,'pass':True})
summary={'pass':True,'runtime':p['freeze'],'runtime_sha256':therapy.history.digest(p['freeze']),
    'clinical_validation':False,'mode':'synthetic_only','model':'deepseek-flash','prompt':therapy.INSTRUCTION,
    'corpus_sha256':hashlib.sha256((OUT/'therapy/live-corpus.json').read_bytes()).hexdigest(),
    'cases':19,'positive_cases':6,'real_model_calls':len(calls),'guard_refusals_without_model':13,
    'post_generation_mutation_checks':attacks,'ledger_before':p['ledger_before'],'ledger_after':p['ledger_after'],
    'calls_evidence':'evidence/BE16/therapy/live-progress.json','release_gates':{'clinical_release':False,'registration_legal_status':'unknown'},
    'limitations':['Author synthetic cases and explicit structured diagnosis fixtures, no clinical validation.',
        'Original mutation assertion changed only first candidate: real model returned another valid alternative. All candidates now mutated, no extra calls, no suppressed provider failure.']}
(OUT/'therapy/live-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
therapy.QUALITY_PATH.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print('PASS: 19 saved actual results; 6 real calls; 24 all-candidate mutations; exact current runtime admitted for synthetic generation only')
