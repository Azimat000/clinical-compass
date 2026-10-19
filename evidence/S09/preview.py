"""Create a separate synthetic browser preview; never touches the working database."""
import secrets
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'apps/tests')]
from apps.compass.web import create_app
from apps.compass.db import connect
from apps.compass.repository import seed_demo
from apps.compass import decisions
from test_access import setup_identities
path=ROOT/'var/s09-ui.sqlite3'
if path.exists():raise SystemExit('Refusing to overwrite preview database')
create_app(path);db=connect(path);seed_demo(db);setup_identities(db)
db.execute("INSERT INTO care_relationships(id,patient_id,doctor_id,starts_at) VALUES('preview-link','D01','doc-a','2026-01-01T00:00:00+00:00')")
for category,urgency in [('mandatory','urgent'),('desirable','planned')]:
 pid=decisions.draft(db,{'id':'doc-a','role':'doctor'},'D01',{
 'kind':'referral','content':'Вымышленный проект направления для проверки интерфейса',
 'basis':'Синтетический визит, клиническая проверка не проводилась','uncertainties':'Оценка тяжести требует врача',
 'request_key':secrets.token_hex(16),'routing_reference':'routing-reference-v1','route_category':category,'route_urgency':urgency,
 'route_specialty':'Терапевт (вымышленный)','route_severity':'Синтетические сведения; тяжесть неизвестна',
 'route_population':'Взрослый синтетический профиль D01','route_population_status':'known','route_age_years':'35',
 'route_evidence':'КР457_3 §5, указатель для врача; применимость не подтверждена клинически',
 'route_unavailable':'Вымышленный резервный порядок; внешнего канала в прототипе нет'})
 if category=='mandatory':
  version=db.execute('SELECT version FROM proposals WHERE id=?',(pid,)).fetchone()[0]
  decisions.confirm(db,{'id':'doc-a','role':'doctor'},'D01',pid,{'version':str(version),'decision':'approved','rationale':'Проверка только синтетического интерфейса','reviewed':'yes'})
db.close()
print('Synthetic preview ready')
