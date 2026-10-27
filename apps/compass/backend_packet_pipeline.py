"""Complete packet execution; partial model assertions never become a diagnosis."""
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time

from . import backend_context_packets as packets, backend_diagnosis_codec as codec
from . import backend_diagnosis_service as diagnostic, backend_risk_context as risk
from . import backend_snapshot as snapshots, backend_sources as sources, backend_model as adapter
from .backend_analyses import validate_schema

VERSION='packet-analysis-v2'
EXECUTION_VERSION='fe03b-packets-v1'
ROOT=Path(__file__).resolve().parents[2]
QUALITY=ROOT/'evidence/FE03B/quality.json'
DEADLINE=180
TOTAL_CAP=4000000
MAX_WORKERS=3
LOCAL_TASK=('This is a local evidence pass, not a full diagnosis. All original records and revisions are supplied across packets. '
 'Only quote unit_id from THIS packet occurrences. Old/unknown/other-person evidence must not establish a current fact. '
 'Use as_of_day and observation_day: only observation_day may establish current diagnostic facts. '
 'Different record dates are chronology, not a current contradiction. Missing evidence in a packet is unknown with empty refs. '
 'For each fact return p (supporting quote IDs), n (denying quote IDs), u (explicit not-assessed quote IDs). '
 'Return empty arrays when absent. Never output state or conflicting: the server combines the cited polarities. '
 'For mania_hypomania and prior_depressive_episode only, explicit OWN past episodes remain positive historical cautions across dates; '
 'family/relative episodes never establish a patient fact. Do not infer an exclusion or duration from absence. No diagnosis.\n')


def config():
    return adapter.Config(model='deepseek-flash',max_input_bytes=16000,max_output_tokens=codec.MAX_OUTPUT_TOKENS,
                          timeout=60,total_micro_usd=TOTAL_CAP)


def release():
    files=['backend_packet_pipeline.py','backend_packet_store.py','backend_context_packets.py','backend_jobs.py']
    return {'version':VERSION,'execution_version':EXECUTION_VERSION,'code':{f:hashlib.sha256(Path(__file__).with_name(f).read_bytes()).hexdigest() for f in files},
            'diagnostic':diagnostic.release(),'risk_prompt_sha256':risk.PROMPT_SHA256,
            'risk_schema_sha256':snapshots.digest(risk.SCHEMA),'deadline_seconds':DEADLINE,
            'total_cap_micro_usd':TOTAL_CAP,'per_call_micro_usd':20000,'max_workers':MAX_WORKERS,'response_format':'signed-local-facts-v1','latest_observation_policy':'same_latest_record_day_v1'}


def eligible(unit, day):
    m=unit['metadata'];event=m['event_at']
    return (isinstance(unit['value'],str) and bool(unit['value'].strip()) and m['current_revision'] is True
            and m['status']=='known' and m['context']=='current' and isinstance(event,str)
            and event[:10]<=day and bool(set(unit['categories']) & {'visits','wellbeing','anamnesis'}))


def observation_day(snapshot,units):
    return max((u['metadata']['event_at'][:10] for u in units if eligible(u,snapshot['day'])),default=None)


def wire(packet):
    """Explicit labels for the model; full compact manifest stays server-side."""
    value={k:deepcopy(v) for k,v in packet.items() if k not in
        ('texts','units','columns','metadata','metadata_columns','occurrence_columns')}
    value['transport'].pop('metadata_indexes',None)
    # Replace only the transport instructions; original task content is unchanged.
    value['task']=('Evidence groups below have literal text and explicit unit_ids. '
        'Quote ONLY a unit_id listed in the SAME group as that exact text. Never use group positions as IDs. '
        'All metadata applies to that group. Each packet is only part of the full history. '
        +packet['task'].removeprefix(packets.PREFIX))
    value['groups']=[]
    for row in packet['units']:
        by_meta={}
        for uid,position,meta in row[3]:by_meta.setdefault(meta,[]).append({'unit_id':uid,'original_position':position})
        for meta,occurrences in by_meta.items():
            value['groups'].append({'text':packet['texts'][row[0]],'unit_ids':[o['unit_id'] for o in occurrences],
                'original_positions':[o['original_position'] for o in occurrences],
                'categories':deepcopy(row[1]),'code':deepcopy(row[2]),
                'metadata':dict(zip(packet['metadata_columns'],deepcopy(packet['metadata'][meta])))})
    return value


