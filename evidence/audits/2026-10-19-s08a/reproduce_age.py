import sys,tempfile,secrets,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT),str(ROOT/'apps/tests')]
from test_access import setup_identities,login,csrf
from apps.compass.db import connect
from apps.compass.repository import seed_demo
from apps.compass import access,assessments,records
from apps.compass.web import create_app
out={}
with tempfile.TemporaryDirectory() as t:
 path=Path(t)/'audit.sqlite3';app=create_app(path);db=connect(path);seed_demo(db);setup_identities(db)
 access.accept_invite(db,'pat-a',access.invite(db,'doc-a','D01'))
 client=app.test_client();login(client,'doc-a')
 def attempt():
  before=db.execute('SELECT count(*) FROM assessment_requests').fetchone()[0]
  res=client.post('/patients/D01/assessment-requests',data={'csrf':csrf(client),'assignment_key':secrets.token_hex(16),'form_version_id':assessments.definition()['id'],'age_status':'known','age_years':'35','age_basis':'Новый врачебный источник в синтетической проверке'})
  return {'http_status':res.status_code,'created_requests':db.execute('SELECT count(*) FROM assessment_requests').fetchone()[0]-before}
 db.execute("UPDATE patients SET age_status='conflicting' WHERE id='D01'")
 records.save(db,{'id':'doc-a','role':'doctor'},'D01','visit',{'request_key':secrets.token_hex(16),'observed_on':records.today().isoformat(),'age_status':'known','age_years':'35','summary':'Новый сверенный возраст, прежнее противоречие разобрано'})
 out['initial_conflict_after_new_doctor_record']=attempt()
 db.execute("UPDATE patients SET age_status='known',age_years=NULL,birth_date='2010-01-01' WHERE id='D01'")
 out['birth_date_2010_vs_form_age_35']=attempt()
 print(json.dumps(out,ensure_ascii=False,indent=2))
