"""Append authored fictional medication schedules/marks; never clinical prescribing.

Dry run by default. Recognized S30 roster only, private backup before one atomic
append. Historical actors/dates are simulated; actual import time is audited.
Not called at startup. Neutral names carry no real drug/dose recommendation.
"""
import argparse
from contextlib import closing
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from apps.compass import backup, decisions, medications
from apps.compass import db as database
from tools import replace_roster

DATASET = ROOT / 'data/fictional/medications-20261023.json'
EVENT = 'fictional.medications_loaded'
PROVENANCE = dict(synthetic=True, simulated_dates=True, clinical_review=False,
                  real_user_trial=False, fictional_medication_names=True)


def stable(*parts):
    return hashlib.sha256(':'.join(parts).encode()).hexdigest()[:32]


def load_dataset():
    data = json.loads(DATASET.read_text())
    roster = replace_roster.load_dataset()
    if (data['version'] != 'clinic-medications-20261023-v1' or data['provenance'] != PROVENANCE
            or data['roster_sha256'] != hashlib.sha256(replace_roster.DATASET.read_bytes()).hexdigest()
            or set(data['patients']) != {p['id'] for p in roster['patients']}):
        raise ValueError('Unrecognized fictional medication dataset')
    for pid, p in data['patients'].items():
        # Structural checks only, not clinical dose validation.
        if (p['days'] != 60 or p['quarters'] != 4 or 'условное название' not in p['name']
                or not p['context'].strip() or set(p['missed']) & set(p['unmarked'])):
            raise ValueError('Invalid authored fixture')
        if pid in ('P104', 'P106') and p['start'] != '2026-10-23':
            raise ValueError('Do not rewrite unknown/absent prior treatment')
        if p['missed'] != (['2026-10-22'] if pid == 'P103' else []):
            raise ValueError('Exactly one explicit missed dose is authored')
    return data, roster


def plan(db):
    data, roster = load_dataset()
    sha = hashlib.sha256(DATASET.read_bytes()).hexdigest()
    origins = db.execute("SELECT metadata_json FROM audit_entries WHERE event='fictional.roster_loaded'").fetchall()
    if len(origins) != 1:
        raise ValueError('Expected the recognized fictional roster')
    origin = json.loads(origins[0][0])
    if (origin.get('synthetic') is not True or origin.get('clinical_review') is not False
            or origin.get('dataset_sha256') not in (data['roster_sha256'],
                '0672755710be534f138666eda271ef3498465e56e177a59787721ccdc0d7a872')):
        raise ValueError('Unrecognized roster origin')
    prior = db.execute('SELECT metadata_json FROM audit_entries WHERE event=? AND entity_id=?', (EVENT, data['version'])).fetchall()
    if len(prior) > 1 or prior and json.loads(prior[0][0]).get('dataset_sha256') != sha:
        raise ValueError('Import provenance differs')
    if prior:
        # Check every imported immutable row, even if subsequent genuine use added marks/plans.
        expected = json.loads(prior[0][0])['rows']
        for table, items in expected.items():
            key = 'request_key' if table == 'medication_marks' else 'proposal_id' if table == 'decision_drafts' else 'id'
            for row in items:
                stored = db.execute('SELECT * FROM '+table+' WHERE '+key+'=?', (row[key],)).fetchone()
                if stored is None or dict(stored) != row:
                    raise ValueError('Previously imported row differs or is missing')
        return dict(version=data['version'], sha256=sha, rows={}, already_imported=True)
    rows = {t: [] for t in ('proposals', 'decision_drafts', 'doctor_confirmations', 'care_actions', 'medication_marks')}
    through = datetime.fromisoformat(data['marked_through'])
    for person in roster['patients']:
        pid = person['id']; p = data['patients'][pid]
        identity = db.execute('SELECT * FROM patients WHERE id=?', (pid,)).fetchone()
        relation = db.execute('''SELECT r.* FROM care_relationships r JOIN users u ON u.id=r.doctor_id
            WHERE r.patient_id=? AND r.doctor_id=? AND r.ends_at IS NULL AND u.disabled=0''', (pid, person['doctor'])).fetchall()
        if (not identity or identity['synthetic'] != 1 or identity['user_id'] != person['login']
                or identity['code'] != person['name'] or len(relation) != 1):
            raise ValueError('Fictional identity/doctor differs: '+pid)
        if medications.approved(db, pid) or db.execute('SELECT 1 FROM medication_marks WHERE patient_id=?', (pid,)).fetchone():
            raise ValueError('Preserve existing medication work; refusing to merge: '+pid)
        anchors = db.execute('''SELECT p.*,c.confirmed_at,a.id action_id,d.reference_json FROM proposals p
            JOIN doctor_confirmations c ON c.proposal_id=p.id JOIN care_actions a ON a.confirmation_id=c.id
            JOIN decision_drafts d ON d.proposal_id=p.id WHERE p.patient_id=? AND c.doctor_id=?
            AND c.decision='approved' ORDER BY p.version''', (pid, person['doctor'])).fetchall()
        if (len(anchors) != 2 or [json.loads(a['payload_json'])['content'] for a in anchors] != person['plans']
                or db.execute('SELECT count(*) FROM proposals WHERE patient_id=?', (pid,)).fetchone()[0] != 2):
            raise ValueError('Original plans differ; refusing overwrite: '+pid)
        start = date.fromisoformat(p['start'])
        med = dict(name=p['name'], start=p['start'], end=(start+timedelta(days=p['days']-1)).isoformat(),
                   days=p['days'], slots=[dict(time=p['time'], quarters=p['quarters'])])
        phases = ['historical', 'current'] if start < date(2026,10,23) else ['current']
        plans = []
        for offset, phase in enumerate(phases):
            anchor = anchors[0 if phase == 'historical' else -1]
            stamp = '2026-09-11T15:30:00.000000+00:00' if phase == 'historical' else '2026-10-23T03:00:00.000000+00:00'
            if relation[0]['starts_at'] > stamp:
                raise ValueError('Care relationship did not exist')
            proposal = stable(data['version'],pid,phase,'proposal')
            cid = stable(data['version'],pid,phase,'confirmation')
            aid = stable(data['version'],pid,phase,'action')
            version = 3 + offset
            payload = json.loads(anchor['payload_json'])
            payload.update(medications=[med], medication_context=p['context'] if phase=='current' else
                'Начало отдельного расписания приёма. Прежние сведения и дневник сохранены; эффект лечения здесь не устанавливается.')
            # Keep original care text; a schedule is a separate field, never a replacement for diary tasks.
            rows['proposals'].append(dict(id=proposal,patient_id=pid,kind='plan_change',version=version,
                payload_json=decisions.canonical(payload),input_snapshot_json=anchor['input_snapshot_json'],
                catalog_version_id=None,created_at=stamp,status='draft'))
            rows['decision_drafts'].append(dict(proposal_id=proposal,actor_id=person['doctor'],relationship_id=relation[0]['id'],
                request_key=stable(data['version'],pid,phase,'draft'),parent_proposal_id=anchor['id'],reference_json=anchor['reference_json']))
            rows['doctor_confirmations'].append(dict(id=cid,proposal_id=proposal,doctor_id=person['doctor'],proposal_version=version,
                decision='approved',rationale='Отдельное расписание приёма; дневник и прежний план наблюдения сохраняются.',confirmed_at=stamp))
            rows['care_actions'].append(dict(id=aid,confirmation_id=cid,approval_decision='approved',effective_at=stamp,
                supersedes_id=anchor['action_id']))
            plans.append((proposal,datetime.fromisoformat(stamp)))
        for offset in range((through.date()-start).days+1):
            day=start+timedelta(days=offset)
            due=datetime.fromisoformat(day.isoformat()+'T'+p['time']+'+03:00')
            if due>through or day.isoformat() in p['unmarked']:
                continue
            proposal=next(i for i,stamp in reversed(plans) if stamp<=due)
            rows['medication_marks'].append(dict(patient_id=pid,proposal_id=proposal,med_index=0,slot_index=0,
                dose_on=day.isoformat(),actor_id=person['login'],actual_quarters=0 if day.isoformat() in p['missed'] else p['quarters'],
                recorded_at=(due+timedelta(minutes=10)).isoformat(),request_key=stable(data['version'],pid,day.isoformat(),'mark')))
    # Deterministic identifiers must never collide with another import or user work.
    for table, items in rows.items():
        key='request_key' if table=='medication_marks' else 'proposal_id' if table=='decision_drafts' else 'id'
        for row in items:
            if db.execute('SELECT 1 FROM '+table+' WHERE '+key+'=?',(row[key],)).fetchone():
                raise ValueError('Partial import or conflicting identifier')
    return dict(version=data['version'],sha256=sha,rows=rows,already_imported=False)