def response_schema(branch):
    if branch=='risk':return deepcopy(risk.SCHEMA)
    value=codec.schema(branch)
    ids=list(diagnostic.criteria.release()['conditions'][branch]['facts'])
    value['properties']['facts']['items']=codec.obj({
        'id':{'enum':ids},'p':deepcopy(codec.REFS),'n':deepcopy(codec.REFS),'u':deepcopy(codec.REFS)})
    # Ambiguous local durations remain unknown; no invented negative duration.
    value['properties']['duration']=deepcopy(codec.DURATION)
    value['properties']['duration']['properties']['state']['enum']=['known','unknown']
    return value


def plans(snapshot,operation):
    if operation not in ('risk','diagnosis'):raise adapter.ModelError('operation_unavailable')
    units=risk.prepare_snapshot(snapshot);day=observation_day(snapshot,units)
    result={}
    for branch in (diagnostic.criteria.release()['conditions'] if operation=='diagnosis' else ['risk']):
        value=diagnostic.payload(snapshot,branch) if operation=='diagnosis' else codec.payload(snapshot,'depressive_episode')
        if operation=='risk':
            value.update(task=risk.INSTRUCTION,branch='risk',version=risk.VERSION)
            for key in ('facts','expected_fact_count','duration_unit'):value.pop(key,None)
        else:
            task=value['task'].split('Example JSON',1)[0].replace('{id,state,refs}','{id,p,n,u}')
            value['task']=task+'\n'+LOCAL_TASK
        value.update(as_of_day=snapshot['day'],observation_day=day)
        schema=response_schema(branch)
        try:result[branch]=(packets.prepare(value,schema,config(),split_occurrences=True,request_transform=wire),schema)
        except packets.PacketError:raise adapter.ModelError('input_too_large') from None
    return result


class Cancel:
    def __init__(self,external):self.external=external;self.until=time.monotonic()+DEADLINE
    def is_set(self):return time.monotonic()>=self.until or bool(self.external and self.external.is_set())
    def check(self):
        if time.monotonic()>=self.until:raise adapter.ModelError('timeout')
        if self.external and self.external.is_set():raise adapter.ModelError('cancelled')


def check_response(snapshot,branch,packet,value):
    validate_schema(value,response_schema(branch))
    allowed={o[0] for row in packet['units'] for o in row[3]}
    indexed={u['unit_id']:u for u in risk.prepare_snapshot(snapshot)}
    if branch=='risk':
        refs=[e for c in value['candidates'] for e in c['evidence']]
        if any(e['unit_id'] not in allowed for e in refs):raise adapter.ModelError('packet_evidence_mismatch')
        risk.verify(value,[indexed[i] for i in allowed],snapshots.digest(snapshot))
        return
    condition=diagnostic.criteria.release()['conditions'][branch]
    quotes={q['id']:q for q in value['quotes']}
    if len(quotes)!=len(value['quotes']) or len({(q['unit_id'],q['quote']) for q in quotes.values()})!=len(quotes):
        raise adapter.ModelError('packet_response_invalid')
    for q in quotes.values():
        if q['unit_id'] not in allowed:raise adapter.ModelError('packet_evidence_mismatch')
        diagnostic.legacy._evidence([{'unit_id':q['unit_id'],'quote':q['quote']}],indexed)
    facts={f['id']:f for f in value['facts']}
    if len(facts)!=len(value['facts']) or set(facts)!=set(condition['facts']):raise adapter.ModelError('packet_response_invalid')
    for fact in facts.values():
        refs=fact['p']+fact['n']+fact['u']
        if len(refs)>8 or len(set(refs))!=len(refs) or set(refs)-set(quotes):
            raise adapter.ModelError('packet_response_invalid')
    duration=value['duration'];refs=duration['refs']
    if (len(set(refs))!=len(refs) or set(refs)-set(quotes)
            or duration['state']=='known' and not refs):raise adapter.ModelError('packet_response_invalid')
    d=value['duration']
    if (d['state']=='known') != (d['value'] is not None):raise adapter.ModelError('packet_response_invalid')
    if d['state']=='known' and not codec.literal_duration(d['value'],condition['duration']['unit'],[quotes[i]['quote'] for i in d['refs']]):
        raise adapter.ModelError('packet_response_invalid')


