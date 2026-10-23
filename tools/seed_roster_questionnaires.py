"""Append explicitly authored PHQ/GAD fictional histories to the recognized S30 roster.

No clinical inference, score conversion, clock patch, source activation, UPDATE or DELETE.
Historical dates/actors are simulated. A real-time provenance record identifies the import.
Dry run by default; --apply requires a new private backup. Never runs at service startup.
"""
import argparse
from contextlib import closing
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from apps.compass import assessments, backup, db as database
from tools import replace_roster

DATASET = ROOT / 'data/fictional/questionnaires-20261023.json'
S30_V1_SHA = '0672755710be534f138666eda271ef3498465e56e177a59787721ccdc0d7a872'
EVENT = 'fictional.questionnaires_loaded'


def load_dataset():
    data = json.loads(DATASET.read_text())
    roster = replace_roster.load_dataset()
    roster_sha = hashlib.sha256(replace_roster.DATASET.read_bytes()).hexdigest()
    if (data['roster_sha256'] != roster_sha or data['version'] != 'clinic-questionnaires-20261023-v1'
            or data['provenance'] != {'synthetic': True, 'simulated_dates': True, 'clinical_review': False,
                'real_user_trial': False, 'authored_item_responses': True, 'derived_from_dass': False}
            or data['dates'] != ['2026-09-11', '2026-10-02', '2026-10-22']
            or data['forms'] != {'phq': 'PHQ9-RU-Z-2023-demo-v1', 'gad': 'GAD7-RU-Z-2023-demo-v1'}
            or set(data['patients']) != {p['id'] for p in roster['patients']}):
        raise ValueError('Unrecognized authored dataset or roster')
    for profile in roster['patients']:
        item = data['patients'][profile['id']]
        if len(item['rationale']) != 3 or any(not s.strip() for s in item['rationale']):
            raise ValueError('Every date requires an authored narrative rationale')
        for code in ('phq', 'gad'):
            if len(item[code]) != 3:
                raise ValueError('Three response vectors required')
            form = assessments.definition(data['forms'][code])
            metric = next(iter(form['subscales']))
            for index, vector in enumerate(item[code]):
                score = assessments.score_answers(vector, form)
                expected = item['expected'][index][0 if code == 'phq' else 1]
                if (score[metric] if score is not None else None) != expected:
                    raise ValueError('Reference score mismatch')
    return data, roster


def stable_id(*parts):
    return hashlib.sha256(':'.join(parts).encode()).hexdigest()[:32]


