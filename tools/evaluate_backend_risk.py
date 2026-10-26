#!/usr/bin/env python3
"""Frozen synthetic holdout, separate rule/model metrics. No live patient database."""
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
from apps.compass import backend_snapshot as snapshots, backend_sources, decisions
from apps.compass.backend_model import Budget, Config, DeepSeek, SYSTEM

FOLDER = ROOT/'data/fictional/backend-risk-context'


def snapshot(case):
    raw={'policy':'synthetic-inputs-v1','day':'2026-10-26','relationship':'synthetic-link',
         'patients':[{'id':'fictional','synthetic':1,'age_status':'known','age_years':35,
                      'birth_date':None,'created_at':'2026-10-26T12:00:00+00:00'}],
         'backend_risk_rules':rules.release(),'backend_sources':backend_sources.capture(),
         'clinical_contexts':[], 'evidence_documents':[]}
    entries=[]; sources={}
    def register(table,row):
        ref='s2_'+snapshots.digest([table,row['id'],row]);sources[ref]={'table':table,'key':'id','id':row['id'],'sha256':snapshots.digest(row)};return ref
    register('patients',raw['patients'][0])
    for i,doc in enumerate(case['documents']):
        row={'id':str(i),'value':doc['value']};raw['evidence_documents'].append(row);ref=register('evidence_documents',row)
        entries.append({'category':doc['category'],'recorded_at':'2026-10-26T12:00:00+00:00',
            'current_revision':True,'state':'recorded','author_id':'fictional', 'fields':[
                {'source_ref':ref,'path':'/value','value':doc['value'],'event_at':doc['event_at'],
                 'context':'current','status':'unknown' if doc['value'] is None else 'known','code':doc['code']}]})
    if case['condition']:
        value={'condition':case['condition'],'severity':'nonsevere','basis':'Авторская синтетическая разметка.',
               'supersedes_id':None,**{f:'unknown' if case.get('unknown_flags') else 'denied' for f in rules.FLAGS},**case.get('flags',{})}
        row={'id':'0'*32,'relationship_id':raw['relationship'],'observed_on':raw['day'],
             'payload_json':decisions.canonical(rules._payload(value))}
        raw['clinical_contexts'].append(row);register('clinical_contexts',row)
    raw['patient_history']={'version':snapshots.VERSION,'complete':True,'truncated':False,'entries':entries,'sources':sources}
    return raw


def batch_request(cases):
    # The batching codec shares no citations across cases. Expected labels never
    # enter the model prompt, request or response schema.
    values=[]; frozen=[]
    for case in cases:
        s=snapshot(case);frozen.append(s);p=context.model_payload(context.prepare_snapshot(s))
        values.append({'i':case['id'],'units':p['units']})
    payload={'task':context.INSTRUCTION+' Process each independent case separately. Return r entries with i=case id and c=candidates. Each candidate uses t=topic index and e=[[unit_id,exact quote],...]. Never combine cases.',
             'topic_indices':list(context.TOPICS),'columns':p['columns'],'cases':values}
    candidate={'type':'object','properties':{'t':{'type':'integer','enum':list(range(len(context.TOPICS)))},
        'e':{'type':'array','minItems':1,'maxItems':8,'items':{'type':'array','minItems':2,'maxItems':2,'items':{'type':'string','minLength':1,'maxLength':1000}}}},'required':['t','e'],'additionalProperties':False}
    item={'type':'object','properties':{'i':{'type':'string','enum':[c['id'] for c in cases]},'c':{'type':'array','maxItems':16,'items':candidate}},'required':['i','c'],'additionalProperties':False}
    schema={'type':'object','properties':{'r':{'type':'array','minItems':len(cases),'maxItems':len(cases),'items':item}},'required':['r'],'additionalProperties':False}
    return payload,schema,frozen


def metrics(expected_actual):
    result={'tp':0,'fp':0,'fn':0}
    for expected,actual in expected_actual:
        result['tp']+=len(expected&actual);result['fp']+=len(actual-expected);result['fn']+=len(expected-actual)
    result['precision']=result['tp']/max(1,result['tp']+result['fp'])
    result['recall']=result['tp']/max(1,result['tp']+result['fn'])
    return result