def merge_branch(snapshot,branch,cells):
    """Same latest observation day only; all older assertions remain checkpoints."""
    units={u['unit_id']:u for u in risk.prepare_snapshot(snapshot)}
    day=observation_day(snapshot,units.values())
    conditions=diagnostic.criteria.release()['conditions'][branch]
    assertions={fid:[] for fid in conditions['facts']};durations=[]
    for cell in cells:
        value=cell['response']['value'];quotes={q['id']:q for q in value['quotes']}
        def current_refs(claim,lifetime=False):
            refs=[]
            for ref in claim['refs']:
                q=quotes[ref];unit=units[q['unit_id']]
                if eligible(unit,snapshot['day']) and (unit['metadata']['event_at'][:10]==day or lifetime and claim['state'] in ('present','conflicting')):
                    refs.append((q['unit_id'],q['quote']))
            # Mixed current/historical references cannot prove a current assertion.
            return refs if len(refs)==len(claim['refs']) else []
        for fact in value['facts']:
            for key,state in [('p','present'),('n','denied'),('u','unknown')]:
                claim={'state':state,'refs':fact[key]}
                refs=current_refs(claim,fact['id'] in ('mania_hypomania','prior_depressive_episode'))
                if refs:assertions[fact['id']].append((state,refs))
        refs=current_refs(value['duration'])
        if refs:durations.append((value['duration']['state'],value['duration']['value'],refs))
    pool={};quotes=[]
    def refs_for(evidence):
        result=[]
        for identity in dict.fromkeys(evidence):
            if identity not in pool:
                if len(pool)>=16:raise adapter.ModelError('aggregate_limit')
                pool[identity]='q'+str(len(pool)+1);quotes.append({'id':pool[identity],'unit_id':identity[0],'quote':identity[1]})
            result.append(pool[identity])
        if len(result)>8:raise adapter.ModelError('aggregate_limit')
        return result
    def combine(items):
        pos=[];neg=[];unknown=[]
        for state,refs in items:
            if state=='unknown':unknown+=refs
            elif state=='present':pos+=refs
            elif state=='denied':neg+=refs
            else:pos+=refs[:1];neg+=refs[1:]
        if set(pos)&set(neg):raise adapter.ModelError('packet_response_invalid')
        if unknown and not (pos or neg):return {'state':'unknown','refs':refs_for(unknown)}
        state='conflicting' if pos and neg else 'present' if pos else 'denied' if neg else 'unknown'
        result={'state':state,'refs':refs_for([*pos,*neg])}
        if state=='conflicting':result['present_ref_count']=len(dict.fromkeys(pos))
        return result
    facts=[{'id':fid,**combine(items)} for fid,items in assertions.items()]
    known=[(v,refs) for state,v,refs in durations if state=='known']
    uncertain=[refs for state,_,refs in durations if state!='known']
    distinct={v for v,_ in known}
    if uncertain or len(distinct)>1:
        # Unknown is conservative; conflicting positive numeric durations cannot
        # be represented as signed symptom claims without inventing a denial.
        duration={'state':'unknown','value':None,'refs':refs_for([q for _,rs in known for q in rs]+[q for rs in uncertain for q in rs])}
    elif known:duration={'state':'known','value':known[0][0],'refs':refs_for([q for _,rs in known for q in rs])}
    else:duration={'state':'unknown','value':None,'refs':[]}
    merged={'quotes':quotes,'facts':facts,'duration':duration}
    validate_schema(merged,codec.schema(branch));return merged


def historical_cautions(snapshot,branch,cells):
    units={u['unit_id']:u for u in risk.prepare_snapshot(snapshot)}
    day=observation_day(snapshot,units.values());result={}
    for cell in cells:
        value=cell['response']['value'];quotes={q['id']:q for q in value['quotes']}
        for fact in value['facts']:
            if fact['id'] not in ('mania_hypomania','prior_depressive_episode') or not fact['p']:continue
            for ref in fact['p']:
                q=quotes[ref];u=units[q['unit_id']];m=u['metadata']
                if (u['code']=='family_history' or m['current_revision'] is not True or m['status']!='known'
                        or not isinstance(m['event_at'],str) or m['event_at'][:10]>snapshot['day']):continue
                if m['context']=='current' and m['event_at'][:10]==day:continue
                if m['context'] not in ('current','cumulative_history'):continue
                key=(branch,fact['id'],q['unit_id'],q['quote'])
                result[key]={'branch':branch,'fact_id':fact['id'],'unit_id':q['unit_id'],'quote':q['quote'],
                    'event_at':m['event_at'],'context':m['context'],'interpretation':'historical_assertion_requires_physician_review'}
    return list(result.values())


