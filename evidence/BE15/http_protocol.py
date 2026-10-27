"""Real loopback HTTP + separate production worker + explicit physician review.

Only disposable synthetic data. Physician/diagnosis setup is an explicit
structured mechanical fixture; it is not independent clinical evidence.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from werkzeug.serving import make_server, WSGIRequestHandler
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from apps.compass import access, backend_plan_review as review, backend_therapy as therapy
from apps.compass import backend_analyses as analyses
from apps.compass.web import create_app
from apps.tests.test_backend_plan_review import PlanReviewTests
from apps.tests import test_access
OUT=Path(__file__).resolve().parent
class Quiet(WSGIRequestHandler):
    def log(self,*args,**kwargs):pass

def main():
    case=PlanReviewTests();case.setUp();server=None
    try:
        case.diagnosis();case.reconcile();checks=[]
        cookies={uid:access.COOKIE+'='+c.get_cookie(access.COOKIE).value for uid,c in case.clients.items()}
        tokens={uid:test_access.csrf(c) for uid,c in case.clients.items()}
        def launch():
            server=make_server('127.0.0.1',0,create_app(case.path),request_handler=Quiet)
            thread=Thread(target=server.serve_forever,daemon=True);thread.start();return server,thread
        server,thread=launch()
        def call(method,path,body=None,uid='doc-a',csrf=True):
            headers={'Content-Type':'application/json'}
            if uid:headers['Cookie']=cookies[uid]
            if csrf and uid:headers['X-CSRF-Token']=tokens[uid]
            req=Request(f'http://127.0.0.1:{server.server_port}'+path,
                data=None if body is None else json.dumps(body).encode(),headers=headers,method=method)
            try:response=urlopen(req,timeout=20)
            except HTTPError as exc:response=exc
            with response:
                raw=response.read();return response.status,json.loads(raw) if raw else None,response.headers
        status,created,headers=call('POST',case.url,case.body('plan'));assert status==202
        checks.append('analysis202');location=headers['Location']
        key=ROOT/'var/deepseek-api-key';assert not key.stat().st_mode&0o077
        env=dict(os.environ);env['DEEPSEEK_API_KEY']=key.read_text().strip()
        worker=subprocess.run([sys.executable,'-m','apps.compass','--db',str(case.path),'worker','--once','--lane','generation'],
            cwd=ROOT,env=env,capture_output=True,text=True,timeout=85)
        env.pop('DEEPSEEK_API_KEY',None);assert worker.returncode==0,worker.stderr[:200]
        status,value,_=call('GET',location)
        assert status==200 and value['status']=='ready',value
        assert value['care_plan_context']['therapy']['model_metadata']['test_double'] is False
        assert value['care_plan_context']['therapy']['report']['recommendations']
        checks.append('default_worker_real_DeepSeek_ready')
        url=location+'/plan-reviews';body=case.edit_body(value)
        assert call('POST',url,body,csrf=False)[0]==403;checks.append('create_csrf403')
        assert call('POST',url,body,uid='pat-a')[0]==403;checks.append('patient_create403')
        status,draft,headers=call('POST',url,body);assert status==200,draft
        path='/api/v1/patients/D01/plan-reviews/'+draft['proposal_id']
        assert headers['Cache-Control']=='no-store';checks.append('create200_no_store')
        assert call('POST',url,body)[1]==draft;checks.append('create_retry_exact')
        assert call('GET','/api/patients/D01/decisions',uid='pat-a')[1]['decisions']==[]
        checks.append('unapproved_hidden')
        edited=case.edit_body(value);edited['medication']['days']=21
        edited['medication']['times']=['22:00'] if len(edited['medication']['times'])==1 else ['10:00','22:00']
        status,new,_=call('POST',url,edited);assert status==200,new;checks.append('edited_version200')
        assert call('POST',path,case.confirmation(draft))[0]==409;checks.append('obsolete_revision409')
        newpath='/api/v1/patients/D01/plan-reviews/'+new['proposal_id']
        for uid in ('pat-a','doc-b'):
            assert call('GET',newpath,uid=uid)[0] in (403,404)
            checks.append(uid+'_review_denied')
        assert call('GET',newpath,uid=None)[0]==401;checks.append('anonymous401')
        assert call('POST',newpath,case.confirmation(new),csrf=False)[0]==403;checks.append('confirm_csrf403')
        status,confirmed,_=call('POST',newpath,case.confirmation(new));assert status==200,confirmed
        assert confirmed['decision']=='approved';checks.append('physician_confirm200')
        assert call('POST',newpath,case.confirmation(new))[1]==confirmed;checks.append('confirm_retry_exact')
        patient=call('GET','/api/patients/D01/decisions',uid='pat-a')[1]['decisions']
        assert [r['id'] for r in patient]==[new['proposal_id']];checks.append('only_approved_patient_content')
        from apps.compass import medications, communication
        assert medications.calendar(case.db,'D01')['current_medications'][0]['days']==21
        assert communication.current_action(case.db,'D01')
        assert len(communication.view(case.db,{'id':'pat-a','role':'patient'},'D01')['tasks'])==len(edited['items'])
        assert case.db.execute('SELECT count(*) FROM care_actions').fetchone()[0]==1
        checks.append('one_existing_action_calendar_tasks')
        server.shutdown();thread.join();server.server_close();server=None
        server,thread=launch();assert call('GET',newpath)[1]==confirmed;checks.append('restart_receipt_preserved')
        assert case.db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert not case.db.execute('PRAGMA foreign_key_check').fetchall();checks.append('integrity_foreign_keys')
        result={'pass':True,'checks_count':len(checks),'checks':checks,'real_model_calls':1,
            'transport':'actual loopback HTTP','worker':'separate production CLI/default executor',
            'diagnosis_setup':'structured mechanical synthetic fixture, not independent clinical validation',
            'runtime_sha256':review.runtime(),'generation_runtime':therapy.generation_release(),
            'model_outcome':value,'confirmed':confirmed,'clinical_release':'blocked','active_service_changed':False}
        (OUT/'http-protocol.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print('PASS:',len(checks),'real HTTP/default worker/review/calendar checks; one genuine model call')
    finally:
        if server:server.shutdown();thread.join();server.server_close()
        case.tearDown()
if __name__=='__main__':main()
