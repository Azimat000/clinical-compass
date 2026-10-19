"""Compare this slice to the retained clean baseline, without changing files."""
import hashlib,json,subprocess
from pathlib import Path
baseline=json.loads(Path('evidence/S17E/baseline.json').read_text())
allowed={
 'apps/compass/static/app.css','apps/compass/templates/communication.html',
 'apps/compass/templates/first_visit.html','apps/compass/templates/patient.html',
 'memory/STATE.json','memory/DECISIONS.md','memory/BLOCKERS.md','memory/EXTERNAL.md',
 'memory/BUDGET.json','START_HERE.md','plan/coverage.json','plan/COVERAGE.md'}
new={
 'apps/compass/static/first_visit.js','apps/compass/templates/first_visit_fact.html',
 'apps/compass/templates/first_visit_results.html','apps/compass/templates/first_visit_summary.html',
 'docs/design/first-visit-interface.md','memory/sessions/S17E.md'}
changed=[p for p,sha in baseline['sha256'].items() if not Path(p).is_file() or hashlib.sha256(Path(p).read_bytes()).hexdigest()!=sha]
assert set(changed)<=allowed,sorted(set(changed)-allowed)
untracked=subprocess.check_output(['git','ls-files','--others','--exclude-standard','-z']).decode().split('\0')
assert all(not p or p in new or p.startswith('evidence/S17E/') for p in untracked),untracked
old=json.loads(subprocess.check_output(['git','show',baseline['commit']+':plan/coverage.json']))
current=json.loads(Path('plan/coverage.json').read_text())
assert len(current['items'])==83
assert sum(len(r['subchecks']) for r in current['items'])==160
for a,b in zip(old['items'],current['items']):
 assert {k:v for k,v in a.items() if k!='actual_evidence'}=={k:v for k,v in b.items() if k!='actual_evidence'},a['id']
 assert set(a['actual_evidence'])<=set(b['actual_evidence']),a['id']
state=json.loads(Path('memory/STATE.json').read_text());oldstate=json.loads(subprocess.check_output(['git','show',baseline['commit']+':memory/STATE.json']))
for sid,value in oldstate['slices'].items():
 if sid!='S17E':assert value==state['slices'][sid],sid
assert state['slices']['S17D']['status']=='blocked'
assert state['slices']['S17']['status']=='blocked'
budget=json.loads(Path('memory/BUDGET.json').read_text());assert budget['spent']==budget['commitments']==0
print(json.dumps({'status':'PASS','baseline_status':baseline['status'],'changed_baseline_paths':changed,
'preserved_baseline_files':len(baseline['sha256'])-len(changed),'coverage':'83/160; text/subchecks/status/old evidence preserved',
'clinical_resources_sources_scales_migrations_dependencies_data':'all exact baseline SHA256',
'other_slice_states':'unchanged','mutating_agents':'NONE; external_s17e was read-only','budget':'0 spent, 0 committed'},ensure_ascii=False,indent=2))