def outcome(snapshot,operation,proof):
    if operation=='risk' and proof.get('incomplete'):
        if proof.get('runtime_sha256')!=snapshots.digest(release()) or proof['incomplete'] not in {
                'timeout','budget_exceeded','packet_response_invalid','packet_evidence_mismatch','packet_incomplete',
                'packet_quality_not_admitted','input_too_large','aggregate_limit'}:raise adapter.ModelError('packet_manifest_mismatch')
        report=risk.analyze_snapshot(snapshot,synthetic=True)
        report['errors']=[{'code':proof['incomplete'],'stage':'model_candidate_evaluation'}]
        return {**deepcopy(report['structured']),'risk_context_report':report}
    planned=plans(snapshot,operation);expected=[]
    for branch,(plan,_) in planned.items():
        for packet,sha in zip(plan['packets'],plan['packet_sha256']):expected.append((branch,packet,sha))
    cells=proof['cells']
    if proof.get('runtime_sha256')!=snapshots.digest(release()) or len(cells)>len(expected):raise adapter.ModelError('packet_manifest_mismatch')
    for cell,(branch,packet,sha) in zip(cells,expected):
        if (cell['branch']!=branch or cell['packet_index']!=packet['transport']['packet_index'] or cell['payload_sha256']!=sha):
            raise adapter.ModelError('packet_manifest_mismatch')
        check_response(snapshot,branch,packet,cell['response']['value'])
    incomplete=proof.get('incomplete')
    if not incomplete and len(cells)!=len(expected):raise adapter.ModelError('packet_incomplete')
    if operation=='diagnosis':
        if incomplete:raise adapter.ModelError('packet_incomplete')
        merged={branch:merge_branch(snapshot,branch,[c for c in cells if c['branch']==branch]) for branch in planned}
        cautions=[c for branch in planned for c in historical_cautions(snapshot,branch,[x for x in cells if x['branch']==branch])]
        # Cumulative-history cautions cannot be recast as current symptom proof.
        # Hold the narrow automatic hypothesis for explicit physician review.
        for caution in cautions:
            if caution['context']=='cumulative_history':
                next(f for f in merged[caution['branch']]['facts'] if f['id']==caution['fact_id']).update(state='unknown',refs=[])
                next(f for f in merged[caution['branch']]['facts'] if f['id']==caution['fact_id']).pop('present_ref_count',None)
        context=diagnostic.named_interpret(snapshot,merged)
        if cautions and context['leading'] is not None:
            raw=deepcopy(context['raw']);raw['leading']=None;context=diagnostic.interpret(snapshot,raw)
        return {'diagnosis_report':{'context':context,'named_assertions':merged,'model_metadata':{
            'codec':VERSION,'packet_count':len(cells),'pipeline_deadline_seconds':DEADLINE,
            'observation_day':observation_day(snapshot,risk.prepare_snapshot(snapshot)),'historical_cautions':cautions,
            'calls':[c['response']['metadata'] for c in cells]}}}
    report=risk.analyze_snapshot(snapshot,synthetic=True)
    if incomplete:
        report['errors']=[{'code':incomplete,'stage':'model_candidate_evaluation'}]
    else:
        proposals={}
        for cell in cells:
            for c in cell['response']['value']['candidates']:
                key=snapshots.digest([c['topic'],sorted((e['unit_id'],e['quote']) for e in c['evidence'])]);proposals[key]=c
        if len(proposals)>16:raise adapter.ModelError('aggregate_limit')
        report.update(model_candidates=risk.verify({'candidates':list(proposals.values())},risk.prepare_snapshot(snapshot),snapshots.digest(snapshot)),
            model_evaluation='candidates_only',errors=[],model_metadata={'provider':'deepseek','requested_model':'deepseek-flash',
            'test_double':any(c['response']['metadata'].get('test_double') is True for c in cells),'packet_count':len(cells)})
    return {**deepcopy(report['structured']),'risk_context_report':report}


