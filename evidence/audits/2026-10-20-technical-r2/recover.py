from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'evidence/S15'))
"""Actual process kills, dropped loopback transport, hot journal and destroyed DB restore."""
from common import *
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import tempfile
import threading
from apps.compass.backup import copy_database, checked
from apps.compass import events


def rows(db):
    tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    return {t: sorted([list(r) for r in db.execute('SELECT * FROM "'+t+'"')],key=repr) for t in tables}


def main():
    result={'machine':machine(),'scope':'Synthetic local files only; SIGKILL is not host/power/storage failure; monotonic timings, operator detection excluded'}
    with tempfile.TemporaryDirectory(prefix='hac-s15-recovery-') as folder:
        root=Path(folder);path=root/'db'; fixture(path); server=Server(path,root);server.start()
        class Proxy(BaseHTTPRequestHandler):
            protocol_version='HTTP/1.0'
            def log_message(self,*args): pass
            def do_GET(self):self.forward()
            def do_POST(self):self.forward()
            def forward(self):
                mode=self.server.mode
                body=self.rfile.read(int(self.headers.get('Content-Length','0')))
                if mode=='drop_before':
                    self.close_connection=True;return
                connection=http.client.HTTPConnection('127.0.0.1',server.port,timeout=10)
                try:
                    connection.request(self.command,self.path,body,dict(self.headers))
                    response=connection.getresponse();payload=response.read()
                    if mode=='drop_after':
                        self.close_connection=True;return
                    self.send_response(response.status)
                    for key,value in response.getheaders():
                        if key.lower() not in ('connection','transfer-encoding','content-length'): self.send_header(key,value)
                    self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
                finally:connection.close()
        proxy=ThreadingHTTPServer(('127.0.0.1',0),Proxy);proxy.mode='ok'
        thread=threading.Thread(target=proxy.serve_forever,daemon=True);thread.start()
        pat=Browser(f'http://127.0.0.1:{proxy.server_port}');pat.login('load-pat-0')
        doc=Browser(server.url);doc.login('load-doc-0')
        def count():
            db=connect(path);n=db.execute('SELECT count(*) FROM self_reports').fetchone()[0];db.close();return n
        def failed_send(data):
            try:pat.post('/patients/L000/self-reports',data)
            except (OSError,http.client.HTTPException):return
            raise AssertionError('Transport unexpectedly succeeded')
        try:
            route='/patients/L000/self-reports'
            data=form(True);proxy.mode='drop_before';failed_send(data);assert count()==0
            proxy.mode='ok';assert pat.post(route,data)[0]==200;assert count()==1
            result['network_before_accept']={'not_sent':1,'retry_saved':1,'duplicates':0,'mode':'proxy closes TCP before upstream request; not physical network shutdown'}
            data=form(True);proxy.mode='drop_after';failed_send(data);assert count()==2
            proxy.mode='ok';assert pat.post(route,data)[0]==200;assert count()==2
            result['network_after_commit']={'response_lost':1,'server_saved':1,'retry_duplicates':0}
            # Worker absent for both accepted critical reports.
            db=connect(path)
            pending=db.execute("SELECT count(*) FROM outbox_events WHERE topic='clinical.critical.medication_safety.v1' AND status='pending'").fetchone()[0]
            assert pending==2
            assert db.execute('SELECT count(*) FROM critical_delivery').fetchone()[0]==0
            db.close()
            data=form(True);t=time.perf_counter();server.stop();failed_send(data);assert count()==2
            server.start();assert pat.post(route,data)[0]==200;assert count()==3
            result['application_kill']={'downtime_through_verified_retry_ms':(time.perf_counter()-t)*1000,'during_outage_not_accepted':1,'saved_after_retry':1,'committed_lost':0}
            # Kill a real worker inside its handler before COMMIT; journal rollback must recover it.
            marker=root/'worker-ready'
            worker_code="""
import sys,time
from pathlib import Path
from apps.compass.db import connect
from apps.compass.events import process_one,HANDLERS
p,marker=sys.argv[1:]
db=connect(p)
def pause(db,event):
    HANDLERS[event['topic']](db,event)
    Path(marker).write_text(event['id'])
    time.sleep(120)
process_one(db,{key:pause for key in HANDLERS})
"""
            worker=subprocess.Popen([sys.executable,'-c',worker_code,str(path),str(marker)],cwd=ROOT)
            try:
                deadline=time.monotonic()+10
                while not marker.exists():
                    assert worker.poll() is None
                    if time.monotonic()>deadline:raise RuntimeError('worker marker timeout')
                    time.sleep(.01)
                killed_id=marker.read_text();worker.kill();worker.wait(timeout=10)
            finally:
                if worker.poll() is None:worker.kill();worker.wait()
            db=connect(path)
            assert db.execute('SELECT status FROM outbox_events WHERE id=?',(killed_id,)).fetchone()[0]=='pending'
            t=time.perf_counter()
            subprocess.run([sys.executable,'-m','apps.compass','--db',str(path),'worker','--once'],cwd=ROOT,check=True,timeout=20)
            ready_count=db.execute('SELECT count(*) FROM critical_delivery WHERE ready_at IS NOT NULL AND received_at IS NULL').fetchone()[0]
            assert ready_count==3
            items=json.loads(doc.request('/api/critical')[1]);assert len(items)==3
            for item in items:assert doc.post('/critical/'+item['id']+'/received',{})[0]==204
            assert db.execute('SELECT count(*) FROM critical_delivery WHERE received_at IS NOT NULL AND seen_at IS NULL AND reacted_at IS NULL').fetchone()[0]==3
            result['worker_kill']={'killed_inside_transaction_event_rolled_back_to_pending':True,'recovered_ready':3,'http_receipts':3,'human_seen':0,'reacted':0,'restart_to_receipts_ms':(time.perf_counter()-t)*1000}
            db.close()
            # Snapshot while server is running; exact baseline retained. No writes race this comparison.
            before=connect(path);snapshot_rows=rows(before);before.close()
            t=time.perf_counter();manifest=copy_database(path,root/'backup');backup_ms=(time.perf_counter()-t)*1000
            backup_finished=time.perf_counter()
            # One more committed critical report after backup: it WILL be lost from this recovery point.
            assert pat.post(route,form(True))[0]==200;assert count()==4
            failure=time.perf_counter();server.stop()
            # Real destroyed DB header, original already stopped; no process restart substitute.
            with path.open('r+b') as stream:stream.write(b'DESTROYED-S15!!!\x00');stream.flush();os.fsync(stream.fileno())
            try:
                import sqlite3
                with sqlite3.connect(path) as broken:broken.execute('PRAGMA integrity_check').fetchall()
            except sqlite3.DatabaseError:detected=True
            else:detected=False
            assert detected
            t=time.perf_counter();restore=copy_database(root/'backup',root/'restored',manifest['sha256'])
            restored=connect(root/'restored');assert rows(restored)==snapshot_rows;checked(restored);restored.close()
            server.path=root/'restored';server.start()
            assert doc.request('/api/patients/L000/history')[0]==200
            assert pat.post(route,form(True))[0]==200
            # Validate old rows BEFORE canary write and then ensure new write/critical outbox survives.
            restored=connect(server.path);checked(restored)
            assert restored.execute('SELECT count(*) FROM self_reports').fetchone()[0]==4
            assert restored.execute('SELECT count(*) FROM care_actions').fetchone()[0]==0
            restored.close()
            rto=(time.perf_counter()-failure)*1000
            result['destroyed_database_restore']={'corruption_detected':detected,'backup_ms':backup_ms,
                'backup':manifest,'all_snapshot_tables_equal_before_canary':True,'snapshot_tables':len(snapshot_rows),
                'rpo_age_at_failure_ms':(failure-backup_finished)*1000,
                'committed_post_backup_reports_lost':1,'post_backup_critical_events_lost':1,
                'snapshot_reports_restored':3,'snapshot_http_receipts_restored':3,
                'rto_failure_to_http_read_write_ms':rto,'restore_to_ready_ms':(time.perf_counter()-t)*1000,
                'limit':'No automatic scheduler/offsite copy. RPO age at completion lower bound during backup; no concurrent writes in this snapshot. Lost post-backup data cannot be recovered without another retained source.'}
            server.stop()
            # Hot rollback journal: spill dirty pages then kill writer mid-transaction.
            crash=root/'hot';copy_database(root/'backup',crash)
            db=connect(crash);db.execute('CREATE TABLE s15_crash_probe(id INTEGER PRIMARY KEY,payload BLOB)');db.close()
            marker=root/'hot-ready'
            child_code="""
import sys,time
from pathlib import Path
from apps.compass.db import connect
p,marker=sys.argv[1:]
db=connect(p);db.execute('PRAGMA cache_size=10');db.execute('BEGIN IMMEDIATE')
db.execute("UPDATE patients SET code='UNCOMMITTED' WHERE id='L000'")
for i in range(300):db.execute('INSERT INTO s15_crash_probe(payload) VALUES(?)',(b'X'*8192,))
Path(marker).write_text('dirty pages spilled, not committed');time.sleep(120)
"""
            writer=subprocess.Popen([sys.executable,'-c',child_code,str(crash),str(marker)],cwd=ROOT)
            try:
                deadline=time.monotonic()+10
                while not marker.exists():
                    assert writer.poll() is None
                    if time.monotonic()>deadline:raise RuntimeError('dirty page timeout')
                    time.sleep(.01)
                journal=Path(str(crash)+'-journal');journal_bytes=journal.stat().st_size
                journal_header=journal.read_bytes()[:8].hex();assert journal_bytes>512 and journal_header!='0000000000000000'
                writer.kill();writer.wait(timeout=10)
            finally:
                if writer.poll() is None:writer.kill();writer.wait()
            t=time.perf_counter();db=connect(crash);checked(db)
            assert db.execute('SELECT count(*) FROM s15_crash_probe').fetchone()[0]==0
            assert db.execute("SELECT code FROM patients WHERE id='L000'").fetchone()[0]=='L000'
            assert db.execute('SELECT count(*) FROM critical_delivery WHERE received_at IS NOT NULL').fetchone()[0]==3
            result['hot_journal_recovery']={'journal_bytes_before_kill':journal_bytes,'header':journal_header,
                'open_and_checks_ms':(time.perf_counter()-t)*1000,'uncommitted_rows_retained':0,'committed_receipts_retained':3,'integrity':'ok','foreign_keys':[]}
            db.close()
        finally:
            server.stop();proxy.shutdown();proxy.server_close();thread.join(timeout=5)
    Path('evidence/audits/2026-10-20-technical-r2/recovery.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
