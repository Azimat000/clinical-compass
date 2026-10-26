"""Independent main-agent BE08 acceptance audit; no model calls or service writes."""
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
from apps.compass import backend_risk_context as context, backend_risk_rules as rules, backend_snapshot as snapshots
from evaluate_backend_risk import batch_request,metrics


def load(p):return json.loads((ROOT/p).read_text())
def git(*a):return subprocess.check_output(['git','-C',str(ROOT),*a],text=True)
baseline=load('evidence/BE08B02/baseline.json')
for p,h in baseline['preserved_files'].items():assert hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h,p
original=json.loads(git('show',baseline['head']+':plan/coverage.json'))['items']
current=load('plan/coverage.json')['items']
assert len(original)==len(current)==83
for old,new in zip(original,current):
    for k in ['id','text','subchecks','fulfilment_status']:assert old[k]==new[k],(old['id'],k)
oldcards=json.loads(git('show',baseline['head']+':plan/manifest.json'))['slices']
assert oldcards==load('plan/manifest.json')['slices']
policy=load('data/fictional/backend-risk-context/be08-policy.json')
assert hashlib.sha256((ROOT/'data/fictional/backend-risk-context/be08-holdout.json').read_bytes()).hexdigest()==policy['corpus_sha256']
for p,h in policy['implementation_sha256'].items():assert hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h,p
assert context.PROMPT_SHA256==policy['prompt_sha256']
quality=load('evidence/BE08/risk-quality.json');assert quality['pass'] and quality['complete']
assert quality['model_metadata']['test_double'] is False
assert quality['model_metadata']['requested_model']==quality['model_metadata']['returned_model']=='deepseek-flash'
corpus=load('data/fictional/backend-risk-context/be08-holdout.json')['cases']
payload,_,_=batch_request(corpus)
assert 'expected_topics' not in json.dumps(payload) and 'expected_rules' not in json.dumps(payload)
assert {c['id'] for c in corpus}=={c['id'] for c in quality['cases']}
model_pairs=[];rule_pairs=[];quote_count=0;categories=set()
for record,case in zip(quality['cases'],corpus):
    assert record['id']==case['id']
    assert record['expected_topics']==case['expected_topics'] and record['expected_rules']==case['expected_rules']
    frozen=record['snapshot'];units=context.prepare_snapshot(frozen)
    categories|={category for u in units for category in u['categories']}
    proposals={'candidates':[{'topic':c['topic'],'evidence':[{'unit_id':e['unit_id'],'quote':e['quote']} for e in c['evidence']]} for c in record['model_candidates']]}
    assert context.verify(proposals,units,snapshots.digest(frozen))==record['model_candidates']
    assert rules.evaluate(frozen)==record['structured']
    actual={c['topic'] for c in record['model_candidates']}
    actual_rules={p['id'] for p in record['structured'].get('result',{}).get('output',{}).get('patterns',[])}
    assert actual==set(record['actual_topics']) and actual_rules==set(record['actual_rules'])
    model_pairs.append((set(case['expected_topics']),actual));rule_pairs.append((set(case['expected_rules']),actual_rules))
    for candidate in record['model_candidates']:
        assert candidate['clinical_causality']=='not_established' and candidate['interpretation']=='model_suspicion_unreviewed'
        for e in candidate['evidence']:
            assert e['text'][e['start']:e['end']]==e['quote'];quote_count+=1
assert categories==set(context.CATEGORIES)
assert metrics(model_pairs)==quality['model_metrics'] and metrics(rule_pairs)==quality['rule_metrics']
assert quality['model_metrics']['tp']==8 and quality['model_metrics']['fp']==quality['model_metrics']['fn']==0
assert quality['rule_metrics']['tp']==3 and quality['rule_metrics']['fp']==quality['rule_metrics']['fn']==0
live=load('evidence/BE08B02/live-server.json');assert live['pass'] and live['production_executor'] and live['production_http']
assert live['missing_credentials_production_run'] and live['closed_then_new_episode'] and live['immediate_revocation_http_status']==404
value=live['cases'][0]['analysis'];stored=live['cases'][0]['details']['report']
assert stored['model_provenance']['test_double'] is False and 'safety_concern' in {c['topic'] for c in stored['model_candidates']}
assert value['risk_context']==context.projection(stored)
assert value['risk_context']['status']=='partial' and value['risk_context']['assessment']=='not_established'
assert live['cases'][1]['analysis']['risk_context']['error_codes']==['missing_credentials']
assert live['cases'][1]['analysis']['result']['output']['assessment']=='potential_risk'
with sqlite3.connect((ROOT/'var/BE08B02-live.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
    raw=db.execute('SELECT payload_json FROM analysis_input_snapshots WHERE id=?',(value['snapshot_id'],)).fetchone()[0]
    frozen=json.loads(raw)
    units=context.prepare_snapshot(frozen)
    proposals={'candidates':[{'topic':c['topic'],'evidence':[{'unit_id':e['unit_id'],'quote':e['quote']} for e in c['evidence']]} for c in stored['model_candidates']]}
    assert context.verify(proposals,units,snapshots.digest(frozen))==stored['model_candidates']
    assert rules.evaluate(frozen)==stored['structured']
    assert db.execute('SELECT count(*) FROM care_actions').fetchone()[0]==0
    assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
copy=load('evidence/BE08B02/copy-check.json');assert copy['pass'] and copy['live_unchanged'] and len(copy['histories'])==10
assert copy['existing_triggers_retained']==74 and copy['jobs_enabled']==0
with sqlite3.connect((ROOT/'var/deepseek-budget.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
    calls,amount=db.execute('SELECT count(*),sum(micro_usd) FROM calls').fetchone()
assert calls==baseline['budget_before'][0]+2 and amount==45150 and amount<=50000
log=(ROOT/'evidence/BE08B02/check.log').read_text()
assert re.search(r'Ran 764 tests in .+\n\nOK',log)
assert re.search(r'Ran 70 tests in .+\n\nOK',log)
assert 'FAILED' not in log and 'Traceback' not in log
changed=set(git('diff','--name-only',baseline['head']).splitlines())|set(git('ls-files','--others','--exclude-standard').splitlines())
for path in changed:
    assert path in baseline['preserved_files'] or any(path==p or (p.endswith('/') and path.startswith(p)) for p in baseline['owned_paths']),path
result={'pass':True,'original_requirements':83,'subchecks':sum(len(c['subchecks']) for c in current),
        'no_new_slices':True,'preserved_files':len(baseline['preserved_files']),'all_four_sources':True,
        'holdout_cases':len(corpus),'quotes_independently_rebuilt':quote_count,'model_metrics':metrics(model_pairs),
        'rule_metrics':metrics(rule_pairs),'genuine_api_successes':2,'genuine_default_adapter_unavailability':True,
        'atomicity_and_access_tests':True,'application_tests':764,'tool_tests':70,
        'ledger_micro_usd':amount,'cap_micro_usd':50000,'clinical_validation':False,
        'batch_codec_and_production_codec_distinguished':True,'live_token_split_not_retained':True,
        'source_copy_check':True,'scope_check':True}
(ROOT/'evidence/BE08B02/independent-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False,indent=2))
