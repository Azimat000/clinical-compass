"""Create a new, explicitly synthetic browser fixture; refuse existing paths."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'apps/tests'))
from test_access import setup_identities
from test_clinical_rules import ClinicalRuleTests
from test_decisions import DecisionTests
from apps.compass.db import connect,migrate
from apps.compass.repository import seed_demo
from apps.compass import access,records,clinical_rules,decisions,events

def main():
    path=Path(sys.argv[1] if len(sys.argv)>1 else 'var/s13-final.sqlite3')
    if path.exists(): raise SystemExit('Existing path refused; choose a new synthetic fixture database')
    db=connect(path);migrate(db);seed_demo(db);setup_identities(db)
    access.accept_invite(db,'pat-a',access.invite(db,'doc-a','D01'))
    access.accept_invite(db,'pat-b',access.invite(db,'doc-a','D02'))
    db.execute("UPDATE users SET display_name='Врач демо' WHERE id='doc-a'")
    db.execute("UPDATE users SET display_name='Пациент демо' WHERE id='pat-a'")
    doc={'id':'doc-a','role':'doctor'};pat={'id':'pat-a','role':'patient'}
    records.save(db,pat,'D01','self_report',{'request_key':'a'*32,'observed_on':records.today().isoformat(),'wellbeing':'better','summary':'Синтетическая запись для проверки интерфейса S13.'})
    clinical_rules.save_context(db,doc,'D01',ClinicalRuleTests.context_form(None))
    records.save(db,pat,'D01','self_report',ClinicalRuleTests.form(None))
    for category in ['mandatory','desirable']:
        decisions.draft(db,doc,'D01',DecisionTests.values(None,kind='referral',route_category=category))
    while events.process_one(db):pass
    assert db.execute('SELECT count(*) FROM critical_events').fetchone()[0]==1
    db.close();print('PASS: separate synthetic browser database created')
if __name__=='__main__':main()
