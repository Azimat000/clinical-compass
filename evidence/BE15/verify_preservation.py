"""Independent main-agent preservation/migration checks, no live writes."""
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import sys
import tempfile
from urllib.request import urlopen
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from apps.compass.db import connect,migrate
from apps.compass import decisions,backend_plan_review as review
OUT=Path(__file__).resolve().parent

def sha(b):return hashlib.sha256(b).hexdigest()
def tables(db):
    return {t[0]:sha(json.dumps(db.execute('SELECT * FROM "'+t[0]+'"').fetchall(),sort_keys=True,default=str).encode())
            for t in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")}
def rows(db):
    return {t[0]:sorted(tuple(r) for r in db.execute('SELECT * FROM "'+t[0]+'"'))
            for t in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")}

def main():
    baseline=json.loads((OUT/'baseline.json').read_text())
    live=sqlite3.connect('file:'+str(ROOT/'var/compass.sqlite3')+'?mode=ro',uri=True)
    assert tables(live)==baseline['active_database_tables']
    assert sha((ROOT/'var/clinic-20261026-access.md').read_bytes())==baseline['access_sha256']
    for name,h in baseline['preserved_files'].items():assert sha((ROOT/name).read_bytes())==h,name
    migration={}
    with tempfile.TemporaryDirectory(prefix='be15-preservation-') as directory:
        clone=Path(directory)/'copy.sqlite3';target=sqlite3.connect(clone);live.backup(target);target.close()
        db=connect(clone)
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='backend_plan_reviews'").fetchone()
        user=dict(db.execute("SELECT * FROM users WHERE role='doctor' AND disabled=0 ORDER BY id LIMIT 1").fetchone())
        patient=db.execute('SELECT patient_id FROM care_relationships WHERE doctor_id=? AND ends_at IS NULL LIMIT 1',(user['id'],)).fetchone()[0]
        pid=decisions.draft(db,user,patient,{'kind':'plan_change','content':'Механическая проверка в отключённой копии.',
            'basis':'Техническая синтетика','uncertainties':'Не клиническое решение','request_key':secrets.token_hex(16)})
        version=db.execute('SELECT version FROM proposals WHERE id=?',(pid,)).fetchone()[0]
        cid=decisions.confirm(db,user,patient,pid,{'version':str(version),'decision':'approved','rationale':'Только проверка механики в копии.','reviewed':'yes'})
        assert cid; migration['legacy015_manual_confirmation']=True
        before=rows(db)
        old_objects={r['name']:r['sql'] for r in db.execute("SELECT name,sql FROM sqlite_master WHERE type IN ('table','trigger','index')")}
        migrate(db)
        after=rows(db)
        for table,values in before.items():
            if table!='schema_migrations':assert after[table]==values,table
        objects={r['name']:r['sql'] for r in db.execute("SELECT name,sql FROM sqlite_master WHERE type IN ('table','trigger','index')")}
        for name,sql in old_objects.items():assert objects[name]==sql,name
        assert 'backend_plan_reviews' in after
        once=rows(db);migrate(db);assert rows(db)==once
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        migration.update(old_tables_preserved=len(before)-1,old_objects_preserved=len(old_objects),
            repeated_migration=True,integrity='ok',foreign_key_violations=0)
        db.close()
    with urlopen('http://127.0.0.1:8000/healthz',timeout=5) as response:
        health=json.loads(response.read());assert response.status==200
    assert health['schema_version']=='015_medication_marks',health
    ledger=sqlite3.connect(ROOT/'var/deepseek-budget.sqlite3').execute('SELECT count(*),sum(micro_usd) FROM calls').fetchone()
    assert ledger==(153,739853),ledger
    http=json.loads((OUT/'http-protocol.json').read_text());assert http['pass'] and http['checks_count']==19
    assert http['runtime_sha256']==review.runtime()
    assert tables(live)==baseline['active_database_tables'];live.close()
    result={'pass':True,'active_tables_unchanged':len(baseline['active_database_tables']),
        'accounts_unchanged':True,'preexisting_files_unchanged':len(baseline['preserved_files']),
        'migration':migration,'active_health':health,'ledger_before':[152,738449],'ledger_after':list(ledger),
        'new_model_calls':1,'new_ceiling_micro_usd':1404,'remaining_micro_usd':260147,
        'general_regression':'not run: user explicitly deferred general check',
        'http_checks':19,'runtime_sha256':review.runtime(),'clinical_release':'blocked'}
    (OUT/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
