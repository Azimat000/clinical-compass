"""Local conversation and explicit physician-scheduled adherence; no medical inference."""
from datetime import datetime, timezone
import secrets
from . import access, decisions
from .db import now, transaction

Error = decisions.DecisionError
LABELS = {'taken':'Выполнено', 'missed':'Пропущено', 'unknown':'Нет сведений', 'conflicting':'Противоречие'}


def text(form, key, limit=4000, required=True):
    return decisions.checked_text(form, key, limit, required)


def key(form):
    value = text(form, 'request_key', 32)
    if len(value) != 32 or any(c not in '0123456789abcdef' for c in value):
        raise Error('Обновите форму: неверный ключ повтора.')
    return value


def pair(db, user, patient_id):
    if not db.execute('SELECT 1 FROM users WHERE id=? AND disabled=0', (user['id'],)).fetchone():
        raise Error('Кабинет недоступен.', 403)
    if access.visible_patient(db, user, patient_id) is None:
        raise Error('Карточка недоступна.', 404)
    r = db.execute('''SELECT r.*,p.user_id FROM care_relationships r JOIN patients p ON p.id=r.patient_id
        JOIN users u ON u.id=r.doctor_id JOIN users v ON v.id=p.user_id
        WHERE r.patient_id=? AND r.ends_at IS NULL AND r.starts_at<=? AND u.disabled=0 AND v.disabled=0''',
        (patient_id, now())).fetchone()
    if not r:
        raise Error('Нужна действующая связь двух кабинетов.', 409)
    return r


def current_action(db, patient_id):
    return db.execute('''SELECT a.*,p.kind,p.payload_json FROM care_actions a
        JOIN doctor_confirmations c ON c.id=a.confirmation_id JOIN proposals p ON p.id=c.proposal_id
        WHERE p.patient_id=? ORDER BY p.version DESC LIMIT 1''', (patient_id,)).fetchone()


def task_for(db, r, task_id):
    task = db.execute('SELECT * FROM adherence_tasks WHERE id=? AND relationship_id=?', (task_id,r['id'])).fetchone()
    if not task:
        raise Error('Пункт недоступен.',404)
    return task


def superseded(db, task):
    cutoff=db.execute('''SELECT min(a.effective_at) FROM care_actions a
        JOIN doctor_confirmations c ON c.id=a.confirmation_id JOIN proposals p ON p.id=c.proposal_id
        WHERE p.patient_id=? AND p.version>(SELECT p0.version FROM care_actions a0
          JOIN doctor_confirmations c0 ON c0.id=a0.confirmation_id JOIN proposals p0 ON p0.id=c0.proposal_id
          WHERE a0.id=?)''',(task['patient_id'],task['action_id'])).fetchone()[0]
    return bool(cutoff and task['due_at']>=cutoff)


def send(db, user, patient_id, form):
    retry, body = key(form), text(form,'body')
    entry, task = text(form,'entry_id',64,False), text(form,'task_id',64,False)
    with transaction(db):
        r = pair(db,user,patient_id)
        recipient = r['doctor_id'] if user['role']=='patient' else r['user_id']
        if entry and not db.execute('SELECT 1 FROM clinical_entries WHERE id=? AND patient_id=?',(entry,patient_id)).fetchone():
            raise Error('Запись недоступна.',404)
        if task:
            task_for(db,r,task)
        old = db.execute('''SELECT m.*,c.relationship_id,x.* FROM messages m JOIN conversations c ON c.id=m.conversation_id
            JOIN message_context x ON x.message_id=m.id WHERE m.idempotency_key=?''',(retry,)).fetchone()
        if old:
            if (old['sender_id'],old['relationship_id'],old['body'],old['entry_id'],old['task_id']) != (user['id'],r['id'],body,entry or None,task or None):
                raise Error('Ключ уже использован с другим содержимым.',409)
            return old['id']
        db.execute('INSERT OR IGNORE INTO conversations VALUES(?,?)',(secrets.token_hex(16),r['id']))
        conversation = db.execute('SELECT id FROM conversations WHERE relationship_id=?',(r['id'],)).fetchone()[0]
        mid = secrets.token_hex(16)
        db.execute('INSERT INTO messages VALUES(?,?,?,?,?,?)',(mid,conversation,user['id'],body,now(),retry))
        db.execute('INSERT INTO message_context VALUES(?,?,?,?)',(mid,recipient,entry or None,task or None))
        access.audit(db,user['id'],'message.saved',mid)
        return mid


def receipt(db,user,patient_id,message_id,kind):
    if kind not in ('received','read'):
        raise Error('Неизвестная отметка.',400)
    with transaction(db):
        r=pair(db,user,patient_id)
        m=db.execute('''SELECT m.id FROM messages m JOIN conversations c ON c.id=m.conversation_id
            JOIN message_context x ON x.message_id=m.id WHERE m.id=? AND c.relationship_id=? AND x.recipient_id=?''',
            (message_id,r['id'],user['id'])).fetchone()
        if not m:
            raise Error('Сообщение недоступно.',404)
        for k in (('received','read') if kind=='read' else ('received',)):
            cursor=db.execute('INSERT OR IGNORE INTO message_receipts VALUES(?,?,?,?)',(message_id,k,user['id'],now()))
            if cursor.rowcount:
                access.audit(db,user['id'],'message.'+k,message_id)


