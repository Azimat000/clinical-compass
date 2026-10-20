"""Preserve a private synthetic v1 copy, then test v1 review alongside v2 import."""
from pathlib import Path
from contextlib import closing
import hashlib,json,re,secrets,sys,subprocess
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from apps.compass.backup import copy_database,readonly
from apps.compass.db import connect
from apps.compass.web import create_app
from apps.compass import extraction

source=ROOT/'var/longitudinal-20261020-final.sqlite3'
target=ROOT/'var/technical-r2-upgrade-accepted.sqlite3'
credentials=json.loads((ROOT/'var/longitudinal-20261020-final-credentials.json').read_text())
copy_database(source,target)
# The18 preserved imports happen to have empty v1 candidates. Add one explicit
# legacy candidate using the exact prior committed v1 source, only in this copy.
namespace={'__package__':'apps.compass','__name__':'apps.compass.legacy_extraction_probe'}
legacy_source=subprocess.check_output(['git','show','a17d1b6:apps/compass/extraction.py'],cwd=ROOT,text=True)
exec(compile(legacy_source,'a17d1b6:apps/compass/extraction.py','exec'),namespace)
with closing(connect(target)) as fixture_db:
 legacy_id=namespace['save_import'](fixture_db,{'id':credentials['doctor'],'role':'doctor'},'D01','35 лет. F41.1. Авиандр 10 мг.',secrets.token_hex(16))
with closing(readonly(target)) as db:
 original=[tuple(r) for r in db.execute('SELECT * FROM text_imports ORDER BY id')]
 assert len(original)==19 and all(json.loads(r[6])['version']=='literal-v1' for r in original)
 counts={t:db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('care_actions','clinical_entries','critical_events')}
app=create_app(target)
with closing(readonly(target)) as db:assert original==[tuple(r) for r in db.execute('SELECT * FROM text_imports ORDER BY id')]
client=app.test_client()
def token(response):return re.search(r'name="csrf" value="([^"]+)"',response.text).group(1)
assert client.post('/login',data={'csrf':token(client.get('/login')),'login':credentials['doctor'],'password':credentials['password']}).status_code==302
page=client.get('/patients/D01/imports');assert page.status_code==200 and 'literal-v1' in page.text
assert client.post('/patients/D01/imports',data={'csrf':token(page),'source_text':'Есть ли беременность? Сведения о возрасте отсутствуют.','request_key':secrets.token_hex(16)}).status_code==303
page=client.get('/patients/D01/imports');assert 'literal-v1' in page.text and 'literal-v2' in page.text
old=next(r for r in original if r[0]==legacy_id);candidate=json.loads(old[6])['candidates'][0]
assert client.post('/patients/D01/imports/'+old[0]+'/review',data={'csrf':token(page),'request_key':secrets.token_hex(16),'candidate_id':candidate['id'],'field':candidate['field'],'assertion':candidate['assertion'],'value':extraction.canonical(candidate['value']),'quote':candidate['quote'],'reason':'Сверка старого синтетического кандидата после обновления','disposition':'accept'}).status_code==303
with closing(readonly(target)) as db:
 assert all(tuple(db.execute('SELECT * FROM text_imports WHERE id=?',(r[0],)).fetchone())==r for r in original)
 assert counts=={t:db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in counts}
 assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 assert not db.execute('PRAGMA foreign_key_check').fetchall()
report={'status':'PASS','old_imports_preserved':18,'additional_controlled_v1_candidate_fixture':1,'old_version':'literal-v1','new_version':'literal-v2','old_candidate_review_accepted':True,'automatic_clinical_writes':0,'source_database_modified':False,'integrity':'ok','foreign_key_errors':0}
(ROOT/'evidence/audits/2026-10-20-technical-r2/upgrade.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(report))
