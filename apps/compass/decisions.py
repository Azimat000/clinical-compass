"""Manual decisions for synthetic cases, independent of inactive clinical rules."""
import hashlib
import json
from pathlib import Path
import re
import secrets
from . import access, records, routing
from .db import now, transaction

KINDS = {'therapy_start': 'Назначение терапии', 'therapy_change': 'Изменение терапии',
         'therapy_stop': 'Отмена терапии', 'referral': 'Направление', 'plan_change': 'Изменение плана'}
REFERENCE_PATH = Path(__file__).with_name('resources') / 'therapy-reference-v2.json'


class DecisionError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def reference():
    value = json.loads(REFERENCE_PATH.read_text())
    # This module must never implicitly enable an automatic medical algorithm.
    if value.get('active_rules') is not False or value.get('mode') != 'reference_only':
        raise RuntimeError('Unreviewed clinical release')
    return value


def checked_text(form, name, limit=4000, required=True):
    try:
        value = records.text_field(form, name, limit)
    except records.RecordError as error:
        raise DecisionError(str(error)) from None
    if required and not value:
        raise DecisionError('Заполните решение, основание и описание неопределённости.')
    return value


def doctor_relationship(db, user, patient_id):
    active_user = db.execute("SELECT 1 FROM users WHERE id=? AND role='doctor' AND disabled=0", (user['id'],)).fetchone()
    if user['role'] != 'doctor' or not active_user:
        raise DecisionError('Подтверждение доступно только врачу.', 403)
    if access.visible_patient(db, user, patient_id) is None:
        raise DecisionError('Карточка недоступна.', 404)
    row = db.execute('''SELECT r.id FROM care_relationships r JOIN patients p ON p.id=r.patient_id
        WHERE r.patient_id=? AND r.doctor_id=? AND r.ends_at IS NULL AND r.starts_at<=? AND p.synthetic=1''',
        (patient_id, user['id'], now())).fetchone()
    if not row:
        raise DecisionError('Нет действующей связи с синтетическим случаем.', 409)
    return row['id']


def snapshot(db, patient_id, relationship_id):
    """Conservative exact comparison: ANY new clinical information requires rereview."""
    result = {'policy': 'synthetic-inputs-v1', 'day': records.today().isoformat(), 'relationship': relationship_id,
              'reference': hashlib.sha256(canonical(reference()).encode()).hexdigest()}
    for table in ('patients', 'encounters', 'observations', 'clinical_entries', 'assessments',
                  'self_reports', 'adverse_events', 'therapy_courses', 'alerts', 'documents', 'age_reviews'):
        key = 'id' if table == 'patients' else 'patient_id'
        result[table] = [dict(r) for r in db.execute(f'SELECT * FROM {table} WHERE {key}=? ORDER BY id', (patient_id,))]
    result['assessment_results'] = [dict(r) for r in db.execute('''SELECT ar.* FROM assessment_results ar
        JOIN assessments a ON a.id=ar.assessment_id WHERE a.patient_id=? ORDER BY ar.assessment_id''', (patient_id,))]
    result['actions'] = [dict(r) for r in db.execute('''SELECT a.*,c.proposal_id FROM care_actions a
        JOIN doctor_confirmations c ON c.id=a.confirmation_id JOIN proposals p ON p.id=c.proposal_id
        WHERE p.patient_id=? ORDER BY a.id''', (patient_id,))]
    for table in ('source_versions', 'catalog_versions', 'assessment_form_releases'):
        result[table] = sorted((dict(r) for r in db.execute(f'SELECT * FROM {table}')), key=canonical)
    return canonical(result)


