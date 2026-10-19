"""Upgrade a database populated by the actually accepted baseline, not a recreated schema."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
BASE = json.loads((ROOT/'evidence/S08/baseline.json').read_text())['base_commit']


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        old = tmp/'old'; old.mkdir()
        archive = subprocess.run(['git','archive',BASE],cwd=ROOT,check=True,capture_output=True).stdout
        subprocess.run(['tar','-xf','-','-C',str(old)],input=archive,check=True)
        path = tmp/'populated.sqlite3'
        script = '''import sys,json,secrets
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/apps/tests']
from apps.compass.db import connect,migrate
from apps.compass.repository import seed_demo
from apps.compass import decisions
from test_access import setup_identities
from apps.compass.web import create_app
create_app(sys.argv[2])
db=connect(sys.argv[2]);migrate(db);seed_demo(db);setup_identities(db)
db.execute("INSERT INTO care_relationships(id,patient_id,doctor_id,starts_at) VALUES('upgrade-link','D01','doc-a','2026-01-01T00:00:00+00:00')")
actor={'id':'doc-a','role':'doctor'}
def draft():
 return decisions.draft(db,actor,'D01',{'kind':'therapy_start','content':'Old synthetic therapy decision','basis':'Old synthetic source','uncertainties':'Unknown risk','request_key':secrets.token_hex(16)})
a=draft();decisions.confirm(db,actor,'D01',a,{'version':'1','decision':'approved','rationale':'Old synthetic physician confirmation','reviewed':'yes'})
b=draft();print(json.dumps({'approved':a,'pending':b}));db.close()
'''
        ids = json.loads(subprocess.check_output([sys.executable,'-c',script,str(old),str(path)],cwd=tmp,text=True))
        from apps.compass.db import connect
        from apps.compass.web import create_app
        from apps.compass import decisions
        db=connect(path)
        def snapshot():
            tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE '%_fts%' ORDER BY name")]
            return {t: sorted([list(r) for r in db.execute('SELECT * FROM "'+t+'"')],key=repr) for t in tables}
        before=snapshot()
        create_app(path)
        assert snapshot()==before, 'Existing database rows changed on startup'
        approved=db.execute('SELECT p.payload_json,d.reference_json FROM proposals p JOIN decision_drafts d ON d.proposal_id=p.id WHERE p.id=?',(ids['approved'],)).fetchone()
        assert json.loads(approved['reference_json'])['id']=='therapy-reference-v1'
        assert 'therapy_review' not in json.loads(approved['payload_json'])
        pending=db.execute('SELECT * FROM proposals WHERE id=?',(ids['pending'],)).fetchone()
        try:
            decisions.confirm(db,{'id':'doc-a','role':'doctor'},'D01',pending['id'],{'version':str(pending['version']),'decision':'approved','rationale':'Attempt after upgrade','reviewed':'yes'})
            raise AssertionError('Old pending project accepted despite changed reference')
        except decisions.DecisionError as error:
            assert error.status==409
        assert snapshot()==before, 'Denied confirmation changed existing rows'
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        protected=json.loads((ROOT/'evidence/S08/baseline.json').read_text())['protected_sha256']
        assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==sha for p,sha in protected.items())
        definitions=[{k:i[k] for k in ('id','text','subchecks')} for i in json.loads((ROOT/'plan/coverage.json').read_text())['items']]
        assert definitions==json.loads((ROOT/'evidence/S08/baseline.json').read_text())['coverage_definition']
        result={'baseline':BASE,'tables_preserved':len(before),'nonempty_tables':sum(bool(v) for v in before.values()),'old_reference_preserved':True,'old_confirmed_action_preserved':True,'old_pending_confirmation_status':409,'integrity_check':'ok','foreign_key_errors':0,'protected_files':len(protected),'requirements_preserved':len(definitions),'subchecks_preserved':sum(len(i['subchecks']) for i in definitions)}
        (ROOT/'evidence/S08/upgrade.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(result,ensure_ascii=False));db.close()

if __name__=='__main__':main()
