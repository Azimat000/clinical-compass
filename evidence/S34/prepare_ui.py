"""Disposable synthetic questionnaire histories. Never runs against the service database."""
from datetime import date
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'apps/tests')]
from test_access import setup_identities
from apps.compass import access, assessments
from apps.compass.db import connect, migrate
from apps.compass.repository import seed_demo
from tools.replace_roster import fictional_day, key

path = ROOT / 'var/S34-ui-check.sqlite3'
if path.exists():
    raise SystemExit('Fixture already exists; choose a fresh file instead of overwriting it')
db = connect(path)
migrate(db); seed_demo(db); setup_identities(db); assessments.install_form(db)
access.accept_invite(db, 'pat-a', access.invite(db, 'doc-a', 'D01'))
db.execute("UPDATE care_relationships SET starts_at='2026-09-01T00:00:00+00:00'")
db.execute("UPDATE patients SET created_at='2026-09-01T00:00:00+00:00'")
db.execute("UPDATE users SET display_name='Марина Соколова' WHERE id='doc-a'")
doctor = {'id':'doc-a','role':'doctor'}; patient = {'id':'pat-a','role':'patient'}
for form in assessments.definitions():
    for i, day in enumerate(['2026-10-02','2026-10-09','2026-10-16','2026-10-22']):
        with fictional_day(date.fromisoformat(day), 12):
            request = assessments.assign(db, doctor, 'D01', {'assignment_key':key(), 'form_version_id':form['id'],
                'age_status':'known','age_years':'35','age_basis':'Вымышленный профиль для проверки интерфейса.'})
            values = {'form_version_id':form['id'], **{f'answer_{n}':str(max(0, 3-i)) for n in range(1,len(form['items'])+1)}}
            if i == 2 and form['code']=='GAD-7': values['answer_3']=''
            assessments.submit(db, patient, request, values)
Path(ROOT/'evidence/S34/fixture.json').write_text(json.dumps({'database':'var/S34-ui-check.sqlite3','synthetic':True,
    'simulated_dates':True,'clinical_review':False,'real_user_trial':False,'forms':[f['code'] for f in assessments.definitions()],
    'history_rows':12,'not_applied_to_active_service':True},ensure_ascii=False,indent=2)+'\n')
db.close()
print('Prepared disposable S34 fixture')
