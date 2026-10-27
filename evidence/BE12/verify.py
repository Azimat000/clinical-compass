"""Main-agent BE12 HTTP/default CLI worker, source/evidence and preservation checks."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from werkzeug.serving import make_server, WSGIRequestHandler

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from apps.compass import access, backend_care_plan as plans, backend_analyses as analyses
from apps.compass.db import connect,migrate
from apps.compass.web import create_app
from apps.tests import test_backend_contracts,test_access
from apps.tests.test_backend_care_plan import CarePlanTests
OUT=Path(__file__).resolve().parent
sha=lambda value:hashlib.sha256(value).hexdigest()

class Quiet(WSGIRequestHandler):
    def log(self,*args,**kwargs):pass

def live():
    case=CarePlanTests('test_supported_depression_content_provenance_and_no_actions');case.setUp()
    server=None
    try:
        case.diagnosis();token=test_access.csrf(case.clients['doc-a'])
        cookies={uid:access.COOKIE+'='+c.get_cookie(access.COOKIE).value for uid,c in case.clients.items()}
        def launch():
            server=make_server('127.0.0.1',0,create_app(case.path),request_handler=Quiet)
            thread=Thread(target=server.serve_forever,daemon=True);thread.start();return server,thread
        server,thread=launch();checks=[]
        def call(method,path,body=None,uid='doc-a',csrf=True):
            headers={'Content-Type':'application/json'}
            if uid:headers['Cookie']=cookies[uid]
            if csrf:headers['X-CSRF-Token']=token
            request=Request('http://127.0.0.1:'+str(server.server_port)+path,
                data=None if body is None else json.dumps(body).encode(),headers=headers,method=method)
            try:response=urlopen(request,timeout=20)
            except HTTPError as exc:response=exc
            with response:
                raw=response.read();return response.status,json.loads(raw) if raw else None,response.headers
        body=case.body('plan');before=test_backend_contracts.table_rows(case.db)
        assert call('POST',case.url,body,uid=None)[0]==401;checks.append('anonymous401')
        for uid in ('pat-a','doc-b'):
            assert call('POST',case.url,body,uid=uid)[0] in (403,404);checks.append(uid+'_denied')
        assert call('POST',case.url,body,csrf=False)[0]==403;checks.append('csrf403')
        status,created,headers=call('POST',case.url,body);assert status==202;checks.append('create202')
        location=headers['Location']
        # Separate interpreter, real production CLI, no executor replacement/key.
        env=dict(os.environ);env.pop('DEEPSEEK_API_KEY',None)
        process=subprocess.run([sys.executable,'-m','apps.compass','--db',str(case.path),
            'worker','--once','--lane','generation'],cwd=ROOT,env=env,capture_output=True,text=True,timeout=45)
        assert process.returncode==0,process.stderr
        status,value,headers=call('GET',location)
        assert status==200 and value['status']=='ready',value
        report=value['care_plan_context']['report']
        assert report['status']=='physician_diagnosis_draft';checks.append('default_CLI_worker_ready200')
        assert headers['Cache-Control']=='no-store'
        assert not report['applied'] and not report['patient_published'];checks.append('no_actions_or_patient_publication')
        assert call('POST',case.url,body)[1]==value;checks.append('idempotent_retry')
        assert call('HEAD',location)[0]==200;checks.append('read_only_HEAD200')
        for uid in ('pat-a','doc-b'):
            assert call('GET',location,uid=uid)[0] in (403,404);checks.append(uid+'_result_denied')
        server.shutdown();thread.join();server.server_close();server=None
        server,thread=launch()
        assert call('GET',location)[1]==value;checks.append('restart_preserves_report')
        case.diary(summary='Новые вымышленные сведения после завершения проекта.')
        assert call('GET',location)[1]['status']=='stale';checks.append('data_change_stale')
        after=test_backend_contracts.table_rows(case.db)
        for table in ('care_actions','referrals','treatment_plan_versions','doctor_confirmations','proposals','medication_marks'):
            if table in before:assert before[table]==after[table],table
        return {'pass':True,'checks_count':len(checks),'checks':checks,'worker':'separate production CLI interpreter, --once --lane generation',
            'transport':'real loopback HTTP','diagnosis_input':'explicit structured mechanics fixture, not model/clinical quality','model_calls':0}
    finally:
        if server:server.shutdown();thread.join();server.server_close()
        case.tearDown()

def scenarios():
    result=[]
    cases=[('depression',{},'physician_diagnosis_draft'),('GAD',{'kind':'generalized_anxiety'},'physician_diagnosis_draft'),
        ('unreviewed',{'reviewed':False},'conditional_clarification'),
        ('organic_unknown',{'unknown':'organic_cause'},'conditional_clarification'),
        ('risk',{'risk':{'suicidal_plan':'present','suicidal_intent':'unknown'}},'conditional_clarification'),
        ('mania',{'changes':{'mania_hypomania':[1]}},'conditional_clarification')]
    for name,kw,status in cases:
        case=CarePlanTests('test_supported_depression_content_provenance_and_no_actions');case.setUp()
        try:
            case.diagnosis(**kw);value=case.plan();assert value['status']=='ready',value
            report=value['care_plan_context']['report'];assert report['status']==status
            snapshot=json.loads(case.db.execute('SELECT payload_json FROM analysis_input_snapshots WHERE id=?',(value['snapshot_id'],)).fetchone()[0])
            outcome={k:value[k] for k in ('status','result','errors','model')}
            plans.verify(snapshot,outcome,value['care_plan_context'])
            for item in report['items']:
                for ref in item['evidence_refs']:assert plans.snapshots.resolve(snapshot,ref) is not None
                assert item['timing']['interval_days'] is None
                c=json.loads(plans.CATALOG.read_text())['items'][item['source']['claim_id'][5:]]
                if '-clarify-' in item['id']:
                    branch='generalized_anxiety' if report['condition']=='F41.1' else 'depressive_episode'
                    fid=item['id'].split('-clarify-')[1]
                    source=plans.diagnostic.criteria.release()['conditions'][branch]['facts'][fid]
                    assert item['source']['pdf_page']==source['pdf_page'] and item['source']['section']==source['section']
                else:assert item['source']['pdf_page']==c['pdf_page'] and item['source']['section']==c['section']
            result.append({'case':name,'pass':True,'report':report,'scope':'structured mechanics, no clinical accuracy claim'})
        finally:case.tearDown()
    (OUT/'scenarios.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return {'pass':True,'count':len(result),'evidence':'evidence/BE12/scenarios.json'}

def preservation():
    base=json.loads((OUT/'baseline.json').read_text())
    for name,digest in base['preserved_files'].items():assert sha((ROOT/name).read_bytes())==digest,name
    assert sha((ROOT/'var/clinic-20261026-access.md').read_bytes())==base['access_sha256']
    assert sha((ROOT/'var/deepseek-budget.sqlite3').read_bytes())==base['ledger_sha256']
    with closing(sqlite3.connect('file:'+str(ROOT/'var/compass.sqlite3')+'?mode=ro',uri=True)) as db:
        current={r[0]:sha(json.dumps(db.execute('SELECT * FROM "'+r[0]+'"').fetchall(),sort_keys=True,default=str).encode())
            for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert current==base['active_db_tables'],'live database changed'
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        with tempfile.TemporaryDirectory() as tmp:
            copy=connect(Path(tmp)/'copy.sqlite3')
            try:
                db.backup(copy);before=test_backend_contracts.table_rows(copy)
                schema=dict(copy.execute("SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL"))
                migrate(copy);after=test_backend_contracts.table_rows(copy)
                for table,rows in before.items():
                    actual=after[table]
                    if table=='schema_migrations':actual=[r for r in actual if json.loads(r)[0] in {json.loads(x)[0] for x in rows}]
                    assert rows==actual,table
                newer=dict(copy.execute("SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL"))
                assert all(newer[k]==v for k,v in schema.items())
                once=test_backend_contracts.table_rows(copy);migrate(copy);assert once==test_backend_contracts.table_rows(copy)
                assert copy.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
                assert not copy.execute('PRAGMA foreign_key_check').fetchall()
                migration={'pass':True,'copy_only':True,'new_migration':False,'preserved_old_tables':len(before),'preserved_schema_objects':len(schema),'repeated_migrate':True}
            finally:copy.close()
    coverage=json.loads((ROOT/'plan/coverage.json').read_text())
    strip=lambda d:[{k:v for k,v in i.items() if k!='actual_evidence'} for i in d['items']]
    assert sha(json.dumps(strip(coverage),ensure_ascii=False,sort_keys=True).encode())==base['coverage_invariants_sha256']
    return {'pass':True,'live_tables_unchanged':len(current),'four_foreign_files_unchanged':True,
        'credentials_unchanged':True,'ledger_unchanged':True,'migration_copy':migration,
        'requirements':len(coverage['items']),'subchecks':sum(len(i['subchecks']) for i in coverage['items'])}

if __name__=='__main__':
    result={'status':'PASS','runtime':plans.release(),'clinical_ready':False,
        'http':live(),'scenarios':scenarios(),'preservation':preservation()}
    (OUT/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))
