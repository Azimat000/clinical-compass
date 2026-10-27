"""Frozen regression of actual packet/model/queue outcomes. No live DB writes."""
from contextlib import closing
from copy import deepcopy
from datetime import timedelta,datetime,timezone
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import sqlite3
import sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from apps.compass import backend_packet_pipeline as pipeline,backend_packet_store as store
from apps.compass import backend_analyses as analyses,backend_jobs as jobs,backend_model as model,records
from apps.tests.diagnosis_fixtures import CleanDiagnosticCase
OUT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('risk_reference',ROOT/'tools/evaluate_backend_risk.py')
risk_reference=importlib.util.module_from_spec(spec);spec.loader.exec_module(risk_reference)
read=lambda p:json.loads(p.read_text())
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

def ledger():
    with closing(sqlite3.connect('file:'+str(ROOT/'var/deepseek-budget.sqlite3')+'?mode=ro',uri=True)) as db:
        return list(db.execute('SELECT count(*),sum(micro_usd) FROM calls').fetchone())

def freeze():
    return {'runtime_sha256':pipeline.snapshots.digest(pipeline.release()),'development_sha256':sha(OUT/'development.json'),
            'regression_sha256':sha(OUT/'regression.json'),'protocol_sha256':sha(Path(__file__)),
            'frozen_before_live':True,'independent_clinical_review':False,'reuses_prior_controls':True}

def fixture(case):
    f=CleanDiagnosticCase();f.populate(case)
    for i in range(case.get('padding_records',0)):
        records.save(f.db,f.patient,'D01','self_report',{'request_key':secrets.token_hex(16),
            'observed_on':(records.today()-timedelta(days=20+i)).isoformat(),
            'summary':f'Архивная синтетическая строка {i}. Подробности нынешнего состояния в эту дату не собирались. Сведения для проверки сохранности длинной истории.','wellbeing':'unknown'})
    for i,note in enumerate(case.get('old_notes',[])):
        records.save(f.db,f.patient,'D01','self_report',{'request_key':secrets.token_hex(16),
            'observed_on':(records.today()-timedelta(days=50+i)).isoformat(),'summary':note,'wellbeing':'unknown'})
    f.db.execute('UPDATE backend_job_settings SET generation_version=?',(pipeline.EXECUTION_VERSION,))
    return f

class Recorder:
    def __init__(self,path):self.path=path;self.calls=[]
    def generate(self,data,schema,**kw):
        row={'branch':data['branch'],'packet_index':data['transport']['packet_index'],
             'payload_sha256':pipeline.snapshots.digest(data)}
        try:
            response=model.DeepSeek(pipeline.config(),model.Budget(ROOT/'var/deepseek-budget.sqlite3')).generate(data,schema,**kw)
            row['response']=response;return response
        except model.ModelError as exc:row.update(error_code=exc.code,safe_usage=exc.usage);raise
        finally:
            self.calls.append(row);self.path.write_text(json.dumps(self.calls,ensure_ascii=False,indent=2)+'\n')

def prepare():
    rows=[]
    for phase in ['development','regression']:
        for case in read(OUT/(phase+'.json'))['cases']:
            f=None
            try:
                if case['operation']=='diagnosis':f=fixture(case);snapshot=f.snapshot()
                else:snapshot=risk_reference.snapshot(case)
                planned=pipeline.plans(snapshot,case['operation'])
                rows.append({'phase':phase,'id':case['id'],'operation':case['operation'],
                    'packet_count':sum(len(v[0]['packets']) for v in planned.values()),
                    'maximum_reservation_micro_usd':sum(v[0]['total_reservation_micro_usd'] for v in planned.values())})
            finally:
                if f:f.close()
    value={'freeze':freeze(),'ledger':ledger(),'rows':rows,'cap_micro_usd':pipeline.TOTAL_CAP,'per_call_micro_usd':20000,
           'all_cases_worst_reservations_micro_usd':sum(r['maximum_reservation_micro_usd'] for r in rows),
           'all_cases_calls':sum(r['packet_count'] for r in rows),'new_network_calls':0,
           'retry_limit':3,'policy':'freeze before calls; failed requests retain costs; no overwrite; checkpoints reuse only exact run'}
    (OUT/'budget-plan.json').write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');return value

