"""Synthetic display fixture for unchanged old rules; no new clinical activation."""
import sys
sys.path.insert(0,'.')
sys.path.insert(0,'apps/tests')
from test_clinical_rules import ClinicalRuleTests
from test_decisions import DecisionTests
from apps.compass import events,decisions,records
from apps.compass.db import connect,now
x=connect(sys.argv[1]);case=ClinicalRuleTests();case.db=x
case.doc={'id':'doc-a','role':'doctor'};case.pat={'id':'pat-a','role':'patient'}
x.execute("INSERT INTO care_relationships VALUES('rel','D01','doc-a',?,NULL)",(now(),))
x.execute("UPDATE patients SET age_status='known',age_years=19,birth_date=NULL,created_at=? WHERE id='D01'",(records.today().isoformat(),))
case.context();case.save()
while events.process_one(x):pass
for category in ('mandatory','desirable'):
    values=DecisionTests().values(kind='referral',route_category=category,route_age_years='19')
    proposal=decisions.draft(x,case.doc,'D01',values)
    if category=='desirable':
        decisions.confirm(x,case.doc,'D01',proposal,{'decision':'approved','version':'2','reviewed':'yes','rationale':'Синтетическая проверка отображения'})
assert x.execute('SELECT count(*) FROM critical_events').fetchone()[0]==1
x.close()
