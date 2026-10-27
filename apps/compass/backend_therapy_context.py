"""Versioned synthetic physician factual reconciliation, separate from treatment."""
from contextlib import nullcontext
import json
import secrets
from . import backend_analyses as analyses, backend_snapshot as history, access, decisions
from .db import transaction, now

VERSION = 'therapy-context-v1'
# The full union also guards factors not limited to a single product.
FLAGS = ('pregnancy breastfeeding hepatic_impairment severe_renal_impairment mania_hypomania '
         'uncontrolled_epilepsy bleeding_risk qt_risk electrolyte_disorder renal_impairment '
         'epilepsy organic_brain_disease low_body_weight hyponatremia_risk renal_egfr_below60 '
         'hepatic_failure_child_pugh_a_b_c cardiovascular_disease endocrine_disease substance_dependence '
         'alcohol_use diabetes glaucoma suicidal_risk serotonin_syndrome_risk cyp2c19_poor_metabolizer '
         'lactose_intolerance akathisia seizure_history ect dehydration other_special_condition').split()

def obj(properties):
    return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}
def text(n):return {'type':'string','minLength':1,'maxLength':n}
def nullable(schema):return {'oneOf':[schema,{'type':'null'}]}
MEDICATION = obj({'product_id':nullable(text(64)), 'ingredient':text(80),
    'state':{'enum':['current','recently_stopped']}, 'prescribed':{'type':'boolean'},
    'actual':{'type':'boolean'}, 'daily_dose_mg':nullable({'type':'number','minimum':0}),
    'strength_mg':nullable({'type':'number','minimum':0}),
    'times_per_day':nullable({'type':'integer','minimum':1,'maximum':12}),
    'unit':text(20),'form':text(80)})
SCHEMA = obj({'request_key':{**text(32),'pattern':'[0-9a-f]{32}'},
    'expected_version':{'type':'integer','minimum':0}, 'base_sha256':{**text(64),'pattern':'[0-9a-f]{64}'},
    'goal':{'enum':['initiation','maintenance','change','stop']},
    'facts':obj({k:{'enum':[True,False,None,'conflicting']} for k in FLAGS}),
    'allergies':{'type':'array','maxItems':100,'items':text(100)},
    'allergies_complete':nullable({'type':'boolean'}),
    'medications':{'type':'array','maxItems':30,'items':MEDICATION},
    'medications_complete':nullable({'type':'boolean'}),
    'response':{'enum':['effective','partial','none','unknown']},
    'tolerability':{'enum':['good','adverse','unknown']},
    'prior_first_line':{'enum':['ineffective','intolerant','not_tried','unknown']},
    'basis':text(4000),'reviewed':{'type':'boolean','const':True}})


def head(db, patient_id):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='backend_therapy_contexts'").fetchone():return None
    return db.execute('SELECT * FROM backend_therapy_contexts WHERE patient_id=? ORDER BY version DESC LIMIT 1',(patient_id,)).fetchone()


def base(db, patient_id, relationship):
    # Context is absent from the diagnosis snapshot, so reconciliation itself
    # cannot manufacture a new diagnosis or force endless self-invalidation.
    return history.digest(json.loads(analyses.capture(db, patient_id, relationship)))


def view(db, user, patient_id):
    with (nullcontext(db) if db.in_transaction else transaction(db)):
        relationship=analyses.authorize(db,user,patient_id)
        row=head(db,patient_id); digest=base(db,patient_id,relationship)
        return {'version':VERSION,'base_sha256':digest,'expected_version':row['version'] if row else 0,
                'current':None if row is None or row['relationship_id']!=relationship else {'id':row['id'],'actor_id':row['actor_id'],
                'relationship_id':row['relationship_id'],'recorded_at':row['recorded_at'],
                'fresh':row['base_sha256']==digest and row['relationship_id']==relationship,
                'payload':json.loads(row['payload_json'])},'clinical_release':False}


def record(db,user,patient_id,body):
    with (nullcontext(db) if db.in_transaction else transaction(db)):
        relationship=analyses.authorize(db,user,patient_id)
        analyses.validate_schema(body,SCHEMA)
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='backend_therapy_contexts'").fetchone():
            raise analyses.AnalysisError('Нужна миграция отдельной копии базы.',409,'therapy_context_unavailable')
        encoded=decisions.canonical(body)
        old=db.execute('SELECT * FROM backend_therapy_contexts WHERE patient_id=? AND actor_id=? AND request_key=?',
            (patient_id,user['id'],body['request_key'])).fetchone()
        if old:
            original=json.loads(old['payload_json']);original.pop('version')
            if decisions.canonical(original)!=encoded or old['relationship_id']!=relationship:
                raise analyses.AnalysisError('Повтор содержит другие сведения.',409,'idempotency_conflict')
            return {'id':old['id'],'version':old['version'],'recorded_at':old['recorded_at']}
        row=head(db,patient_id)
        if body['expected_version']!=(row['version'] if row else 0):
            raise analyses.AnalysisError('Сверка уже изменена.',409,'revision_conflict')
        if body['base_sha256']!=base(db,patient_id,relationship):
            raise analyses.AnalysisError('История или диагноз изменились; нужна новая сверка.',409,'stale_inputs')
        patient=db.execute('SELECT synthetic FROM patients WHERE id=?',(patient_id,)).fetchone()
        if not patient or patient['synthetic']!=1:
            raise analyses.AnalysisError('Только вымышленные случаи.',409,'synthetic_only')
        ident=secrets.token_hex(16);stamp=now();version=body['expected_version']+1
        db.execute('INSERT INTO backend_therapy_contexts VALUES(?,?,?,?,?,?,?,?,?,?)',
            (ident,patient_id,relationship,user['id'],version,row['id'] if row else None,
             body['request_key'],body['base_sha256'],decisions.canonical(dict(body,version=VERSION)),stamp))
        access.audit(db,user['id'],'analysis.therapy_reconciled',ident)
        return {'id':ident,'version':version,'recorded_at':stamp}


def prepare(db,user,patient_id,raw):
    relationship=analyses.authorize(db,user,patient_id)
    row=head(db,patient_id)
    # A new relationship cannot inherit a previous physician's private reconciliation.
    if row is None or row['relationship_id']!=relationship:return None
    # raw is the same capture before plan-specific dependencies were added.
    value={k:v for k,v in raw.items() if k!='care_plan_input'}
    return {'row':dict(row),'fresh':row['base_sha256']==history.digest(value) and row['relationship_id']==relationship}
