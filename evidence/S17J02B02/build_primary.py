"""Reproduce reviewed receipt/card bytes for B02. No network or source text copies."""
import json,sys,re
from pathlib import Path
from datetime import datetime,timedelta
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from apps.compass.retrieval_corpus import sha
from apps.compass.retrieval_primary import IDENTITIES, PREFIX, POLICY, PIN_FIELDS, STORAGE
E='evidence/S17J02B02/'

def write(path,obj):
 p=ROOT/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
# Verified-TLS acquisition returned by isolated read-only researcher; no original bytes retained.
SOURCES={
'DASS42_RU_TRANSLATION':('2026-10-20T21:32:44.277931+00:00',42572,'2678f43db388d18dcc0e071e7bdbf8fd3eef16a30b653d6f511f12473b3fd21f','Перевод Фаттахова и коллег, официальная страница UNSW; acquisition-2026-10-21'),
'DASS42_RU_FORM':('2026-10-20T21:32:47.102091+00:00',478406,'5d3fa16c44edd0be88dc0448d0a129f706e0d9ef5954d8e7b932291b2fe33c86','DASS-42; перевод Фаттахов–Горобец,2024; exact-PDF-5d3fa16c'),
'DASS42_EN_KEY':('2026-10-20T21:32:48.824516+00:00',15550,'5ceafc6731340b382bdd6eea256ea5f394dfe9897440615911f2cef84a977892','UNSW DASS template; exact-PDF-5ceafc67'),
'DASS42_GUIDANCE':('2026-10-20T21:32:50.871039+00:00',98485,'a4800f9439e4828d57c4bcd243e4a848b50c404740cae05d4990c2a77bd638b5','UNSW DASS FAQ; acquisition-2026-10-21-a4800f94'),
'DASS42_DOWNLOAD_TERMS':('2026-10-20T21:32:52.840601+00:00',42252,'0afb51a8737cc9c895ebfdf01d5ff37e7541d6d2ff68a30ab8a32fbbe554bd39','UNSW DASS download terms; acquisition-2026-10-21-0afb51a8'),
'DASS42_RU_VALIDATION_2025':('2026-10-20T21:32:53.681713+00:00',264960,'26816da0c47c02e14bd8bd0479688e00dfe4d1bcc7181771f58adb4d86b94d17','2025;125(5):103–107; DOI10.17116/jnevro2025125051103; HTML acquisition-2026-10-21')}
FACTS={
'DASS42_RU_FORM':[
(1,'Титул и инструкция; пункты1–16; продолжение на PDFс.2','Какая точная русская форма связана с выпуском HAC?','На официальном бланке указаны DASS, Lovibond и Lovibond(1995), перевод И.М.Фаттахова и Е.А.Горобец(2024). В нём42пункта; это полная DASS-42, а не короткая DASS-21.'),
(1,'Инструкция перед пунктом1','К какому периоду относятся ответы?','Русский бланк спрашивает о самочувствии за предыдущую неделю.')],
'DASS42_EN_KEY':[
(1,'Full42-item DASS — scoring template; обе стороны','Как связаны номера пунктов с отдельными шкалами?','Шаблон полной DASS-42 распределяет номера по трём отдельным шкалам: депрессия, тревога и стресс. Каждая содержит14пунктов.'),
(1,'Scoring notes: full42-item DASS versus DASS21','Почему нельзя удваивать суммы этой полной формы?','Указание шаблона об удвоении относится к DASS-21. Для полной42-пунктовой формы подсчитываются отдельные суммы; этот множитель к ней не относится.')],
'DASS42_RU_TRANSLATION':[
(None,'Основной текст после заголовка: авторы перевода и scoring template','На чём основана сверка русского ключа?','Официальная страница перевода подтверждает одинаковый порядок русских и английских пунктов DASS. Английский шаблон показывает принадлежность номеров шкалам, но его нельзя просто наложить на русскую вёрстку. На этой странице отдельный русский шаблон не опубликован.')],
'DASS42_GUIDANCE':[
(None,'FAQ, вопрос3: permission / public domain','Как отдельно установить основание использования формы и ключа?','Разработчики DASS обозначают опросник как public domain и допускают скачивание и копирование бланков и ключа без отдельного разрешения.'),
(None,'FAQ, вопрос10: lower age limit','Что известно о возрастной рекомендации разработчиков?','FAQ допускает DASS с14лет при обычных языковых навыках.'),
(None,'FAQ, вопросы5 и13: clinical cutoffs / DSM diagnoses','Почему балл не равен категориальному диагнозу?','Разработчики описывают баллы DASS как размерные показатели симптомов и отделяют их от категориальных диагностических инструментов.'),
(None,'FAQ, вопросы9 и21: computer/online; website/app','Какие ограничения есть у электронного проведения?','FAQ допускает компьютерный подсчёт, сохраняя запрет выдавать рассчитанные баллы респонденту и автоматически интерпретировать их. Для сайта или приложения описана ограниченная определённая группа с передачей результатов клиницисту или исследователю; открытый доступ для неопределённого круга людей этим не разрешён.')],
'DASS42_DOWNLOAD_TERMS':[
(None,'Download page: public domain / do not modify or sell','Какие условия сохранения точной формы указаны отдельно?','Страница загрузки разрешает скачивание и копирование DASS, но требует не изменять формы и не продавать сами шкалы ради прибыли.')],
'DASS42_RU_VALIDATION_2025':[
(None,'Резюме → Материал и методы; библиографический блок,с.103–107 статьи','На какой русскоязычной выборке проверялся инструмент?','В статье2025года описана проверка на250русскоязычных пациентах соматического стационара с эмоциональными нарушениями и100контролях. Возраст участников в проверенном доступном тексте не указан; его нельзя восстановить из FAQ или названия шкалы.'),
(None,'Резюме → Материал и методы: перевод и психометрическая проверка','Какие виды проверки описаны в публикации?','Авторы описывают прямой и обратный перевод, лингвистическую и психометрическую проверку русской DASS, включая согласованность и чувствительность к изменениям.')],
}

