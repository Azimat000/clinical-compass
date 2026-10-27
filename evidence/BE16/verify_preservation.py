"""Read-only final gate for actual files/live DB/accounting; no live clinical writes."""
import hashlib,json,sqlite3,subprocess,sys
from pathlib import Path
from urllib.request import urlopen
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from apps.compass import backend_therapy as therapy,backend_plan_review as review
OUT=Path(__file__).resolve().parent
sha=lambda b:hashlib.sha256(b).hexdigest()
def tables(db):
    return {t[0]:sha(json.dumps(db.execute('SELECT * FROM "'+t[0]+'"').fetchall(),sort_keys=True,default=str).encode())
        for t in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")}
def main():
    baseline=json.loads((OUT/'baseline.json').read_text())
    db=sqlite3.connect('file:'+str(ROOT/'var/compass.sqlite3')+'?mode=ro',uri=True)
    assert tables(db)==baseline['active_database_tables'];db.close()
    assert sha((ROOT/'var/clinic-20261026-access.md').read_bytes())==baseline['access_sha256']
    for path,digest in baseline['preserved_files'].items():assert sha((ROOT/path).read_bytes())==digest,path
    owned={'apps/compass/backend_therapy.py','apps/compass/backend_therapy_context.py','apps/compass/backend_risk_context.py',
        'apps/compass/web.py','apps/tests/test_backend_security.py','evidence/BE14/therapy-quality.json',
        'START_HERE.md','AGENTS.md','plan/backend/README.md','plan/slices/BE16.md','plan/backend/requirements.json','plan/coverage.json','plan/COVERAGE.md',
        'memory/STATE.json','memory/DECISIONS.md','memory/BLOCKERS.md','memory/EXTERNAL.md','memory/BUDGET.json','memory/sessions/BE16.md'}
    changed=[]
    for path,digest in baseline['tracked_sha256'].items():
        current=ROOT/path
        if not current.is_file() or sha(current.read_bytes())!=digest:
            assert path in owned or path.startswith('evidence/BE16/'),path
            changed.append(path)
    untracked=subprocess.check_output(['git','ls-files','--others','--exclude-standard','-z'],cwd=ROOT).decode().split('\0')
    for path in filter(None,untracked):
        assert path in baseline['preserved_files'] or path in owned or path.startswith('evidence/BE16/'),path
    with urlopen('http://127.0.0.1:8000/healthz',timeout=5) as response:
        health=json.loads(response.read());assert response.status==200
    assert health['schema_version']=='015_medication_marks'
    ledger_db=sqlite3.connect('file:'+str(ROOT/'var/deepseek-budget.sqlite3')+'?mode=ro',uri=True)
    ledger=list(ledger_db.execute('SELECT count(*),sum(micro_usd) FROM calls').fetchone())
    assert list(ledger_db.execute('SELECT count(*),sum(micro_usd) FROM calls WHERE rowid<=?',(baseline['ledger'][0],)).fetchone())==baseline['ledger']
    ledger_db.close()
    q=json.loads(therapy.QUALITY_PATH.read_text());assert q['pass'] and q['runtime_sha256']==therapy.history.digest(therapy.generation_release())
    h=json.loads((OUT/'http-protocol.json').read_text());assert h['pass'] and h['checks_count']==23 and h['runtime_sha256']==review.runtime()
    assert ledger[0]-baseline['ledger'][0]==7
    assert ledger[1]<=1000000
    calls=json.loads((OUT/'therapy/live-progress.json').read_text())['calls']
    metas=[c['response']['metadata'] for c in calls]+[h['model_outcome']['care_plan_context']['therapy']['model_metadata']]
    assert len(metas)==7 and all(m['test_double'] is False for m in metas)
    assert sum(m['cost_ceiling_micro_usd'] for m in metas)==ledger[1]-baseline['ledger'][1]
    result={'pass':True,'active_tables_unchanged':len(baseline['active_database_tables']),'accounts_unchanged':True,
        'preserved_files':len(baseline['preserved_files']),'changed_tracked_paths':changed,'active_health':health,
        'ledger_before':baseline['ledger'],'ledger_after':ledger,'new_model_calls':7,
        'new_ceiling_micro_usd':ledger[1]-baseline['ledger'][1],'remaining_micro_usd':1000000-ledger[1],
        'known_tokens':sum(m['usage']['total_tokens'] for m in metas),'estimated_peak_usd':sum(m['estimated_peak_cost_nano_usd'] for m in metas)/1e9,
        'estimated_offpeak_usd':sum(m['estimated_offpeak_cost_nano_usd'] for m in metas)/1e9,
        'runtime_sha256':review.runtime(),'therapy_runtime_sha256':q['runtime_sha256'],
        'http_checks':23,'therapy_cases':19,'post_generation_mutations':24,
        'clinical_release':'blocked','general_regression':'not run: user explicitly deferred general check',
        'actual_invoice':None,'rub_conversion':None,'new_dependencies':False,'migrations':False}
    (OUT/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
