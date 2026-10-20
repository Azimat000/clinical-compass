"""Reproduce exact reviewed source records; new scope never rewrites legacy J02."""
import copy,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from apps.compass.retrieval_corpus import digest,sha
from evidence.S17J02B.review_core import MAP
AT='2026-10-21T00:11:23+03:00';DUE='2026-10-22T00:11:23+03:00'
PREFIX='evidence/S17J02B/'
def write(p,o): (ROOT/p).write_text(json.dumps(o,ensure_ascii=False,indent=2)+'\n')
old=json.loads((ROOT/'data/retrieval/source-registry.json').read_text())
matrix=json.loads((ROOT/'data/retrieval/coverage-matrix.json').read_text())
review=dict(version='S17J02B-reviewed-core-1',reviewed_at='2026-10-21T00:24:16+03:00',reviewer='Codex main agent: direct PDF/content audit plus isolated read-only source and legal researchers; not independent clinical approval',independent_clinical_validation=False,documents={},scope='34 new authored factual notes; two old purpose-specific quotes unchanged; no full text or new quote. Source clauses and HAC policy boundaries have distinct origins.')
records=[]
for prior in old['sources'][:2]:
 item=copy.deepcopy(prior);doc=item['document_id'];di=0 if doc=='KR301_3' else 1
 path=f'data/retrieval/packages/J02B/{doc}.json';data=(ROOT/path).read_bytes();bundle=json.loads(data)
 rows=[]
 for f in bundle['fragments']:
  num=int(f['fragment_id'].split('-F')[-1]);links=[]
  for c in matrix['cells']:
   if c['direction']!=('depression' if di==0 else 'generalized_anxiety_disorder'):continue
   suffix=c['id'].split('-',2)[-1]
   for aspect,pair in MAP.get(suffix,{}).items():
    if num in pair[di]: links.append(dict(unit_id=c['id'],aspect=aspect))
  if num>=6: assert links, f['fragment_id']+' unmapped new fact'
  pages=[f['page']]
  if doc=='KR301_3' and num==14:pages=[33,34]
  if doc=='KR457_3' and num==8:pages=[10,11,12]
  if doc=='KR457_3' and num==10:pages=[11,12]
  if doc=='KR457_3' and num in [17,18]:pages=[31,32]
  if doc=='KR457_3' and num==19:pages=[32,33]
  rows.append(dict(fragment_id=f['fragment_id'],page=f['page'],supporting_pages=pages,fragment_sha256=digest(f),authored_text_sha256=sha(f['paraphrase'].encode()),claim_type=f['claim_type'],purpose=f['purpose'],coverage_links=links,source_check='PASS: main agent inspected original physical page and adjacent context; read-only content auditor checked all F06–F22; five coordinate/phrasing concerns resolved in draft-audit.md',scope_check='Selected factual reference for own frozen HAC question; independent language; no table/key/dosing grid/treatment algorithm or sequential chapter reconstruction',clinical_origin='Only source-supported clinical clause; factual population metadata also verified in official API',boundary_origin='Explicit HAC limitation, not Ministry guideline recommendation or approved clinical rule',policy_evidence=['docs/architecture/retrieval-coverage-contract.md','docs/clinical/followup-recommendation-spec.md'],new_fact=num>=6))
 cr=copy.deepcopy(item['rights']['content_review']);cr.update(fragment_ids=[f['fragment_id'] for f in bundle['fragments']],artifact_sha256=sha(data),record_path=PREFIX+'source-content-review.json')
 review['documents'][doc]=dict(source_sha256=item['sha256'],artifact_sha256=sha(data),fragment_ids=cr['fragment_ids'],quoted_characters=cr['quoted_characters'],basis=cr['basis'],text_and_context_verified=True,attribution_verified=True,source_type_preserved=True,full_pdf_license_verified=False,cards=rows)
 item.update(admission_id=f'S17J02B-{doc}-reviewed-core-1',decision_origin='New exact scope reviewed independently from J02: authored factual notes selected by frozen HAC matrix, GK1259(5); old two necessary quotes retained under GK1274(1)(1); no fulltext license or independent clinical validation',verified_at=AT,review_due_at=DUE,artifact_path=path,artifact_sha256=sha(data))
 item['rights'].update(content_review=cr,evidence=[PREFIX+'rights-decision.md',PREFIX+'source-content-review.json'],limitation='Only exact reviewed J02B JSON. Index paraphrase only; old onequote/source retained separately, no newquotes/fullPDF/OCR/tables/keys/algorithms. Not personal prescribing or complete dossiers.')
 item['verification'].update(checked_at=AT,evidence=[PREFIX+'research.md'],evidence_sha256=sha((ROOT/(PREFIX+'research.md')).read_bytes()),method='isolated_read_only_researcher_official_API_current_status_and_network_PDF_SHA_match; main_exact_local_content_review')
 item['population']['evidence']=[PREFIX+'research.md'];item['indications']['evidence']=[PREFIX+'research.md']
 records.append(item)
write(PREFIX+'source-content-review.json',review)
for item in records:
 item['rights']['evidence_sha256']={p:sha((ROOT/p).read_bytes()) for p in item['rights']['evidence']}
write('data/retrieval/packages/J02B/registry.json',dict(schema_version=1,policy_version='corpus-admission-2-reviewed-cards',sources=records))
policy=dict(schema_version=1,enabled=['J02','J02B'],packages=[dict(id='J02',root=None,registry='data/retrieval/source-registry.json'),dict(id='J02B',root='data/retrieval/packages/J02B',registry='data/retrieval/packages/J02B/registry.json',replaces={i['document_id']:digest(i) for i in old['sources'][:2]})])
write('data/retrieval/admission-packages.json',policy)
print('New exact reviewed package: two KR replacements; original J02 records untouched')
