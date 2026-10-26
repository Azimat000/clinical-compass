"""Main-agent independent audit of actual artifacts, active data and protected ledger."""
from contextlib import closing
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'START_HERE.md').is_file());sys.path.insert(0,str(ROOT))
from apps.compass import backend_diagnosis_service as service,backend_diagnosis_codec as codec
from apps.compass import backend_sources as sources,backend_snapshot as snapshots,backend_risk_context as context
OUT=Path(__file__).resolve().parent;FINAL=OUT/'iteration-5'
read=lambda p:json.loads(p.read_text())
sha=lambda b:hashlib.sha256(b).hexdigest()
BASE=read(OUT/'baseline.json')
ALTERNATIVE_FIELDS={'mania_hypomania','organic_cause','somatic_cause','medication_cause','substance_cause',
                    'other_primary_disorder','panic_disorder','phobic_disorder','ocd','hypochondriacal_disorder'}

def audit():
    assert BASE['diff']==BASE['cached_diff']==''
    for path,expected in BASE['preserved_files'].items():assert sha((ROOT/path).read_bytes())==expected,path
    assert sha((ROOT/'var/clinic-20261026-access.md').read_bytes())==BASE['access_sha256']
    with closing(sqlite3.connect('file:'+str(ROOT/'var/compass.sqlite3')+'?mode=ro',uri=True)) as db:
        tables={t:sha(json.dumps(sorted(json.dumps(row,ensure_ascii=False,default=str) for row in db.execute('SELECT * FROM "'+t+'"')),ensure_ascii=False).encode()) for (t,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        assert tables==BASE['active_db_tables']
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
        assert db.execute('SELECT count(*) FROM patients').fetchone()[0]==10
    with closing(sqlite3.connect('file:'+str(ROOT/'var/deepseek-budget.sqlite3')+'?mode=ro',uri=True)) as db:
        all_rows=[list(r) for r in db.execute('SELECT * FROM calls ORDER BY id')]
        assert all(r in all_rows for r in BASE['ledger_rows'])
        ledger=list(db.execute('SELECT count(*),sum(micro_usd) FROM calls').fetchone())
        assert ledger[1]<=1000000
    for path in ['apps/compass/ages.py','apps/compass/backend_diagnoses.py','apps/compass/backend_diagnosis_criteria.py',
                 'apps/compass/backend_risk_rules.py','apps/compass/backend_risk_context.py','apps/compass/backend_jobs.py',
                 'data/backend/diagnosis-criteria-v1.json','data/retrieval/source-registry.json','data/backend/source-catalog-v1.json',
                 'apps/requirements.lock','plan/manifest.json']:
        assert (ROOT/path).read_bytes()==subprocess.check_output(['git','show',BASE['head']+':'+path],cwd=ROOT),path
    coverage=read(ROOT/'plan/coverage.json')
    old=json.loads(subprocess.check_output(['git','show',BASE['head']+':plan/coverage.json'],cwd=ROOT))
    assert [(i['id'],i['text'],i['subchecks'],i['fulfilment_status']) for i in coverage['items']]==[(i['id'],i['text'],i['subchecks'],i['fulfilment_status']) for i in old['items']]
    current=sources.capture();catalog=service.criteria.release()
    for c in catalog['conditions'].values():
        sources.require(current,[c['admission_claim']],'diagnosis',age_min=18,age_max=120,condition=c['condition'])
        source=current['sources'][c['source_id']]['source'];assert sha((ROOT/source['path']).read_bytes())==source['sha256']
    runtime=snapshots.digest(service.release());inventory=[];citation_count=0;phases={}
    for phase in ('development','holdout','integration'):
        folder=FINAL/('live-'+phase);summary=read(folder/'summary.json')
        assert summary['pass'] and summary['freeze']['runtime_sha256']==runtime
        assert sha((FINAL/'development.json').read_bytes())==summary['freeze']['development_sha256']
        assert sha((FINAL/'holdout.json').read_bytes())==summary['freeze']['holdout_sha256']
        assert sha((FINAL/'protocol.py').read_bytes())==summary['freeze']['protocol_sha256']
        assert sha((ROOT/'apps/tests/diagnosis_fixtures.py').read_bytes())==summary['freeze']['fixture_sha256']
        cases=read(FINAL/('development.json' if phase=='development' else 'holdout.json'))['cases']
        if phase=='integration':cases=cases[:1]
        metrics={'cases':len(cases),'valid':0,'leading':0,'disposition':0,'facts':0,'expected_facts':0,
                 'alternative_facts':0,'expected_alternative_facts':0,'durations':0,'expected_durations':0,
                 'dangerous_positive_facts':0,'dangerous_omissions':0,
                 'raw_model_facts_correct':0,'raw_model_expected_facts':0,'raw_model_alternative_facts_correct':0,'raw_model_expected_alternative_facts':0,'queue_attempts':0}
        for case in cases:
            value=read(folder/(case['id']+'.json'));calls=read(folder/(case['id']+'-calls.json'))
            assert 2<=len(calls)<=6 and value['valid_response'] and value['care_actions']==0
            snapshot=value['snapshot'];units={u['unit_id']:u for u in context.prepare_snapshot(snapshot)}
            named={call['branch']:call['response']['value'] for call in calls}
            reconstructed=service.named_interpret(snapshot,named)
            saved=value['report']['diagnosis_report']
            assert reconstructed==saved['context'] and named==saved['named_assertions']
            assert snapshots.digest(snapshot)==reconstructed['snapshot_sha256']
            for call in calls:
                metadata=call['response']['metadata']
                assert metadata['test_double'] is False and metadata['returned_model']=='deepseek-flash'
                assert metadata['requested_model']=='deepseek-flash' and metadata['max_output_tokens']==1536
                for q in call['response']['value']['quotes']:
                    u=units[q['unit_id']];assert q['quote'] and q['quote'] in u['text'];citation_count+=1
                payload=service.payload(snapshot,call['branch'])
                assert sha(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode())==call['payload_sha256']
                assert sha(json.dumps(codec.schema(call['branch']),sort_keys=True).encode())==call['schema_sha256']
            assert reconstructed['established_diagnosis'] is reconstructed['diagnosis_code'] is reconstructed['plan'] is None
            assert reconstructed['clinical_ready'] is False
            actual={h['kind']+'.'+f['id']:f['state'] for h in reconstructed['hypotheses'][:2] for f in h['facts']}
            raw_actual={kind+'.'+f['id']:f['state'] for kind,part in named.items() for f in part['facts']}
            raw_checks={k:raw_actual[k]==v for k,v in case['expected_facts'].items()}
            metrics['raw_model_facts_correct']+=sum(raw_checks.values());metrics['raw_model_expected_facts']+=len(raw_checks)
            raw_alternatives=[v for k,v in raw_checks.items() if k.split('.')[1] in ALTERNATIVE_FIELDS]
            metrics['raw_model_alternative_facts_correct']+=sum(raw_alternatives);metrics['raw_model_expected_alternative_facts']+=len(raw_alternatives)
            checks={k:actual[k]==v for k,v in case['expected_facts'].items()}
            assert all(checks.values()) and checks==value['fact_checks']
            durations={k:reconstructed['raw']['durations'][k]['value']==v for k,v in case['expected_durations'].items()}
            assert all(durations.values()) and durations==value['duration_checks']
            assert reconstructed['leading']==case['leading'] and reconstructed['disposition']==case['disposition']
            dangerous=[k for k in case.get('dangerous_facts',[]) if actual[k]!='present'];assert dangerous==[]
            metrics['queue_attempts']+=value.get('queue_attempts',1)
            metrics['valid']+=1;metrics['leading']+=1;metrics['disposition']+=1
            metrics['facts']+=sum(checks.values());metrics['expected_facts']+=len(checks)
            alternative=[ok for k,ok in checks.items() if k.split('.')[1] in ALTERNATIVE_FIELDS]
            metrics['alternative_facts']+=sum(alternative);metrics['expected_alternative_facts']+=len(alternative)
            metrics['durations']+=sum(durations.values());metrics['expected_durations']+=len(durations)
            metrics['dangerous_positive_facts']+=len(case.get('dangerous_facts',[]))
            if phase=='holdout':
                inventory.append({'id':case['id'],'leading':reconstructed['leading'],'disposition':reconstructed['disposition'],
                    'known_facts':[{ 'kind':h['kind'],'id':f['id'],'state':f['state'],
                        'quotes':[reconstructed['evidence'][abs(i)-1]['quote'] for i in f['refs']]}
                        for h in reconstructed['hypotheses'][:2] for f in h['facts'] if f['state']!='unknown']})
        phases[phase]=metrics
    http_report=None
    http_path=OUT/'default-http-report.json'
    if http_path.exists():
        http=read(http_path)
        assert http['status']=='PASS' and http['runtime_sha256']==runtime
        assert http['driver_sha256']==sha((OUT/'default_http.py').read_bytes())
        assert http['default_executor'] is True and http['test_double'] is False
        assert http['creation_http_status']==202 and http['idempotent_before_and_after'] is True
        assert http['read_head_access_cancel_and_stale']=='PASS' and http['care_actions']==0
        assert http['ledger_after'][0]-http['ledger_before'][0]==2
        default_calls=read(OUT/'default-http-calls.json')
        named={call['branch']:call['response']['value'] for call in default_calls}
        reconstructed=service.named_interpret(http['snapshot'],named)
        assert reconstructed==http['outcome']['diagnosis_report']['context']
        for call in default_calls:
            assert call['response']['metadata']['test_double'] is False
            assert call['response']['metadata']['returned_model']=='deepseek-flash'
            units={u['unit_id']:u for u in context.prepare_snapshot(http['snapshot'])}
            for q in call['response']['value']['quotes']:
                assert q['quote'] and q['quote'] in units[q['unit_id']]['text'];citation_count+=1
            payload=service.payload(http['snapshot'],call['branch'])
            assert sha(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode())==call['payload_sha256']
        http_report={'status':'PASS','http_create':202,'real_default_model_calls':2,
                     'idempotence_access_cancel_stale':'PASS','care_actions':0}

    # Every actual call has one durable ledger entry; old unknown reservations stay untouched.
    traces=[call for file in OUT.rglob('*-calls.json') for call in read(file)]
    assert len(all_rows)-len(BASE['ledger_rows'])==len(traces)
    meta=[c['response']['metadata'] for c in traces if 'response' in c]
    safe=[c['safe_usage'] for c in traces if c.get('safe_usage')]
    assert len(meta)+len(safe)==len(traces)
    assert sum(m['cost_ceiling_micro_usd'] for m in meta)+sum(m['cost_ceiling_micro_usd'] for m in safe)==ledger[1]-BASE['ledger'][1]
    accounting={'new_calls':len(traces),'known_prompt_tokens':sum(m['usage']['prompt_tokens'] for m in meta)+sum(m['prompt_tokens'] for m in safe),
        'known_completion_tokens':sum(m['usage']['completion_tokens'] for m in meta)+sum(m['completion_tokens'] for m in safe),
        'new_ledger_ceiling_micro_usd':ledger[1]-BASE['ledger'][1],'ledger':ledger,
        'cap_micro_usd':1000000,'remaining_micro_usd':1000000-ledger[1],
        'known_estimated_peak_usd':sum(m['estimated_peak_cost_nano_usd'] for m in meta)/1e9,
        'known_estimated_offpeak_usd':sum(m['estimated_offpeak_cost_nano_usd'] for m in meta)/1e9,
        'price_metadata_calls':len(meta),'safe_usage_only_calls':len(safe),
        'safe_usage_peak_upper_usd':sum(m['prompt_tokens']*.0000003+m['completion_tokens']*.0000012 for m in safe),
        'actual_invoice':None,'rub_conversion':None,'old_ledger_preserved':True,'old_unknown_reservations_micro_usd':4072}
    allowed={'apps/compass/backend_diagnosis_codec.py','apps/compass/backend_diagnosis_service.py',
      'apps/compass/backend_model.py','apps/tests/diagnosis_fixtures.py','apps/tests/test_backend_diagnosis_codec.py',
      'apps/tests/test_backend_diagnosis_integration.py','apps/tests/test_backend_model.py',
      'apps/tests/test_backend_contracts.py','apps/tests/test_clinic_medication_revision.py',
      'docs/architecture/backend-api.json','docs/architecture/backend-diagnoses.md',
      'START_HERE.md','memory/STATE.json','memory/sessions/BE10B02.md','memory/DECISIONS.md',
      'memory/BLOCKERS.md','memory/EXTERNAL.md','memory/BUDGET.json','plan/backend/requirements.json',
      'plan/coverage.json','plan/COVERAGE.md','evidence/BE10/diagnosis-quality.json','evidence/BE10B02/acceptance.md'}
    changed=set(subprocess.check_output(['git','diff','HEAD','--name-only'],cwd=ROOT,text=True).splitlines())
    new=set(subprocess.check_output(['git','ls-files','--others','--exclude-standard'],cwd=ROOT,text=True).splitlines())-set(BASE['preserved_files'])
    secret=(ROOT/'var/deepseek-api-key').read_bytes().strip()
    for path in changed|new:
        assert path in allowed or path.startswith('evidence/BE10B02/revision-v2/'),path
        assert secret not in (ROOT/path).read_bytes(),path
    state=read(ROOT/'memory/STATE.json')
    assert state['current_slice'] is None and state['last_accepted_slice']=='BE10B02' and state['next_slice']=='BE10B'
    assert state['slices']['BE10B02']['status']=='accepted'
    assert state['slices']['BE10B02']['commit_ref']=='refs/tags/slice/BE10B02'
    assert state['backend_program']['clinical_release']=='blocked' and state['backend_program']['active_service_migrated'] is False
    for sid in ('BE10B','BE10','BE11'):assert state['slices'][sid]['status']=='planned'
    proof={'status':'PASS','runtime_sha256':runtime,'clinical_ready':False,'active_tables_unchanged':len(tables),
           'scope':'PASS','secret_scan':'PASS','parent_statuses_preserved':True,'patients':10,'integrity':'ok','foreign_keys':'PASS','access_and_4_foreign_files':'PASS',
           'coverage_requirements':len(coverage['items']),'subchecks':sum(len(i['subchecks']) for i in coverage['items']),
           'source_gates':'PASS','citations_independently_checked':citation_count,'default_http':http_report,'phases':phases,'accounting':accounting}
    (OUT/'citation-review.json').write_text(json.dumps(inventory,ensure_ascii=False,indent=2)+'\n')
    (OUT/'accounting.json').write_text(json.dumps(accounting,ensure_ascii=False,indent=2)+'\n')
    return proof

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--write-quality',action='store_true');args=parser.parse_args()
    proof=audit()
    (OUT/'verification.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n')
    if args.write_quality:
        value={'version':service.VERSION,'pass':True,'admitted':'synthetic_only',
               'runtime_sha256':proof['runtime_sha256'],'clinical_ready':False,'independent_clinical_review':False,
               'fixed_dataset':read(FINAL/'live-holdout/summary.json')['freeze'],
               'metrics':proof['phases']['holdout'],'mechanics_integration':proof['phases']['integration'],
               'evidence':'evidence/BE10B02/revision-v2/verification.json',
               'previous_failed_evidence':['evidence/BE10B02/diagnosis-quality.json','evidence/BE10B02/revision-v2/iteration-2/live-holdout/summary.json'],
               'limitations':['Small authored synthetic control, not independent clinical validation.',
                             'Raw model quality is reported separately; unverified qualifiers remain unknown with the proposal preserved.',
                             'Exact quotes/units/formal criteria do not verify clinical interpretation.',
                             'Provider weights are not immutable; sources expire at the unchanged BE03 deadline.']}
        (ROOT/'evidence/BE10/diagnosis-quality.json').write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(proof,ensure_ascii=False,indent=2))
