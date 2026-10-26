"""Separate synthetic copy for all browser mutations."""
import json
from pathlib import Path
import secrets
import sqlite3
from apps.compass import communication
from apps.compass.db import connect, now
path=Path('var/S54-ui-check.sqlite3')
a=sqlite3.connect('var/backups/S54-before-plan-tasks.sqlite3');b=sqlite3.connect(path);a.backup(b);a.close();b.close();path.chmod(0o600)
db=connect(path)
user=dict(db.execute("SELECT * FROM users WHERE id='m.sokolova'").fetchone())
relation=db.execute("SELECT r.*,p.user_id FROM care_relationships r JOIN patients p ON p.id=r.patient_id WHERE r.patient_id='P101' AND r.ends_at IS NULL").fetchone()
head=communication.current_action(db,'P101')
task=communication.schedule(db,user,'P101',dict(action_id=head['id'], request_key=secrets.token_hex(16), label='Проверка S54: выполнить рекомендацию врача', due_at=now(), reviewed='yes'))
future=communication.schedule(db,user,'P101',dict(action_id=head['id'], request_key=secrets.token_hex(16), label='Проверка S54: будущая рекомендация', due_at='2030-01-01T00:00:00+03:00', reviewed='yes'))
Path('var/S54-browser-fixture.json').write_text(json.dumps(dict(doctor_login=user['id'], patient_login=relation['user_id'], task=task, future=future),ensure_ascii=False)+'\n')
db.close()
print('PASS: separate synthetic fixture')
