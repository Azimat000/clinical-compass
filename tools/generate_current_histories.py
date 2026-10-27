"""Explicitly requested production generation over the existing synthetic roster.

No fixtures, assertions, browser checks, quality evaluation or clinical edits.
Risk uses the real adapter under the existing budget, citation and source fences.
Plans are drafts/clarifications; physician diagnoses and prescriptions stay intact.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from apps.compass import backend_analyses as analyses, backend_jobs, events
from apps.compass import backend_packet_pipeline as packets, backend_model, backend_analysis_history
from apps.compass.backend_packet_store import Store
from apps.compass.db import connect, transaction, now

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--db',required=True)
parser.add_argument('--lane',choices=['risk','plan-intents'],required=True)
args = parser.parse_args()
authorization=json.loads((ROOT/'var/current-history-generation-authorization.json').read_text())
if (authorization.get('enabled') is not True or authorization.get('synthetic_only') is not True or authorization.get('quality_pass') is not False
        or authorization.get('operations') != ['risk','diagnosis','plan']):
    raise RuntimeError('Missing explicit synthetic generation authorization')
allowed=set(authorization['patient_ids'])
db=connect(args.db)

def roster():
    return [dict(row) for row in db.execute('''SELECT r.patient_id,r.doctor_id,r.id relationship_id
        FROM care_relationships r JOIN patients p ON p.id=r.patient_id
        JOIN users u ON u.id=r.doctor_id WHERE p.synthetic=1 AND r.ends_at IS NULL
        AND r.starts_at<=? AND u.disabled=0 ORDER BY r.patient_id''',(now(),))
        if row['patient_id'] in allowed]


def enqueue(row,operation):
    user={'id':row['doctor_id'],'role':'doctor'}
    with transaction(db):
        relationship=analyses.authorize(db,user,row['patient_id'])
        raw=analyses.capture(db,row['patient_id'],relationship,operation=operation)
        request_key=hashlib.sha256(('requested-current-history-v1:'+operation+':'+relationship+':'+raw).encode()).hexdigest()[:32]
        value=analyses.create(db,user,row['patient_id'],{'contract_version':'1.0','operation':operation,'request_key':request_key})
    print(json.dumps({'patient_id':row['patient_id'],'operation':operation,'run_id':value['run_id'],'status':value['status']},ensure_ascii=False),flush=True)
    return value

try:
    if args.lane=='risk':
        secret=ROOT/'var/deepseek-api-key'
        if secret.stat().st_mode & 0o077:raise RuntimeError('Credential must be private')
        os.environ['DEEPSEEK_API_KEY']=secret.read_text().strip()
        model=backend_model.DeepSeek(packets.config(),backend_model.Budget(ROOT/'var/deepseek-budget.sqlite3'))
        requested_runs={enqueue(row,'risk')['run_id'] for row in roster()}
        while True:
            if events.process_one(db):continue
            work=backend_jobs.claim(db,lane='risk')
            if work is None:time.sleep(1);continue
            if work.get('skipped'):continue
            try:
                # Internal real-model injection is limited to authorized existing
                # synthetic patients; packet publication independently recomputes.
                if work['run']['patient_id'] not in allowed:raise backend_model.ModelError('synthetic_only')
                store=Store(args.db,work)
                if work['run']['id'] in requested_runs:
                    outcome=packets.execute('risk',work['snapshot'],model=model,store=store,cancel=store)
                else:
                    outcome=backend_jobs.execute('risk',work['snapshot'],store=store,cancel=store)
            except Exception as exc:
                code=exc.code if isinstance(exc,backend_model.ModelError) else 'executor_error'
                backend_jobs.finish(db,work,error=code)
            else:
                backend_jobs.finish(db,work,outcome=outcome)
    else:
        pending={row['patient_id']:row for row in roster()}
        deadline=time.monotonic()+7200
        while pending and time.monotonic()<deadline:
            for patient,row in list(pending.items()):
                user={'id':row['doctor_id'],'role':'doctor'}
                history=backend_analysis_history.read(db,user,patient,operation='diagnosis')
                if not history['items']:
                    enqueue(row,'diagnosis')
                    continue
                if history['items'][0]['status'] in ('queued','running'):continue
                enqueue(row,'plan')
                del pending[patient]
            if pending:time.sleep(3)
        print(json.dumps({'plan_intents_finished':not pending,'remaining_patients':list(pending)},ensure_ascii=False),flush=True)
finally:
    db.close()