def summary(result):
    return dict(version=result['version'],sha256=result['sha256'],already_imported=result['already_imported'],
                additions={t:len(rows) for t,rows in result['rows'].items()})


def seed(path, *, apply=False, backup_path=None):
    path=Path(path).resolve()
    with closing(backup.readonly(path)) as db:
        db.row_factory=sqlite3.Row
        preview=plan(db)
    if not apply or preview['already_imported']:
        return dict(applied=apply,backup=None,**summary(preview))
    if backup_path is None:
        raise ValueError('A new private backup is required')
    copied=backup.copy_database(path,backup_path)
    with closing(database.connect(path)) as db:
        with database.transaction(db):
            result=plan(db)
            if result['already_imported']:
                return dict(applied=True,backup=str(backup_path),**summary(result))
            for table, items in result['rows'].items():
                for row in items:
                    keys=list(row)
                    cursor=db.execute('INSERT INTO '+table+' ('+','.join(keys)+') VALUES('+','.join('?' for _ in keys)+')',tuple(row[k] for k in keys))
                    if table=='medication_marks':
                        row['sequence']=cursor.lastrowid
            provenance=dict(PROVENANCE,actual_imported_at=database.now(),dataset_sha256=result['sha256'],
                dataset_version=result['version'],source=str(DATASET.relative_to(ROOT)),rows=result['rows'],
                version_order='imported snapshots use new versions; simulated event dates shown explicitly')
            db.execute('INSERT INTO audit_entries(event,entity_id,occurred_at,metadata_json) VALUES(?,?,?,?)',
                (EVENT,result['version'],provenance['actual_imported_at'],decisions.canonical(provenance)))
            backup.checked(db)
    return dict(applied=True,backup=str(Path(backup_path).resolve()),backup_sha256=copied['sha256'],**summary(result))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',default='var/compass.sqlite3');parser.add_argument('--apply',action='store_true');parser.add_argument('--backup')
    args=parser.parse_args()
    print(json.dumps(seed(args.db,apply=args.apply,backup_path=args.backup),ensure_ascii=False,indent=2))
