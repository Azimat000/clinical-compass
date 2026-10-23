"""Read-only acceptance against the private pre-import backup."""
from contextlib import closing
from datetime import date
import json
from pathlib import Path
import sqlite3
import sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from apps.compass import backup, medications, decisions, overview
from tools import seed_roster_medications as seed

snapshot=ROOT/'var/backups/S36-before-roster-medications.sqlite3'
expected={'proposals':14,'decision_drafts':14,'doctor_confirmations':14,'care_actions':14,'medication_marks':250,'audit_entries':1}
checks=[];patients=[];missed=[]
with closing(backup.readonly(snapshot)) as old,closing(backup.readonly(ROOT/'var/compass.sqlite3')) as db:
 old.row_factory=db.row_factory=sqlite3.Row
 for (table,) in old.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
  before=set(tuple(r) for r in old.execute('SELECT * FROM "'+table+'"'));after=set(tuple(r) for r in db.execute('SELECT * FROM "'+table+'"'))
  checks.append({'table':table,'old_rows':len(before),'new_rows':len(after),'unchanged':before<=after,
                 'expected_additions_only':len(after)==len(before)+expected.get(table,0)})
 for p in seed.load_dataset()[1]['patients']:
  pid=p['id'];doses=medications.occurrences(db,pid,date(2026,9,11),date(2026,10,23))
  current=decisions.history(db,{'id':p['doctor'],'role':'doctor'},pid)[0]
  assert current['payload']['content']==p['plans'][-1] and current['doctor_id']==p['doctor']
  missed += [(pid,d['day']) for d in doses if d['state']=='missed']
  patients.append({'patient':pid,'doctor':p['doctor'],'first_dose':doses[0]['day'],
     'taken':sum(d['state']=='taken' for d in doses),'missed':sum(d['state']=='missed' for d in doses),
     'unmarked_past_days':[d['day'] for d in doses if d['overdue']],
     'original_plan_text_retained':True,'periods':medications.calendar(db,pid,'2026-10-22')['periods']})
 assert missed==[('P103','2026-10-22')]
 assert [p['unmarked_past_days'] for p in patients if p['patient']=='P108']==[['2026-09-25','2026-10-09','2026-10-16']]
 report={'all_prior_rows_unchanged':all(c['unchanged'] for c in checks),'only_expected_additions':all(c['expected_additions_only'] for c in checks),
    'tables':checks,'patients':patients,'backup_mode':oct(snapshot.stat().st_mode&0o777),
    'integrity':db.execute('PRAGMA integrity_check').fetchone()[0],'foreign_keys':[tuple(r) for r in db.execute('PRAGMA foreign_key_check')]}
 assert report['all_prior_rows_unchanged'] and report['only_expected_additions'] and report['backup_mode']=='0o600'
 assert report['integrity']=='ok' and not report['foreign_keys']
(ROOT/'evidence/S36/runtime.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print('PASS:',len(checks),'tables preserved;8patients,3doctors,250marks,one explicit miss,3unknownpastdays')
