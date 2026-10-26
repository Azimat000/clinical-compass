"""Switch the explicitly requested local roster after independent acceptance."""
from contextlib import closing
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from apps.compass.backup import copy_database
from apps.compass.db import connect
from evidence.S55.verify import verify

active_path = ROOT/'var/active-service.json'
active = json.loads(active_path.read_text())
database = ROOT/'var/compass.sqlite3'
candidate = ROOT/'var/S55-candidate.sqlite3'
backup = ROOT/'var/backups/S55-before-roster.sqlite3'
assert active['database'] == str(database)
assert candidate.is_file() and not backup.exists()
assert json.loads((ROOT/'evidence/S55/browser.json').read_text())['status'] == 'PASS'
verify(candidate, database)
for name, pid in active['processes'].items():
    command = subprocess.check_output(['ps','-p',str(pid),'-o','command='], text=True).strip()
    assert '-m apps.compass' in command and str(database) in command
    assert ('serve --port 8000' in command if name == 'server' else command.endswith('worker'))
candidate_pid = int((ROOT/'var/S55-browser-server.pid').read_text())
command = subprocess.check_output(['ps','-p',str(candidate_pid),'-o','command='],text=True)
assert str(candidate) in command and 'serve --port 8055' in command
os.kill(candidate_pid, signal.SIGTERM)
for pid in active['processes'].values():
    os.kill(pid,signal.SIGTERM)
for attempt in range(50):
    with socket.socket() as sock:
        if sock.connect_ex(('127.0.0.1',8000)) != 0:
            break
    time.sleep(.2)
else:
    raise RuntimeError('Old server still listens; database not replaced')
# Snapshot the last actual state after all old processes stopped.
saved = copy_database(database, backup)
with closing(connect(candidate)) as db:
    db.execute('DELETE FROM sessions')
verify(candidate, backup)
os.replace(candidate,database)
database.chmod(0o600)
processes = {}
for name,args in [('server',['serve','--port','8000']),('worker',['worker'])]:
    with (ROOT/f'var/clinic-20261026-{name}.log').open('ab') as log:
        p = subprocess.Popen([str(ROOT/'.venv/bin/python'),'-m','apps.compass','--db',str(database),*args],
            cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    processes[name] = p.pid
    (ROOT/f'var/clinic-20261026-{name}.pid').write_text(str(p.pid)+'\n')
active.update(database=str(database),accounts=str(ROOT/'var/clinic-20261026-accounts.json'),processes=processes,
              dataset='clinic-roster-20261026-v1')
active_path.write_text(json.dumps(active,ensure_ascii=False,indent=2)+'\n')
accounts = json.loads((ROOT/'var/clinic-20261026-accounts.json').read_text())['accounts']
fd = os.open(ROOT/'var/clinic-20261026-access.md', os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,'w') as handle:
    handle.write('# Доступ к Клиническому компасу\n\nhttp://127.0.0.1:8000\n\n')
    handle.write('Врачи и пациенты имеют отдельные кабинеты. Пароли индивидуальны; храните файл локально.\n\n')
    handle.write('| Имя | Роль | Логин | Пароль |\n|---|---|---|---|\n')
    for a in accounts:
        handle.write(f"| {a['name']} | {'Врач' if a['role']=='doctor' else 'Пациент'} | {a['login']} | {a['password']} |\n")
for attempt in range(50):
    try:
        with urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=2) as response:
            health=json.load(response)
        break
    except (OSError,ValueError):
        time.sleep(.2)
else:
    raise RuntimeError('New local server not ready; original private snapshot preserved')
assert health['status']=='ok'
for pid in processes.values():
    os.kill(pid,0)
result=verify(database,backup)
result.update(health=health,processes=processes,backup=dict(path='var/backups/S55-before-roster.sqlite3',
              sha256=saved['sha256'],mode=oct(backup.stat().st_mode&0o777)))
(ROOT/'evidence/S55/runtime.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print('PASS: new roster active on port 8000; server and worker running; old identities absent')
