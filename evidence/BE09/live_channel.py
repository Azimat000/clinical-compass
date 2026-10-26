"""Real local HTTP + production worker, on a new synthetic DB and no API key."""
import http.cookiejar
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from apps.tests.test_backend_alerts import BackendAlertTests
from apps.tests.test_access import PASSWORD
from apps.compass import backend_alerts as alerts

case=BackendAlertTests();case.setUp()
server=None
try:
    case.positive();case.enable()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    base=f'http://127.0.0.1:{port}'
    env={'PATH':os.environ['PATH'],'PYTHONPATH':str(ROOT),'LANG':'en_US.UTF-8'}
    with (ROOT/'evidence/BE09/http-server.log').open('w') as log:
        server=subprocess.Popen([str(ROOT/'.venv/bin/python'),'-m','apps.compass','--db',str(case.path),'serve','--port',str(port)],cwd=ROOT,env=env,stdout=log,stderr=log)
        for _ in range(100):
            try:
                urllib.request.urlopen(base+'/healthz',timeout=1).close();break
            except OSError:time.sleep(.05)
        else:raise RuntimeError('server startup failed')
        def session(uid):
            opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            text=opener.open(base+'/login').read().decode()
            csrf=re.search(r'name="csrf" value="([^"]+)"',text)[1]
            data=urllib.parse.urlencode({'csrf':csrf,'login':uid,'password':PASSWORD}).encode()
            opener.open(base+'/login',data).close()
            return opener
        def token(opener):
            return re.search(r'name="csrf" value="([^"]+)"',opener.open(base+'/').read().decode())[1]
        doctor=session('doc-a');patient=session('pat-a');other=session('doc-b')
        body={'csrf':token(patient),'request_key':secrets.token_hex(16),'observed_on':'2026-10-26',
              'summary':'Новая вымышленная запись для проверки доставки.','wellbeing':'worse'}
        started=time.perf_counter()
        req=urllib.request.Request(base+'/patients/D01/self-reports',data=urllib.parse.urlencode(body).encode(),headers={'Accept':'application/json'})
        try:patient.open(req).close()
        except urllib.error.HTTPError as e:raise RuntimeError(e.read().decode()) from None
        saved_ms=(time.perf_counter()-started)*1000
        worker=subprocess.run([str(ROOT/'.venv/bin/python'),'-m','apps.compass','--db',str(case.path),'worker','--lane','risk','--once'],cwd=ROOT,env=env,capture_output=True,text=True,timeout=45)
        assert worker.returncode==0,worker.stderr
        value=json.load(doctor.open(base+'/api/v1/physician/alerts'))
        assert len(value['items'])==1,value
        item=value['items'][0];assert item['state']=='delivered' and item['actions']==[]
        delivered_ms=(time.perf_counter()-started)*1000
        detail=json.load(doctor.open(base+'/api/v1/physician/alerts/'+item['id']))
        assert detail['state']=='delivered' and not detail['clinical_ready']
        csrf=token(doctor)
        receipt={'action':'received','expected_revision':item['episode_revision'],'reason':'','request_key':'be09-live-receipt-20261026'}
        req=urllib.request.Request(base+'/api/v1/physician/alerts/'+item['id']+'/actions',data=json.dumps(receipt).encode(),headers={'Content-Type':'application/json','X-CSRF-Token':csrf})
        received=json.load(doctor.open(req));assert received['state']=='received'
        receipt_ms=(time.perf_counter()-started)*1000
        assert [a['action'] for a in received['actions']]==['received']
        checks=[]
        for who,opener,expected in [('patient',patient,403),('foreign_doctor',other,404)]:
            try:opener.open(base+'/api/v1/physician/alerts/'+item['id']);raise AssertionError('unexpected access')
            except urllib.error.HTTPError as e:assert e.code==expected;checks.append({'actor':who,'status':e.code})
        run=case.db.execute('SELECT payload_json FROM analysis_result_versions ORDER BY rowid DESC LIMIT 1').fetchone()[0]
        analysis=json.loads(run)
        assert analysis['risk_context']['error_codes']==['missing_credentials']
        # Restart the actual HTTP process, retaining the same authenticated session.
        server.terminate();server.wait(timeout=10)
        server=subprocess.Popen([str(ROOT/'.venv/bin/python'),'-m','apps.compass','--db',str(case.path),'serve','--port',str(port)],cwd=ROOT,env=env,stdout=log,stderr=log)
        for _ in range(100):
            try:restarted=json.load(doctor.open(base+'/api/v1/physician/alerts/'+item['id']));break
            except OSError:time.sleep(.05)
        else:raise RuntimeError('restart failed')
        assert restarted['state']=='received' and len(restarted['actions'])==1
        assert case.db.execute('SELECT count(*) FROM care_actions').fetchone()[0]==0
        result={'pass':True,'synthetic':True,'clinical_validation':False,'real_http':True,'production_worker_exit':worker.returncode,
                'external_model_calls':0,'model_error':'missing_credentials','rule_preserved':True,
                'record_save_ms':round(saved_ms,3),'record_to_channel_ms':round(delivered_ms,3),'record_to_physician_receipt_ms':round(receipt_ms,3),
                'receipt_actor':'synthetic authenticated test physician, not real human reading',
                'states':['queued','delivered','received'],'view_or_decision_inferred':False,'access_checks':checks,
                'restart_receipt_preserved':True,'care_actions':0,'attempts':detail['attempt_log'],
                'live_service_8000_touched':False,'channel':alerts.CHANNEL}
        (ROOT/'evidence/BE09/live-channel.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(result,ensure_ascii=False,indent=2))
finally:
    if server is not None and server.poll() is None:server.terminate();server.wait(timeout=10)
    case.tearDown()