def therapy_review(form, kind):
    """Record the physician's source-based assessment, never infer drug suitability."""
    if kind not in ('therapy_start', 'therapy_change', 'therapy_stop'):
        return None
    ref = reference()
    if form.get('therapy_reference') != ref['version']:
        raise DecisionError('Справка изменилась или не просмотрена. Обновите форму.', 409)
    conclusion = form.get('aviandr_conclusion')
    if conclusion not in ('not_selected', 'insufficient_data', 'individual_review'):
        raise DecisionError('Запишите результат рассмотрения Авиандра.')
    checks = []
    for area in ref['review_areas']:
        status = form.get('review_' + area['id'], 'unknown')
        if status not in ('reviewed', 'concern', 'unknown', 'conflicting'):
            raise DecisionError('Недопустимое состояние проверки терапии.')
        note = checked_text(form, 'note_' + area['id'], 1500)
        checks.append({'id': area['id'], 'status': status, 'note': note})
    unresolved = [c['id'] for c in checks if c['status'] in ('unknown', 'conflicting')]
    concerns = [c['id'] for c in checks if c['status'] == 'concern']
    if conclusion == 'individual_review' and (unresolved or concerns):
        raise DecisionError('Есть риск, неизвестность или противоречие. Выберите отказ от выбора препарата либо недостаток данных.', 409)
    return {'reference_version': ref['version'], 'conclusion': conclusion,
            'checks': checks, 'unresolved': unresolved, 'concerns': concerns,
            'automatic_recommendation': False, 'eligibility_established': False,
            'basis': checked_text(form, 'aviandr_basis', 2000)}


def draft(db, user, patient_id, form):
    kind = checked_text(form, 'kind', 40)
    if kind not in KINDS:
        raise DecisionError('Выберите вид решения.')
    payload = {name: checked_text(form, name) for name in ('content', 'basis', 'uncertainties')}
    payload.update(kind=kind, mode='manual_synthetic', automatic=False)
    if kind == 'referral':
        payload['routing_review'] = routing.review(form)
    review = therapy_review(form, kind)
    if review is not None:
        payload['therapy_review'] = review
    parent = checked_text(form, 'parent_id', 64, False)
    token = checked_text(form, 'request_key', 32)
    if not re.fullmatch('[0-9a-f]{32}', token):
        raise DecisionError('Обновите форму.')
    retry = hashlib.sha256(f'{user["id"]}:{patient_id}:{token}'.encode()).hexdigest()
    text = canonical(payload)
    with transaction(db):
        relationship = doctor_relationship(db, user, patient_id)
        old = db.execute('''SELECT p.*,d.parent_proposal_id FROM proposals p JOIN decision_drafts d ON d.proposal_id=p.id
            WHERE d.request_key=?''', (retry,)).fetchone()
        if old:
            if old['payload_json'] != text or (old['parent_proposal_id'] or '') != parent:
                raise DecisionError('Повторная отправка содержит другие сведения.', 409)
            return old['id']
        if parent and not db.execute('''SELECT 1 FROM proposals p JOIN decision_drafts d ON d.proposal_id=p.id
            WHERE p.id=? AND p.patient_id=?''', (parent, patient_id)).fetchone():
            raise DecisionError('Предыдущий проект недоступен.', 404)
        pid = secrets.token_hex(16)
        version = db.execute('SELECT coalesce(max(version),0)+1 FROM proposals WHERE patient_id=?', (patient_id,)).fetchone()[0]
        db.execute('''INSERT INTO proposals(id,patient_id,kind,version,payload_json,input_snapshot_json,created_at,status)
            VALUES(?,?,?,?,?,?,?,'draft')''', (pid, patient_id, kind, version, text, snapshot(db, patient_id, relationship), now()))
        db.execute('INSERT INTO decision_drafts VALUES(?,?,?,?,?,?)',
                   (pid, user['id'], relationship, retry, parent or None, canonical(reference())))
        access.audit(db, user['id'], 'decision.draft_created', pid)
        return pid