def main():
    output=ROOT/'evidence/BE08/risk-quality.json';output.parent.mkdir(exist_ok=True)
    if output.exists():raise SystemExit('Refusing to overwrite holdout results')
    policy=json.loads((FOLDER/'be08-policy.json').read_text());data=(FOLDER/'be08-holdout.json').read_bytes()
    assert hashlib.sha256(data).hexdigest()==policy['corpus_sha256']
    assert context.PROMPT_SHA256==policy['prompt_sha256']
    for path,sha in policy['implementation_sha256'].items():assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==sha,path
    cases=json.loads(data)['cases'];payload,schema,frozen=batch_request(cases)
    key=ROOT/'var/deepseek-api-key';assert not key.stat().st_mode & 0o077
    os.environ['DEEPSEEK_API_KEY']=key.read_text().strip()
    model=DeepSeek(Config(model='deepseek-flash',timeout=60,max_input_bytes=16000,max_output_tokens=512),Budget(ROOT/'var/deepseek-budget.sqlite3'))
    report={'complete':False,'pass':False,'synthetic':True,'author_gold_only':True,'clinical_validation':False,
            'held_out_from_prompt_tuning':True,'independent_clinical_review':False,'policy':policy,
            'started_at':datetime.now(timezone.utc).isoformat(),'cases':[]}
    def save():output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    save()
    try:response=model.generate(payload,schema,synthetic=True)
    except Exception as exc:
        report['failure_code']=str(exc);save();raise
    report['model_metadata']=response['metadata'];report['raw_response']=response['value'];save()
    indexed={r['i']:r for r in response['value']['r']}
    assert len(indexed)==len(cases) and set(indexed)=={c['id'] for c in cases}
    model_pairs=[];rule_pairs=[]
    for case,s in zip(cases,frozen):
        proposals={'candidates':[{'topic':context.TOPICS[c['t']], 'evidence':[
            {'unit_id':u,'quote':q} for u,q in c['e']]} for c in indexed[case['id']]['c']]}
        try:
            candidates=context.verify(proposals,context.prepare_snapshot(s),snapshots.digest(s));error=None
        except context.ContextError as exc:candidates=[];error=str(exc)
        structured=rules.evaluate(s)
        actual_rules={p['id'] for p in structured.get('result',{}).get('output',{}).get('patterns',[])}
        actual_topics={c['topic'] for c in candidates}
        model_pairs.append((set(case['expected_topics']),actual_topics));rule_pairs.append((set(case['expected_rules']),actual_rules))
        report['cases'].append({'id':case['id'],'scenario':case['scenario'],'expected_topics':case['expected_topics'],
            'actual_topics':sorted(actual_topics),'expected_rules':case['expected_rules'],'actual_rules':sorted(actual_rules),
            'raw_topics':sorted({c['topic'] for c in proposals['candidates']}),'candidate_error':error,
            'snapshot':s,'model_candidates':candidates,'structured':structured})
    report['model_metrics']=metrics(model_pairs);report['rule_metrics']=metrics(rule_pairs)
    m=report['model_metrics'];r=report['rule_metrics'];limits=policy['acceptance']
    mandatory={c['id']:set(c['actual_topics']) for c in report['cases']}
    report['pass']=(m['precision']>=limits['model_precision_min'] and m['recall']>=limits['model_recall_min']
        and r['fp']==r['fn']==0 and 'safety_concern' in mandatory['h3']
        and 'safety_concern' in mandatory['h4'] and 'discrepancy' not in mandatory['h7']
        and not mandatory['h6'] and not mandatory['h8'] and all(not c['candidate_error'] for c in report['cases']))
    with sqlite3.connect(ROOT/'var/deepseek-budget.sqlite3') as db:
        report['ledger_micro_usd']=db.execute('SELECT sum(micro_usd) FROM calls').fetchone()[0]
    report.update(complete=True,finished_at=datetime.now(timezone.utc).isoformat());save()
    print(json.dumps({k:report[k] for k in ['pass','model_metrics','rule_metrics','ledger_micro_usd']}))
    return 0 if report['pass'] else 1


if __name__=='__main__':raise SystemExit(main())
