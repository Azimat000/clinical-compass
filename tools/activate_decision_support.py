"""Switch the explicitly requested local UI, preserving the current database.

No test suite, browser request, provider request or clinical seed is performed.
Startup readiness is a process hand-off, not an acceptance check.
"""
from pathlib import Path
import json
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
meta_path = ROOT / 'var/active-service.json'
meta = json.loads(meta_path.read_text())
stamp = time.strftime('%Y%m%d-%H%M%S')
folder = ROOT / 'var/backups' / ('decision-support-' + stamp)
folder.mkdir(parents=True, mode=0o700)
database = Path(meta['database'])
# Online SQLite backup preserves a complete transaction snapshot, no SQL exports.
with sqlite3.connect(str(database)) as source, sqlite3.connect(str(folder/'before.sqlite3')) as destination:
    source.backup(destination)
(folder/'before.sqlite3').chmod(0o600)
shutil.copy2(meta_path, folder/'active-service.json')
(folder/'active-service.json').chmod(0o600)
python = str(ROOT/'.venv/bin/python') if (ROOT/'.venv/bin/python').exists() else sys.executable
old = meta['processes']
for pid in old.values():
    try: os.kill(pid, signal.SIGTERM)
    except ProcessLookupError: pass
# Wait only for stopped process identities before migrating the same file.
for _ in range(50):
    alive = []
    for pid in old.values():
        try: os.kill(pid, 0); alive.append(pid)
        except ProcessLookupError: pass
    if not alive: break
    time.sleep(.1)
else:
    raise RuntimeError('Previous service did not stop; database not migrated')
# Take the final stopped-state backup too: no last-second history is lost.
with sqlite3.connect(str(database)) as source, sqlite3.connect(str(folder/'stopped.sqlite3')) as destination:
    source.backup(destination)
(folder/'stopped.sqlite3').chmod(0o600)
sys.path.insert(0, str(ROOT))
from apps.compass.db import connect, migrate, transaction, now
from apps.compass import events
ready = ROOT/'var'/('decision-support-ready-'+stamp)
children = []
try:
    db = connect(database)
    try:
        migrate(db)
        with transaction(db):
            db.execute("UPDATE backend_job_settings SET enabled=1,generation_version='fe03b-packets-v1' WHERE id=1")
            # Intent only: current roster and all clinical rows stay as they are.
            for row in db.execute('''SELECT r.patient_id,r.id,r.doctor_id FROM care_relationships r
                JOIN patients p ON p.id=r.patient_id JOIN users u ON u.id=r.doctor_id
                WHERE p.synthetic=1 AND r.ends_at IS NULL AND r.starts_at<=? AND u.disabled=0''',(now(),)).fetchall():
                events.enqueue(db,'backend.data_changed.v1',row['patient_id'],
                    {'relationship_id':row['id'],'doctor_id':row['doctor_id']})
    finally:
        db.close()
    def launch(command, name, cwd=ROOT):
        log = open(ROOT/'var'/('decision-support-'+name+'.log'),'ab',buffering=0)
        os.chmod(log.name,0o600)
        try: child = subprocess.Popen(command,cwd=cwd,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        finally: log.close()
        children.append(child)
        return child
    server_code = '''from pathlib import Path
from apps.compass.web import create_app
from waitress import create_server
app = create_app(DATABASE)
server = create_server(app,host='127.0.0.1',port=8000,threads=4)
Path(READY).write_text(str(__import__('os').getpid()))
server.run()
'''.replace('DATABASE',repr(str(database))).replace('READY',repr(str(ready)))
    server = launch([python,'-c',server_code],'server')
    for _ in range(150):
        if ready.exists(): break
        if server.poll() is not None: raise RuntimeError('Server startup failed; see private server log')
        time.sleep(.1)
    else: raise RuntimeError('Server startup timed out')
    risk = launch([python,'-m','apps.compass','--db',str(database),'worker','--lane','risk'],'risk')
    generation = launch([python,str(ROOT/'tools/run_decision_support_worker.py'),'--db',str(database)],'generation')
    meta.update(processes={'server':server.pid,'worker':risk.pid,'generation_worker':generation.pid},
                runtime_directory=str(ROOT),runtime_ref='decision-support-ui-unverified',
                decision_support={'activated_at':stamp,'backup':str(folder),'validation':'not_run_by_user_request',
                                  'quality_gate':'preserved','database_preserved':True})
    meta_path.write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n')
    meta_path.chmod(0o600)
    ready.unlink(missing_ok=True)
    print(json.dumps({'activated':True,'port':8000,'processes':meta['processes'],'backup':str(folder),'tests_run':False},ensure_ascii=False))
except BaseException:
    for child in children:
        if child.poll() is None:
            child.terminate()
            try: child.wait(timeout=10)
            except subprocess.TimeoutExpired: child.kill(); child.wait()
    # No new server served before its ready marker; startup failures restore the
    # stopped snapshot. Once ready, leave data intact for operator recovery.
    if not ready.exists():
        with sqlite3.connect(str(folder/'stopped.sqlite3')) as source, sqlite3.connect(str(database)) as destination:
            source.backup(destination)
        for name, command in [('server',['serve','--port','8000']),('worker',['worker'])]:
            log=open(folder/('rollback-'+name+'.log'),'ab')
            process=subprocess.Popen([python,'-m','apps.compass','--db',str(database),*command],cwd=meta['runtime_directory'],stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            log.close(); meta['processes'][name]=process.pid
        meta_path.write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n')
    raise
