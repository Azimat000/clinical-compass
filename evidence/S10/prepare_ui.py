"""Disposable local synthetic UI fixture, no working database modifications."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'apps/tests')]
from apps.compass.db import connect,migrate,now
from apps.compass.repository import seed_demo
from apps.compass import clinical_rules as rules, records
from test_access import setup_identities
p=ROOT/'var/s10-ui.sqlite3'
assert not p.exists(), 'Use a fresh fixture path; never overwrite'
db=connect(p);migrate(db);seed_demo(db);setup_identities(db)
db.execute("INSERT INTO care_relationships VALUES('s10-rel','D01','doc-a',?,NULL)",(now(),))
rules.save_context(db,{'id':'doc-a','role':'doctor'},'D01',{
 'request_key':'c'*32,'observed_on':records.today().isoformat(),
 'gad_status':'present','severity':'nonsevere','suicide_risk':'denied','psychiatric_comorbidity':'denied',
 'treatment_resistance':'denied','aviandr_prescription':'active','clinical_basis':'Synthetic source F41.1',
 'prescription_basis':'Synthetic documented existing prescription'})
db.close()
