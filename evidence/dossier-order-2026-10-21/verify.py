"""Independent comparison of the approved proposal, actual plan and pre-work state."""
import hashlib,json,subprocess,sys
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools'))
from validate_plan import validate,ready_id
E=ROOT/'evidence/dossier-order-2026-10-21'
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
 baseline=json.loads((E/'baseline.json').read_text());base=baseline['head']
 def old_json(p):return json.loads(subprocess.check_output(['git','show',base+':'+p],cwd=ROOT))
 proposal=json.loads((ROOT/'evidence/S17J02B03B/plan-amendment-proposal.json').read_text());approval=json.loads((E/'approval.json').read_text())
 assert approval['answer']=='Разрешить подготовку досье' and approval['proposal_sha256']==sha(ROOT/approval['approved_proposal'])
 before=old_json('plan/manifest.json');current=json.loads((ROOT/'plan/manifest.json').read_text());old={c['id']:c for c in before['slices']};new={c['id']:c for c in current['slices']};expected={c['id']:c for c in proposal['new_slices']}
 assert set(new)-set(old)==set(expected) and len(expected)==9 and len(new)==len(current['slices'])
 for sid,c in expected.items():assert new[sid]==c,sid
 dependencies={c['id']:c for c in proposal['existing_dependency_changes']}
 for sid,c in old.items():
  for k,v in c.items():
   if sid in dependencies and k=='depends_on':assert new[sid][k]==dependencies[sid]['after']
   else:assert new[sid][k]==v,(sid,k)
 assert new['S17J02C']['depends_on'][0]=='S17J02B'
 meds=json.loads((ROOT/'data/retrieval/planned-medications.json').read_text())['medications'];section_count=0
 for (sid,c),med in zip(expected.items(),meds):
  card=(ROOT/('plan/slices/'+sid+'.md')).read_text()
  for section in med['required_sections']:assert '- '+section+'\n' in card;section_count+=1
  for target in med['registration_targets']:
   for key in ['trade_name','registration','form','route','official_url','status']:assert target[key] in card,(sid,key)
  for key in ['tasks','outputs','acceptance']:
   for entry in c[key]:assert entry in card,(sid,key)
  assert 'STATUS: PLANNED. Не начат.' in card and c['depends_on']==['S17J02B03A']
 assert section_count==90
 old_cover=old_json('plan/coverage.json');coverage=json.loads((ROOT/'plan/coverage.json').read_text());assert len(coverage['items'])==len(old_cover['items'])==83
 assert sum(len(c['subchecks']) for c in coverage['items'])==160
 for a,b in zip(old_cover['items'],coverage['items']):
  for key in a:
   if key=='verification_slices':
    additions=[sid for sid,c in expected.items() if a['id'] in c['requirement_ids']]
    assert b[key]==a[key]+additions,(a['id'],key)
   else:assert b[key]==a[key],(a['id'],key)
 state=json.loads((ROOT/'memory/STATE.json').read_text());old_state=old_json('memory/STATE.json')
 assert state['last_accepted_slice']==old_state['last_accepted_slice']=='S17J02B03A'
 for sid,entry in old_state['slices'].items():
  for key,value in entry.items():
   if sid=='S17J02B03B' and key=='reason':assert state['slices'][sid]['status']=='blocked'
   else:assert state['slices'][sid][key]==value,(sid,key)
 for sid in expected:assert state['slices'][sid]==dict(status='planned',commit_ref=None,handoff=expected[sid]['handoff_path'],reason=None)
 assert state['current_slice'] is None and state['next_slice']==ready_id(current['slices'],state)=='S17J02C01'
 assert state['pending_plan_amendment']['status']=='approved_and_applied' and state['pending_plan_amendment']['applied'] is True
 assert state['latest_coverage_core']==old_state['latest_coverage_core'] and state['latest_supplemental_admission']==old_state['latest_supplemental_admission']
 errors,summary=validate(ROOT);assert not errors,errors
 owned=json.loads((E/'ownership.json').read_text())['owned_paths']
 def owns(p):return any(p==q or q.endswith('/') and p.startswith(q) for q in owned)
 changed=subprocess.check_output(['git','diff','--name-only',base],cwd=ROOT).decode().splitlines()
 untracked=subprocess.check_output(['git','ls-files','--others','--exclude-standard'],cwd=ROOT).decode().splitlines();created=[p for p in untracked if p not in baseline['untracked']]
 assert all(owns(p) for p in changed+created),[p for p in changed+created if not owns(p)]
 for p,h in baseline['sha256'].items():
  if not owns(p):assert sha(ROOT/p)==h,p
 budget=json.loads((ROOT/'memory/BUDGET.json').read_text());old_budget=old_json('memory/BUDGET.json')
 for key in ['spent','commitments','transactions','limit']:assert budget[key]==old_budget[key]
 report=dict(status='PASS_PLAN_CHANGE_ONLY',checked_at=datetime.now(timezone.utc).isoformat(),explicit_user_approval=True,new_slice_ids=list(expected),all_new_nodes_match_approved_proposal=True,only_approved_existing_dependencies_changed=True,old_tasks_outputs_acceptance_verbatim=True,medications=9,sections=90,requirements=83,subchecks=160,fulfilment_statuses_and_actual_evidence_unchanged=True,all_new_slices_planned_not_started=True,last_accepted_slice_unchanged=True,next_slice='S17J02C01',source_corpus_clinical_resources_frozen_scope_and_old_evidence_unchanged=True,preexisting_user_files_unchanged=True,old_slice_statuses_unchanged=True,clinical_approval=False,clinical_activation=False,spending_unchanged=True,scope_compliance='PASS',plan_validation=summary)
 (E/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
 print('PASS:exact approved9nodes/2dependency changes;90sections;old tasks/outputs/criteria83/160 preserved;no dossier started;nextC01')
if __name__=='__main__':main()
