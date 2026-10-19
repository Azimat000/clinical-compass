"""Preserve actual S08 rows and reject old pending referrals without rewriting history."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
BASE=json.loads((ROOT/'evidence/S09/baseline.json').read_text())['head']


def main():
    with tempfile.TemporaryDirectory() as temp:
        tmp=Path(temp); old=tmp/'old';old.mkdir();path=tmp/'old.sqlite3'
        archive=subprocess.check_output(['git','archive',BASE],cwd=ROOT)
        subprocess.run(['tar','-xf','-','-C',str(old)],input=archive,check=True)
        script='''import sys,json,secrets
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/apps/tests']
from apps.compass.web import create_app
from apps.compass.db import connect,migrate
from apps.compass.repository import seed_demo
from apps.compass import decisions
from test_access import setup_identities
create_app(sys.argv[2]);db=connect(sys.argv[2]);seed_demo(db);setup_identities(db)
db.execute("INSERT INTO care_relationships(id,patient_id,doctor_id,starts_at) VALUES('upgrade-link','D01','doc-a','2026-01-01T00:00:00+00:00')")
actor={'id':'doc-a','role':'doctor'}
def draft():
 return decisions.draft(db,actor,'D01',{'kind':'referral','content':'Old synthetic referral','basis':'Old synthetic assessment','uncertainties':'Unknown severity','request_key':secrets.token_hex(16)})
a=draft();decisions.confirm(db,actor,'D01',a,{'version':'1','decision':'approved','rationale':'Old synthetic confirmation','reviewed':'yes'})
b=draft();print(json.dumps({'approved':a,'pending':b}));db.close()
'''
        ids=json.loads(subprocess.check_output([sys.executable,'-c',script,str(old),str(path)],cwd=tmp,text=True))
        from apps.compass.db import connect
        from apps.compass.web import create_app
        from apps.compass import decisions, access
        db=connect(path)
        def snapshot():
            tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
            return {t:sorted([list(r) for r in db.execute('SELECT * FROM "'+t+'"')],key=repr) for t in tables}
        before=snapshot();create_app(path)
        assert snapshot()==before
        pending=db.execute('SELECT * FROM proposals WHERE id=?',(ids['pending'],)).fetchone()
        try:
            decisions.confirm(db,{'id':'doc-a','role':'doctor'},'D01',pending['id'],{'version':str(pending['version']),'decision':'approved','rationale':'Attempt after upgrade','reviewed':'yes'})
            raise AssertionError('Old incomplete routing accepted')
        except decisions.DecisionError as error: assert error.status==409
        assert snapshot()==before
        approved=decisions.history(db,{'id':'pat-a','role':'patient'},'D01')
        assert len(approved)==1 and approved[0]['id']==ids['approved'] and approved[0]['action_id']
        token,failure=access.authenticate(db,'doc-a','synthetic-test-password-2026','127.0.0.1')
        assert token and not failure
        client=create_app(path).test_client()
        client.set_cookie(access.COOKIE,token)
        assert 'категория и срочность не записаны' in client.get('/demo/D01').text
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        baseline=json.loads((ROOT/'evidence/S09/baseline.json').read_text())
        protected=[p for p in baseline['hashes'] if '/migrations/' in p or '/resources/therapy-' in p or '/resources/dass' in p]
        assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==baseline['hashes'][p] for p in protected)
        definitions=lambda x:[{k:i[k] for k in ('id','text','subchecks')} for i in x['items']]
        old_coverage=json.loads(subprocess.check_output(['git','show',BASE+':plan/coverage.json'],cwd=ROOT,text=True))
        current=json.loads((ROOT/'plan/coverage.json').read_text())
        assert definitions(old_coverage)==definitions(current)
        result={'baseline':BASE,'tables_preserved':len(before),'nonempty_tables':sum(bool(v) for v in before.values()),'old_confirmed_referral_preserved':True,'old_pending_referral_status':409,'legacy_badge_explicit':True,'integrity':'ok','foreign_key_errors':0,'protected_files':len(protected),'requirements_preserved':len(current['items']),'subchecks_preserved':sum(len(i['subchecks']) for i in current['items'])}
        (ROOT/'evidence/S09/upgrade.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(result,ensure_ascii=False));db.close()

if __name__=='__main__':main()
