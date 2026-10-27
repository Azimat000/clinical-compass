"""Revalidate unchanged canonical requests against retained genuine responses.

Only administrative budget cap and source-only failure behavior changed after
live-development-02. This is offline replay, never a claim of new model calls.
"""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from apps.compass import backend_packet_pipeline as pipeline
OUT=Path(__file__).resolve().parent
source=OUT/'live-development-02';results=[]
for cid in ['DV01','DV02','DVR01']:
    old=json.loads((source/(cid+'.json')).read_text());calls=json.loads((source/(cid+'-calls.json')).read_text())
    planned=pipeline.plans(old['snapshot'],old['operation']);cells=[]
    for branch,(plan,schema) in planned.items():
        for packet,sha in zip(plan['packets'],plan['packet_sha256']):
            index=packet['transport']['packet_index'];call=next(c for c in calls if c['branch']==branch and c['packet_index']==index)
            assert pipeline.snapshots.digest(pipeline.wire(packet))==call['payload_sha256'],'Request changed; fresh real calls required'
            assert call['response']['metadata']['test_double'] is False
            pipeline.check_response(old['snapshot'],branch,packet,call['response']['value'])
            cells.append({'branch':branch,'packet_index':index,'payload_sha256':sha,'response':call['response']})
    proof={'runtime_sha256':pipeline.snapshots.digest(pipeline.release()),'cells':cells}
    fresh=pipeline.outcome(old['snapshot'],old['operation'],proof)
    # Runtime fingerprints legitimately change with the authorized budget ceiling.
    def clinical(value):
        if isinstance(value,dict):return {k:clinical(v) for k,v in value.items() if k not in ('runtime','runtime_sha256','packet_proof')}
        if isinstance(value,list):return [clinical(v) for v in value]
        return value
    assert clinical(fresh)==clinical(old['outcome'])
    results.append({'id':cid,'pass':True,'genuine_prior_responses':len(cells),'canonical_requests_identical':True,'clinical_output_identical':True})
report={'pass':True,'runtime_sha256':pipeline.snapshots.digest(pipeline.release()),'source':'live-development-02','new_model_calls':0,'results':results}
(OUT/'development-replay.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print('PASS: unchanged actual requests, all genuine prior responses revalidated; no new calls')