def confirm(db, user, patient_id, proposal_id, form):
    decision = checked_text(form, 'decision', 16)
    rationale = checked_text(form, 'rationale')
    if decision not in ('approved', 'rejected') or form.get('reviewed') != 'yes':
        raise DecisionError('Нужны отдельное решение и подтверждение просмотра сведений.')
    try:
        version = int(checked_text(form, 'version', 8))
    except ValueError:
        raise DecisionError('Проверьте версию проекта.') from None
    with transaction(db):
        relationship = doctor_relationship(db, user, patient_id)
        proposal = db.execute('''SELECT p.*,d.relationship_id FROM proposals p JOIN decision_drafts d ON d.proposal_id=p.id
            WHERE p.id=? AND p.patient_id=?''', (proposal_id, patient_id)).fetchone()
        if not proposal:
            raise DecisionError('Проект недоступен.', 404)
        if proposal['version'] != version or proposal['relationship_id'] != relationship:
            raise DecisionError('Версия или связь с врачом изменилась.', 409)
        previous = db.execute('SELECT * FROM doctor_confirmations WHERE proposal_id=?', (proposal_id,)).fetchone()
        if previous:
            if previous['decision'] != decision or previous['rationale'] != rationale or previous['doctor_id'] != user['id']:
                raise DecisionError('Решение уже записано с другим содержимым.', 409)
            return previous['id']
        if proposal['status'] != 'draft':
            raise DecisionError('Проект закрыт.', 409)
        if decision == 'approved' and proposal['kind'] == 'referral':
            routing.confirmable(db, patient_id, json.loads(proposal['payload_json']))
        if decision == 'approved' and proposal['input_snapshot_json'] != snapshot(db, patient_id, relationship):
            raise DecisionError('После создания проекта изменились данные, план, источник или день. Изучите сведения и создайте новую версию.', 409)
        cid, stamp = secrets.token_hex(16), now()
        db.execute('INSERT INTO doctor_confirmations VALUES(?,?,?,?,?,?,?)',
                   (cid, proposal_id, user['id'], version, decision, rationale, stamp))
        if decision == 'approved':
            head = db.execute('''SELECT a.id FROM care_actions a JOIN doctor_confirmations c ON c.id=a.confirmation_id
                JOIN proposals p ON p.id=c.proposal_id WHERE p.patient_id=? ORDER BY p.version DESC LIMIT 1''', (patient_id,)).fetchone()
            db.execute('INSERT INTO care_actions VALUES(?,?,?,?,?)',
                       (secrets.token_hex(16), cid, 'approved', stamp, head['id'] if head else None))
        access.audit(db, user['id'], 'decision.' + decision, proposal_id)
        return cid


def history(db, user, patient_id):
    rows = db.execute('''SELECT p.*,d.actor_id,d.parent_proposal_id,d.reference_json,c.decision,c.rationale,
        c.doctor_id,c.confirmed_at,a.id AS action_id,a.supersedes_id FROM proposals p
        JOIN decision_drafts d ON d.proposal_id=p.id
        LEFT JOIN doctor_confirmations c ON c.proposal_id=p.id LEFT JOIN care_actions a ON a.confirmation_id=c.id
        WHERE p.patient_id=? ORDER BY p.version DESC''', (patient_id,)).fetchall()
    result = []
    for r in rows:
        if user['role'] != 'doctor' and r['decision'] != 'approved':
            continue
        entry = {k: r[k] for k in ('id','kind','version','created_at','actor_id','parent_proposal_id',
                                  'decision','rationale','doctor_id','confirmed_at','action_id','supersedes_id')}
        entry['payload'] = json.loads(r['payload_json'])
        if user['role'] != 'doctor':
            entry['payload'].pop('therapy_review', None)
            review = entry['payload'].pop('routing_review', None)
            if review:
                entry['payload']['route'] = {k: review[k] for k in ('target', 'category', 'urgency')}
        if user['role'] == 'doctor':
            entry['reference'] = json.loads(r['reference_json'])
            entry['input_snapshot'] = json.loads(r['input_snapshot_json'])
        result.append(entry)
    return result
