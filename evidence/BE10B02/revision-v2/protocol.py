"""Reviewable diagnostic protocol. Default is offline sizing; live needs raised cap.

No existing run is overwritten. Development must pass before untouched holdout.
Only an explicit --phase argument can select a real-provider run after approval.
"""
from contextlib import closing
from datetime import datetime,timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from apps.compass import backend_analyses as analyses,backend_jobs as jobs,backend_model as model
from apps.compass import backend_diagnosis_service as service,backend_diagnosis_codec as codec
from apps.tests.diagnosis_fixtures import CleanDiagnosticCase

OUT=Path(__file__).resolve().parent
CONFIG=lambda:model.Config(model='deepseek-flash',max_input_bytes=16000,max_output_tokens=codec.MAX_OUTPUT_TOKENS,timeout=60)
sha=lambda b:hashlib.sha256(b).hexdigest()
read=lambda p:json.loads(p.read_text())

def ledger():
    with closing(sqlite3.connect('file:'+str(ROOT/'var/deepseek-budget.sqlite3')+'?mode=ro',uri=True)) as db:
        return list(db.execute('SELECT count(*),sum(micro_usd) FROM calls').fetchone())

def freeze_values():
    return {'development_sha256':sha((OUT/'development.json').read_bytes()),
            'holdout_sha256':sha((OUT/'holdout.json').read_bytes()),
            'protocol_sha256':sha(Path(__file__).read_bytes()),
            'runtime_sha256':service.snapshots.digest(service.release()),
            'fixture_sha256':sha((ROOT/'apps/tests/diagnosis_fixtures.py').read_bytes()),
            'frozen_before_live':True,'independent_clinical_review':False}

