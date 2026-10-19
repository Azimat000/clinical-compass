"""Standalone opt-in extension exercise in a disposable database."""
import hashlib
import json
from pathlib import Path
import tempfile
from apps.compass import assessments, extensions, record_summary
from apps.compass.db import connect,migrate
from apps.compass.repository import seed_demo


def run():
    core = ['db.py','assessments.py','clinical_rules.py','decisions.py','events.py','records.py']
    base = Path('apps/compass')
    before = {p:hashlib.sha256((base/p).read_bytes()).hexdigest() for p in core}
    with tempfile.TemporaryDirectory() as tmp:
        db=connect(Path(tmp)/'extensions.sqlite3'); migrate(db); seed_demo(db); assessments.install_form(db)
        tables = ['source_versions','catalog_versions','observations','assessments','care_actions','critical_events','outbox_events']
        old = {t:[tuple(r) for r in db.execute('SELECT * FROM '+t)] for t in tables}
        bundle=json.loads(Path('evidence/S13/test-bundle.json').read_text())
        extensions.install(db,bundle); extensions.install(db,bundle)
        scores={v:extensions.preview(db,'test-scale-'+v,[1]*42) for v in ('v1','v2')}
        assert scores=={'v1':{'test':42},'v2':{'test':21}}
        assert extensions.preview(db,'test-scale-v1',[None]+[1]*41) is None
        drug={v:extensions.preview(db,'test-drug-'+v) for v in ('v1','v2')}
        rules={v:extensions.preview(db,'test-rule-'+v,{'synthetic_flag':v}) for v in ('v1','v2')}
        assert all(r['result']=='matched' for r in rules.values())
        assert extensions.preview(db,'test-rule-v1',{})['result']=='unknown'
        assert extensions.preview(db,'test-rule-v1',{'synthetic_flag':'v2'})['result']=='no_match'
        for table in tables:
            rows=[tuple(r) for r in db.execute('SELECT * FROM '+table)]
            assert all(r in rows for r in old[table]),table
            if table not in ('source_versions','catalog_versions'): assert rows==old[table],table
        tampered=json.loads(json.dumps(bundle));tampered['items'][0]['definition']['title']='changed'
        try: extensions.install(db,tampered)
        except ValueError: pass
        else: raise AssertionError('Overwrite accepted')
        # Atomic rollback of a bundle with one invalid member.
        invalid=json.loads(json.dumps(bundle)); invalid['items'][0]['id']='test-rollback';invalid['items'][0]['code']='ROLLBACK';invalid['items'][1]['kind']='executable'
        try: extensions.install(db,invalid)
        except ValueError: pass
        else: raise AssertionError('Invalid kind accepted')
        assert not db.execute("SELECT 1 FROM catalog_versions WHERE id='test-rollback'").fetchone()
        inactive=[dict(r) for r in db.execute("SELECT id,status FROM catalog_versions WHERE id LIKE 'test-%'")]
        assert len(inactive)==6 and all(r['status']=='inactive' for r in inactive)
        from apps.compass import access,records
        for uid,role in [('test-doc','doctor'),('test-pat','patient')]:
            db.execute('INSERT INTO users VALUES(?,?,?,?,0)',(uid,role,uid,None))
        db.execute("UPDATE patients SET user_id='test-pat' WHERE id='D01'")
        access.accept_invite(db,'test-pat',access.invite(db,'test-doc','D01'))
        records.save(db,{'id':'test-pat','role':'patient'},'D01','self_report',
                     {'request_key':'a'*32,'observed_on':records.today().isoformat(),'summary':'Test completeness'})
        summary=record_summary.summarize(db,'D01')
        assert summary=={'records':1,'known':0,'unknown':4,'denied':0,'conflicting':0}
        assert before=={p:hashlib.sha256((base/p).read_bytes()).hexdigest() for p in core}
        result={'status':'PASS','scope':'synthetic_test only; not clinical plug-in activation','scores':scores,'drugs':drug,'rules':rules,
                'versions':inactive,'independent_feature':summary,'old_rows_preserved':True,'incomplete_no_score':True,
                'overwrite_rejected':True,'atomic_rollback':True,'core_sha256':before,'core_unchanged_during_extension':True}
        db.close()
    Path('evidence/S13/extensions.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print('PASS: 6 inactive versions, scoring/reference/rule simulation, unchanged core, old rows preserved')

if __name__=='__main__':run()
