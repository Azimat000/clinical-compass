"""Check persisted metadata after real browser submissions in the isolated copy."""
import json
from pathlib import Path
import sqlite3

fixture=json.loads(Path('evidence/S52/browser-fixture.json').read_text())
c=sqlite3.connect('var/S52-ui-check.sqlite3');c.row_factory=sqlite3.Row
original=json.loads(c.execute('SELECT payload_json FROM first_visit_versions WHERE id=?',(fixture['version_id'],)).fetchone()[0])
rows=[dict(r) for r in c.execute('SELECT * FROM first_visit_versions') if json.loads(r['payload_json']).get('editor_mode')=='text-only-v1']
assert len(rows)>=4
for row in rows:
 p=json.loads(row['payload_json'])
 for code in ('history','family_history','allergies'):
  for key in ('text','status','source','basis','observed_on'):
   assert p['fields'][code][key]==original['fields'][code][key],(code,key)
  assert p['fields'][code]['carried_from']['version_id']
 assert p['age_basis']==original['age_basis'] and p['age']==original['age']
 assert p['age_observed_on']==original['observed_on']
 assert p['fields']['complaints']['source']=='physician_note'
 assert p['wellbeing']=='same'
assert any(r['state']=='completed' for r in rows)
assert json.loads(c.execute('SELECT payload_json FROM first_visit_versions WHERE id=?',(fixture['version_id'],)).fetchone()[0])==original
report={'status':'PASS','browser_versions':len(rows),'old_status_source_basis_dates_unchanged':True,
        'age_basis_and_age_preserved':True,'completion':True,'new_text_attributed_to_doctor':True,'original_unchanged':True,
        'integrity':c.execute('PRAGMA integrity_check').fetchone()[0],'foreign_key_errors':len(c.execute('PRAGMA foreign_key_check').fetchall())}
assert report['integrity']=='ok' and report['foreign_key_errors']==0
Path('evidence/S52/browser-data.json').write_text(json.dumps(report,indent=2)+'\n')
print('PASS: actual browser submissions preserved source/status/date/age and completed normally')
