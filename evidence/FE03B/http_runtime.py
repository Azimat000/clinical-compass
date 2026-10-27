"""Real loopback HTTP + independent production CLI workers, default model executor."""
from contextlib import ExitStack
from datetime import timedelta
import json,os
from pathlib import Path
import secrets,subprocess,sys,time
from urllib.request import Request,urlopen
from urllib.error import HTTPError
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from apps.compass import access,records,backend_packet_pipeline as pipeline,backend_model as model
from apps.tests.diagnosis_fixtures import CleanDiagnosticCase
OUT=Path(__file__).resolve().parent

def ledger():
    import sqlite3
    with sqlite3.connect('file:'+str(ROOT/'var/deepseek-budget.sqlite3')+'?mode=ro',uri=True) as db:
        return list(db.execute('SELECT count(*),sum(micro_usd) FROM calls').fetchone())

def main():
    assert json.loads(pipeline.QUALITY.read_text())['pass']
    f=CleanDiagnosticCase();procs=[];checks=[];before=ledger();port=8064
    key=ROOT/'var/deepseek-api-key';assert key.stat().st_mode&0o077==0
    env=dict(os.environ);env['DEEPSEEK_API_KEY']=key.read_text().strip()
    try:
        f.db.execute('UPDATE backend_job_settings SET enabled=0')
        case=json.loads((OUT/'regression.json').read_text())['cases'][0]
        f.populate(case)
        for i in range(4):
            records.save(f.db,f.patient,'D01','self_report',{'request_key':secrets.token_hex(16),
                'observed_on':(records.today()-timedelta(days=30+i)).isoformat(),
                'summary':f'Синтетический архив {i}: исходные сведения этой даты сохранены полностью. Текущее состояние здесь не оценивалось.','wellbeing':'unknown'})
        f.db.execute('UPDATE backend_job_settings SET enabled=1,generation_version=?',(pipeline.EXECUTION_VERSION,))
        raw=f.snapshot();old_sizes=[model.request_metrics(pipeline.diagnostic.payload(raw,k),pipeline.codec.schema(k),pipeline.config())['input_bytes'] for k in pipeline.diagnostic.criteria.release()['conditions']]
        cookies={u:access.COOKIE+'='+c.get_cookie(access.COOKIE).value for u,c in f.clients.items()}
        tokens={u:f.db.execute('SELECT csrf_token FROM sessions WHERE token_hash=?',(access.digest(c.get_cookie(access.COOKIE).value),)).fetchone()[0] for u,c in f.clients.items()}
        def check(label,value=True):assert value,label;checks.append(label)
        with ExitStack() as stack:
            def launch(name,args,key_enabled):
                path=ROOT/f'var/FE03B-{name}.log';fd=os.open(path,os.O_CREAT|os.O_TRUNC|os.O_WRONLY,0o600)
                log=stack.enter_context(os.fdopen(fd,'w'))
                childenv=dict(env)
                if not key_enabled:childenv.pop('DEEPSEEK_API_KEY',None)
                p=subprocess.Popen([sys.executable,'-m','apps.compass','--db',str(f.path),*args],cwd=ROOT,env=childenv,stdout=log,stderr=log)
                procs.append(p);return p
            launch('server',['serve','--port',str(port)],False)
            for _ in range(100):
                try:
                    with urlopen(f'http://127.0.0.1:{port}/healthz',timeout=.3) as r:
                        if r.status==200:break
                except OSError:time.sleep(.1)
            else:raise AssertionError('server not started')
            def call(method,path,body=None,uid='doc-a',csrf=True):
                headers={'Content-Type':'application/json'}
                if uid:headers['Cookie']=cookies[uid]
                if uid and csrf:headers['X-CSRF-Token']=tokens[uid]
                req=Request(f'http://127.0.0.1:{port}'+path,data=None if body is None else json.dumps(body).encode(),headers=headers,method=method)
                try:r=urlopen(req,timeout=25)
                except HTTPError as e:r=e
                with r:
                    b=r.read();return r.status,json.loads(b) if b and r.headers.get_content_type()=='application/json' else None,r.headers
            url='/api/v1/patients/D01/analyses';locations={}
            for op in ['risk','diagnosis']:
                body={'contract_version':'1.0','operation':op,'request_key':secrets.token_hex(16)}
                check(op+'_CSRF403',call('POST',url,body,csrf=False)[0]==403)
                status,value,headers=call('POST',url,body);check(op+'_202',status==202)
                locations[op]=headers['Location'];check(op+'_idempotent',call('POST',url,body)[1]['run_id']==value['run_id'])
            launch('risk-worker',['worker','--lane','risk'],True);launch('generation-worker',['worker','--lane','generation'],True)
            start=time.monotonic();results={}
            while time.monotonic()-start<590:
                results={op:call('GET',path)[1] for op,path in locations.items()}
                if all(v['status'] not in ('queued','running') for v in results.values()):break
                time.sleep(1)
            check('default_diagnosis_ready',results['diagnosis']['status']=='ready')
            check('default_diagnosis_exact',results['diagnosis']['result']['output']['leading']['id']=='depressive_episode')
            check('default_risk_model_complete',results['risk'].get('risk_context',{}).get('model_evaluation')=='candidates_only')
            check('both_lanes_alive',all(p.poll() is None for p in procs))
            cps=[dict(row) for row in f.db.execute('SELECT * FROM analysis_packet_results ORDER BY operation,branch,packet_index')]
            check('genuine_provider_checkpoints',all(json.loads(c['response_json'])['metadata']['test_double'] is False for c in cps))
            check('multiple_packets',sum(c['operation']=='diagnosis' for c in cps)>2)
            for op,path in locations.items():
                for uid,status in [('pat-a',403),('doc-b',404),(None,401)]:check(op+'_role_'+str(status),call('GET',path,uid=uid)[0]==status)
            count=f.db.execute('SELECT count(*) FROM analysis_runs').fetchone()[0];l=ledger()
            for _ in range(3):
                check('history_GET_no_store',call('GET',url)[2]['Cache-Control']=='no-store');check('history_HEAD200',call('HEAD',url)[0]==200)
            check('reads_no_generation',ledger()==l and f.db.execute('SELECT count(*) FROM analysis_runs').fetchone()[0]==count)
            check('no_care_action',f.db.execute('SELECT count(*) FROM care_actions').fetchone()[0]==0)
            f.db.execute("UPDATE sessions SET expires_at='2000' WHERE user_id='doc-a'")
            check('expired401',call('GET',url)[0]==401)
            check('integrity_FK',f.db.execute('PRAGMA integrity_check').fetchone()[0]=='ok' and not f.db.execute('PRAGMA foreign_key_check').fetchall())
            report={'pass':True,'checks':checks,'checks_count':len(checks),'transport':'real Waitress CLI HTTP',
                'worker':'two actual production CLI processes, default executor, genuine DeepSeek',
                'runtime_sha256':pipeline.snapshots.digest(pipeline.release()),'original_named_input_bytes':old_sizes,
                'elapsed_seconds':round(time.monotonic()-start,3),'analyses':results,'checkpoints':cps,
                'ledger_before':before,'ledger_after':ledger(),'clinical_release':'blocked','working_service_changed':False}
            (OUT/'http-runtime.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
            print('PASS:',len(checks),'HTTP/default CLI checks;',len(cps),'genuine checkpoints',flush=True)
    finally:
        for p in reversed(procs):
            if p.poll() is None:p.terminate()
        for p in procs:
            try:p.wait(timeout=8)
            except subprocess.TimeoutExpired:p.kill();p.wait(timeout=5)
        env.pop('DEEPSEEK_API_KEY',None);f.close()
if __name__=='__main__':main()
