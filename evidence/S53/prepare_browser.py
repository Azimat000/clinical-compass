"""Build a separate local copy with a synthetic linked message; never write to the live database."""
import json
from pathlib import Path
import secrets
import sqlite3
from apps.compass import communication
from apps.compass.db import connect, now

path=Path('var/S53-ui-check.sqlite3')
a=sqlite3.connect('var/backups/S53-before-messages.sqlite3');b=sqlite3.connect(path);a.backup(b);a.close();b.close();path.chmod(0o600)
db=connect(path)
user=dict(db.execute("SELECT * FROM users WHERE id='m.sokolova'").fetchone())
relation=db.execute("SELECT r.*,p.user_id FROM care_relationships r JOIN patients p ON p.id=r.patient_id WHERE r.patient_id='P101' AND r.ends_at IS NULL").fetchone()
head=communication.current_action(db,'P101')
task=communication.schedule(db,user,'P101',{'action_id':head['id'],'request_key':secrets.token_hex(16),'label':'Контекст пункта S53 <проверка>','due_at':now(),'reviewed':'yes'})
# schedule returns an ID; read it independently for the fixture.
task_id=db.execute("SELECT id FROM adherence_tasks WHERE label='Контекст пункта S53 <проверка>'").fetchone()[0]
communication.send(db,user,'P101',{'request_key':secrets.token_hex(16),'body':'Синтетическое сообщение S53 с сохранённым контекстом','task_id':task_id})
Path('var/S53-browser-fixture.json').write_text(json.dumps({'doctor_login':user['id'],'patient_login':relation['user_id']},ensure_ascii=False)+'\n')
db.close()
print('PASS: separate synthetic fixture')