def plan(db):
    data, roster = load_dataset()
    sha = hashlib.sha256(DATASET.read_bytes()).hexdigest()
    origins = db.execute("SELECT metadata_json FROM audit_entries WHERE event='fictional.roster_loaded'").fetchall()
    if len(origins) != 1:
        raise ValueError('Expected one recognized fictional roster origin')
    origin = json.loads(origins[0]['metadata_json'])
    if (any(origin.get(k) is not v for k, v in {'synthetic': True, 'simulated_dates': True,
                    'clinical_review': False, 'real_user_trial': False}.items())
            or origin.get('dataset_version') not in ('clinic-roster-20261023-v1', 'clinic-roster-20261023-v2')
            or origin.get('dataset_sha256') not in (S30_V1_SHA, data['roster_sha256'])
            or origin.get('observation_start') != data['dates'][0] or origin.get('observation_end') != data['dates'][-1]):
        raise ValueError('Not the recognized synthetic roster')
    prior = db.execute('SELECT metadata_json FROM audit_entries WHERE event=? AND entity_id=?', (EVENT, data['version'])).fetchall()
    if len(prior) > 1 or prior and json.loads(prior[0]['metadata_json'])['dataset_sha256'] != sha:
        raise ValueError('Existing import provenance differs from the dataset')
    forms = {code: assessments.available_form(db, form_id) for code, form_id in data['forms'].items()}
    changes, skipped = [], []
    for profile in roster['patients']:
        pid = profile['id']
        patient = db.execute('SELECT * FROM patients WHERE id=?', (pid,)).fetchone()
        if (not patient or patient['synthetic'] != 1 or patient['user_id'] != profile['login']
                or patient['code'] != profile['name'] or patient['age_status'] != 'known'
                or patient['age_years'] != profile['age']):
            raise ValueError('Fictional identity/age differs from the approved roster: ' + pid)
        for index, day in enumerate(data['dates']):
            original = db.execute('''SELECT q.*,a.id source_assessment_id FROM assessment_requests q
                JOIN assessment_results r ON r.request_id=q.id JOIN assessments a ON a.id=r.assessment_id
                JOIN catalog_versions c ON c.id=q.form_version_id
                WHERE q.patient_id=? AND c.code='DASS-42' AND r.observed_on=?''', (pid, day)).fetchall()
            visit = db.execute('''SELECT id FROM clinical_entries WHERE patient_id=? AND kind='visit'
                AND actor_id=? AND observed_on=? AND summary=?''', (pid, profile['doctor'], day, profile['visits'][index])).fetchall()
            if len(original) != 1 or len(visit) != 1:
                raise ValueError('Original fictional visit/DASS anchor missing or ambiguous: ' + pid + ' ' + day)
            source = original[0]
            previous_answers = json.loads(db.execute('SELECT answers_json FROM assessments WHERE id=?', (source['source_assessment_id'],)).fetchone()[0])
            if previous_answers[20] != data['patients'][pid]['prior_dass_item21'][index]:
                raise ValueError('Original DASS safety-related response differs; re-author the fixture explicitly')
            relation = db.execute('''SELECT r.* FROM care_relationships r JOIN users d ON d.id=r.doctor_id
                JOIN users p ON p.id=? WHERE r.id=? AND r.patient_id=? AND r.doctor_id=?
                AND r.ends_at IS NULL AND d.disabled=0 AND p.disabled=0''',
                (profile['login'], source['relationship_id'], pid, profile['doctor'])).fetchone()
            age = json.loads(source['age_snapshot_json'])
            if (not relation or source['requested_by'] != profile['doctor'] or source['age_on'] != day
                    or source['age_years'] != profile['age'] or age['status'] != 'known'
                    or age['years'] != profile['age'] or not age.get('verification_token')):
                raise ValueError('Historic age or care relationship is not eligible')
            for code, form in forms.items():
                if not form['min_age'] <= source['age_years'] <= form['max_age']:
                    raise ValueError('Historic age outside the exact form release')
                requested = day + ('T13:10:00.000000+00:00' if code == 'phq' else 'T13:20:00.000000+00:00')
                received = day + ('T13:15:00.000000+00:00' if code == 'phq' else 'T13:25:00.000000+00:00')
                if relation['starts_at'] > requested:
                    raise ValueError('Care relationship did not exist at the simulated date')
                request_id = stable_id(data['version'], pid, form['id'], day, 'request')
                assessment_id = stable_id(data['version'], pid, form['id'], day, 'assessment')
                vector = data['patients'][pid][code][index]
                scores = assessments.score_answers(vector, form)
                payload = assessments.canonical({'form_version_id': form['id'], 'age': age, 'age_basis': source['age_basis']})
                request_row = (request_id, pid, relation['id'], form['id'], profile['doctor'], requested,
                    day+'T21:00:00.000000+00:00', day, source['age_years'], source['age_basis'], source['age_snapshot_json'],
                    hashlib.sha256(('S35:'+request_id).encode()).hexdigest(), payload)
                assessment_row = (assessment_id, pid, form['id'], profile['doctor'], received,
                    assessments.canonical(vector), None, 'complete' if scores is not None else 'incomplete', assessments.scoring_version(form))
                result_row = (assessment_id, request_id, profile['login'], day, received,
                    assessments.canonical(scores) if scores is not None else None)
                summary = {'patient_id': pid, 'day': day, 'code': form['code'], 'request_id': request_id,
                    'assessment_id': assessment_id, 'scores': scores, 'source_assessment_id': source['source_assessment_id'],
                    'source_visit_entry_id': visit[0]['id'], 'incomplete': scores is None}
                existing = [db.execute('SELECT * FROM '+table+' WHERE '+key+'=?', (value,)).fetchone()
                            for table, key, value in [('assessment_requests','id',request_id),
                                ('assessments','id',assessment_id),('assessment_results','assessment_id',assessment_id)]]
                if any(existing):
                    if not all(existing) or [tuple(r) for r in existing] != [request_row, assessment_row, result_row]:
                        raise ValueError('Existing fixture rows differ; refusing overwrite')
                    skipped.append({**summary, 'reason': 'already_imported'})
                    continue
                if db.execute('''SELECT 1 FROM assessments a JOIN assessment_results r ON r.assessment_id=a.id
                    JOIN catalog_versions c ON c.id=a.scale_version_id WHERE a.patient_id=? AND c.code=? AND r.observed_on=?''',
                    (pid, form['code'], day)).fetchone():
                    skipped.append({**summary, 'reason': 'existing_other_response_preserved'})
                    continue
                if prior:
                    raise ValueError('A previously imported row is missing; refusing silent repair')
                changes.append({'summary': summary, 'request': request_row, 'assessment': assessment_row, 'result': result_row})
    return {'changes': changes, 'skipped': skipped, 'dataset_sha256': sha, 'dataset_version': data['version']}


def public(result):
    return {**result, 'changes': [item['summary'] for item in result['changes']]}


def seed(path, *, apply=False, backup_path=None):
    path = Path(path).resolve()
    with closing(backup.readonly(path)) as db:
        db.row_factory = sqlite3.Row
        preview = plan(db)
    if not apply or not preview['changes']:
        return {'applied': apply, 'backup': None, **public(preview)}
    if backup_path is None:
        raise ValueError('A new private backup path is required')
    snapshot = backup.copy_database(path, backup_path)
    with closing(database.connect(path)) as db:
        with database.transaction(db):
            result = plan(db)
            for item in result['changes']:
                db.execute('INSERT INTO assessment_requests VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)', item['request'])
                db.execute('INSERT INTO assessments VALUES(?,?,?,?,?,?,?,?,?)', item['assessment'])
                db.execute('INSERT INTO assessment_results VALUES(?,?,?,?,?,?)', item['result'])
            if result['changes']:
                stamp = database.now()
                provenance = {'synthetic': True, 'simulated_dates': True, 'clinical_review': False, 'real_user_trial': False,
                    'actual_imported_at': stamp, 'authored_item_responses': True, 'derived_from_dass': False,
                    'dataset_version': result['dataset_version'], 'dataset_sha256': result['dataset_sha256'],
                    'source': str(DATASET.relative_to(ROOT)), 'entries': [i['summary'] for i in result['changes']]}
                db.execute('INSERT INTO audit_entries(event,entity_id,occurred_at,metadata_json) VALUES(?,?,?,?)',
                    (EVENT, result['dataset_version'], stamp, assessments.canonical(provenance)))
            backup.checked(db)
    return {'applied': True, 'backup': str(Path(backup_path).resolve()), 'backup_sha256': snapshot['sha256'], **public(result)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', default='var/compass.sqlite3')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--backup')
    args = parser.parse_args()
    print(json.dumps(seed(args.db, apply=args.apply, backup_path=args.backup), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
