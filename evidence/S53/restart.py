"""Restart only the recorded local service against the same preserved database."""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import time
import urllib.request

root = Path(__file__).resolve().parents[2]
active = root / 'var/active-service.json'
state = json.loads(active.read_text())
database = str(root / 'var/compass.sqlite3')
assert state['database'] == database
for name, pid in state['processes'].items():
    command = subprocess.check_output(['ps', '-p', str(pid), '-o', 'command='], text=True).strip()
    assert '-m apps.compass' in command and database in command and ('serve --port 8000' in command if name == 'server' else command.endswith('worker')), (name, pid)
for pid in state['processes'].values():
    os.kill(pid, signal.SIGTERM)
for attempt in range(50):
    with socket.socket() as sock:
        if sock.connect_ex(('127.0.0.1', 8000)) != 0:
            break
    time.sleep(.2)
else:
    raise RuntimeError('Old server still listens')
processes = {}
for name, args in [('server', ['serve', '--port', '8000']), ('worker', ['worker'])]:
    with (root / f'var/clinic-20261023-{name}.log').open('ab') as log:
        p = subprocess.Popen([str(root / '.venv/bin/python'), '-m', 'apps.compass', '--db', database, *args],
                             cwd=root, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    processes[name] = p.pid
    (root / f'var/clinic-20261023-{name}.pid').write_text(str(p.pid)+'\n')
state['processes'] = processes
active.write_text(json.dumps(state, ensure_ascii=False, indent=2)+'\n')
for attempt in range(50):
    try:
        with urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2) as response:
            health = json.load(response)
        break
    except (OSError, ValueError):
        time.sleep(.2)
else:
    raise RuntimeError('Updated server not ready')
assert health['status'] == 'ok', health
for pid in processes.values():
    os.kill(pid, 0)
(root / 'evidence/S53/runtime-health.json').write_text(json.dumps({'status':'PASS','database':'var/compass.sqlite3','health':health,'processes':processes},indent=2)+'\n')
print('PASS: server and worker updated on the same database; /healthz ok')
