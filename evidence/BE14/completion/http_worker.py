"""Actual loopback HTTP, default separate production CLI worker and real model."""
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Thread
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from werkzeug.serving import make_server,WSGIRequestHandler
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from apps.compass import access,backend_therapy as therapy,backend_analyses as analyses
from apps.compass.web import create_app
from apps.tests import test_backend_therapy_integration as tests,test_access,test_backend_contracts
OUT=Path(__file__).resolve().parent
class Quiet(WSGIRequestHandler):
    def log(self,*args,**kwargs):pass

def main():
    quality=json.loads((ROOT/'evidence/BE14/therapy-quality.json').read_text())
    assert quality['pass'] and quality['runtime_sha256']==therapy.history.digest(therapy.generation_release())
    case=tests.TherapyIntegrationTests('test_positive_source_bound_plan_no_treatment_changes');case.setUp();server=None
    try:
        case.diagnosis();checks=[]
        cookies={uid:access.COOKIE+'='+c.get_cookie(access.COOKIE).value for uid,c in case.clients.items()}
        token=test_access.csrf(case.clients['doc-a'])
        def launch():
            server=make_server('127.0.0.1',0,create_app(case.path),request_handler=Quiet)
            thread=Thread(target=server.serve_forever,daemon=True);thread.start();return server,thread
        server,thread=launch()
        def call(method,path,body=None,uid='doc-a',csrf=True):
            headers={'Content-Type':'application/json'}
            if uid:headers['Cookie']=cookies[uid]
            if csrf:headers['X-CSRF-Token']=token
            req=Request(f'http://127.0.0.1:{server.server_port}'+path,
                data=None if body is None else json.dumps(body).encode(),headers=headers,method=method)
            try:response=urlopen(req,timeout=20)
            except HTTPError as exc:response=exc
            with response:
                raw=response.read();return response.status,json.loads(raw) if raw else None,response.headers
        path='/api/v1/patients/D01/therapy-context';body=case.reconciliation()
        assert call('GET',path,uid=None)[0]==401;checks.append('anonymous401')
        for uid in ('pat-a','doc-b'):
            assert call('GET',path,uid=uid)[0] in (403,404);checks.append(uid+'_context_denied')
        assert call('POST',path,body,csrf=False)[0]==403;checks.append('csrf403')
        status,receipt,_=call('POST',path,body);assert status==200;checks.append('context_append200')
        assert call('POST',path,body)[1]==receipt;checks.append('context_exact_retry')
        before=test_backend_contracts.table_rows(case.db)
        status,created,headers=call('POST',case.url,case.body('plan'));assert status==202;checks.append('plan202')
        location=headers['Location'];env=dict(os.environ)
        key=ROOT/'var/deepseek-api-key';assert not key.stat().st_mode&0o077
        env['DEEPSEEK_API_KEY']=key.read_text().strip()
        worker=subprocess.run([sys.executable,'-m','apps.compass','--db',str(case.path),'worker','--once','--lane','generation'],
            cwd=ROOT,env=env,capture_output=True,text=True,timeout=85)
        env.pop('DEEPSEEK_API_KEY',None)
        assert worker.returncode==0,worker.stderr[:200]
        status,value,headers=call('GET',location);assert status==200 and value['status']=='ready',value
        extension=value['care_plan_context']['therapy'];report=extension['report']
        assert report['recommendations'] and extension['model_metadata']['test_double'] is False
        assert headers['Cache-Control']=='no-store';checks.extend(['default_CLI_real_model_ready','source_bound_positive_draft','no_store'])
        assert call('HEAD',location)[0]==200;checks.append('HEAD200')
        for uid in ('pat-a','doc-b'):
            assert call('GET',location,uid=uid)[0] in (403,404);checks.append(uid+'_draft_denied')
        server.shutdown();thread.join();server.server_close();server=None
        server,thread=launch();assert call('GET',location)[1]==value;checks.append('restart_exact_result')
        run_id=created['run_id'];frozen=json.loads(case.db.execute('SELECT payload_json FROM analysis_input_snapshots WHERE id=?',(created['snapshot_id'],)).fetchone()[0])
        assert analyses.inputs(case.db,case.user,'D01',run_id,reference=report['recommendations'][0]['evidence_refs'][0])['source']['row']['id']==receipt['id']
        checks.append('frozen_physician_evidence_resolves')
        case.diary(summary='Новая вымышленная запись после генерации.')
        assert call('GET',location)[1]['status']=='stale';checks.append('new_data_stale')
        after=test_backend_contracts.table_rows(case.db)
        for table in ('care_actions','treatment_plan_versions','doctor_confirmations','proposals','medication_marks'):
            if table in before:assert before[table]==after[table],table
        checks.append('no_treatment_mutations')
        result={'pass':True,'checks':checks,'checks_count':len(checks),'real_model_calls':1,
            'worker':'separate default production CLI, no injected executor','transport':'real loopback HTTP',
            'diagnosis_fixture':'explicit physician/structured synthetic fixture, no clinical validation',
            'snapshot':frozen,'outcome':value,'clinical_release':False}
        (OUT/'http-worker.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print('PASS:',len(checks),'HTTP/default worker/evidence/preservation checks; real model call1')
    finally:
        if server:server.shutdown();thread.join();server.server_close()
        case.tearDown()
if __name__=='__main__':main()
