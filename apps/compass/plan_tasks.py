"""Explicit items of an approved decision, shared by the two plan screens."""
from datetime import date
from . import communication, decisions


def view(db, user, patient_id):
    try:
        data = communication.view(db, user, patient_id)
    except decisions.DecisionError as error:
        if user['role'] != 'patient' or error.status != 409:
            raise
        return dict(tasks=[], head=None, authors={})
    actions = {r['id']: dict(r) for r in db.execute('''SELECT a.id,p.id proposal_id,p.version
        FROM care_actions a JOIN doctor_confirmations c ON c.id=a.confirmation_id
        JOIN proposals p ON p.id=c.proposal_id WHERE p.patient_id=?''', (patient_id,))}
    for task in data['tasks']:
        action = actions[task['action_id']]
        task.update(proposal_id=action['proposal_id'], version=action['version'],
                    revision=task['history'][-1]['id'] if task['history'] else '')
    authors = {}
    # Historical entries may have a physician author from the same relationship.
    actors = {h['actor_id'] for t in data['tasks'] for h in t['history']}
    for actor in actors:
        row = db.execute('SELECT display_name FROM users WHERE id=?', (actor,)).fetchone()
        authors[actor] = row['display_name'] if row else 'Автор не указан'
    head = {k: data['head'][k] for k in ('id', 'kind')} if data['head'] and user['role'] == 'doctor' else None
    return dict(tasks=data['tasks'], head=head, authors=authors)


def schedule(db, user, patient_id, form):
    try:
        raw = form.get('due_on', '')
        day = date.fromisoformat(raw)
        if day.isoformat() != raw or day.year < 1900:
            raise ValueError()
    except (ValueError, TypeError):
        raise decisions.DecisionError('Укажите дату выполнения с 1900 года.') from None
    return communication.schedule(db, user, patient_id,
        {**form, 'due_at': day.isoformat() + 'T00:00:00+03:00'}, allow_referral=True)
