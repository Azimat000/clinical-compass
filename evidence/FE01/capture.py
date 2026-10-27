"""Render incumbent screens in an isolated database; never use the live app factory."""
from pathlib import Path
import hashlib
import json
import re
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from apps.compass.web import create_app

target = ROOT / 'var/FE01-capture.sqlite3'
if not target.exists():
    with sqlite3.connect(f'file:{ROOT}/var/compass.sqlite3?mode=ro', uri=True) as source:
        with sqlite3.connect(target) as copy:
            source.backup(copy)
target.chmod(0o600)
app = create_app(target)
client = app.test_client()
login = client.get('/login').get_data(as_text=True)
csrf = re.search(r'name="csrf" value="([^"]+)"', login).group(1)
account = next(a for a in json.loads((ROOT/'var/clinic-20261026-accounts.json').read_text())['accounts'] if a['login'] == 'e.orlova')
response = client.post('/login', data={'csrf': csrf, 'login': account['login'], 'password': account['password']})
assert response.status_code in (302, 303), response.status_code
out = ROOT/'docs/design/prototypes/FE01/baseline'
out.mkdir(parents=True, exist_ok=True)
manifest = []
for name, route in [('signals', '/'), ('diagnosis', '/demo/P201'), ('plan', '/patients/P201/decisions')]:
    response = client.get(route)
    assert response.status_code == 200, (route, response.status_code)
    html = response.get_data(as_text=True)
    html = re.sub(r'(name="(?:csrf|request_key)" value=")[^"]*', r'\1', html)
    html = '\n'.join(line.rstrip() for line in html.splitlines()).rstrip()+'\n'
    (out/f'{name}.html').write_text(html)
    manifest.append({'screen': name, 'route': route, 'status': 200, 'sha256': hashlib.sha256(html.encode()).hexdigest(), 'redacted': ['csrf', 'request_key']})
(ROOT/'evidence/FE01/capture.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
print('PASS: 3 incumbent screens, isolated database; credentials omitted')