def schedule(db,user,patient_id,form):
    retry, label = key(form), text(form,'label',500)
    action_id = text(form,'action_id',64)
    try:
        due=datetime.fromisoformat(text(form,'due_at',40))
        if due.tzinfo is None:
            raise ValueError()
        due=due.astimezone(timezone.utc).isoformat(timespec='microseconds')
    except ValueError:
        raise Error('Укажите дату и время с часовым поясом, например 2026-10-20T09:00:00+03:00.') from None
    if form.get('reviewed') != 'yes':
        raise Error('Подтвердите соответствие пункту решения врача.')
    with transaction(db):
        decisions.doctor_relationship(db,user,patient_id)
        r=pair(db,user,patient_id)
        old=db.execute('SELECT * FROM adherence_tasks WHERE request_key=?',(retry,)).fetchone()
        if old:
            if (old['relationship_id'],old['doctor_id'],old['action_id'],old['label'],old['due_at']) != (r['id'],user['id'],action_id,label,due):
                raise Error('Ключ уже использован с другим содержимым.',409)
            return old['id']
        head=current_action(db,patient_id)
        if not head or head['id'] != action_id or head['kind'] in ('therapy_stop','referral'):
            raise Error('Нужен текущий подтверждённый лечебный план. Обновите страницу.',409)
        tid=secrets.token_hex(16)
        db.execute('INSERT INTO adherence_tasks VALUES(?,?,?,?,?,?,?,?,?)',
                   (tid,patient_id,r['id'],action_id,label,due,now(),user['id'],retry))
        access.audit(db,user['id'],'adherence.scheduled',tid)
        return tid


def report(db,user,patient_id,task_id,form):
    retry, outcome, reason=key(form),text(form,'outcome',16),text(form,'reason',1000,False)
    if outcome not in LABELS or (outcome in ('missed','conflicting') and not reason):
        raise Error('Выберите результат; для пропуска или противоречия укажите причину.')
    with transaction(db):
        r=pair(db,user,patient_id)
        task=task_for(db,r,task_id)
        old=db.execute('SELECT * FROM adherence_entries WHERE request_key=?',(retry,)).fetchone()
        if old:
            if (old['task_id'],old['actor_id'],old['outcome'],old['reason']) != (task_id,user['id'],outcome,reason):
                raise Error('Ключ уже использован с другим содержимым.',409)
            return old['id']
        if superseded(db,task):
            raise Error('План заменён: этот пункт больше не учитывается.',409)
        if task['due_at']>now():
            raise Error('Отметка доступна после указанного времени.',409)
        rid=secrets.token_hex(16)
        db.execute('INSERT INTO adherence_entries VALUES(?,?,?,?,?,?,?)',(rid,task_id,user['id'],outcome,reason,now(),retry))
        access.audit(db,user['id'],'adherence.reported',rid)
        return rid


def view(db,user,patient_id):
    r=pair(db,user,patient_id)
    messages=[dict(m) for m in db.execute('''SELECT m.*,x.recipient_id,x.entry_id,x.task_id,
        (SELECT occurred_at FROM message_receipts WHERE message_id=m.id AND kind='received') AS received_at,
        (SELECT occurred_at FROM message_receipts WHERE message_id=m.id AND kind='read') AS read_at
        FROM messages m JOIN conversations c ON c.id=m.conversation_id JOIN message_context x ON x.message_id=m.id
        WHERE c.relationship_id=? ORDER BY m.sent_at,m.id''',(r['id'],))]
    head=current_action(db,patient_id)
    tasks=[]
    counts={k:0 for k in LABELS}
    counts.update(due=0,future=0,superseded=0)
    stamp=now()
    for row in db.execute('SELECT * FROM adherence_tasks WHERE relationship_id=? ORDER BY due_at,id',(r['id'],)):
        t=dict(row)
        t['history']=[dict(h) for h in db.execute('SELECT * FROM adherence_entries WHERE task_id=? ORDER BY recorded_at,id',(t['id'],))]
        t['outcome']=t['history'][-1]['outcome'] if t['history'] else 'unknown'
        # A newer plan stops future old tasks at its effective time, retaining historical due tasks.
        t['superseded']=superseded(db,t)
        t['future']=t['due_at']>stamp
        if t['superseded']: counts['superseded']+=1
        elif t['future']: counts['future']+=1
        else:
            counts['due']+=1
            counts[t['outcome']]+=1
        tasks.append(t)
    known=counts['taken']+counts['missed']
    counts['known']=known
    counts['percent']=round(100*counts['taken']/known,1) if known else None
    entries=db.execute('SELECT id,observed_on,kind FROM clinical_entries WHERE patient_id=? ORDER BY recorded_at DESC',(patient_id,)).fetchall()
    return dict(messages=messages,tasks=tasks,counts=counts,head=dict(head) if head else None,entries=entries,labels=LABELS)
