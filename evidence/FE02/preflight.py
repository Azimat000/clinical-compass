"""Offline explanation of the actual diagnostic failure; no provider request."""
import json
from pathlib import Path
import sqlite3
import sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from apps.compass import backend_diagnosis_service as service,backend_diagnosis_codec as codec
from apps.compass import backend_diagnosis_criteria as criteria,backend_model as model,backend_snapshot as snapshots,backend_therapy as therapy
with sqlite3.connect('file:'+str(ROOT/'var/FE02-integration.sqlite3')+'?mode=ro',uri=True) as db:
    row=db.execute("SELECT s.payload_json FROM analysis_runs r JOIN analysis_input_snapshots s ON s.id=r.snapshot_id WHERE r.operation='diagnosis'").fetchone()
    snapshot=json.loads(row[0])
cfg=model.Config(model='deepseek-flash',max_input_bytes=16000,max_output_tokens=codec.MAX_OUTPUT_TOKENS,timeout=60)
branches={}
for kind in criteria.release()['conditions']:
    data=service.payload(snapshot,kind);schema=codec.schema(kind)
    metrics=model.request_metrics(data,schema,cfg)
    try:model.preflight(data,schema,cfg);code='admitted'
    except model.ModelError as exc:code=exc.code
    branches[kind]={'input_bytes':metrics['input_bytes'],'reservation_micro_usd':metrics['reservation_micro_usd'],'reason':code}
result={'status':'PASS','scope':'offline sizing and unchanged runtime admission only; not a model response',
        'branches':branches,'max_input_bytes':16000,'per_call_micro_usd':20000,'network_calls':0,
        'diagnosis_runtime_admitted':json.loads((ROOT/'evidence/BE10/diagnosis-quality.json').read_text())['runtime_sha256']==snapshots.digest(service.release()),
        'therapy_runtime_admitted':json.loads(therapy.QUALITY_PATH.read_text())['runtime_sha256']==snapshots.digest(therapy.generation_release()),
        'diagnosis_runtime_sha256':snapshots.digest(service.release()),'therapy_runtime_sha256':snapshots.digest(therapy.generation_release())}
assert result['diagnosis_runtime_admitted'] and result['therapy_runtime_admitted']
assert branches['depressive_episode']['reason']=='context_limit'
(ROOT/'evidence/FE02/preflight.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False,indent=2))
