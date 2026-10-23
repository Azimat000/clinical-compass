"""Verify all pre-existing rows, exact additions and all active physician series read-only."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from apps.compass import assessments, backup, follow_up
from tools import seed_roster_questionnaires as seed
snapshot=ROOT/'var/backups/S35-before-roster-questionnaires.sqlite3'
expected={'assessment_requests':48,'assessments':48,'assessment_results':48,'audit_entries':1}
checks=[];series=[]
with closing(backup.readonly(snapshot)) as old, closing(backup.readonly(ROOT/'var/compass.sqlite3')) as db:
 old.row_factory=db.row_factory=sqlite3.Row
 for row in old.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
  table=row[0];before=[tuple(x) for x in old.execute('SELECT * FROM "'+table+'"')];after=[tuple(x) for x in db.execute('SELECT * FROM "'+table+'"')]
  checks.append({'table':table,'old_rows':len(before),'new_rows':len(after),'old_rows_unchanged':set(before)<=set(after),
     'expected_additions_only':len(after)==len(before)+expected.get(table,0) and set(before)<=set(after)})
 data,roster=seed.load_dataset()
 for p in roster['patients']:
  user={'id':p['doctor'],'role':'doctor'};history=assessments.history(db,user,p['id'])
  for index,(key,code) in enumerate([('phq','PHQ-9'),('gad','GAD-7')]):
   rows=sorted([r for r in history if r['form']['code']==code],key=lambda r:r['observed_on'])
   actual=[next(iter(r['scores'].values())) if r['scores'] is not None else None for r in rows]
   expect=[r[index] for r in data['patients'][p['id']]['expected']]
   assert actual==expect,(p['id'],code,actual,expect)
   assert [r['answers'] for r in rows]==data['patients'][p['id']][key]
   group=assessments.trends(rows)[0]
   series.append({'patient_id':p['id'],'code':code,'values':actual,'points':len(group['series'][0]['points']),
      'segments':[len(s) for s in group['series'][0]['segments']],'matches_authored_answers':True})
  summary=follow_up.view(db,user,p['id'],{'start':'2026-09-11','end':'2026-10-22'})
  assert len(summary['assessment_trends'])==3
 report={'all_prior_rows_unchanged':all(c['old_rows_unchanged'] for c in checks),
   'only_expected_additions':all(c['expected_additions_only'] for c in checks),'checks':checks,'series':series,
   'backup_mode':oct(snapshot.stat().st_mode&0o777),'integrity':db.execute('PRAGMA integrity_check').fetchone()[0],
   'foreign_keys':[tuple(r) for r in db.execute('PRAGMA foreign_key_check')]}
 assert report['all_prior_rows_unchanged'] and report['only_expected_additions'] and report['backup_mode']=='0o600'
 assert report['integrity']=='ok' and not report['foreign_keys']
(ROOT/'evidence/S35/runtime.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print('PASS:',len(checks),'tables preserved,48new results,16new series and8follow-up summaries')