def live(phase,label):
    plan=read(OUT/'budget-plan.json');assert plan['freeze']==freeze(),'Changed runtime/protocol/corpus; freeze again before calls'
    assert datetime.now(timezone.utc)<datetime.fromisoformat('2026-10-27T19:17:00+03:00'),'Source gate expired'
    destination=OUT/label;assert not destination.exists(),'Refuse overwrite/repeated paid run'
    destination.mkdir()
    key=ROOT/'var/deepseek-api-key';assert key.stat().st_mode&0o077==0
    os.environ['DEEPSEEK_API_KEY']=key.read_text().strip()
    before=ledger();results=[]
    for case in read(OUT/(phase+'.json'))['cases']:
        f=None;record={'id':case['id'],'operation':case['operation'],'pass':False};recorder=Recorder(destination/(case['id']+'-calls.json'))
        try:
            if case['operation']=='diagnosis':
                f=fixture(case);run=analyses.create(f.db,f.user,'D01',{'contract_version':'1.0','operation':'diagnosis','request_key':secrets.token_hex(16)})
                work=jobs.claim(f.db,'generation');snapshot=work['snapshot'];record['snapshot']=snapshot
                start=__import__('time').monotonic()
                outcome=pipeline.execute('diagnosis',snapshot,recorder,store.Store(f.path,work))
                record.update(outcome=outcome,elapsed_seconds=round(__import__('time').monotonic()-start,3))
                assert jobs.finish(f.db,work,outcome)
                analysis=analyses.read(f.db,f.user,'D01',run['run_id']);record['analysis']=analysis
                assert analysis['status'] in ('ready','unsupported','insufficient_data'),analysis['status']
                ctx=outcome['diagnosis_report']['context']
                actual={h['kind']+'.'+q['id']:q['state'] for h in ctx['hypotheses'][:2] for q in h['facts']}
                raw_actual={k+'.'+f['id']:f['state'] for k,part in outcome['diagnosis_report']['named_assertions'].items() for f in part['facts']}
                record['raw_fact_checks']={k:raw_actual[k]==v for k,v in case['expected_facts'].items()}
                record.update(leading_exact=ctx['leading']==case['leading'],disposition_exact=ctx['disposition']==case['disposition'],
                    fact_checks={k:actual[k]==v for k,v in case['expected_facts'].items()},
                    duration_checks={k:ctx['raw']['durations'][k]['value']==v for k,v in case.get('expected_durations',{}).items()},
                    dangerous_omissions=[k for k in case.get('dangerous_facts',[]) if actual[k]!='present'],
                    packet_count=len(outcome['packet_proof']['cells']),checkpoints=f.db.execute('SELECT count(*) FROM analysis_packet_results').fetchone()[0])
                cautions=outcome['diagnosis_report']['model_metadata']['historical_cautions']
                record['historical_caution_check']=(len(cautions)>=case.get('required_historical_cautions',0) and not (case.get('forbid_historical_cautions') and cautions))
                record['pass']=(record['historical_caution_check'] and record['leading_exact'] and record['disposition_exact'] and all(record['fact_checks'].values())
                                and all(record['duration_checks'].values()) and not record['dangerous_omissions'])
                assert f.db.execute('SELECT count(*) FROM care_actions').fetchone()[0]==0
            else:
                snapshot=risk_reference.snapshot(case);record['snapshot']=snapshot
                outcome=pipeline.execute('risk',snapshot,recorder);record['outcome']=outcome
                report=outcome['risk_context_report'];actual={c['topic'] for c in report['model_candidates']}
                record.update(expected_topics=case['expected_topics'],actual_topics=sorted(actual),
                    expected_rules=case['expected_rules'],actual_rules=sorted(p['id'] for p in report['structured'].get('result',{}).get('output',{}).get('patterns',[])),
                    packet_count=len(outcome['packet_proof']['cells']))
                record['pass']=(report['model_evaluation']=='candidates_only' and not report['errors'])
        except Exception as exc:record.update(error_code=getattr(exc,'code','validation_or_publication_error'),error_type=type(exc).__name__)
        finally:
            if f:f.close()
        (destination/(case['id']+'.json')).write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
        results.append(record)
        print(case['id'],'PASS' if record['pass'] else 'FAIL',record.get('error_code',''),flush=True)
    os.environ.pop('DEEPSEEK_API_KEY',None)
    diag=[r for r in results if r['operation']=='diagnosis'];risks=[r for r in results if r['operation']=='risk']
    metrics=risk_reference.metrics([(set(r.get('expected_topics',[])),set(r.get('actual_topics',[]))) for r in risks])
    rule_errors=sum(set(r.get('expected_rules',[]))!=set(r.get('actual_rules',[])) for r in risks)
    mandatory=all(not set(r.get('actual_topics',[])) for r in risks if r['id'] in ('h6','h8')) and all('discrepancy' not in r.get('actual_topics',[]) for r in risks if r['id']=='h7') and all('safety_concern' in r.get('actual_topics',[]) for r in risks if r['id'] in ('h3','h4'))
    passed=all(r['pass'] for r in results) and (not risks or metrics['precision']>=.85 and metrics['recall']>=.85 and rule_errors==0 and mandatory)
    summary={'pass':passed,'phase':phase,'cases':len(results),'diagnosis_cases':len(diag),'risk_cases':len(risks),
        'diagnostic_valid':sum(r['pass'] for r in diag),'expected_facts':sum(len(r.get('fact_checks',{})) for r in diag),
        'correct_facts':sum(sum(r.get('fact_checks',{}).values()) for r in diag),'raw_model_correct_facts':sum(sum(r.get('raw_fact_checks',{}).values()) for r in diag),'dangerous_omissions':sum(len(r.get('dangerous_omissions',[])) for r in diag),
        'risk_metrics':metrics,'risk_rule_case_errors':rule_errors,'negative_chronology_checks':mandatory,
        'freeze':freeze(),'ledger_before':before,'ledger_after':ledger(),'real_model':True,
        'independent_clinical_review':False,'results':[r['id'] for r in results]}
    (destination/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n');return summary

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--phase',choices=['development','regression']);p.add_argument('--label');a=p.parse_args()
    result=live(a.phase,a.label) if a.phase and a.label else prepare()
    print(json.dumps(result,ensure_ascii=False,indent=2))
