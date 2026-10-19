"""Reproducible finite closed-loop HTTP bursts; full raw request timings retained."""
from common import *
from concurrent.futures import ThreadPoolExecutor
import tempfile
import threading
from apps.compass import events, extraction


def run(users):
    with tempfile.TemporaryDirectory(prefix='hac-s15-load-') as folder:
        path=Path(folder)/'db'; people=fixture(path,users//2)
        server=Server(path,folder); server.start()
        worker_log=open(Path(folder)/'worker.log','wb')
        worker=subprocess.Popen([sys.executable,'-m','apps.compass','--db',str(path),'worker'],cwd=ROOT,stdout=worker_log,stderr=worker_log)
        measurements=[]; stop_monitor=threading.Event()
        def monitor():
            while not stop_monitor.is_set():
                try:
                    raw=subprocess.check_output(['ps','-o','pid=,pcpu=,rss=','-p',str(server.process.pid)+','+str(worker.pid)],text=True)
                    measurements.append({'elapsed_s':time.perf_counter()-monitor_start,'processes':[dict(zip(('pid','cpu_percent_ps','rss_kib'),map(float,line.split()))) for line in raw.splitlines()]})
                except subprocess.CalledProcessError:pass
                stop_monitor.wait(.2)
        monitor_start=time.perf_counter()
        monitor_thread=threading.Thread(target=monitor,daemon=True);monitor_thread.start()
        try:
            clients=[]; logins=[]
            # Login separately: steady-state load must not confuse scrypt with page costs.
            for doc,pat,pid in people:
                for uid,role in ((doc,'doctor'),(pat,'patient')):
                    b=Browser(server.url)
                    auth=connect(path); started=time.perf_counter()
                    token,error=access.authenticate(auth,uid,PASSWORD,f'192.0.2.{len(clients)+1}')
                    logins.append((time.perf_counter()-started)*1000); assert error is None
                    b.token=auth.execute('SELECT csrf_token FROM sessions WHERE token_hash=?',(access.digest(token),)).fetchone()[0]
                    auth.close()
                    for handler in b.opener.handlers:
                        if isinstance(handler,HTTPCookieProcessor):
                            handler.cookiejar.set_cookie(http.cookiejar.Cookie(0,access.COOKIE,token,None,False,'127.0.0.1',False,False,'/',True,False,None,True,None,None,{}))
                    assert b.request('/')[0]==200
                    clients.append((b,role,pid))
            poll_stop=threading.Event();poll_threads=[];poll_samples=[]
            def poll(b):
                while not poll_stop.is_set():
                    try:
                        code,body,ms=b.request('/api/critical'); assert code==200
                        poll_samples.append({'route':'/api/critical','code':code,'ms':ms})
                        for item in json.loads(body):
                            if not item['received']:
                                code,body,ms=b.post('/critical/'+item['id']+'/received',{})
                                poll_samples.append({'route':'critical/received','code':code,'ms':ms});assert code==204
                    except Exception as exc:
                        poll_samples.append({'error':type(exc).__name__,'code':0,'ms':0})
                    poll_stop.wait(3)
            for b,role,pid in clients:
                if role=='doctor':
                    other=Browser(server.url);other.token=b.token
                    for handler in b.opener.handlers:
                        if isinstance(handler,HTTPCookieProcessor):
                            for h in other.opener.handlers:
                                if isinstance(h,HTTPCookieProcessor):
                                    for cookie in handler.cookiejar:h.cookiejar.set_cookie(cookie)
                    t=threading.Thread(target=poll,args=(other,),daemon=True);poll_threads.append(t);t.start()
            barrier=threading.Barrier(users); samples=[]; lock=threading.Lock(); errors=[]
            def task(client):
                b,role,pid=client; local=[]
                barrier.wait(timeout=30)
                for cycle in range(4):
                    paths=['/',f'/demo/{pid}',f'/api/patients/{pid}/history',
                           f'/patients/{pid}/decisions' if role=='doctor' else f'/patients/{pid}/self-reports',
                           '/?q='+pid if role=='doctor' else f'/api/patients/{pid}/history']
                    for route in paths:
                        start=time.perf_counter()
                        try:
                            code,body,ms=b.post(route,form(critical=(cycle%2==0))) if route.endswith('/self-reports') else b.request(route)
                            local.append({'role':role,'route':route,'cycle':cycle,'code':code,'ms':ms})
                        except Exception as exc:
                            local.append({'role':role,'route':route,'cycle':cycle,'code':0,'ms':(time.perf_counter()-start)*1000,'error':type(exc).__name__})
                with lock:samples.extend(local)
            begin=time.perf_counter()
            with ThreadPoolExecutor(max_workers=users) as pool:list(pool.map(task,clients))
            duration=time.perf_counter()-begin
            # Explicit doctor fetch and display-receipt submission; HTTP receipt, not human visibility.
            delivery=[]
            for b,role,pid in clients:
                if role!='doctor':continue
                deadline=time.monotonic()+15
                while True:
                    code,body,ms=b.request('/api/critical'); assert code==200
                    items=json.loads(body)
                    if len(items)>=2:break
                    if time.monotonic()>deadline:raise RuntimeError('critical backlog not drained')
                    time.sleep(.05)
                for item in items:
                    assert b.post('/critical/'+item['id']+'/received',{})[0]==204
                assert b.request('/critical')[0]==200
            poll_stop.set()
            for t in poll_threads:t.join(timeout=65)
            assert all(not t.is_alive() for t in poll_threads)
            db=connect(path)
            from datetime import datetime
            for row in db.execute('SELECT e.recorded_at,d.ready_at,d.received_at,d.seen_at,d.reacted_at FROM critical_delivery d JOIN critical_events c ON c.id=d.event_id JOIN clinical_rule_evaluations v ON v.id=c.evaluation_id JOIN clinical_entries e ON e.id=v.entry_id'):
                delta=lambda t:(datetime.fromisoformat(t)-datetime.fromisoformat(row['recorded_at'])).total_seconds()*1000
                assert row['ready_at'] and row['received_at'] and row['seen_at'] is None and row['reacted_at'] is None
                delivery.append({'ready_ms':delta(row['ready_at']),'receipt_ms':delta(row['received_at'])})
            from apps.compass.backup import checked
            checked(db)
            counts={t:db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('self_reports','critical_events','care_actions')}
            assert counts=={'self_reports':users//2*4,'critical_events':users//2*2,'care_actions':0},counts
            db.close()
            good=[s['ms'] for s in samples if s['code']==200]; failures=[s for s in samples if s['code']!=200]
            return {'users':users,'pairs':users//2,'requests':len(samples),'cycles':4,'duration_s':duration,
                'requests_per_s':len(samples)/duration,'http_ms':summary([s['ms'] for s in samples]),
                'session_setup_authenticate_sequential_ms':summary(logins),'errors':failures,'error_fraction':len(failures)/len(samples),
                'counts':counts,'critical_ready_ms':summary([d['ready_ms'] for d in delivery]),
                'critical_receipt_ms':summary([d['receipt_ms'] for d in delivery]),
                'receipt_method':'Parallel doctor HTTP polling every 3s, then final drain after workload. Receipt POST confirms synthetic HTTP client, not browser render or human response',
                'raw_requests':samples,'raw_delivery':delivery,'poll_requests':poll_samples,'poll_errors':[p for p in poll_samples if p['code'] not in (200,204)],
                'resource_samples':measurements,
                'resource_limit':'ps sampled CPU/RSS server+worker includes sequential setup; client/OS resources excluded; sampled peaks may miss short peaks',
                'server_log': '\n'.join(p.read_text() for p in Path(folder).glob('server*.log')),
                'worker_log':Path(folder,'worker.log').read_text()}
        finally:
            if 'poll_stop' in locals():
                poll_stop.set()
                for t in poll_threads:t.join(timeout=65)
            stop_monitor.set();monitor_thread.join(timeout=3)
            worker.kill();worker.wait(timeout=10);worker_log.close();server.stop()


def main():
    runs=[]
    for n in (10,50,100):
        print('Running',n,flush=True); runs.append(run(n))
        Path('evidence/S15/load.json').write_text(json.dumps({'machine':machine(),'method':'fresh DB each run; 50/50 doctor/patient; preauthenticated sessions via real authenticate with distinct synthetic address per user; HTTP login/IP limiter excluded; barrier start, 4 cycles x 5 requests/user, no think time; same machine clients/server/worker; finite burst not endurance', 'runs':runs},ensure_ascii=False,indent=2))
    perf={'machine':machine(),'load_reference':'evidence/S15/load.json'}
    with tempfile.TemporaryDirectory() as folder:
        path=Path(folder)/'db'; fixture(path);db=connect(path)
        values=[]
        for _ in range(100):
            t=time.perf_counter(); records.save(db,{'id':'load-pat-0','role':'patient'},'L000','self_report',form(True));values.append((time.perf_counter()-t)*1000)
        perf['record_and_rules_transaction_ms']=summary(values)
        for name,text in [('short','Пациент 35 лет. Диагноз F41.1. Аллергия неизвестна.'),('near_limit',('Пациент 35 лет. Диагноз F41.1.\n'*400))]:
            values=[]
            for _ in range(100):
                t=time.perf_counter();extraction.extract(text);values.append((time.perf_counter()-t)*1000)
            perf['extraction_'+name]={'bytes':len(text.encode()),'timings':summary(values)}
        from apps.compass import decisions
        ref=decisions.reference();values=[]
        for _ in range(30):
            data={'request_key':secrets.token_hex(16),'kind':'therapy_start','content':'Synthetic manual draft only',
                  'basis':'Synthetic fixture','uncertainties':'Requires real physician',
                  'therapy_reference':ref['version'],'aviandr_conclusion':'insufficient_data','aviandr_basis':'Synthetic insufficient data',
                  **{'note_'+a['id']:'Synthetic review, no actual treatment' for a in ref['review_areas']}}
            t=time.perf_counter();decisions.draft(db,{'id':'load-doc-0','role':'doctor'},'L000',data);values.append((time.perf_counter()-t)*1000)
        perf['manual_recommendation_draft_transaction_ms']=summary(values)
        perf['recommendation_limit']='No automatic recommendation generator exists; measures manual draft creation with evidence snapshot; no confirmation/treatment.'
        assert db.execute('SELECT count(*) FROM care_actions').fetchone()[0]==0
        db.close()
        server=Server(path,folder);server.start()
        try:
            doctor=Browser(server.url);doctor.login('load-doc-0')
            idle={}
            for route in ('/','/?q=L000','/demo/L000','/patients/L000/decisions','/patients/L000/imports','/critical'):
                times=[]
                for _ in range(30):
                    code,body,ms=doctor.request(route);assert code==200;times.append(ms)
                idle[route]=summary(times)
            perf['idle_http_full_response_ms']=idle
            perf['interface_limit']='HTTP bytes received and server HTML generation; browser paint/interaction latency is not measured'
        finally:server.stop()
    Path('evidence/S15/performance.json').write_text(json.dumps(perf,ensure_ascii=False,indent=2))
    assert all(not r['errors'] and not r['poll_errors'] for r in runs)

if __name__=='__main__':main()
