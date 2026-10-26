#!/usr/bin/env python3
"""BE08 real local HTTP server + production worker, private synthetic SQLite only."""
import http.cookiejar
import json
import os
from pathlib import Path
import re
import secrets
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from apps.compass import backend_analyses as analyses, backend_jobs as jobs, backend_risk_context as context
from apps.compass import backend_risk_rules as rules, backend_risk_episodes as episodes, records
from apps.compass.backend_model import SYSTEM
from apps.compass.db import connect,migrate,now
from apps.compass.repository import seed_demo
from apps.tests.test_access import setup_identities,PASSWORD,PASSWORD_HASH


def main():
    output=ROOT/'evidence/BE08B02/live-server.json'
    if output.exists():raise SystemExit('Refusing to overwrite live evidence')
    path=ROOT/'var/BE08B02-live.sqlite3'
    if path.exists():raise SystemExit('Refusing to overwrite DB')
    db=connect(path);migrate(db);seed_demo(db);setup_identities(db)
    db.execute('INSERT INTO users VALUES(?,?,?,?,0)',('pat-c','patient','pat-c',PASSWORD_HASH))
    row=dict(db.execute("SELECT * FROM patients WHERE id='D01'").fetchone())
    row.update(id='BE08NEW',code='BE08NEW',user_id='pat-c',age_status='known',age_years=35,birth_date=None,created_at=now())
    db.execute('INSERT INTO patients('+','.join(row)+') VALUES('+','.join('?' for _ in row)+')',tuple(row.values()))
    db.execute('INSERT INTO care_relationships VALUES(?,?,?,?,NULL)',('be08-link','BE08NEW','doc-a',now()))
    user={'id':'doc-a','role':'doctor'}
    flags={f:'denied' for f in rules.FLAGS};flags['suicidal_plan']='present'
    initial={'condition':'F32','severity':'unknown','basis':'Вымышленное свидетельство для технической проверки.', 'supersedes_id':None,**flags}
    cid=rules.record_context(db,user,'BE08NEW',records.today().isoformat(),initial,secrets.token_hex(16))
    records.save(db,{'id':'pat-c','role':'patient'},'BE08NEW','self_report',{'request_key':secrets.token_hex(16),
        'observed_on':records.today().isoformat(),'summary':'Хочу убить себя.','wellbeing':'worse'})
    db.execute('UPDATE backend_job_settings SET enabled=1,generation_version=?',(context.EXECUTION_VERSION,))
    raw=json.loads(analyses.capture(db,'BE08NEW','be08-link'))
    payload=context.model_payload(context.prepare_snapshot(raw))
    n=len((SYSTEM+json.dumps({'data':payload,'response_schema':context.SCHEMA},ensure_ascii=False,allow_nan=False)).encode())
    with sqlite3.connect(ROOT/'var/deepseek-budget.sqlite3') as budget:
        before=budget.execute('SELECT sum(micro_usd) FROM calls').fetchone()[0]
    reservation=n+512+256*5
    assert before+reservation<=50000,('genuine live reservation exceeds cap',before,reservation)
    report={'pass':False,'synthetic':True,'production_executor':True,'production_http':True,
            'active_service_untouched':True,'input_bytes':n,'reservation_micro_usd':reservation,
            'budget_before':before,'cases':[]}
    def save():output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    save()
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
    base=f'http://127.0.0.1:{port}'
    env=os.environ.copy();env.pop('DEEPSEEK_API_KEY',None)
    children=[]
    serverlog=open(ROOT/'evidence/BE08B02/http-server.log','w')
    server=subprocess.Popen([sys.executable,'-m','apps.compass','--db',str(path),'serve','--port',str(port)],cwd=ROOT,env=env,stdout=serverlog,stderr=serverlog)
    children.append(server)
    try:
        deadline=time.monotonic()+15
        while True:
            try:
                with urllib.request.urlopen(base+'/healthz',timeout=1) as response:json.load(response)
                break
            except OSError:
                if time.monotonic()>deadline:raise
                time.sleep(.1)
        opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        def request(path,body=None,headers=None):
            with opener.open(urllib.request.Request(base+path,data=body,headers=headers or {}),timeout=15) as response:
                return response.status,response.read(),dict(response.headers)
        page=request('/login')[1].decode();csrf=re.search(r'name="csrf" value="([^"]+)"',page).group(1)
        logged=request('/login',urllib.parse.urlencode({'login':'doc-a','password':PASSWORD,'csrf':csrf}).encode(),{'Content-Type':'application/x-www-form-urlencoded'})[1].decode()
        csrf=re.search(r'name="csrf" value="([^"]+)"',logged).group(1)
        def create():
            status,body,headers=request('/api/v1/patients/BE08NEW/analyses',json.dumps({'contract_version':'1.0','operation':'risk','request_key':secrets.token_hex(16)}).encode(),{'Content-Type':'application/json','X-CSRF-Token':csrf})
            assert status==202;return json.loads(body),headers['Location']
        def worker(key=False):
            childenv=env.copy()
            if key:
                secret=ROOT/'var/deepseek-api-key';assert not secret.stat().st_mode & 0o077
                childenv['DEEPSEEK_API_KEY']=secret.read_text().strip()
            done=subprocess.run([sys.executable,'-m','apps.compass','--db',str(path),'worker','--lane','risk','--once'],cwd=ROOT,env=childenv,capture_output=True,text=True,timeout=75)
            assert done.returncode==0,done.stderr
        run,url=create();worker(key=True)
        value=json.loads(request(url)[1]);details=json.loads(request(url+'/risk-context')[1])
        assert value['status']=='ready' and value['result']['output']['assessment']=='potential_risk',value
        assert value['risk_context']['model_evaluation']=='candidates_only',value
        assert len(value['risk_context']['candidate_ids'])>=1,value
        assert details['report']['model_provenance']['test_double'] is False
        assert details['report']['model_candidates'][0]['interpretation']=='model_suspicion_unreviewed'
        report['cases'].append({'case':'real_provider_http_queue_worker','analysis':value,'details':details})
        save()
        # Real production adapter with credentials absent, no replaced network.
        missing,url_missing=create();worker()
        partial=json.loads(request(url_missing)[1])
        assert partial['status']=='ready' and partial['result']['output']['assessment']=='potential_risk'
        assert partial['risk_context']['error_codes']==['missing_credentials']
        assert partial['risk_context']['assessment']=='not_established'
        report['cases'].append({'case':'real_adapter_unavailable','analysis':partial})
        # Close only the rule episode, then a new physician source opens a new one.
        original=next(e for e in episodes.read(db,user,'BE08NEW') if e['origin']=='rule')
        episodes.close(db,user,'BE08NEW',original['id'],original['revision'],'Синтетическое рассмотрение завершено.',secrets.token_hex(16))
        run,url_repeat=create();worker()
        assert len([e for e in episodes.read(db,user,'BE08NEW') if e['origin']=='rule'])==1
        initial.update(supersedes_id=cid,basis='Новое синтетическое свидетельство после закрытия.')
        rules.record_context(db,user,'BE08NEW',records.today().isoformat(),initial,secrets.token_hex(16))
        run,url_new=create();worker()
        rule_episodes=[e for e in episodes.read(db,user,'BE08NEW') if e['origin']=='rule']
        assert len(rule_episodes)==2 and {e['state'] for e in rule_episodes}=={'open','closed'}
        report['episodes']=episodes.read(db,user,'BE08NEW')
        assert db.execute('SELECT count(*) FROM care_actions').fetchone()[0]==0
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        # Real HTTP relationship revocation must immediately deny stored data.
        db.execute('UPDATE care_relationships SET ends_at=? WHERE id=?',(now(),'be08-link'))
        try:request(url+'/risk-context');raise AssertionError('revoked relationship was readable')
        except urllib.error.HTTPError as exc:assert exc.code==404
        with sqlite3.connect(ROOT/'var/deepseek-budget.sqlite3') as budget:
            report['budget_after']=budget.execute('SELECT sum(micro_usd) FROM calls').fetchone()[0]
        report.update(pass_=True,integrity='ok',foreign_key_errors=0,care_actions=0,
                      real_model_calls=1,missing_credentials_production_run=True,closed_then_new_episode=True,
                      immediate_revocation_http_status=404,worker_processes=4)
        report['pass']=report.pop('pass_');save()
        print(json.dumps({k:report[k] for k in ['pass','budget_after','real_model_calls','closed_then_new_episode']}))
    finally:
        for child in children:
            if child.poll() is None:child.terminate()
            child.wait(timeout=10)
        serverlog.close();db.close()


if __name__=='__main__':main()
