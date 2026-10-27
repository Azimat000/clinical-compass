"""Repeatable synthetic longitudinal audit. Never opens an existing database.

Uses real application HTTP handlers through Flask's in-process client, not a
browser or external clinical validation. Run separately from any real data.
"""
import argparse
from datetime import timedelta, datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import secrets
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from werkzeug.security import generate_password_hash
from apps.compass import access, assessments, decisions, events, records, communication
from apps.compass.db import connect, migrate, now
from apps.compass.repository import seed_demo
from apps.compass.web import create_app


def run(path):
    if path.exists():
        raise ValueError('Refusing to overwrite an existing database')
    db = connect(path)
    migrate(db)
    seed_demo(db)
    app = create_app(path)
    password = secrets.token_urlsafe(24)
    hashed = generate_password_hash(password, method='scrypt:32768:8:1')
    docid = 'cycle-doctor'
    db.execute('INSERT INTO users VALUES(?,?,?,?,0)', (docid, 'doctor', 'Врач — синтетический стенд', hashed))
    clients = {}
    checks = 0
    started = time.perf_counter()
    latencies = []

    def expect(condition, label):
        nonlocal checks
        checks += 1
        if not condition:
            raise AssertionError(label)

    def scalar(sql, args=()):
        return db.execute(sql, args).fetchone()[0]

    def login(uid, index):
        c = app.test_client()
        # Distinct simulated workstations; production login limits stay intact.
        c.environ_base['REMOTE_ADDR'] = f'127.0.1.{index}'
        token = re.search(r'name="csrf" value="([^"]+)"', c.get('/login').text).group(1)
        expect(c.post('/login', data={'csrf': token, 'login': uid, 'password': password}).status_code == 302, 'login '+uid)
        clients[uid] = c

    def post(uid, url, data, status=303):
        c = clients[uid]
        token = re.search(r'name="csrf" value="([^"]+)"', c.get('/', follow_redirects=True).text).group(1)
        t = time.perf_counter()
        r = c.post(url, data={'csrf': token, **data})
        latencies.append((time.perf_counter()-t)*1000)
        expect(r.status_code == status, f'{url}: expected {status}, got {r.status_code}: {r.text[:180]}')
        return r

    login(docid, 1)
    profiles = []
    for i, p in enumerate(db.execute('SELECT * FROM patients ORDER BY id').fetchall()):
        profiles.append({'id': p['id'], 'age_status': p['age_status'], 'age': p['age_years'], 'scenario': 'original-S03'})
    variants = [
        (35,'known','improving'), (45,'known','persistent'), (65,'known','worsening'),
        (19,'known','adverse-event'), (17,'known','minor'), (18,'known','boundary-18'),
        (None,'unknown','unknown-age'), (None,'conflicting','conflicting-age'),
        (28,'known','missed-task'), (54,'known','unknown-outcome'),
        (38,'known','conflicting-outcome'), (72,'known','critical-transport')]
    for i,(age,state,scenario) in enumerate(variants,1):
        pid = f'CY{i:02}'
        db.execute('INSERT INTO patients VALUES(?,?,?,NULL,?,?,1,?)',
                   (pid,None,f'Синтетический {i:02} — {scenario}',age,state,now()))
        profiles.append({'id':pid,'age_status':state,'age':age,'scenario':scenario})
    traces = []
    for index,p in enumerate(profiles,2):
        pid = p['id']; uid = 'cycle-'+pid
        db.execute('INSERT INTO users VALUES(?,?,?,?,0)',(uid,'patient','Вымышленный пациент '+pid,hashed))
        db.execute('UPDATE patients SET user_id=? WHERE id=?',(uid,pid))
        login(uid,index)
        invitation = post(docid,'/invitations',{'patient_id':pid},200)
        token = re.search(r'readonly value="([^"]+)"',invitation.text).group(1)
        post(uid,'/link',{'invitation':token},302)
        # The audit retains the initial narrative; no diagnosis is inferred.
        narrative = f'Полностью вымышленная история {pid}. Жалобы на тревогу и нарушения сна. Источник: синтетический сценарий {p["scenario"]}. Клиническое заключение не утверждено.'
        post(docid,f'/patients/{pid}/imports',{'source_text':narrative,'request_key':secrets.token_hex(16)})
        trace = {**p,'rounds':[]}
        adult = p['age_status']=='known' and p['age'] is not None and p['age']>=18
        age = {'age_status':p['age_status']}
        if p['age_status']=='known': age['age_years']=str(p['age'])
        if p['age_status']=='conflicting': age['age_detail']='Разные синтетические источники: 17 и 35 лет'
        for round_no,days in enumerate((21,14,7,0)):
            day=(records.today()-timedelta(days=days)).isoformat()
            wellbeing = ('same','better','worse','unknown')[(index+round_no)%4]
            adverse = round_no==2 and p['scenario'] in ('adverse-event','critical-transport','worsening')
            report={'request_key':secrets.token_hex(16),'observed_on':day,'wellbeing':wellbeing,
                    'summary':f'Синтетическое наблюдение {round_no+1}, {pid}',**age,
                    'complaints_status':'known','complaints_text':f'Вымышленная динамика: {wellbeing}',
                    'adverse_events_status':'known' if adverse else 'unknown'}
            if adverse: report['adverse_events_text']='Вымышленное нежелательное явление; причинность не установлена'
            post(uid,f'/patients/{pid}/self-reports',report)
            post(uid,f'/patients/{pid}/self-reports',report)
            visit={'request_key':secrets.token_hex(16),'base_revision':'0','state':'completed',
                   'visit_kind':'first' if round_no==0 else 'repeat','observed_on':day,
                   'not_collected':'yes','complaints_status':'known','complaints_text':f'Синтетический визит {round_no+1}',
                   'complaints_basis':'Вымышленная беседа','age_source':'patient','age_basis':'Синтетический профиль',**age,
                   'action_draft':'Обсудить сведения; это не действующее назначение'}
            before=scalar('SELECT count(*) FROM care_actions a JOIN doctor_confirmations c ON c.id=a.confirmation_id JOIN proposals p ON p.id=c.proposal_id WHERE p.patient_id=?',(pid,))
            post(docid,f'/patients/{pid}/first-visits/new',visit)
            expect(scalar('SELECT count(*) FROM care_actions a JOIN doctor_confirmations c ON c.id=a.confirmation_id JOIN proposals p ON p.id=c.proposal_id WHERE p.patient_id=?',(pid,))==before,'visit never activates a plan')
            form=assessments.definition()
            assignment={'assignment_key':secrets.token_hex(16),'form_version_id':form['id'],
                        'age_basis':'Вымышленный профиль',**age}
            if adult:
                post(docid,f'/patients/{pid}/assessment-requests',assignment)
                rid=db.execute('SELECT id FROM assessment_requests WHERE patient_id=? ORDER BY requested_at DESC',(pid,)).fetchone()[0]
                answers={'form_version_id':form['id'],**{f'answer_{n}':str((index+round_no)%4) for n in range(1,43)}}
                post(uid,'/assessments/'+rid,{k:v for k,v in answers.items() if k!='answer_42'})
                incomplete=clients[docid].get(f'/api/patients/{pid}/assessments').json['assessments'][0]
                expect(incomplete['scores'] is None,'incomplete form has no score')
                post(uid,'/assessments/'+rid,answers,409)
                post(docid,f'/patients/{pid}/assessment-requests',{**assignment,'assignment_key':secrets.token_hex(16)})
                rid=db.execute('SELECT id FROM assessment_requests WHERE patient_id=? ORDER BY requested_at DESC',(pid,)).fetchone()[0]
                post(uid,'/assessments/'+rid,answers)
                result=clients[docid].get(f'/api/patients/{pid}/assessments').json['assessments'][0]
                expect(all(v==14*((index+round_no)%4) for v in result['scores'].values()),'DASS exact three subscale sums')
            else:
                post(docid,f'/patients/{pid}/assessment-requests',assignment,400)
                expect(scalar('SELECT count(*) FROM assessments WHERE patient_id=?',(pid,))==0,'age blocked without a score')
            # New information invalidates a pending proposal on the server.
            def draft(kind='plan_change'):
                values={'request_key':secrets.token_hex(16),'kind':kind,'content':'Синтетический план наблюдения — не для лечения',
                        'basis':'Вымышленный визит','uncertainties':'Клиническая проверка отсутствует',
                        'therapy_reference':decisions.reference()['version'],'aviandr_conclusion':'insufficient_data',
                        'aviandr_basis':'Вымышленные сведения недостаточны для назначения',
                        **{'note_'+a['id']:'Синтетическая проверка: неизвестно' for a in decisions.reference()['review_areas']}}
                if kind=='referral':
                    values.update(routing_reference='routing-reference-v1',route_specialty='Терапевт',
                        route_category='mandatory' if index%2 else 'desirable',route_urgency='planned',
                        route_population_status='known',route_age_years=str(p['age']),
                        route_severity='Вымышленная оценка',route_population='Синтетический взрослый профиль',
                        route_evidence='Ручной синтетический проект врача',route_unavailable='Уточнить вручную')
                post(docid,f'/patients/{pid}/decisions',values)
                return db.execute('SELECT * FROM proposals WHERE patient_id=? ORDER BY version DESC',(pid,)).fetchone()
            def confirm(proposal,actor=docid,status=303):
                return post(actor,f'/patients/{pid}/decisions/{proposal["id"]}/confirm',{
                    'version':str(proposal['version']),'decision':'approved','reviewed':'yes',
                    'rationale':'Ролевой технический стенд; не реальная врачебная проверка'},status)
            stale=draft()
            post(uid,f'/patients/{pid}/communication/send',{'request_key':secrets.token_hex(16),'body':'Вымышленное уточнение после проекта'})
            confirm(stale,status=409)
            proposal=draft()
            confirm(proposal,actor=uid,status=403)
            expect(scalar('SELECT count(*) FROM care_actions a JOIN doctor_confirmations c ON c.id=a.confirmation_id JOIN proposals p ON p.id=c.proposal_id WHERE p.patient_id=?',(pid,))==before,'draft and patient cannot activate a plan')
            confirm(proposal); confirm(proposal)
            action=db.execute('SELECT a.id FROM care_actions a JOIN doctor_confirmations c ON c.id=a.confirmation_id WHERE c.proposal_id=?',(proposal['id'],)).fetchone()[0]
            taskkey=secrets.token_hex(16)
            task={'request_key':taskkey,'action_id':action,'label':'Синтетическая запись дневника',
                  'due_at':(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat(),'reviewed':'yes'}
            post(docid,f'/patients/{pid}/communication/schedule',task)
            post(docid,f'/patients/{pid}/communication/schedule',task)
            tid=scalar('SELECT id FROM adherence_tasks WHERE request_key=?',(taskkey,))
            outcome=('taken','missed','unknown','conflicting')[(index+round_no)%4]
            post(uid,f'/patients/{pid}/communication/report',{'request_key':secrets.token_hex(16),
                 'task_id':tid,'outcome':outcome,'reason':'Вымышленная причина/уточнение'})
            for actor,body in ((uid,'Вымышленный вопрос'),(docid,'Вымышленный ответ')):
                messagekey=secrets.token_hex(16)
                post(actor,f'/patients/{pid}/communication/send',{'request_key':messagekey,'body':body})
                mid=scalar('SELECT id FROM messages WHERE idempotency_key=?',(messagekey,))
                post(docid if actor==uid else uid,f'/patients/{pid}/communication/read',{'message_id':mid})
            if adult and round_no==3:
                referral=draft('referral'); confirm(referral)
            for actor in (uid,docid):
                page=clients[actor].get('/demo/'+pid)
                expect(page.status_code==200 and report['summary'] in page.text,'both cabinets retain longitudinal history')
            # Another patient cannot read this card.
            if index>2:
                other='cycle-'+profiles[0]['id']
                expect(clients[other].get('/demo/'+pid).status_code==404,'cross-patient isolation')
            trace['rounds'].append({'observed_on':day,'wellbeing':wellbeing,'adverse_event':adverse,
                'assessment':'completed' if adult else 'blocked-age','outcome':outcome,
                'plan':'separate simulated physician confirmation','stale_confirmation':409})
        traces.append(trace)
    # Existing, unchanged A02 transport scenario; no new clinical branch.
    pid='CY12'; uid='cycle-'+pid
    post(docid,f'/patients/{pid}/clinical-context',{'request_key':secrets.token_hex(16),
        'observed_on':records.today().isoformat(),'gad_status':'present','severity':'nonsevere',
        'suicide_risk':'denied','psychiatric_comorbidity':'denied','treatment_resistance':'denied',
        'aviandr_prescription':'active','clinical_basis':'Вымышленный прежний контекст',
        'prescription_basis':'Вымышленное назначение из синтетического сценария'})
    post(uid,f'/patients/{pid}/self-reports',{'request_key':secrets.token_hex(16),
        'observed_on':records.today().isoformat(),'safety_form_version':'aviandr-safety-v1',
        'safety_taken':'present','safety_after_dose':'present','safety_current':'present','safety_rigidity':'present'})
    processed=0
    while events.process_one(db): processed+=1
    event= db.execute('SELECT id FROM critical_events WHERE patient_id=?',(pid,)).fetchone()
    expect(event is not None,'existing A02 creates actual synthetic event')
    for action in ('received','seen','acknowledged','reacted'):
        post(docid,f'/critical/{event[0]}/{action}',{'reaction':'Синтетическая реакция на стенде, не медицинское действие'},204 if action=='received' else 303)
    expect(scalar('SELECT reacted_at FROM critical_delivery WHERE event_id=?',(event[0],)) is not None,'reaction is durable and separate')
    counts={t:scalar('SELECT count(*) FROM '+t) for t in ('patients','text_imports','self_reports','first_visit_versions','assessments',
        'proposals','doctor_confirmations','care_actions','adherence_tasks','adherence_entries','messages','message_receipts','adverse_events','critical_events')}
    expect(counts['patients']==18,'six original plus twelve new profiles')
    expect(counts['first_visit_versions']==72,'eighteen first visits and fifty-four follow-ups')
    expect(counts['self_reports']==73,'seventy-two reports plus one critical report, no retry duplicates')
    expect(counts['adherence_tasks']==72 and counts['adherence_entries']==72,'seventy-two task cycles without retry duplicates')
    expect(scalar('PRAGMA integrity_check')=='ok','database integrity')
    expect(db.execute('PRAGMA foreign_key_check').fetchall()==[],'foreign key integrity')
    expect(scalar("SELECT count(*) FROM outbox_events WHERE status!='processed'")==0,'no unprocessed or dead events')
    db.close()
    # Recreate the application and re-read sessions and all 18 histories.
    restarted=create_app(path)
    for p in profiles:
        uid='cycle-'+p['id']; fresh=restarted.test_client()
        fresh.set_cookie(access.COOKIE,clients[uid].get_cookie(access.COOKIE).value)
        expect(fresh.get('/demo/'+p['id']).status_code==200,'history after application recreation')
    report={'status':'PASS','synthetic':True,'independent_clinical_validation':False,
        'head':__import__('subprocess').check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'transport':'Flask HTTP test client; not browser/network timing','checks':checks,
        'duration_seconds':round(time.perf_counter()-started,3),'post_count':len(latencies),
        'post_mean_ms':round(sum(latencies)/len(latencies),3),'post_max_ms':round(max(latencies),3),
        'counts':counts,'events_processed':processed,'profiles':traces,
        'limitations':['All clinical actors are simulated; no medical expert participated',
            'Backdated synthetic observations, not elapsed real follow-up',
            'No new clinical rules, no short instrument, no real patients',
            'Application recreation is not an OS restart; make smoke tests actual process restart',
            'No claim of extraction accuracy, usability with humans or external deployment readiness']}
    return report, {'doctor':docid,'patients':['cycle-'+p['id'] for p in profiles],'password':password,'synthetic':True}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--credentials',type=Path,required=True)
    args=parser.parse_args()
    for output in (args.report,args.credentials):
        if output.exists(): parser.error(f'Refusing to overwrite {output}')
    result,credentials=run(args.db)
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    # Passwords stay in ignored local storage, never the evidence report.
    import os
    fd=os.open(args.credentials,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'w') as out: json.dump(credentials,out,ensure_ascii=False,indent=2)
    print(json.dumps({k:v for k,v in result.items() if k!='profiles'},ensure_ascii=False,indent=2))
