"""Activate the checked fictional edition, preserving the latest local auth state."""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from apps.compass.backup import copy_database
from tools.revise_clinic_medications import build
from evidence.S56.verify import verify

active_path=ROOT/'var/active-service.json'
active=json.loads(active_path.read_text())
database=ROOT/'var/compass.sqlite3'
snapshot=ROOT/'var/backups/S56-before-activation.sqlite3'
target=ROOT/'var/S56-final.sqlite3'
assert active['database']==str(database) and not snapshot.exists() and not target.exists()
assert json.loads((ROOT/'evidence/S56/browser.json').read_text())['status']=='PASS'
for name,pid in active['processes'].items():
    command=subprocess.check_output(['ps','-p',str(pid),'-o','command='],text=True)
    assert str(database) in command and '-m apps.compass' in command
    assert ('serve --port 8000' in command if name=='server' else command.strip().endswith('worker'))
copy_pid=int((ROOT/'var/S56-browser-server.pid').read_text())
command=subprocess.check_output(['ps','-p',str(copy_pid),'-o','command='],text=True)
assert 'S56-candidate.sqlite3' in command and 'serve --port 8056' in command
os.kill(copy_pid,signal.SIGTERM)
for pid in active['processes'].values():os.kill(pid,signal.SIGTERM)
for attempt in range(50):
    with socket.socket() as sock:
        if sock.connect_ex(('127.0.0.1',8000))!=0:break
    time.sleep(.2)
else:raise RuntimeError('Original server still listens; source untouched')


def start():
    processes={}
    for name,args in [('server',['serve','--port','8000']),('worker',['worker'])]:
        with (ROOT/f'var/clinic-20261026-{name}.log').open('ab') as log:
            p=subprocess.Popen([str(ROOT/'.venv/bin/python'),'-m','apps.compass','--db',str(database),*args],
                cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        processes[name]=p.pid
        (ROOT/f'var/clinic-20261026-{name}.pid').write_text(str(p.pid)+'\n')
    return processes


try:
    saved=copy_database(database,snapshot)
    # Rebuild from the LAST offline state, retaining newer successful logins/audit.
    result=build(snapshot,target)
    verify(target,snapshot)
except BaseException:
    active['processes']=start()
    active_path.write_text(json.dumps(active,ensure_ascii=False,indent=2)+'\n')
    raise
os.replace(target,database)
database.chmod(0o600)
active.update(processes=start(),medication_revision=result['revision'])
active_path.write_text(json.dumps(active,ensure_ascii=False,indent=2)+'\n')
for attempt in range(50):
    try:
        with urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=2) as response:health=json.load(response)
        break
    except (OSError,ValueError):time.sleep(.2)
else:raise RuntimeError('Updated local service not ready; original snapshot retained')
assert health['status']=='ok'
for pid in active['processes'].values():os.kill(pid,0)
checked=verify(database,snapshot)
checked.update(health=health,processes=active['processes'],
               backup=dict(path='var/backups/S56-before-activation.sqlite3',sha256=saved['sha256'],mode=oct(snapshot.stat().st_mode&0o777)))
(ROOT/'evidence/S56/runtime.json').write_text(json.dumps(checked,ensure_ascii=False,indent=2)+'\n')
print('PASS: reconciled fictional medication history active; users, IDs, passwords and source releases retained')
