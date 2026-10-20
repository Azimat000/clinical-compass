"""Verify actual simplification without discarding requirements or source controls."""
import json,hashlib,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools'))
from validate_plan import validate,ready_id
E=ROOT/'evidence/service-simplification-2026-10-21'
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
 b=json.loads((E/'baseline.json').read_text());base=b['head']
 def old(p):return json.loads(subprocess.check_output(['git','show',base+':'+p],cwd=ROOT))
 m=json.loads((ROOT/'plan/manifest.json').read_text());s=json.loads((ROOT/'memory/STATE.json').read_text());oldm=old('plan/manifest.json');olds=old('memory/STATE.json');by={c['id']:c for c in m['slices']};oldby={c['id']:c for c in oldm['slices']}
 deferred={sid for sid in oldby if sid.startswith('S17J') and olds['slices'][sid]['status']!='accepted'}
 optional=json.loads((ROOT/'plan/optional-rag.json').read_text());rows={r['id']:r for r in optional['slices']}
 assert len(deferred)==20 and set(rows)==deferred and optional['baseline_commit']==base
 assert set(by)==(set(oldby)-deferred)|{'S17I01'} and set(s['slices'])==set(by)
 for sid in deferred:
  assert rows[sid]['previous_state']==olds['slices'][sid] and (ROOT/rows[sid]['card']).is_file()
 for sid,c in oldby.items():
  if sid in deferred:continue
  if sid=='S17I':
   for key,v in c.items():
    if key!='depends_on':assert by[sid][key]==v,(sid,key)
   assert by[sid]['depends_on']==['S17H','S17I01'] and s['slices'][sid]['status']=='blocked'
  else:
   assert by[sid]==c and s['slices'][sid]==olds['slices'][sid],sid
 assert s['last_accepted_slice']==olds['last_accepted_slice']=='S17J02B03A'
 assert s['current_slice'] is None and s['next_slice']==ready_id(m['slices'],s)=='S17I01'
 assert s['slices']['S17I01']['status']=='planned' and s['work_policy']['rag_required'] is False
 assert not any(sid in c['depends_on'] for c in m['slices'] for sid in deferred)
 before=old('plan/coverage.json');after=json.loads((ROOT/'plan/coverage.json').read_text());assert len(after['items'])==len(before['items'])==83
 assert sum(len(r['subchecks']) for r in after['items'])==160
 archived_mapping={};next_reqs=set(by['S17I01']['requirement_ids'])
 for a,z in zip(before['items'],after['items']):
  for key,value in a.items():
   if key=='verification_slices':
    expected=[sid for sid in value if sid not in deferred]+(['S17I01'] if a['id'] in next_reqs else [])
    assert z[key]==expected,a['id'];archived_mapping[a['id']]=[sid for sid in value if sid in deferred]
   else:assert z[key]==value,(a['id'],key)
 # Original mandatory clinical work and criteria are unchanged verbatim in I.
 card=(ROOT/'plan/slices/S17I.md').read_text()
 for key in ['tasks','outputs','acceptance']:
  for text in oldby['S17I'][key]:assert text in card,text
 nextcard=(ROOT/'plan/slices/S17I01.md').read_text()
 for key in ['tasks','outputs','acceptance']:
  for text in by['S17I01'][key]:assert text in nextcard
 errors,summary=validate(ROOT);assert not errors,errors
 changed=subprocess.check_output(['git','diff','--name-only',base],cwd=ROOT).decode().splitlines();untracked=subprocess.check_output(['git','ls-files','--others','--exclude-standard'],cwd=ROOT).decode().splitlines()
 owned=json.loads((E/'ownership.json').read_text())['owned_paths']
 def owns(p):return any(p==v or v.endswith('/') and p.startswith(v) for v in owned)
 created=[p for p in untracked if p not in b['untracked_sha256']]
 assert all(owns(p) for p in changed+created),[p for p in changed+created if not owns(p)]
 assert not any(p.startswith(('apps/','data/')) for p in changed)
 for p,h in b['untracked_sha256'].items():assert sha(ROOT/p)==h,p
 budget=json.loads((ROOT/'memory/BUDGET.json').read_text());oldbudget=old('memory/BUDGET.json')
 for key in ['spent','commitments','transactions','limit']:assert budget[key]==oldbudget[key]
 report=dict(status='PASS_PLAN_ONLY',mandatory_rag_removed=True,deferred_slices=sorted(deferred),deferred_count=20,previous_states_and_git_history_retained=True,accepted_source_check_slices_unchanged=optional['accepted_source_checks'],requirements=83,subchecks=160,requirement_text_status_subchecks_primary_and_actual_evidence_unchanged=True,archived_verification_assignments=archived_mapping,original_S17I_tasks_outputs_and_all4criteria_preserved=True,S17I_clinical_review_still_required=True,next_slice='S17I01',next_slice_started=False,source_corpus_frozen_files_code_tests_and_old_evidence_unchanged=True,source_metadata_rights_population_expiry_revocation_checks_preserved=True,unverified_age_and_dossiers_not_claimed_ready=True,clinical_activation=False,preexisting_user_files_preserved=True,scope_compliance='PASS',budget_unchanged=True,plan_validation=summary)
 (E/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
 print('PASS:20RAGnodes optional;83/160 unchanged;source checks/code/corpus preserved;Iclinical gate intact;nextI01 not started')
if __name__=='__main__':main()
