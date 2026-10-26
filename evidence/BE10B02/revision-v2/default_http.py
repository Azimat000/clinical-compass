"""Real HTTP request boundary + genuine default job executor on temporary authorship."""
from contextlib import closing
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'START_HERE.md').is_file());sys.path.insert(0,str(ROOT))
from apps.compass import backend_analyses as analyses,backend_jobs as jobs,backend_diagnosis_service as service
from apps.compass import backend_diagnosis_codec as codec,records
from apps.tests.diagnosis_fixtures import CleanDiagnosticCase
from apps.tests import test_access
OUT=Path(__file__).resolve().parent
sha=lambda b:hashlib.sha256(b).hexdigest()

def ledger():
    with closing(sqlite3.connect('file:'+str(ROOT/'var/deepseek-budget.sqlite3')+'?mode=ro',uri=True)) as db:
        return list(db.execute('SELECT count(*),sum(micro_usd) FROM calls').fetchone())

def main():
    target=OUT/'default-http-report.json'
    if target.exists():raise SystemExit('Refuse replay/overwrite of actual HTTP evidence')
    quality=json.loads((ROOT/'evidence/BE10/diagnosis-quality.json').read_text())
    runtime=service.snapshots.digest(service.release())
    if quality.get('pass') is not True or quality.get('runtime_sha256')!=runtime:
        raise SystemExit('Exact synthetic quality admission required before credentials or HTTP')
    before=ledger();key=ROOT/'var/deepseek-api-key';assert key.stat().st_mode&0o077==0
    os.environ['DEEPSEEK_API_KEY']=key.read_text().strip()
    fixture=CleanDiagnosticCase();report={'driver_sha256':sha(Path(__file__).read_bytes()),'runtime_sha256':runtime,'ledger_before':before}
    try:
        case=json.loads((OUT/'iteration-5/holdout.json').read_text())['cases'][0];fixture.populate(case)
        client=fixture.clients['doc-a'];url='/api/v1/patients/D01/analyses'
        headers={'X-CSRF-Token':test_access.csrf(client)}
        body={'contract_version':'1.0','operation':'diagnosis','request_key':os.urandom(16).hex()}
        response=client.post(url,json=body,headers=headers);assert response.status_code==202
        run=response.json;repeat=client.post(url,json=body,headers=headers)
        assert repeat.status_code==202 and repeat.json['run_id']==run['run_id']
        assert fixture.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0]==1
        captured={}
        def observe_default(operation,snapshot):
            captured['snapshot']=deepcopy(snapshot)
            result=jobs.execute(operation,snapshot)  # Actual default production dispatch/adapter/transport.
            captured['outcome']=deepcopy(result)
            return result
        assert jobs.process_one(fixture.db,'generation',executor=observe_default)
        value=client.get(url+'/'+run['run_id']).json;assert value['status']=='ready'
        result=captured['outcome']['diagnosis_report'];ctx=result['context']
        assert ctx['leading']==case['leading'] and ctx['established_diagnosis'] is ctx['plan'] is ctx['diagnosis_code'] is None
        assert ctx['clinical_ready'] is False
        detail=client.get(url+'/'+run['run_id']+'/diagnosis-context');assert detail.status_code==200
        assert detail.json['report']==ctx and detail.headers['Cache-Control']=='no-store'
        assert client.head(url+'/'+run['run_id']+'/diagnosis-context').status_code==200
        repeated=client.post(url,json=body,headers=headers);assert repeated.json['run_id']==run['run_id']
        assert ledger()[0]-before[0]==2
        calls=[]
        for kind,m in result['model_metadata']['branches'].items():
            assert m['test_double'] is False and m['returned_model']=='deepseek-flash'
            calls.append({'branch':kind,'payload_sha256':sha(json.dumps(service.payload(captured['snapshot'],kind),ensure_ascii=False,sort_keys=True).encode()),
                'schema_sha256':sha(json.dumps(codec.schema(kind),sort_keys=True).encode()),
                'response':{'value':result['named_assertions'][kind],'metadata':m}})
        (OUT/'default-http-calls.json').write_text(json.dumps(calls,ensure_ascii=False,indent=2)+'\n')
        second={**body,'request_key':os.urandom(16).hex()}
        pending=client.post(url,json=second,headers=headers).json
        cancelled=client.post(url+'/'+pending['run_id']+'/cancel',json={},headers=headers)
        assert cancelled.status_code==200 and cancelled.json['status']=='failed'
        assert not jobs.process_one(fixture.db,'generation')
        assert ledger()[0]-before[0]==2
        for uid in ('doc-b','pat-a','pat-b'):
            assert fixture.clients[uid].get(url+'/'+run['run_id']+'/diagnosis-context').status_code in (403,404)
        records.save(fixture.db,fixture.patient,'D01','self_report',{'request_key':os.urandom(16).hex(),
            'observed_on':records.today().isoformat(),'summary':'Новая авторская запись после анализа.','wellbeing':'unknown'})
        stale=client.get(url+'/'+run['run_id']+'/diagnosis-context').json
        assert stale['analysis_status']=='stale'
        for table in ('care_actions','proposals','doctor_confirmations','therapy_courses'):
            assert fixture.db.execute('SELECT count(*) FROM '+table).fetchone()[0]==0
        report.update(status='PASS',snapshot=captured['snapshot'],outcome=captured['outcome'],
            creation_http_status=202,idempotent_before_and_after=True,default_executor=True,test_double=False,
            read_head_access_cancel_and_stale='PASS',care_actions=0,ledger_after=ledger(),clinical_ready=False)
        target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({k:v for k,v in report.items() if k not in ('snapshot','outcome')},ensure_ascii=False,indent=2))
    finally:fixture.close()

if __name__=='__main__':main()
