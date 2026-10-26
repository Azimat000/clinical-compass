"""One real default-adapter call per frozen synthetic case; never active DB."""
from contextlib import closing
from datetime import datetime,timezone
import hashlib,json,os,sqlite3,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from apps.tests.test_backend_diagnosis_integration import DiagnosisIntegrationTests
from apps.compass import backend_diagnosis_service as service,backend_jobs as jobs,backend_analyses as analyses,records
from apps.compass.backend_model import DeepSeek,Config,Budget
OUT=ROOT/'evidence/BE10B02';path=OUT/'quality-cases.json'
if (OUT/'diagnosis-quality.json').exists():
 raise SystemExit('Existing frozen run: do not overwrite or rerun; prepare a new fixed protocol.')
freeze=json.loads((OUT/'quality-freeze.json').read_text())
assert hashlib.sha256(path.read_bytes()).hexdigest()==freeze['cases_sha256']
assert hashlib.sha256((OUT/'quality-policy.md').read_bytes()).hexdigest()==freeze['policy_sha256']
key=ROOT/'var/deepseek-api-key';assert key.stat().st_mode & 0o077 == 0
os.environ['DEEPSEEK_API_KEY']=key.read_text().strip()
ledger=ROOT/'var/deepseek-budget.sqlite3'
def accounting():
 with closing(sqlite3.connect(ledger)) as db:return list(db.execute('SELECT count(*),sum(micro_usd) FROM calls').fetchone())
before=accounting();results=[]
class Recording:
 def __init__(self):self.response=None;self.request=None
 def generate(self,data,schema,**kw):
  self.request={'payload_sha256':hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),'schema_sha256':hashlib.sha256(json.dumps(schema,sort_keys=True).encode()).hexdigest()}
  self.response=DeepSeek(Config(model='deepseek-flash',max_input_bytes=16000,max_output_tokens=1024,timeout=60),Budget(ledger)).generate(data,schema,**kw)
  return self.response
for item in json.loads(path.read_text())['cases']:
 case=DiagnosisIntegrationTests();case.setUp();adapter=Recording()
 result={'id':item['id'],'expected':item,'real_provider':True,'clinical_review':False}
 try:
  case.enable();today=records.today().isoformat()
  case.visit(observed_on=today,history_text='Synthetic author case; unassessed exclusions are unknown.',history_on=today)
  case.diary(observed_on=today,summary=item['note']);case.questionnaire(missing=True)
  if item.get('second_note'):case.diary(observed_on=today,summary=item['second_note'])
  run=analyses.create(case.db,case.user,'D01',case.body('diagnosis'));work=jobs.claim(case.db,'generation')
  result['snapshot']=work['snapshot']
  report=service.execute('diagnosis',work['snapshot'],adapter)
  result['report']=report;result['request']=adapter.request
  assert jobs.finish(case.db,work,report)
  analysis=analyses.read(case.db,case.user,'D01',run['run_id']);result['published_analysis']=analysis
  response=case.clients['doc-a'].get(case.url+'/'+run['run_id']+'/diagnosis-context')
  result['http_status']=response.status_code
  assert response.status_code==200
  result['http_report_matches']=response.json['report']==report['diagnosis_report']['context']
  result['clinical_actions']=case.db.execute('SELECT count(*) FROM care_actions').fetchone()[0]
  ctx=report['diagnosis_report']['context']
  actual={h['kind']+'.'+f['id']:f['state'] for h in ctx['hypotheses'][:2] for f in h['facts']}
  result['leading_correct']=ctx['leading']==item['leading']
  result['disposition_correct']=ctx['disposition']==item['disposition']
  result['alternative_fact_checks']={k:actual[k]==v for k,v in item['alternative_facts'].items()}
  result['dangerous_omissions']=[k for k in item.get('dangerous_facts',[]) if actual[k]!='present']
  result['valid_response']=True
 except Exception as exc:
  # Only stable exception type/code, never provider body or credentials.
  result['valid_response']=False;result['error_type']=type(exc).__name__
  result['error_code']=getattr(exc,'code','validation_or_publication_error')
  result['request']=adapter.request
  if adapter.response is not None:result['raw_response']=adapter.response
 finally:case.tearDown()
 results.append(result)
 (OUT/('live-'+item['id']+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({k:result[k] for k in ('id','valid_response','error_code','leading_correct','disposition_correct','alternative_fact_checks') if k in result}),flush=True)
 if result.get('error_code')=='budget_exceeded':break
n=len(json.loads(path.read_text())['cases']);good=[r for r in results if r['valid_response']]
alt=[b for r in good for b in r['alternative_fact_checks'].values()]
expected_alt=sum(len(i['alternative_facts']) for i in json.loads(path.read_text())['cases'])
danger=sum(len(i.get('dangerous_facts',[])) for i in json.loads(path.read_text())['cases'])
summary={'version':service.VERSION,'timestamp_utc':datetime.now(timezone.utc).isoformat(),'fixed_dataset':freeze,
 'independent_clinical_review':False,'test_double':False,'expected_cases':n,'completed_cases':len(results),
 'valid_responses':len(good),'leading_exact':sum(r.get('leading_correct',False) for r in good),
 'disposition_exact':sum(r.get('disposition_correct',False) for r in good),
 'alternative_fact_checks':{'correct':sum(alt),'expected':expected_alt,'completed':len(alt)},
 'dangerous_omissions':{'missed':sum(len(r['dangerous_omissions']) for r in good),'expected_positive_facts':danger,
                       'unassessed_cases':[r['id'] for r in results if not r['valid_response']]},
 'ledger_before':before,'ledger_after':accounting(),'cap_micro_usd':100000,
 'results':[{'id':r['id'],'evidence':'evidence/BE10B02/live-'+r['id']+'.json'} for r in results]}
summary['pass']=len(good)==n and summary['leading_exact']==n and summary['disposition_exact']==n and sum(alt)==expected_alt and summary['dangerous_omissions']['missed']==0
(OUT/'diagnosis-quality.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(summary,ensure_ascii=False),flush=True)
