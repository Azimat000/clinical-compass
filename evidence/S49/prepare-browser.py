"""Create a private local copy; synthetic fixture writes stay out of the working DB."""
from pathlib import Path
import json,secrets,sqlite3,subprocess
from apps.compass import first_visits,records
from apps.compass.db import connect
copy=Path('var/S49-ui-check.sqlite3')
with sqlite3.connect('var/compass.sqlite3') as a,sqlite3.connect(copy) as b:a.backup(b)
copy.chmod(0o600)
db=connect(copy);doctor={'id':'m.sokolova','role':'doctor'}
values={'request_key':secrets.token_hex(16),'base_revision':'0','state':'draft','observed_on':records.today().isoformat(),
        'visit_kind':'repeat','not_collected':'yes','age_source':'patient','action_draft':'Синтетическое действие S49',
        'documented_facts':'Синтетические сведения А S49 <b>без исполнения</b>','document_basis':'Синтетический документ А, автор А, 01.10.2026'}
visit=first_visits.save(db,doctor,'P101','new',values)
a=first_visits.history(db,doctor,'P101')[0]
values.update(request_key=secrets.token_hex(16),base_revision='1',documented_facts='Синтетические сведения Б S49',document_basis='Синтетический документ Б, автор Б, 02.10.2026')
first_visits.save(db,doctor,'P101',visit,values);b=first_visits.history(db,doctor,'P101')[0]
Path('evidence/S49/browser-fixture.json').write_text(json.dumps({'visit_id':visit,'version_ids':[a['id'],b['id']]},indent=2)+'\n');db.close()
with open('var/S49-ui-server.log','ab') as log:
 p=subprocess.Popen(['.venv/bin/python','-m','apps.compass','--db',str(copy.resolve()),'serve','--port','8049'],stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
Path('var/S49-ui-server.pid').write_text(str(p.pid))
print('Copy0600; 2 synthetic fixture versions; server8049 started')