def execute(operation,snapshot,model=None,store=None,cancel=None,*,workers=None):
    if snapshot.get('policy')!='synthetic-inputs-v1' or snapshot['patients'][0]['synthetic']!=1:raise adapter.ModelError('synthetic_only')
    runtime=snapshots.digest(release())
    default_model=model is None
    worker_count=(MAX_WORKERS if default_model else 1) if workers is None else workers
    if type(worker_count) is not int or not 1 <= worker_count <= MAX_WORKERS:raise adapter.ModelError('invalid_config')
    if model is None:
        try:q=json.loads(QUALITY.read_text());admitted=q.get('pass') is True and q.get('runtime_sha256')==runtime
        except (OSError,ValueError,TypeError):admitted=False
        if not admitted:
            if operation=='risk':
                proof={'runtime_sha256':runtime,'cells':[],'incomplete':'packet_quality_not_admitted'}
                return {**outcome(snapshot,operation,proof),'packet_proof':proof}
            raise adapter.ModelError('packet_quality_not_admitted')
        model=adapter.DeepSeek(config(),adapter.Budget(ROOT/'var/deepseek-budget.sqlite3'))
    frozen=deepcopy(snapshot);control=Cancel(cancel or store)
    proof={'runtime_sha256':runtime,'cells':[]}
    try:planned=plans(frozen,operation)
    except adapter.ModelError as exc:
        if operation!='risk' or exc.code!='input_too_large':raise
        proof['incomplete']='input_too_large'
        return {**outcome(frozen,operation,proof),'packet_proof':proof}
    tasks=[(branch,packet,sha,schema) for branch,(plan,schema) in planned.items()
           for packet,sha in zip(plan['packets'],plan['packet_sha256'])]
    def process(task):
        branch,packet,sha,schema=task
        if store:store.assert_active()
        control.check()
        if runtime!=snapshots.digest(release()) or frozen['backend_sources']!=sources.capture():
            raise adapter.ModelError('sources_or_engine_changed')
        index=packet['transport']['packet_index']
        response=store.load(operation,branch,index,sha,runtime) if store else None
        if response is None:
            response=model.generate(wire(packet),schema,synthetic=True,cancel=control)
            check_response(frozen,branch,packet,response['value'])
            control.check()
            if runtime!=snapshots.digest(release()) or frozen['backend_sources']!=sources.capture():
                raise adapter.ModelError('sources_or_engine_changed')
            if store:store.save(operation,branch,index,sha,runtime,response)
        else:check_response(frozen,branch,packet,response['value'])
        return {'branch':branch,'packet_index':index,'payload_sha256':sha,'response':deepcopy(response)}
    completed={};failure=None;next_task=0
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        pending={}
        while next_task<len(tasks) and len(pending)<worker_count:
            pending[pool.submit(process,tasks[next_task])]=next_task;next_task+=1
        try:
            while pending:
                control.check()
                done,_=wait(pending,timeout=.1,return_when=FIRST_COMPLETED)
                for future in done:
                    index=pending.pop(future)
                    completed[index]=future.result()
                # Do not schedule replacements until all finished responses in
                # this batch have passed. Running valid responses can checkpoint.
                while next_task<len(tasks) and len(pending)<worker_count:
                    pending[pool.submit(process,tasks[next_task])]=next_task;next_task+=1
        except (adapter.ModelError,ValueError) as exc:
            failure=exc
            for future in pending:future.cancel()
    proof['cells']=[completed[i] for i in sorted(completed)]
    if failure is not None:
        code=getattr(failure,'code','packet_response_invalid')
        if code=='cancelled' and time.monotonic()>=control.until:code='timeout'
        if operation!='risk' or code in ('cancelled','sources_or_engine_changed'):
            if isinstance(failure,adapter.ModelError):raise failure
            raise adapter.ModelError(code) from None
        proof['incomplete']=code if code in {'timeout','budget_exceeded','packet_response_invalid','packet_evidence_mismatch'} else 'packet_incomplete'
        return {**outcome(frozen,operation,proof),'packet_proof':proof}
    try:control.check()
    except adapter.ModelError as exc:
        if operation!='risk' or exc.code!='timeout':raise
        proof['incomplete']='timeout'
        return {**outcome(frozen,operation,proof),'packet_proof':proof}
    if runtime!=snapshots.digest(release()) or frozen['backend_sources']!=sources.capture():raise adapter.ModelError('sources_or_engine_changed')
    try:completed=outcome(frozen,operation,proof)
    except adapter.ModelError as exc:
        if operation!='risk' or exc.code!='aggregate_limit':raise
        proof['incomplete']='aggregate_limit';completed=outcome(frozen,operation,proof)
    return {**completed,'packet_proof':proof}


def verify_publication(snapshot,operation,value,proof,store):
    for cell in proof['cells']:
        saved=store.load(operation,cell['branch'],cell['packet_index'],cell['payload_sha256'],proof['runtime_sha256'])
        if saved!=cell['response']:raise adapter.ModelError('packet_checkpoint_mismatch')
    if outcome(snapshot,operation,proof)!=value:raise adapter.ModelError('packet_projection_mismatch')
