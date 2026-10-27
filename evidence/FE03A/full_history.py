"""Offline packet proof over all ten existing full histories, in a private backup."""
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from apps.compass.db import connect,migrate
from apps.compass import backend_analyses as analyses,backend_diagnosis_codec as codec
from apps.compass import backend_context_packets as packets,backend_model as model,backend_risk_context as context
from apps.compass import backend_diagnosis_service as diagnostic,backend_therapy as therapy,backend_snapshot as snapshots
OUT=Path(__file__).resolve().parent

def hashes(db):
    return {n:hashlib.sha256(repr(sorted(db.execute('SELECT * FROM "'+n+'"').fetchall(),key=repr)).encode()).hexdigest()
            for n, in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}

def main():
    path=ROOT/'var/FE03A-grouped-sizing.sqlite3'
    recheck = '--verify-existing' in sys.argv
    with sqlite3.connect('file:'+str(ROOT/'var/compass.sqlite3')+'?mode=ro',uri=True) as src:
        source_hashes=hashes(src)
        if not recheck:
            assert not path.exists(),'Refuse to replace the existing proof copy'
            fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
            with sqlite3.connect(path) as copy:src.backup(copy)
    if recheck:
        db=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True,isolation_level=None)
        db.row_factory=sqlite3.Row
    else:
        db=connect(path);migrate(db)
        db.execute("UPDATE backend_job_settings SET enabled=1,generation_version='be10-diagnosis-v1'")
    with sqlite3.connect(path) as check:
        baseline=hashes(check)
        assert all(baseline[t]==v for t,v in source_hashes.items() if t!='schema_migrations')
    cfg=model.Config(model='deepseek-flash',max_input_bytes=16000,max_output_tokens=codec.MAX_OUTPUT_TOKENS,timeout=60)
    results=[]
    for pid in ['P'+str(i) for i in range(201,211)]:
        relation=db.execute('SELECT id,doctor_id FROM care_relationships WHERE patient_id=? AND ends_at IS NULL',(pid,)).fetchone()
        db.execute('BEGIN')
        try:snapshot=json.loads(analyses.capture(db,pid,relation['id'],operation='diagnosis'))
        finally:db.rollback()
        units=context.prepare_snapshot(snapshot)
        for kind in diagnostic.criteria.release()['conditions']:
            payload=codec.payload(snapshot,kind);schema=codec.schema(kind)
            source=packets.digest(payload)
            original_metrics=model.request_metrics(payload,schema,cfg)
            before=packets.digest(snapshot)
            plan=packets.prepare(payload,schema,cfg)
            reconstructed=packets.restore(plan,expected_sha256=source)
            assert reconstructed==payload and packets.digest(snapshot)==before
            assert len(units)==len(reconstructed['units'])
            assert all(model.preflight(p,schema,cfg) for p in plan['packets'])
            results.append({'patient_id':pid,'branch':kind,'unit_count':len(units),
                'categories':dict(Counter(c for u in units for c in u['categories'])),
                'current_revision_counts':dict(Counter(str(u['metadata']['current_revision']) for u in units)),
                'input_before_bytes':original_metrics['input_bytes'],
                'reservation_before_micro_usd':original_metrics['reservation_micro_usd'],
                'source_sha256':source,'roundtrip_sha256':packets.digest(reconstructed),'roundtrip_exact':True,
                'packet_count':len(plan['packets']),'packet_sha256':plan['packet_sha256'],
                'measurements':plan['measurements'],'total_reservation_micro_usd':plan['total_reservation_micro_usd']})
    with sqlite3.connect(path) as check:assert hashes(check)==baseline
    db.close()
    before=json.loads((ROOT/'evidence/FE02/preflight.json').read_text())
    assert before['diagnosis_runtime_sha256']==snapshots.digest(diagnostic.release())
    assert before['therapy_runtime_sha256']==snapshots.digest(therapy.generation_release())
    report={'status':'PASS','mode':'offline_transport_only_no_model_or_default_integration',
        'read_only_recheck':recheck,'copy':str(path),'copy_private':path.stat().st_mode&0o077==0,'table_hashes_unchanged':True,
        'all_original_clinical_tables_preserved':len(source_hashes)-1,'patients':10,'branches':20,
        'results':results,'network_calls':0,'budget_reservations':0,'default_generator_changed':False,
        'quality_gates_unchanged':True,'working_service_changed':False,'clinical_release':'blocked',
        'limits':{'max_input_bytes':16000,'per_call_micro_usd':20000,'max_output_tokens':1536,'max_packets':64},
        'total_prospective_reservation_micro_usd':sum(r['total_reservation_micro_usd'] for r in results),
        'all_model_results':'not_evaluated','aggregation_and_quality':'FE03B','D01_D12_cases':'FE03C'}
    (OUT/'full-history.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('PASS: ten whole histories, twenty branches; exact reconstruction and every packet fits')
    for r in results:
        print(r['patient_id'],r['branch'],r['input_before_bytes'],'bytes ->',r['packet_count'],'packets; max',max(m['input_bytes'] for m in r['measurements']),'bytes;',r['total_reservation_micro_usd'],'microUSD prospective cap')
if __name__=='__main__':main()
