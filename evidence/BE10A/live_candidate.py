"""Single real provider call on freshly authored synthetic SQLite fixtures only."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from apps.tests.test_backend_diagnoses import DiagnosisTests
from apps.compass import backend_diagnoses as diagnoses, backend_model as model
from apps.compass import backend_risk_context as context, records

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'evidence/BE10A/live-candidate.json'
key_path=ROOT/'var/deepseek-api-key'
if key_path.stat().st_mode & 0o077:raise SystemExit('unsafe credential permissions')
os.environ['DEEPSEEK_API_KEY']=key_path.read_text().strip()
ledger=ROOT/'var/deepseek-budget.sqlite3'
def accounting():
 with closing(sqlite3.connect(ledger)) as db:
  return dict(zip(('calls','micro_usd'),db.execute('SELECT count(*),sum(micro_usd) FROM calls').fetchone()))
case=DiagnosisTests();case.setUp()
try:
 # New author data only, never the active 10 histories. A mechanics smoke, not
 # blind clinical evaluation. Independent clinical review has not happened.
 today=records.today().isoformat()
 case.visit(observed_on=today,history_text='Entirely fictional adult case. No prior mood episode is documented.',history_on=today)
 note=('Fictional test adult reports persistent low mood, loss of enjoyment, low energy, poor sleep and poor concentration for three weeks; work is impaired. '
       'In this fictional interview the patient explicitly denies any lifetime mania or hypomania. The fictional physician documented no psychosis, no substance use, no medication-related onset and no identified organic or medical cause after assessment. '
       'Current suicidal thoughts, intent, plan and behavior are explicitly denied in this fictional interview. No pervasive six-month worry is described. '
       'These are synthetic author statements, not a real clinical assessment.')
 case.diary(observed_on=today,summary=note);case.questionnaire(missing=True)
 snapshot=case.snapshot()
 original=hashlib.sha256(json.dumps(snapshot,sort_keys=True).encode()).hexdigest()
 units=context.prepare_snapshot(snapshot)
 cfg=model.Config(model='deepseek-flash',max_input_bytes=16000,max_output_tokens=1024,timeout=60)
 adapter=model.DeepSeek(cfg,model.Budget(ledger))
 before=accounting()
 report=diagnoses.analyze_snapshot(snapshot,adapter,synthetic=True)
 after=accounting()
 # Independently check every emitted citation against original unit text/field.
 indexed={u['unit_id']:u for u in units};verified=0
 candidates=report.get('candidates')
 if candidates:
  hypotheses=([candidates['leading']] if candidates['leading'] else [])+candidates['alternatives']
  for h in hypotheses:
   for criterion in h['criteria']:
    for e in criterion['evidence']:
     u=indexed[e['unit_id']]
     assert u['text'][e['start']:e['end']]==e['quote']
     assert e['source_ref']==u['source_ref'] and e['source_sha256']==u['source_sha256']
     assert e['metadata']==u['metadata'];verified+=1
 assert original==hashlib.sha256(json.dumps(snapshot,sort_keys=True).encode()).hexdigest()
 assert case.db.execute('SELECT count(*) FROM care_actions').fetchone()[0]==0
 result={'timestamp_utc':datetime.now(timezone.utc).isoformat(),'scope':'one authored mechanics smoke, not clinical quality',
         'test_double':False,'independent_clinical_review':False,'all_four_categories':sorted({c for u in units for c in u['categories']}),
         'input_snapshot':snapshot,'report':report,'citations_independently_verified':verified,
         'ledger_before':before,'ledger_after':after,'connection_cap_micro_usd':100000,
         'new_clinical_actions':0,'snapshot_unchanged':True}
 OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({k:result[k] for k in ('citations_independently_verified','ledger_before','ledger_after')},ensure_ascii=False))
 print('report',report['status'],report['errors'])
 if report['model_metadata']:print('usage',report['model_metadata']['usage'])
finally:case.tearDown()
