"""Isolated FE02 real HTTP/CLI protocol. Never opens the working DB writable.

Default has no provider key. --live-model is explicit, requires a saved external
verification report and the unchanged source deadline. No fabricated outputs.
"""
import argparse
from contextlib import ExitStack
import hashlib
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen
from datetime import datetime, timezone
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from apps.compass.db import connect, migrate, health
from apps.compass import backend_jobs, backend_diagnosis_service, backend_therapy
OUT = Path(__file__).resolve().parent

def table_hashes(db):
    return {n: hashlib.sha256(repr(sorted(db.execute('SELECT * FROM "'+n+'"').fetchall(), key=repr)).encode()).hexdigest()
            for n, in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}

def ledger():
    with sqlite3.connect('file:'+str(ROOT/'var/deepseek-budget.sqlite3')+'?mode=ro',uri=True) as db:
        return list(db.execute('SELECT count(*),sum(micro_usd) FROM calls').fetchone())

def run(args):
    target = ROOT/'var/FE02-integration.sqlite3'
    assert not target.exists(), 'Refuse to overwrite existing FE02 copy.'
    try:
        with urlopen(f'http://127.0.0.1:{args.port}/healthz',timeout=.3):
            raise RuntimeError('Port already in use')
    except OSError:
        pass
    before_ledger = ledger()
    env = dict(os.environ)
    env.pop('DEEPSEEK_API_KEY',None)
    if args.live_model:
        assert (OUT/'research.md').is_file(), 'External verification report required'
        assert datetime.now(timezone.utc) < datetime.fromisoformat('2026-10-27T19:17:00+03:00'), 'Source deadline expired'
        key = ROOT/'var/deepseek-api-key'
        assert key.stat().st_mode & 0o077 == 0
        env['DEEPSEEK_API_KEY'] = key.read_text().strip()
    fd = os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
    with sqlite3.connect('file:'+str(ROOT/'var/compass.sqlite3')+'?mode=ro',uri=True) as src:
        original = table_hashes(src)
        triggers = dict(src.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger'"))
        with sqlite3.connect(target) as dst: src.backup(dst)
    with sqlite3.connect(target) as db:
        assert original == table_hashes(db)
    db = connect(target);migrate(db)
    # Fingerprint values use tuples, independent of sqlite Row factories.
    with sqlite3.connect(target) as compare:
        migrated = table_hashes(compare)
        assert all(migrated[n]==digest for n,digest in original.items() if n!='schema_migrations')
        current_triggers = dict(compare.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger'"))
        assert all(current_triggers.get(n)==sql for n,sql in triggers.items())
    assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    assert not db.execute('PRAGMA foreign_key_check').fetchall()
    schema = health(db)['schema_version']
    assert db.execute('SELECT enabled FROM backend_job_settings').fetchone()[0]==0
    db.execute('UPDATE backend_job_settings SET enabled=1,generation_version=?', (backend_diagnosis_service.EXECUTION_VERSION,))
    processes=[]; checks=[]; results={}; timings={}
    def check(label, ok=True):
        assert ok,label
        checks.append(label)
    with ExitStack() as stack:
        try:
            def launch(name,command,process_env):
                log=stack.enter_context(open(ROOT/f'var/FE02-{name}.log','w'))
                os.chmod(log.name,0o600)
                proc=subprocess.Popen([sys.executable,'-m','apps.compass','--db',str(target),*command],cwd=ROOT,env=process_env,stdout=log,stderr=log)
                processes.append((name,proc));return proc
            server=launch('server',['serve','--port',str(args.port)],{k:v for k,v in env.items() if k!='DEEPSEEK_API_KEY'})
            base=f'http://127.0.0.1:{args.port}'
            for _ in range(100):
                try:
                    with urlopen(base+'/healthz',timeout=.3) as r:
                        if r.status==200:break
                except OSError:time.sleep(.1)
            else:raise AssertionError('Server did not start')
            accounts=json.loads((ROOT/'var/clinic-20261026-accounts.json').read_text())['accounts']
            clients={}
            for who in ['e.orlova','a.mironov']:
                clients[who]=build_opener(HTTPCookieProcessor(CookieJar()))
            patient_uid=db.execute("SELECT user_id FROM patients WHERE id='P201'").fetchone()[0]
            patient=next(a for a in accounts if a['login']==patient_uid)
            clients[patient_uid]=build_opener(HTTPCookieProcessor(CookieJar()))
            tokens={}
            from urllib.parse import urlencode
            for uid,client in clients.items():
                a=next(a for a in accounts if a['login']==uid)
                with client.open(base+'/login') as r:html=r.read().decode()
                csrf=re.search(r'name="csrf" value="([^"]+)"',html).group(1)
                with client.open(Request(base+'/login',data=urlencode({'csrf':csrf,'login':uid,'password':a['password']}).encode())) as r:html=r.read().decode()
                tokens[uid]=re.search(r'name="csrf" value="([^"]+)"',html).group(1)
            def call(path,method='GET',body=None,uid='e.orlova',csrf=True):
                headers={'Content-Type':'application/json'}
                if uid and csrf:headers['X-CSRF-Token']=tokens[uid]
                req=Request(base+path,data=None if body is None else json.dumps(body).encode(),headers=headers,method=method)
                client=clients[uid] if uid else build_opener()
                try:r=client.open(req,timeout=25)
                except HTTPError as exc:r=exc
                with r:
                    raw=r.read(); data=json.loads(raw) if raw and r.headers.get_content_type()=='application/json' else None
                    return r.status,data,r.headers
            url='/api/v1/patients/P201/analyses'
            check('empty_authenticated_history',call(url)[1]['items']==[])
            for uid,code in [(patient_uid,403),('a.mironov',404),(None,401)]:
                check('history_role_'+str(code),call(url,uid=uid)[0]==code)
            urls=[]
            for op in ['risk','diagnosis','plan']:
                body={'contract_version':'1.0','operation':op,'request_key':secrets.token_hex(16)}
                check(op+'_csrf_rejected',call(url,'POST',body,csrf=False)[0]==403)
                status,value,headers=call(url,'POST',body)
                check(op+'_HTTP202',status==202 and value['status']=='queued')
                urls.append(headers['Location']);results[op]=value
                check(op+'_idempotent',call(url,'POST',body)[1]['run_id']==value['run_id'])
            with sqlite3.connect(target) as compare: before_read=table_hashes(compare)
            l=ledger()
            for _ in range(3):
                check('history_GET_no_store',call(url)[2]['Cache-Control']=='no-store')
                check('history_HEAD200',call(url,'HEAD')[0]==200)
                for path in urls:check('run_GET200',call(path)[0]==200)
                for path in ['/api/v1/physician/alerts','/api/v1/patients/P201/diagnosis-review','/api/v1/patients/P201/therapy-context']:
                    check('existing_read_GET200',call(path)[0]==200)
                    check('existing_read_HEAD200',call(path,'HEAD')[0]==200)
            with sqlite3.connect(target) as compare:
                after_read=table_hashes(compare)
                check('GET_HEAD_no_clinical_writes',all(after_read[t]==v for t,v in before_read.items() if t!='sessions'))
            check('GET_HEAD_no_model_reservation',l==ledger())
            # Genuine production lanes, default executor, no monkeypatches/fixtures.
            start=time.monotonic()
            launch('risk',['worker','--lane','risk'],env)
            launch('generation',['worker','--lane','generation'],env)
            while time.monotonic()-start<145:
                for op,path in zip(['risk','diagnosis','plan'],urls):
                    value=call(path)[1];results[op]=value
                    if value['status'] not in ('queued','running') and op not in timings:
                        timings[op]=round(time.monotonic()-start,3)
                if len(timings)==3:break
                time.sleep(.5)
            check('both_real_worker_processes_alive',all(p.poll() is None for _,p in processes))
            check('three_operations_terminal',len(timings)==3)
            for op,value in results.items():
                check(op+'_honest_result',value['status']=='ready' or (value['result'] is None and bool(value['errors']) or value['status']=='stale'))
                check(op+'_release_blocked',value['release']['status']=='blocked')
            check('three_history_records',call(url)[1]['total']==3)
            # Every role is denied every generated run; no patient result publication.
            for path in urls:
                for uid,code in [(patient_uid,403),('a.mironov',404),(None,401)]:
                    check('run_isolation_'+str(code),call(path,uid=uid)[0]==code)
            with sqlite3.connect('file:'+str(ROOT/'var/compass.sqlite3')+'?mode=ro',uri=True) as live:
                check('no_automatic_care_actions', db.execute('SELECT count(*) FROM care_actions').fetchone()[0] == live.execute('SELECT count(*) FROM care_actions').fetchone()[0])
            user=db.execute("SELECT doctor_id FROM care_relationships WHERE patient_id='P201' AND ends_at IS NULL").fetchone()[0]
            db.execute("UPDATE sessions SET expires_at='2000' WHERE user_id=?",(user,))
            check('expired_session401',call(url)[0]==401)
            check('copy_integrity',db.execute('PRAGMA integrity_check').fetchone()[0]=='ok' and not db.execute('PRAGMA foreign_key_check').fetchall())
        finally:
            for _,p in reversed(processes):
                if p.poll() is None:p.terminate()
            for _,p in processes:
                try:p.wait(timeout=8)
                except subprocess.TimeoutExpired:p.kill();p.wait(timeout=5)
            db.execute('UPDATE backend_job_settings SET enabled=0')
            env.pop('DEEPSEEK_API_KEY',None)
    end_ledger=ledger()
    with sqlite3.connect(target) as compare:
        final=table_hashes(compare)
    preserved=[t for t,h in original.items() if final[t]==h]
    result={'status':'PASS','copy':str(target),'schema':schema,'copy_mode':oct(target.stat().st_mode&0o777),
            'backup_method':'sqlite3.Connection.backup','original_tables':len(original),'migration_preserved_tables':len(original)-1,
            'original_triggers_preserved':len(triggers),'original_history_unchanged_after_smoke':preserved,
            'processes':[{'name':n,'pid':p.pid,'exit':p.returncode} for n,p in processes],
            'server':'waitress CLI loopback','workers':'two production CLI processes risk/generation; default executor',
            'checks':checks,'checks_count':len(checks),'operations':results,'terminal_seconds':timings,
            'generation_version':backend_diagnosis_service.EXECUTION_VERSION,'clinical_release':'blocked',
            'source_deadline':'2026-10-27T19:17:00+03:00','live_model_key_supplied':args.live_model,
            'ledger_before':before_ledger,'ledger_after':end_ledger,'new_reservations':end_ledger[0]-before_ledger[0],
            'new_ceiling_micro_usd':end_ledger[1]-before_ledger[1], 'runtime_stopped':True,'backend_enabled_at_end':False,
            'active_service_changed':False,'model_cap_micro_usd':1000000,'per_call_cap_micro_usd':20000}
    (OUT/'runtime.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    db.close()
    print('PASS:',len(checks),'real HTTP/process checks;',result['new_reservations'],'new model reservations')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--live-model',action='store_true');p.add_argument('--port',type=int,default=8062)
    run(p.parse_args())