def build():
 resource='apps/compass/resources/dass42-ru-v1.json';resource_sha=sha((ROOT/resource).read_bytes())
 assert resource_sha=='e4d758dc1ccffc99fba21f238180baead2d354179e3b3d34a1a4842e418325a2'
 report=dict(schema_version=1,slice='S17J02B02',researcher='/root/b02_dass_primary; isolated read-only context',
     primary_sources={},independent_clinical_validation=False,form_comparison=dict(resource_path=resource,resource_sha256=resource_sha,instruction='MATCH',options='4/4 MATCH',items='42/42 MATCH',key_numbers='42/42 MATCH',method='Researcher compared verified-TLS original PDFs in memory; only technical line-break/hyphen normalization; no file mutations'),
     superseded_transport_attempt='Initial Python acquisition lacked certificate-chain verification and is NOT an admission basis. Repeated /usr/bin/curl with default verified TLS, no -k/--insecure, HTTPS-only, TLS>=1.2, all HTTP200/exit0.',
     limitation='HTML article SHA is a receipt for one dynamic response, not an eternal work identity. No original response bytes/fulltexts retained or indexed. Current means available at checked acquisition, not Ministry clinical approval.')
 content=dict(version='DASS42-reviewed-facts-1',reviewer='Codex main; isolated read-only primary-source comparison',independent_clinical_validation=False,documents={})
 records=[]
 for doc,(kind,locator,urls) in IDENTITIES.items():
  at,size,source_sha,version=SOURCES[doc];url=next(iter(urls));publisher='Медиасфера — страница публикации' if kind=='validation_study' else 'Официальный сайт DASS, UNSW'
  row=dict(verified=True,tls_verified=True,transport='/usr/bin/curl; default certificate verification; HTTPS-only; TLS>=1.2; HTTP200/exit0',source_url=url,source_version=version,checked_at=at,sha256=source_sha,byte_length=size,media_type='application/pdf' if locator=='pdf_page' else 'text/html',locator_kind=locator)
  if doc in {'DASS42_RU_FORM','DASS42_EN_KEY'}:row.update(resource_match_verified=True,resource_sha256=resource_sha)
  if kind=='validation_study':row.update(doi='10.17116/jnevro2025125051103',response_media_type='text/html; charset=utf-8',dynamic_html=True)
  report['primary_sources'][doc]=row
  authors='S.H.Lovibond; P.F.Lovibond. Перевод: И.М.Фаттахов; Е.А.Горобец,2024' if kind=='instrument_form' else 'NOT_STATED_IN_DOCUMENT'
  title=version
  if kind=='validation_study':
   authors='Фаттахов И.М.; Горобец Елена Анатольевна; Хайруллин И.Х.; Есин Радий Германович'
   title='Русскоязычная версия шкалы депрессии, тревоги и стресса. Журнал неврологии и психиатрии им.С.С.Корсакова.2025;125(5):103–107. DOI10.17116/jnevro2025125051103'
  fragments=[]
  for i,(page,section,purpose,text) in enumerate(FACTS[doc],1):
   text=re.sub(r'(?<=[А-Яа-яЁё])(?=\d)|(?<=\d)(?=[А-Яа-яЁё])', ' ', text)
   text=re.sub(r'(?<=\.)(?=[А-ЯЁ])', ' ', text)
   fragments.append(dict(fragment_id=f'{doc}-F{i:02}',page=page,section=section,claim_type='fact',paraphrase=text,quote=None,required_context=[],purpose=purpose,volume_justification='Один самостоятельный справочный факт/граница; без текста вопросов, ключа, таблиц, дословной выдержки или полного источника.'))
  bundle=dict(schema_version=1,representation='reviewed_cards',document_id=doc,source_sha256=source_sha,source_version=version,source_url=url,document_type=kind,
    attribution=dict(title=title,authors=authors,source=publisher,locator='Физическая страница PDF' if locator=='pdf_page' else ('DASS FAQ: точный номер вопроса' if doc=='DASS42_GUIDANCE' else 'Основной текст страницы после заголовка' if doc=='DASS42_RU_TRANSLATION' else 'Условия перед ссылками на загрузку' if doc=='DASS42_DOWNLOAD_TERMS' else 'Библиографический блок; Резюме → Материал и методы')),fragments=fragments)
  artifact=PREFIX+doc+'.cards.json';write(artifact,bundle);ah=sha((ROOT/artifact).read_bytes())
  decision=dict(source_sha256=source_sha,artifact_sha256=ah,fragment_ids=[f['fragment_id'] for f in fragments],quoted_characters=0,basis='GK1259_5_FACTS',text_and_context_verified=True,attribution_verified=True,source_type_preserved=True,full_pdf_license_verified=False,
    cards=[dict(fragment_id=f['fragment_id'],page=f['page'],section=f['section'],purpose=f['purpose'],authored_text_sha256=sha(f['paraphrase'].encode()),source_check='Main review of exact researcher source report/locators; researcher verified primary bytes and exact local form/key. No new medical rule.',scope_check=f['volume_justification']) for f in fragments])
  content['documents'][doc]=decision
  record=dict(document_id=doc,document_family='DASS42',path=PREFIX+doc+'.receipt.json',sha256=source_sha,publisher=publisher,source_url=url,document_type=kind,source_version=version,
    official_status='current',official_origin_verified=True,status='approved',admission_id='S17J02B02-'+doc+'-facts-1',decision_origin='Exact publisher primary source; verified TLS acquisition+SHA; authored fact cards only under separate scoped review, not fulltext licence or clinical approval',verified_at=at,review_due_at=(datetime.fromisoformat(at)+timedelta(days=1)).isoformat(),
    population=dict(verified=True,text='Instrument/study metadata only; Russian study age unknown; FAQ general14+ distinct from HAC demo18–120; not personal clinical applicability',evidence=[E+'source-review.json']),
    indications=dict(verified=True,text='DASS-42 source/form/key/validation/rights reference only; no diagnosis, medication indication or dosing',evidence=[E+'source-review.json']),
    representation='reviewed_cards',artifact_path=artifact,artifact_sha256=ah,original_storage=STORAGE,locator_kind=locator,byte_length=size,media_type=row['media_type'],
    full_text_rights=dict(status='not_admitted',scopes=[],limitation='No original PDF/HTML/article/key/questions retained in retrieval corpus. Reproduction of existing exact form in app remains separately governed by S07.'),
    rights=dict(status='verified',representation='reviewed_cards',scopes=['local_store','local_index','display_reference'],index_fields=['paraphrase'],evidence=[E+'rights-decision.md',E+'content-review.json'],content_review=dict({k:decision[k] for k in ['basis','fragment_ids','quoted_characters','artifact_sha256']},purpose_and_volume_reviewed=True,attribution_reviewed=True,record_path=E+'content-review.json'),limitation='Exact independently authored facts only, no original quotes/fulltexts/keys. New source/claim/representation requires explicit new review.'))
  records.append(record)
 write(E+'source-review.json',report);write(E+'content-review.json',content)
 rh=sha((ROOT/(E+'source-review.json')).read_bytes());pins=[]
 for item in records:
  item['rights']['evidence_sha256']={p:sha((ROOT/p).read_bytes()) for p in item['rights']['evidence']}
  item['verification']={k:item[k] for k in ['sha256','document_type','source_version','source_url','publisher']}
  item['verification'].update(checked_at=item['verified_at'],evidence=[E+'source-review.json'],evidence_sha256=rh,method='isolated read-only researcher; verified-TLS exact bytes; receipt only; exact form47/47 and key42/42 compared')
  receipt=dict(schema_version=1,document_id=item['document_id'],source_url=item['source_url'],source_sha256=item['sha256'],source_version=item['source_version'],checked_at=item['verified_at'],byte_length=item['byte_length'],media_type=item['media_type'],locator_kind=item['locator_kind'],verification_path=E+'source-review.json',verification_sha256=rh)
  write(item['path'],receipt);item['receipt_sha256']=sha((ROOT/item['path']).read_bytes())
  pin={k:item[k] for k in PIN_FIELDS};pin.update(status='approved',resource_bindings=[dict(path=resource,sha256=resource_sha)] if item['document_id'] in {'DASS42_RU_FORM','DASS42_EN_KEY'} else [])
  pins.append(pin)
 write(POLICY,dict(schema_version=1,sources=pins));write(PREFIX+'registry.json',dict(schema_version=1,policy_version='corpus-admission-primary-receipts-1',sources=records))
 p=json.loads((ROOT/'data/retrieval/admission-packages.json').read_bytes())
 p['enabled']=['J02','J02B','DASS42']
 if not any(row['id']=='DASS42' for row in p['packages']):p['packages'].append(dict(id='DASS42',root=PREFIX.rstrip('/'),registry=PREFIX+'registry.json'))
 write('data/retrieval/admission-packages.json',p)
 print('Six pinned primary receipts;',sum(len(v) for v in FACTS.values()),'authored facts; no original text stored')
if __name__=='__main__':build()
