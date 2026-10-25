"""Owner-only mutable form work. Never a clinical source or a notification."""
import hashlib
import json
import re
from . import records, clinical_rules, medication_feedback
from .db import now, transaction

LIMITS = {'request_key':32, 'observed_on':10, 'wellbeing':20, 'age_status':20,
          'age_years':3, 'birth_date':10, 'age_detail':1000, 'summary':4000,
          'safety_form_version':64,
          **{code+'_status':20 for code in records.FIELDS},
          **{code+'_text':2000 for code in records.FIELDS},
          **{'safety_'+code:20 for code in clinical_rules.SAFETY_FIELDS}}
LIMITS.update(medication_feedback.LIMITS)


class Error(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def authorize(db, user, patient_id):
    if user['role'] != 'patient':
        raise Error('Личный черновик доступен только пациенту.', 403)
    if not db.execute('''SELECT 1 FROM patients p JOIN users u ON u.id=p.user_id
        WHERE p.id=? AND u.id=? AND u.role='patient' AND u.disabled=0 AND p.synthetic=1''',
        (patient_id,user['id'])).fetchone():
        raise Error('Черновик недоступен.', 404)


def view(db, user, patient_id):
    authorize(db,user,patient_id)
    row = db.execute('SELECT * FROM self_report_drafts WHERE owner_id=? AND patient_id=?',
                     (user['id'],patient_id)).fetchone()
    return {'revision':row['revision'] if row else 0, 'active':bool(row and row['active']),
            'values':json.loads(row['values_json']) if row else {},
            'updated_at':row['updated_at'] if row else None,
            'request_key':row['request_key'] if row else None}


def revision(form):
    value = form.get('draft_revision','')
    if not isinstance(value,str) or not re.fullmatch(r'[0-9]{1,10}',value):
        raise Error('Обновите версию черновика.',409)
    return int(value)


def values(form):
    # Preserve unfinished text verbatim, including whitespace and contradictions.
    result = {}
    for name,limit in LIMITS.items():
        if name not in form:
            continue
        value = form[name]
        if not isinstance(value,str) or len(value)>limit or any(ord(c)<32 and c not in '\n\r\t' for c in value):
            raise Error('Проверьте размер и формат поля черновика.')
        result[name] = value
    if not re.fullmatch('[0-9a-f]{32}',result.get('request_key','')):
        raise Error('Обновите форму перед сохранением черновика.')
    for name,allowed in {'wellbeing':records.WELLBEING,'age_status':('known','unknown','conflicting'),
                         **{c+'_status':records.STATUSES for c in records.FIELDS},
                         **{'safety_'+c:('unknown','present','denied','conflicting') for c in clinical_rules.SAFETY_FIELDS}}.items():
        if name in result and result[name] not in allowed:
            raise Error('Неизвестное состояние поля черновика.')
    if 'safety_form_version' in result and result['safety_form_version']!='aviandr-safety-v1':
        raise Error('Версия бланка изменилась. Сохраните текст отдельно и откройте новую форму.',409)
    if 'medication_feedback_version' in result and result['medication_feedback_version'] != medication_feedback.VERSION:
        raise Error('Версия дневника изменилась. Откройте новую форму.', 409)
    for key, value in result.items():
        if key.startswith('feedback_') and not key.endswith('_text') and value not in ('', 'yes'):
            raise Error('Неизвестная отметка препарата.')
    return result


def write(db, user, patient_id, current, key, data, active):
    stamp = now()
    db.execute('''INSERT INTO self_report_drafts VALUES(?,?,?,1,?,?,?,?)
        ON CONFLICT(owner_id,patient_id) DO UPDATE SET revision=excluded.revision,
        active=excluded.active,request_key=excluded.request_key,values_json=excluded.values_json,updated_at=excluded.updated_at''',
        (user['id'],patient_id,current['revision']+1,int(active),key,
         json.dumps(data,ensure_ascii=False,sort_keys=True) if active else '{}',stamp))
    return {'revision':current['revision']+1,'active':active,'updated_at':stamp}


def entry_key(user, patient_id, key):
    return hashlib.sha256(f'{user["id"]}:{patient_id}:self_report:{key}'.encode()).hexdigest()


def save(db, user, patient_id, form, delete=False):
    authorize(db,user,patient_id)
    data = values({'request_key':form.get('request_key','')}) if delete else values(form)
    base = revision(form)
    key = data['request_key']
    with transaction(db):
        current = view(db,user,patient_id)
        if db.execute('SELECT 1 FROM clinical_entries WHERE request_key=?', (entry_key(user,patient_id,key),)).fetchone():
            raise Error('Этот самоотчёт уже отправлен. Обновите страницу и проверьте историю.',409)
        # Repeating a save after losing its response is safe, including deletion.
        if current['request_key']==key and (
            (not delete and current['active'] and current['values']==data) or
            (delete and not current['active'] and current['revision']==base+1)):
            return {k:current[k] for k in ('revision','active','updated_at')}
        if current['revision']!=base:
            raise Error('Черновик изменён в другой вкладке. Ваш ввод оставлен на странице; откройте сохранённый черновик отдельно.',409)
        return write(db,user,patient_id,current,key,data,not delete)


def check_submission(db, user, patient_id, form):
    """Called inside the final clinical transaction, after checking an existing receipt."""
    if 'draft_revision' not in form:
        return  # Existing integrations/native callers keep their previous contract.
    current = view(db,user,patient_id)
    if current['revision']!=revision(form) or (current['active'] and current['request_key']!=form.get('request_key')):
        raise Error('Черновик изменился. Проверьте сохранённую версию перед отправкой.',409)


def consumed(db, user, patient_id, form):
    """Clear content in the same transaction as the clinical record; keep a revision tombstone."""
    if 'draft_revision' not in form and not db.execute(
        'SELECT 1 FROM self_report_drafts WHERE owner_id=? AND patient_id=?', (user['id'],patient_id)).fetchone():
        return
    current = view(db,user,patient_id)
    if 'draft_revision' in form or (current['active'] and current['request_key']==form.get('request_key')):
        write(db,user,patient_id,current,form['request_key'],{},False)
