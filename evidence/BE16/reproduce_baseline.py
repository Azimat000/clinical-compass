"""Reproduce pre-fix defects using Git baseline code in memory, disposable DB only."""
import json
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from apps.tests.test_backend_security import BackendSecurityTests
from apps.compass import access, backend_therapy_context as context, web
OUT=Path(__file__).resolve().parent
BASE=json.loads((OUT/'baseline.json').read_text())['head']
def old(path, namespace):
    source=subprocess.check_output(['git','show',BASE+':'+path]).decode()
    exec(compile(source,str(ROOT/path),'exec'),namespace)
    return namespace

def main():
    f=BackendSecurityTests();f.setUp()
    try:
        plan=f.ready_plan();draft=f.draft_plan(plan)
        ns=old('apps/compass/web.py',{'__name__':'apps.compass.web','__file__':web.__file__,'__package__':'apps.compass'})
        client=ns['create_app'](f.path).test_client()
        client.set_cookie(access.COOKIE,f.clients['doc-a'].get_cookie(access.COOKIE).value)
        url='/api/v1/patients/D01/plan-reviews/'+draft['proposal_id']
        before=f.db.execute('SELECT count(*) FROM care_actions').fetchone()[0]
        response=client.open(url,method='HEAD',json=f.confirmation(draft)) # Deliberately no CSRF header.
        after=f.db.execute('SELECT count(*) FROM care_actions').fetchone()[0]
        assert response.status_code==200 and after==before+1
        ns=old('apps/compass/backend_therapy_context.py',{'__name__':'apps.compass.backend_therapy_context','__file__':context.__file__,'__package__':'apps.compass'})
        f.reconcile(basis='OLD_LINK_PRIVATE_CANARY')
        user=f.change_relationship()
        state=ns['view'](f.db,user,'D01')
        assert state['current']['fresh'] is False and 'OLD_LINK_PRIVATE_CANARY' in json.dumps(state)
        result={'baseline':BASE,'reproduced':True,'head_confirmation_without_csrf':{'status':response.status_code,'actions_before':before,'actions_after':after},
            'old_relationship_reconciliation_disclosed':True,'scope':'disposable synthetic DB; baseline source executed in memory; production files and live DB never replaced'}
        (OUT/'baseline-reproduction.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
    finally:f.tearDown()
if __name__=='__main__':main()
