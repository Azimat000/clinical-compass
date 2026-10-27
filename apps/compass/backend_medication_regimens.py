"""Independent, source-bound checks for a narrowly scoped synthetic draft.

A technical pass never grants clinical/registration admission. Unknown inputs
cannot pass. The v1 partial checker remains available for historical callers.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from . import backend_medication_safety as legacy

ROOT=Path(__file__).resolve().parents[2]
CATALOG=ROOT/'data/backend/medication-regimens-v2.json'
VERSION='medication-regimens-v2'


def release():
    value=json.loads(CATALOG.read_text())
    if (value['version']!=VERSION or value['mode']!='synthetic_only' or value['clinical_review'] is not None
            or hashlib.sha256((ROOT/value['evidence']).read_bytes()).hexdigest()!=value['evidence_sha256']):
        raise ValueError('regimen_catalog_not_admitted')
    return value


def runtime():
    return {'version':VERSION,'catalog_sha256':legacy.digest(release()),
            'engine_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def evaluate(candidate,patient,*,at=None):
    at=at or datetime.now(timezone.utc)
    if at.tzinfo is None:raise ValueError('timezone_required')
    if not isinstance(candidate,dict) or not isinstance(patient,dict):raise ValueError('structured_input_required')
    candidate,patient=deepcopy(candidate),deepcopy(patient)
    catalog=release();checks=[];pid=candidate.get('product_id')
    product=catalog['products'].get(pid) if isinstance(pid,str) else None
    source=catalog['sources'][product['source_id']] if product else None
    def fact(key):
        f=patient.get(key)
        if not isinstance(f,dict) or not isinstance(f.get('refs'),list) or not f['refs'] or any(not isinstance(r,str) or not r for r in f['refs']):return None,[]
        return f.get('value'),f['refs']
    def add(code,state,reason,section='scope',refs=()):
        checks.append({'code':code,'state':state,'reason':reason,'input_refs':list(refs),
            'source':None if source is None else {'id':product['source_id'],'url':source['pdf_url'],
                'sha256':source['pdf_sha256'],'section':section,'pages':source['locators'].get(section,[])}})
        if section=='choice' and product is not None:
            checks[-1]['source']={**product['choice_source'],'section':'clinical_choice'}
    add('mode','pass' if patient.get('synthetic') is True and patient.get('mode')=='synthetic_only' else 'block','Только явно вымышленные сведения.')
    if not product:
        add('product','unknown','Точный препарат не входит в проверенную область.')
    else:
        add('product','pass','Точная регистрация/форма найдена, клинический допуск отдельно.')
        checked=datetime.fromisoformat(source['checked_at']);due=datetime.fromisoformat(source['review_due_at'])
        fresh=checked<=at<due<=checked+timedelta(days=1)
        add('source_document','pass' if fresh and source['document_status']=='official_version_observed' else 'unknown',
            'Точная официальная версия инструкции наблюдена и сверена; юридический статус регистрации этим не устанавливается.')
        age,refs=fact('age')
        add('age','pass' if type(age) is int and product['age_min']<=age<=65 else 'unknown',
            'Проверенная ветка: взрослые до 65 лет; пограничный/неизвестный возраст требует уточнения.','age',refs)
        for field in ('form','unit','strength_mg'):
            v=candidate.get(field)
            valid=(legacy.number(v) is not None and v in product['strengths_mg']) if field=='strength_mg' else v==product[field]
            add(field,'pass' if valid else 'block','Проверка точной формы, единицы и силы таблетки.','form')
        add('indication','pass' if candidate.get('indication') in product['indications'] else 'unknown',
            'Проверка зарегистрированного показания в поддерживаемой ветке.','indications')
        allergens,refs=fact('allergies');complete,crefs=fact('allergies_complete')
        groups=[{'macrogol','macrogol_6000','polyethylene_glycol_1521','polyethylene_glycol'},
                {'hypromellose','hypromellose_6cp','hypromellose_2910'},
                {'microcrystalline_cellulose','microcrystalline_cellulose_200'}]
        known=set(catalog['products']) | {p['ingredient'] for p in catalog['products'].values()} | {e for p in catalog['products'].values() for e in p['excipients']}
        known.update(x for g in groups for x in g)
        valid=isinstance(allergens,list) and all(isinstance(x,str) and x in known for x in allergens)
        codes={pid,product['ingredient'],*product['excipients']}
        for group in groups:
            if codes.intersection(group):codes.update(group)
        add('allergies','unknown' if not valid else 'block' if codes.intersection(allergens) else 'pass',
            'Сверка точного препарата, действующего и всех перечисленных вспомогательных веществ.','composition',refs)
        add('allergies_complete','pass' if complete is True else 'unknown','Требуется явное подтверждение полноты сверки аллергий.','contraindications',crefs)
        add('excipient_coverage','pass' if product['excipient_coverage']=='instruction_enumerated' and product['excipients'] else 'unknown',
            'Состав перечислен по точной инструкции, включая оболочку.','composition')
        for key in product['required_facts']:
            value,refs=fact(key);definition=product['required_facts'][key]
            add(key,'unknown' if type(value) is not bool else 'pass' if value is False else 'block' if definition['kind']=='contraindication' else 'unknown',
                definition['question'],definition['section'],refs)
        for general,specific in [('hepatic_impairment','hepatic_failure_child_pugh_a_b_c'),
                ('renal_impairment','severe_renal_impairment'),('renal_impairment','renal_egfr_below60'),
                ('seizure_history','epilepsy'),('epilepsy','uncontrolled_epilepsy')]:
            a,ar=fact(general);b,br=fact(specific)
            if a is False and b is True:
                add('conflict_'+general+'_'+specific,'unknown','Общие и уточняющие сведения о заболевании противоречат друг другу.','cautions',ar+br)
        phase=candidate.get('phase');goal,refs=fact('goal')
        add('goal','pass' if phase==goal and goal in ('initiation','maintenance') else 'unknown',
            'Начало и продолжение различаются. Для изменения/отмены нужна отдельная индивидуальная схема.','dose',refs)
        meds,mrefs=fact('medications');full,refs=fact('medications_complete')
        add('medications_complete','pass' if full is True else 'unknown',
            'Сверить назначенное, фактическое, безрецептурное и недавно отменённое.','interactions',refs)
        if not isinstance(meds,list):
            add('medications','unknown','Состав лекарств не установлен.','interactions',mrefs)
            meds=None
        dose=legacy.number(candidate.get('daily_dose_mg'));strength=legacy.number(candidate.get('strength_mg'));freq=candidate.get('times_per_day')
        low,high=map(lambda x:Decimal(str(x)),product['daily_mg'])
        add('dose','pass' if dose is not None and low<=dose<=high else 'block','Доза в пределах точной поддерживаемой взрослой ветки.','dose')
        add('frequency','pass' if type(freq) is int and freq==product['times_per_day'] else 'block','Кратность по точной инструкции.','dose')
        count=dose/strength/freq if dose and strength and strength>0 and type(freq) is int and freq>0 else None
        divided=count is not None and count>0 and (count==count.to_integral_value() or candidate.get('strength_mg') in product['split_strengths_mg'] and count*2==(count*2).to_integral_value())
        add('tablet_divisibility','pass' if divided else 'unknown','Доза должна получаться подтверждённым числом целых/равных половин таблеток.','form')
        same=[]
        if meds is not None:
            for i,med in enumerate(meds):
                if not isinstance(med,dict) or not isinstance(med.get('ingredient'),str) or not med.get('refs'):
                    add('medication_'+str(i),'unknown','Неполная кодированная сверка препарата.','interactions',mrefs);continue
                ingredient=med['ingredient'];other=catalog['products'].get(med.get('product_id')) if isinstance(med.get('product_id'),str) else None
                if other and other['ingredient']!=ingredient:
                    add('medication_'+str(i),'unknown','Код препарата противоречит веществу.','interactions',med['refs']);continue
                if med.get('state')=='recently_stopped':
                    add('medication_'+str(i),'unknown','Недавняя отмена требует проверенного интервала перехода; он не выводится из даты или рассказа.','interactions',med['refs']);continue
                if med.get('state')!='current':
                    add('medication_'+str(i),'unknown','Не установлена актуальность препарата.','interactions',med['refs']);continue
                if ingredient==product['ingredient']:
                    same.append(med)
                    continuing=(phase=='maintenance' and len(meds)==1 and med.get('product_id')==pid
                        and med.get('prescribed') is True and med.get('actual') is True
                        and all(legacy.number(med.get(k)) is not None and legacy.number(med[k])==legacy.number(candidate.get(k)) for k in ('daily_dose_mg','strength_mg'))
                        and type(med.get('times_per_day')) is int and med['times_per_day']==freq
                        and all(med.get(k)==candidate.get(k) for k in ('unit','form')))
                    add('medication_'+str(i),'pass' if continuing else 'block',
                        'Точное продолжение одного назначенного и фактического режима; иначе дубль/расхождение.','interactions',med['refs'])
                else:
                    rule=product['interactions'].get(ingredient)
                    add('medication_'+str(i),'block' if rule and rule['state']=='block' else 'unknown',
                        rule['reason'] if rule else 'Сочетание выходит за проверенную монотерапию.','interactions',med['refs'])
            if len(same)>1:add('duplicate','block','Несколько записей одного вещества: дублирование не разрешается.','interactions',mrefs)
            allowed=(phase=='initiation' and len(meds)==0) or (phase=='maintenance' and len(meds)==1 and len(same)==1)
            add('monotherapy_scope','pass' if allowed else 'unknown','Поддержана только монотерапия; сочетания/переходы требуют отдельной проверки.','interactions',mrefs)
        if phase=='initiation':
            add('initial_dose','pass' if dose==Decimal(str(product['initial_daily_mg'])) else 'block','Начальная доза берётся из инструкции, а не из максимума диапазона.','dose')
        elif phase=='maintenance':
            response,rrefs=fact('response');tolerance,trefs=fact('tolerability')
            add('response','pass' if response=='effective' else 'unknown','Продолжение требует известного достаточного ответа.','choice',rrefs)
            add('tolerability','pass' if tolerance=='good' else 'unknown','Продолжение требует сверенной хорошей переносимости.','cautions',trefs)
        # Response and tolerability still inform initiation after a previous trial.
        tolerance,refs=fact('tolerability')
        add('adverse_events','pass' if tolerance=='good' else 'unknown','Неизвестная переносимость/нежелательные явления требуют уточнения.','cautions',refs)
        if product['line']=='second':
            prior,refs=fact('prior_first_line')
            add('treatment_line','pass' if prior in ('ineffective','intolerant') else 'unknown',
                'Авиандр рассматривается во второй линии ГТР после сверенного ответа/переносимости первой линии.','choice',refs)
        else:
            add('treatment_line','pass','Первая линия в поддерживаемой клинической ветке.','choice')
    state='block' if any(c['state']=='block' for c in checks) else 'unknown' if any(c['state']=='unknown' for c in checks) else 'pass'
    expiry=min(at+timedelta(days=1),datetime.fromisoformat(source['review_due_at'])) if source else at+timedelta(days=1)
    return {'version':VERSION,**runtime(),'state':state,'synthetic_eligible':state=='pass','eligible':False,
            'clinical_release':False,'applied':False,'checked_at':at.isoformat(),'expires_at':expiry.isoformat(),
            'input_sha256':legacy.digest({'candidate':candidate,'patient':patient}),'checks':checks,
            'release_gates':{'registration_legal_status':'unknown','independent_clinical_review':'not_performed'},
            'coverage':{'restrictions':'enumerated_instruction_narrow_adult_scope','interactions':'monotherapy_only',
                        'phases':['initiation','exact_effective_tolerated_continuation']}}


def verify(candidate,patient,report,*,at=None):
    if evaluate(candidate,patient,at=datetime.fromisoformat(report['checked_at']))!=report:
        raise ValueError('regimen_report_mismatch')
    if not datetime.fromisoformat(report['checked_at'])<=(at or datetime.now(timezone.utc))<datetime.fromisoformat(report['expires_at']):
        raise ValueError('regimen_report_expired_or_future')
    return True
