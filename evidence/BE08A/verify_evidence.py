"""Independent replay of saved evidence, no provider/service writes."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from apps.compass import backend_risk_context as context, backend_risk_rules as rules
from apps.compass.backend_snapshot import digest
from tools.risk_context_smoke import snapshot, metrics

folder=ROOT/'evidence/BE08A'
base=json.loads((folder/'baseline.json').read_text())
for p,sha in base['preserved_files'].items():
    assert hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==sha,p
policy=json.loads((ROOT/'data/fictional/backend-risk-context/policy.json').read_text())
raw=(ROOT/'data/fictional/backend-risk-context/smoke.json').read_bytes()
assert hashlib.sha256(raw).hexdigest()==policy['corpus_sha256']
corpus=json.loads(raw)['cases'];report=json.loads((folder/'candidate-smoke.json').read_text())
assert report['prompt_sha256']==context.PROMPT_SHA256
assert report['policy']==policy
assert len(report['cases'])==len(corpus)==2
citations=0
for case,saved in zip(corpus,report['cases']):
    assert case['id']==saved['id'] and case['expected_topics']==saved['expected_topics']
    frozen=snapshot(case);sha=digest(frozen)
    assert saved['snapshot_sha256']==sha
    result=saved['result'];units=context.prepare_snapshot(frozen)
    assert result['structured']==rules.evaluate(frozen)
    proposals=[{'topic':c['topic'],'evidence':[{'unit_id':e['unit_id'],'quote':e['quote']} for e in c['evidence']]} for c in result['model_candidates']]
    assert context.verify({'candidates':proposals},units,sha)==result['model_candidates']
    for candidate in result['model_candidates']:
        for e in candidate['evidence']:
            assert e['quote']==e['text'][e['start']:e['end']]
            citations+=1
    assert result['assessment']=='not_established' and result['status']=='partial' and result['clinical_ready'] is False
    assert result['model_metadata']['test_double'] is False
assert metrics(report['cases'])==report['candidate_metrics']=={'tp':2,'fp':1,'fn':0}
assert report['real_adapter_failure']['errors']==[{'code':'context_limit','stage':'model_candidate_evaluation'}]
old=json.loads(subprocess.check_output(['git','show',base['head']+':plan/coverage.json'],cwd=ROOT))['items']
new=json.loads((ROOT/'plan/coverage.json').read_text())['items']
assert len(old)==len(new)==83
assert all(a['id']==b['id'] and a['subchecks']==b['subchecks'] and a['fulfilment_status']==b['fulfilment_status'] for a,b in zip(old,new))
result={'pass':True,'independent_quote_replay':citations,'candidate_metrics':report['candidate_metrics'],'semantic_quality_pass':False,'reason':'One false discrepancy candidate; not a closed quality study, BE08B required.','all_original_requirements':83,'preexisting_files_preserved':len(base['preserved_files'])}
(folder/'independent-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False))
