"""BE11 real local HTTP, additive migration and preservation proof. No paid model."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from threading import Thread
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from werkzeug.serving import make_server, WSGIRequestHandler

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from apps.compass import access, backend_diagnosis_service as service, backend_snapshot
from apps.compass import backend_diagnosis_review as review, backend_analyses as analyses
from apps.compass.db import connect, migrate
from apps.compass.web import create_app
from apps.tests import test_backend_contracts, test_access
from apps.tests.test_backend_diagnosis_review import DiagnosisReviewTests

OUT=Path(__file__).resolve().parent
sha=lambda b:hashlib.sha256(b).hexdigest()

def tables(db):
    return {t:sha(json.dumps(sorted(json.dumps(r,ensure_ascii=False,default=str)
        for r in db.execute('SELECT * FROM "'+t+'"')),ensure_ascii=False).encode())
        for (t,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}

class Quiet(WSGIRequestHandler):
    def log(self,*args,**kwargs):pass


def live_http():
    fixture=DiagnosisReviewTests('test_accept_exact_model_provenance_and_original_remains_unreviewed')
    fixture.setUp()
    server=None
    try:
        run=fixture.ready();body=fixture.request_body('accept',run)
        token=test_access.csrf(fixture.clients['doc-a'])
        cookies={uid:access.COOKIE+'='+client.get_cookie(access.COOKIE).value for uid,client in fixture.clients.items()}
        def launch():
            server=make_server('127.0.0.1',0,create_app(fixture.path),request_handler=Quiet)
            thread=Thread(target=server.serve_forever,daemon=True);thread.start()
            return server,thread
        server,thread=launch();checks=[]
        def call(method,body=None,uid='doc-a',csrf=True):
            headers={'Content-Type':'application/json'}
            if uid:headers['Cookie']=cookies[uid]
            if csrf:headers['X-CSRF-Token']=token
            request=Request('http://127.0.0.1:'+str(server.server_port)+fixture.url_review,
                data=None if body is None else json.dumps(body).encode(),headers=headers,method=method)
            try:response=urlopen(request,timeout=10)
            except HTTPError as exc:response=exc
            with response:
                raw=response.read();value=json.loads(raw) if raw else None
                return response.status,value,response.headers
        status,_,_=call('GET',uid=None);assert status==401;checks.append('anonymous401')
        for uid in ('pat-a','doc-b'):
            assert call('POST',body,uid)[0] in (403,404);checks.append(uid+'_denied')
        assert call('POST',body,csrf=False)[0]==403;checks.append('csrf403')
        before=test_backend_contracts.table_rows(fixture.db)
        status,receipt,headers=call('POST',body);assert status==200 and headers['Cache-Control']=='no-store'
        assert receipt['origin']=='model_review' and receipt['action']=='accept'
        assert receipt['clinical_ready'] is receipt['treatment_applied'] is False
        assert call('POST',body)[1]==receipt;checks.extend(['accept200','exact_retry200'])
        changed=dict(body,request_key='f'*32,basis='Другая вкладка.')
        assert call('POST',changed)[0]==409;checks.append('conflicting_tab409')
        state=call('GET')[1];assert state['head_version']==1 and state['current']['fresh']
        assert state['history']==[receipt];checks.append('immutable_history200')
        after=test_backend_contracts.table_rows(fixture.db)
        for table in before:
            if table not in ('backend_diagnosis_reviews','sessions','audit_entries'):
                assert before[table]==after[table],table
        server.shutdown();thread.join();server.server_close();server=None
        server,thread=launch()
        assert call('POST',body)[1]==receipt;checks.append('restart_same_receipt200')
        return {'pass':True,'checks':checks,'checks_count':len(checks),
                'clinical_actions':fixture.db.execute('SELECT count(*) FROM care_actions').fetchone()[0],
                'transport':'real loopback HTTP','inference':'explicit test double; mechanics only',
                'paid_model_calls':0}
    finally:
        if server is not None:server.shutdown();thread.join();server.server_close()
        fixture.tearDown()


def verify():
    base=json.loads((OUT/'baseline.json').read_text())
    for p,h in base['preserved_files'].items():assert sha((ROOT/p).read_bytes())==h,p
    assert sha((ROOT/'var/clinic-20261026-access.md').read_bytes())==base['access_sha256']
    with closing(sqlite3.connect('file:'+str(ROOT/'var/compass.sqlite3')+'?mode=ro',uri=True)) as db:
        assert tables(db)==base['active_db_tables']
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        with tempfile.TemporaryDirectory() as tmp:
            copy=connect(Path(tmp)/'copy.sqlite3')
            try:
                db.backup(copy)
                old=test_backend_contracts.table_rows(copy)
                schema=dict(copy.execute("SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL"))
                migrate(copy)
                after=test_backend_contracts.table_rows(copy)
                for table,rows in old.items():
                    actual=after[table]
                    if table=='schema_migrations':actual=[r for r in actual if json.loads(r)[0] in {json.loads(x)[0] for x in rows}]
                    assert rows==actual,table
                current=dict(copy.execute("SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL"))
                assert all(current[k]==v for k,v in schema.items())
                once=test_backend_contracts.table_rows(copy);migrate(copy)
                assert once==test_backend_contracts.table_rows(copy)
                assert copy.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
                assert not copy.execute('PRAGMA foreign_key_check').fetchall()
                # Nonempty old treatment history also survives a new diagnosis.
                relation = next(r for r in copy.execute('''SELECT r.* FROM care_relationships r
                    JOIN users u ON u.id=r.doctor_id WHERE r.ends_at IS NULL AND u.disabled=0
                    AND u.role='doctor' ORDER BY r.patient_id''')
                    if analyses.age_scope(copy,r['patient_id'])[0] is None)
                user = {'id':relation['doctor_id'],'role':'doctor'}
                state = review.view(copy,user,relation['patient_id'])
                treatment_before = test_backend_contracts.table_rows(copy)
                action_count = copy.execute('SELECT count(*) FROM care_actions').fetchone()[0]
                assert action_count > 0
                review.record(copy,user,relation['patient_id'],{
                    'request_key':'c'*32,'expected_version':state['head_version'],
                    'snapshot_id':state['snapshot_id'],'action':'manual',
                    'run_id':None,'analysis_revision':None,'hypothesis_id':None,
                    'diagnosis':'Вымышленная запись только в отключённой проверочной копии.',
                    'diagnosis_code':None,'basis':'Авторская техническая проверка сохранности.',
                    'uncertainties':'Не клиническое решение настоящего врача.','reviewed':True})
                treatment_after = test_backend_contracts.table_rows(copy)
                for table, rows in treatment_before.items():
                    if table not in ('backend_diagnosis_reviews','analysis_input_snapshots','audit_entries'):
                        assert treatment_after[table] == rows, table
                migration={'pass':True,'preserved_tables':len(old),'schema':'020_backend_diagnosis_review',
                    'old_schema_objects_unchanged':len(schema),'repeatable':True,'copy_only':True,
                    'existing_care_actions_preserved_after_manual_diagnosis':action_count}
            finally:copy.close()
    with closing(sqlite3.connect('file:'+str(ROOT/'var/deepseek-budget.sqlite3')+'?mode=ro',uri=True)) as db:
        assert [list(r) for r in db.execute('SELECT * FROM calls ORDER BY id')]==base['ledger_rows']
        ledger=list(db.execute('SELECT count(*),sum(micro_usd) FROM calls').fetchone())
        assert ledger==[145,730308]
    for name in ('plan/coverage.json','plan/backend/requirements.json'):
        data=json.loads((ROOT/name).read_text())
        invariant=sha(json.dumps([{k:v for k,v in i.items() if k!='actual_evidence'} for i in data['items']],ensure_ascii=False,sort_keys=True).encode())
        assert invariant==base[name+'_invariants_sha256'],name
    allowed = {
        'apps/compass/backend_diagnosis_review.py',
        'apps/compass/migrations/020_backend_diagnosis_review.sql',
        'apps/compass/decisions.py', 'apps/compass/web.py',
        'apps/tests/test_backend_diagnosis_review.py',
        'docs/architecture/backend-diagnosis-review.md',
        'memory/sessions/BE11.md', 'memory/STATE.json', 'memory/DECISIONS.md',
        'memory/BLOCKERS.md', 'memory/EXTERNAL.md', 'memory/BUDGET.json',
        'plan/backend/README.md', 'plan/backend/requirements.json',
        'plan/coverage.json', 'plan/COVERAGE.md', 'START_HERE.md', 'AGENTS.md'}
    changed = set(subprocess.check_output(['git','diff','--name-only',base['head']],cwd=ROOT,text=True).splitlines())
    untracked = set(subprocess.check_output(['git','ls-files','--others','--exclude-standard'],cwd=ROOT,text=True).splitlines())
    for path in changed | (untracked - set(base['preserved_files'])):
        assert path in allowed or path.startswith('evidence/BE11/'), 'unexpected changed path: '+path
    quality=json.loads((ROOT/'evidence/BE10/diagnosis-quality.json').read_text())
    assert quality['pass'] and quality['runtime_sha256']==backend_snapshot.digest(service.release())
    assert quality['clinical_ready'] is False
    return {'pass':True,'preservation':{'active_tables':len(base['active_db_tables']),
            'foreign_files':len(base['preserved_files']),'access_unchanged':True,'ledger':ledger,
            'requirement_text_status_subchecks_unchanged':True},'migration':migration,
            'diagnosis_runtime_sha256':quality['runtime_sha256'],'http':live_http(),
            'clinical_release':'blocked','paid_model_calls':0}

if __name__=='__main__':
    result=verify()
    (OUT/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))