def dry_run():
    rows=[];snapshots=[]
    for phase in ('development','holdout'):
        for case in read(OUT/(phase+'.json'))['cases']:
            fixture=CleanDiagnosticCase()
            try:
                fixture.populate(case);snapshot=fixture.snapshot();fixture.assert_clean(case)
                for kind in service.criteria.release()['conditions']:
                    value=model.preflight(service.payload(snapshot,kind),codec.schema(kind),CONFIG())
                    rows.append({'phase':phase,'id':case['id'],'branch':kind,
                                 'input_bytes':value['input_bytes'],'reservation_micro_usd':value['reservation_micro_usd'],
                                 'request_sha256':sha(value['body']),'schema_sha256':value['schema_sha256']})
                snapshots.append({'phase':phase,'id':case['id'],'categories':snapshot['patient_history']['counts'],
                    'fixture_clean':True,'unapproved_encounters':len(snapshot['encounters']),
                    'care_actions':len(snapshot['actions'])})
            finally:fixture.close()
    used=ledger();development=sum(r['reservation_micro_usd'] for r in rows if r['phase']=='development')
    holdout=sum(r['reservation_micro_usd'] for r in rows if r['phase']=='holdout')
    integration=sum(r['reservation_micro_usd'] for r in rows if r['id']=='H01')
    # An additional untouched 8-case set is budgeted at the unchanged hard per-call ceiling.
    repeat=16*CONFIG().per_call_micro_usd
    minimum=used[1]+development+holdout+integration
    total_worst=minimum+repeat
    rounded=((total_worst+99999)//100000)*100000
    recommended=max(1000000,rounded)
    result={'status':'OFFLINE_ONLY','network_calls':0,'ledger':used,
        'active_total_cap_micro_usd':CONFIG().total_micro_usd,'active_per_call_cap_micro_usd':CONFIG().per_call_micro_usd,
        'max_output_tokens':CONFIG().max_output_tokens,'request_count':len(rows),'rows':rows,'fixtures':snapshots,
        'protective_budget':{'development_8_calls':development,'holdout_16_calls':holdout,'integration_2_calls':integration,
            'one_fresh_repeat_16_calls':repeat,'minimum_total_cap_micro_usd':minimum,
            'minimum_rounded_total_cap_micro_usd':((minimum+49999)//50000)*50000,
            'rounded_cap_with_repeat_micro_usd':rounded,'recommended_total_cap_micro_usd':recommended,
            'recommended_headroom_micro_usd':recommended-total_worst,'recommended_increase_micro_usd':recommended-CONFIG().total_micro_usd,
            'maximum_calls_with_repeat':42,'actual_invoice':None,'rub_conversion':None},
        'money_limit_changed':False,'freeze':freeze_values()}
    (OUT/'budget-plan.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return result

class RecordingAdapter:
    def __init__(self,path):self.path=path;self.calls=[]
    def generate(self,data,schema,**kw):
        record={'branch':data['branch'],'payload_sha256':sha(json.dumps(data,ensure_ascii=False,sort_keys=True).encode()),
                'schema_sha256':sha(json.dumps(schema,sort_keys=True).encode())}
        try:
            result=model.DeepSeek(CONFIG(),model.Budget(ROOT/'var/deepseek-budget.sqlite3')).generate(data,schema,**kw)
            record.update(response=result)
            return result
        except model.ModelError as exc:
            record.update(error_code=exc.code,safe_usage=exc.usage)
            raise
        finally:
            self.calls.append(record)
            self.path.write_text(json.dumps(self.calls,ensure_ascii=False,indent=2)+'\n')

def live(phase):
    plan=read(OUT/'budget-plan.json')
    if plan['freeze']!=freeze_values():raise SystemExit('Changed protocol or fixtures; regenerate offline plan before calls')
    required=plan['protective_budget']['minimum_total_cap_micro_usd']
    if CONFIG().total_micro_usd<required:
        raise SystemExit('Budget increase not authorized/configured; no credentials, reservation or HTTP used')
    destination=OUT/('live-'+phase)
    if destination.exists():raise SystemExit('Refuse replay or overwrite of this frozen run')
    if phase!='development':
        previous=read(OUT/'live-development/summary.json')
        if not previous['pass'] or previous['freeze']!=freeze_values():raise SystemExit('Development not passed on exact version')
    corpus=read(OUT/('development.json' if phase=='development' else 'holdout.json'))
    cases=corpus['cases'] if phase!='integration' else corpus['cases'][:1]
    destination.mkdir();key=ROOT/'var/deepseek-api-key'
    if key.stat().st_mode & 0o077:raise SystemExit('Unsafe credential permissions')
    os.environ['DEEPSEEK_API_KEY']=key.read_text().strip()
    before=ledger();results=[]
    for case in cases:
        fixture=CleanDiagnosticCase();adapter=RecordingAdapter(destination/(case['id']+'-calls.json'))
        value={'id':case['id'],'real_provider':True,'valid_response':False}
        try:
            fixture.populate(case)
            run=analyses.create(fixture.db,fixture.user,'D01',{'contract_version':'1.0','operation':'diagnosis','request_key':os.urandom(16).hex()})
            work=jobs.claim(fixture.db,'generation');value['snapshot']=work['snapshot']
            report=service.execute('diagnosis',work['snapshot'],adapter);value['report']=report
            assert jobs.finish(fixture.db,work,report)
            analysis=analyses.read(fixture.db,fixture.user,'D01',run['run_id'])
            expected_state={'candidates':'ready','insufficient_data':'insufficient_data','unsupported':'unsupported'}[report['diagnosis_report']['context']['disposition']]
            assert analysis['status']==expected_state
            path='/api/v1/patients/D01/analyses/'+run['run_id']+'/diagnosis-context'
            response=fixture.clients['doc-a'].get(path)
            assert response.status_code==200 and response.json['report']==report['diagnosis_report']['context']
            assert fixture.clients['doc-a'].head(path).status_code==200
            assert fixture.clients['doc-b'].get(path).status_code in (403,404)
            fixture.assert_clean(case)
            ctx=report['diagnosis_report']['context']
            actual={h['kind']+'.'+f['id']:f['state'] for h in ctx['hypotheses'][:2] for f in h['facts']}
            value.update(valid_response=True,leading_exact=ctx['leading']==case['leading'],
                disposition_exact=ctx['disposition']==case['disposition'],
                fact_checks={k:actual[k]==v for k,v in case['expected_facts'].items()},
                duration_checks={k:ctx['raw']['durations'][k]['value']==v for k,v in case.get('expected_durations',{}).items()},
                dangerous_omissions=[k for k in case.get('dangerous_facts',[]) if actual[k]!='present'],care_actions=0)
        except Exception as exc:
            value.update(error_code=getattr(exc,'code','validation_or_publication_error'),error_type=type(exc).__name__)
        finally:fixture.close()
        (destination/(case['id']+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
        results.append(value)
    good=[r for r in results if r['valid_response']]
    passed=len(good)==len(cases) and all(r['leading_exact'] and r['disposition_exact'] and all(r['fact_checks'].values()) and all(r['duration_checks'].values()) and not r['dangerous_omissions'] for r in good)
    summary={'pass':passed,'phase':phase,'freeze':freeze_values(),'cases':len(cases),'valid_responses':len(good),
             'ledger_before':before,'ledger_after':ledger(),'results':[r['id'] for r in results],
             'independent_clinical_review':False,'timestamp_utc':datetime.now(timezone.utc).isoformat()}
    (destination/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    return summary

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--phase',choices=['development','holdout','integration'])
    args=parser.parse_args()
    result=live(args.phase) if args.phase else dry_run()
    print(json.dumps(result.get('protective_budget',result),ensure_ascii=False,indent=2))
