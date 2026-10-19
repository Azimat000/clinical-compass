"""Create a populated database using the baseline code, then upgrade with current code."""
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from apps.compass.db import connect,migrate
from apps.compass import assessments,access
from apps.compass.web import create_app

BASE = json.loads((ROOT/'evidence/S08B/baseline.json').read_text())['head']
with tempfile.TemporaryDirectory() as tmp:
    folder=Path(tmp);old_code=folder/'old';old_code.mkdir();path=folder/'upgrade.sqlite3'
    archive=subprocess.check_output(['git','archive',BASE],cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:tar.extractall(old_code,filter='data')
    script='''
import sys,secrets
sys.path.insert(0,'apps/tests')
from apps.compass.db import connect,migrate
from apps.compass.repository import seed_demo
from apps.compass import access,records,assessments,decisions
from test_access import setup_identities
path=sys.argv[1];db=connect(path);migrate(db);seed_demo(db);setup_identities(db)
access.accept_invite(db,'pat-a',access.invite(db,'doc-a','D01'));assessments.install_form(db)
actor={'id':'doc-a','role':'doctor'}
records.save(db,actor,'D01','visit',{'request_key':secrets.token_hex(16),'observed_on':records.today().isoformat(),'adverse_events_status':'known','adverse_events_text':'Синтетическое НЯ'})
values={'assignment_key':secrets.token_hex(16),'form_version_id':assessments.definition()['id'],'age_status':'known','age_years':'35','age_basis':'Вымышленный профиль'}
rid=assessments.assign(db,actor,'D01',values)
assessments.submit(db,actor,rid,{'form_version_id':values['form_version_id'],**{f'answer_{i}':'1' for i in range(1,43)}})
values['assignment_key']=secrets.token_hex(16);assessments.assign(db,actor,'D01',values)
pid=decisions.draft(db,actor,'D01',{'request_key':secrets.token_hex(16),'kind':'plan_change','content':'Вымышленный план','basis':'Синтетический визит','uncertainties':'Неизвестные данные'})
version=db.execute('SELECT version FROM proposals WHERE id=?',(pid,)).fetchone()[0]
decisions.confirm(db,actor,'D01',pid,{'version':str(version),'decision':'approved','reviewed':'yes','rationale':'Синтетическая проверка'})
db.close()
'''
    subprocess.run([sys.executable,'-c',script,str(path)],cwd=old_code,check=True)
    db=connect(path)
    tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name!='schema_migrations'")]
    before={t:sorted([list(r) for r in db.execute('SELECT * FROM "'+t+'"')],key=str) for t in tables}
    migrate(db)
    for table,rows in before.items():assert rows==sorted([list(r) for r in db.execute('SELECT * FROM "'+table+'"')],key=str),table
    assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    assert not db.execute('PRAGMA foreign_key_check').fetchall()
    task=db.execute('SELECT q.id FROM assessment_requests q WHERE NOT EXISTS (SELECT 1 FROM assessment_results r WHERE r.request_id=q.id)').fetchone()[0]
    try:
        assessments.submit(db,{'id':'pat-a','role':'patient'},task,{'form_version_id':assessments.definition()['id'],**{f'answer_{i}':'1' for i in range(1,43)}})
        raise AssertionError('Legacy offer accepted')
    except assessments.AssessmentError as error:assert error.status==409
    assert db.execute('SELECT count(*) FROM assessment_results').fetchone()[0]==1
    assert len(assessments.history(db,{'id':'pat-a','role':'patient'},'D01'))==1
    assert db.execute('SELECT count(*) FROM care_actions').fetchone()[0]==1
    print(json.dumps({'baseline':BASE,'old_tables_preserved':len(tables),'old_nonempty_tables':{t:len(r) for t,r in before.items() if r},'legacy_offer':'rejected 409; new offer required','old_result_and_receipt':'preserved','old_care_action':'preserved','integrity':'ok'},ensure_ascii=False,indent=2))
    db.close()
