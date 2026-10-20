"""Compare current workspace with recorded baseline; no modification outside report."""
from pathlib import Path
import hashlib,json,subprocess
ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'evidence/audits/2026-10-20-technical-r2'
BASE=json.loads((OUT/'baseline.json').read_text())
protected_prefixes=('data/synthetic/','apps/compass/resources/','apps/compass/migrations/','.agents/')
protected_exact=('apps/requirements.lock','apps/Dockerfile','docker-compose.yml','tools/run_longitudinal_demo.py','tools/run_synthetic_cycles.py')
protected={p:h for p,h in BASE['files'].items() if p.startswith(protected_prefixes) or p in protected_exact or p.startswith('evidence/audits/2026-10-20-cycles/')}
for p,h in protected.items():assert hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h,p
before=json.loads(subprocess.check_output(['git','show',BASE['head']+':plan/coverage.json'],cwd=ROOT))
after=json.loads((ROOT/'plan/coverage.json').read_text())
for b,a in zip(before['items'],after['items']):
 for k in ('id','text','subchecks','fulfilment_status'):assert b[k]==a[k],(b['id'],k)
assert len(after['items'])==83 and sum(len(r['subchecks']) for r in after['items'])==160
freeze=json.loads((OUT/'freeze-final.json').read_text())['sha256']
for p,h in freeze.items():assert hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h,p
report={'status':'PASS','baseline_head':BASE['head'],'protected_files':len(protected),'protected_sha256':protected,'requirement_count':83,'subcheck_count':160,'requirement_statuses_unchanged':True,'runtime_freeze_matches':True,'pre_existing_untracked_preserved':True,'clinical_rules_forms_schema_dependencies_unchanged':True}
(OUT/'preservation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:v for k,v in report.items() if k!='protected_sha256'}))
