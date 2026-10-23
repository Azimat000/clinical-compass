"""Append corrections to recognized S30 fictional marks only; preserve all previous rows.
Dry run is the default. --apply requires a new private backup path.
This is a fixture repair, never a rule inferring plan completion from a self-report.
"""
import argparse
from contextlib import closing
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from apps.compass import backup, communication, db as database
from tools import replace_roster

OLD_SHA = '0672755710be534f138666eda271ef3498465e56e177a59787721ccdc0d7a872'
OLD_REASONS = {
    'missed': 'В этот день запись не сделана.',
    'unknown': 'Не помню, сделана ли запись в тот день.',
    'conflicting': 'Отметил выполнение за весь период, но записи есть не за каждый день.',
}
LEGACY = {'P101': {4: 'missed'}, 'P103': {1: 'missed', 3: 'unknown'},
          'P104': {2: 'missed'}, 'P105': {1: 'missed'}, 'P106': {3: 'missed'},
          'P108': {0: 'conflicting', 1: 'missed', 2: 'unknown', 4: 'unknown', 5: 'conflicting'}}
OFFSETS = (0, 7, 14, 21, 28, 35, 41)


def plan(db):
    rows = db.execute("SELECT metadata_json FROM audit_entries WHERE event='fictional.roster_loaded'").fetchall()
    if len(rows) != 1:
        raise ValueError('Expected one recognized fictional roster audit')
    origin = json.loads(rows[0]['metadata_json'])
    dataset = replace_roster.load_dataset()
    allowed_sha = {OLD_SHA, hashlib.sha256(replace_roster.DATASET.read_bytes()).hexdigest()}
    if (origin.get('synthetic') is not True or origin.get('simulated_dates') is not True
            or origin.get('clinical_review') is not False or origin.get('real_user_trial') is not False
            or origin.get('dataset_version') not in ('clinic-roster-20261023-v1', 'clinic-roster-20261023-v2')
            or origin.get('dataset_sha256') not in allowed_sha
            or origin.get('observation_start') != '2026-09-11' or origin.get('observation_end') != '2026-10-22'):
        raise ValueError('Not an eligible fictional S30 database')
    start = date.fromisoformat(origin['observation_start'])
    changes, skipped = [], []
    for profile in dataset['patients']:
        pid = profile['id']
        patient = db.execute('SELECT * FROM patients WHERE id=?', (pid,)).fetchone()
        if not patient or patient['synthetic'] != 1 or patient['user_id'] != profile['login']:
            raise ValueError('Fictional identity differs from the approved roster')
        for index, old_outcome in LEGACY.get(pid, {}).items():
            day = (start + timedelta(days=OFFSETS[index + 1])).isoformat()
            tasks = db.execute('SELECT * FROM adherence_tasks WHERE patient_id=? AND due_at=? AND label=?',
                               (pid, day + 'T08:00:00.000000+00:00', profile['task'])).fetchall()
            if len(tasks) != 1:
                raise ValueError('Expected exactly one original task for ' + pid + ' ' + day)
            task = tasks[0]
            source = db.execute("SELECT id FROM clinical_entries WHERE patient_id=? AND actor_id=? AND kind='self_report' AND observed_on=? AND summary=? AND recorded_at=?",
                                (pid, profile['login'], day, profile['diary'][index + 1], day + 'T09:00:00.000000+00:00')).fetchall()
            if len(source) != 1:
                raise ValueError('Original fictional self-report is missing or changed')
            history = db.execute('SELECT * FROM adherence_entries WHERE task_id=? ORDER BY recorded_at,id', (task['id'],)).fetchall()
            old = [h for h in history if h['actor_id'] == profile['login'] and h['recorded_at'] == day + 'T09:00:00.000000+00:00'
                   and h['outcome'] == old_outcome and h['reason'] == OLD_REASONS[old_outcome]]
            if len(old) > 1:
                raise ValueError('Ambiguous original mark')
            if not old:
                skipped.append({'patient_id': pid, 'day': day, 'reason': 'no_legacy_mark'})
                continue
            old = old[0]
            retry = hashlib.sha256(('S32:' + old['id']).encode()).hexdigest()[:32]
            existing = next((h for h in history if h['request_key'] == retry), None)
            outcome, reason = profile['outcomes'][index], replace_roster.adherence_reason(profile, index)
            if existing:
                if (existing['outcome'], existing['reason']) != (outcome, reason):
                    raise ValueError('Existing correction has different contents')
                skipped.append({'patient_id': pid, 'day': day, 'reason': 'already_corrected'})
                continue
            if history[-1]['id'] != old['id']:
                skipped.append({'patient_id': pid, 'day': day, 'reason': 'later_user_mark_preserved'})
                continue
            user = {'id': profile['login'], 'role': 'patient'}
            relation = communication.pair(db, user, pid)
            if relation['id'] != task['relationship_id'] or communication.superseded(db, task) or task['due_at'] > database.now():
                raise ValueError('Original task is no longer eligible')
            changes.append({'patient_id': pid, 'day': day, 'task_id': task['id'], 'original_mark_id': old['id'],
                            'actor_id': profile['login'], 'old_outcome': old_outcome, 'outcome': outcome,
                            'reason': reason, 'request_key': retry, 'source_entry_id': source[0]['id']})
    return {'changes': changes, 'skipped': skipped}


def repair(path, *, apply=False, backup_path=None):
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError('Existing database required')
    with closing(backup.readonly(path)) as db:
        db.row_factory = sqlite3.Row
        preview = plan(db)
    if not apply:
        return {'applied': False, **preview}
    if not preview['changes']:
        return {'applied': True, 'backup': None, **preview}
    if backup_path is None:
        raise ValueError('A new private backup path is required')
    # Private online backup never overwrites an existing file.
    snapshot = backup.copy_database(path, backup_path)
    with closing(database.connect(path)) as db:
        with database.transaction(db):
            result = plan(db)  # Recheck under the write lock; preserve intervening user marks.
            stamp = database.now()
            for item in result['changes']:
                item['correction_id'] = secrets.token_hex(16)
                db.execute('INSERT INTO adherence_entries VALUES(?,?,?,?,?,?,?)',
                           (item['correction_id'], item['task_id'], item['actor_id'], item['outcome'], item['reason'], stamp, item['request_key']))
            if result['changes']:
                provenance = {'synthetic': True, 'fictional_fixture_correction': True, 'clinical_review': False,
                              'real_user_trial': False, 'actual_corrected_at': stamp, 'corrections': result['changes']}
                db.execute('INSERT INTO audit_entries(event,entity_id,occurred_at,metadata_json) VALUES(?,?,?,?)',
                           ('fictional.adherence_corrected', 'S32', stamp, json.dumps(provenance, ensure_ascii=False)))
        backup.checked(db)
    return {'applied': True, 'backup': str(Path(backup_path).resolve()), 'backup_sha256': snapshot['sha256'], **result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', default='var/compass.sqlite3')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--backup')
    args = parser.parse_args()
    print(json.dumps(repair(args.db, apply=args.apply, backup_path=args.backup), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
