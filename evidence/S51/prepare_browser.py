"""Prepare a synthetic browser fixture in a separate database, never the live service."""
import json
from pathlib import Path
import secrets
import sqlite3
from apps.compass import first_visits, records
from apps.compass.db import connect

path=Path('var/S51-ui-check.sqlite3')
a=sqlite3.connect('var/backups/S51-before-visit-history.sqlite3');b=sqlite3.connect(path);a.backup(b);a.close();b.close();path.chmod(0o600)
db=connect(path)
user=dict(db.execute("SELECT * FROM users WHERE id='m.sokolova'").fetchone())
values={'note_schema':first_visits.NOTE_SCHEMA, 'request_key':secrets.token_hex(16),'base_revision':'0',
        'observed_on':records.today().isoformat(),'visit_kind':'repeat','state':'completed','age_source':'patient',
        'wellbeing':'worse','history_status':'auto','history_text':'Синтетический анамнез S51',
        'family_history_status':'conflicting','family_history_text':'Синтетические противоречивые сведения',
        'mental_status_status':'auto','mental_status_text':'Прежний статус S51 — не переносить',
        'complaints_status':'auto','complaints_text':'Прежние жалобы S51 — не переносить'}
visit=first_visits.save(db,user,'P101','new',values)
item=next(i for i in first_visits.history(db,user,'P101') if i['visit_id']==visit)
Path('evidence/S51/browser-fixture.json').write_text(json.dumps({'visit_id':visit,'version_id':item['id']},indent=2)+'\n')
db.close()
print('PASS: fixture saved only in var/S51-ui-check.sqlite3')
