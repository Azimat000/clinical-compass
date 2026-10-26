"""Internal synthetic episode ledger; deliberately not wired to HTTP or jobs.

An episode groups review work by relationship, origin and topic, not a clinical
diagnosis. Exact references/quotes remain observations, not established facts.
Only a current physician can close an episode. Absence and denial never close it.
"""
from contextlib import contextmanager
from copy import deepcopy
import json
import re
import secrets

from . import backend_analyses as analyses, backend_risk_context as context
from . import backend_risk_rules as rules, backend_snapshot as snapshots, access, decisions
from .db import now, transaction

VERSION = 'risk-episodes-v1'


@contextmanager
def atomic(db):
    # Also roll back our own partial work when a caller catches inside its txn.
    if not db.in_transaction:
        with transaction(db):
            yield
    else:
        name = 'risk_episodes_' + secrets.token_hex(8)
        db.execute('SAVEPOINT ' + name)
        try:
            yield
            db.execute('RELEASE ' + name)
        except BaseException:
            db.execute('ROLLBACK TO ' + name)
            db.execute('RELEASE ' + name)
            raise


def _scope(db, user, patient_id):
    relationship = analyses.authorize(db, user, patient_id)
    if db.execute('SELECT synthetic FROM patients WHERE id=?', (patient_id,)).fetchone()[0] != 1:
        raise analyses.AnalysisError('Доступна только синтетическая история.', 409, 'synthetic_only')
    return relationship


def _episode(db, relationship, episode_id):
    row = db.execute('SELECT * FROM backend_risk_episodes WHERE id=? AND relationship_id=?',
                     (episode_id, relationship)).fetchone()
    if row is None:
        raise analyses.AnalysisError('Эпизод недоступен.', 404, 'not_found')
    return dict(row)


def _versions(db, episode_id):
    return [{**dict(row), 'payload': json.loads(row['payload_json'])} for row in db.execute(
        'SELECT * FROM backend_risk_episode_versions WHERE episode_id=? ORDER BY revision', (episode_id,))]


def read(db, user, patient_id, episode_id=None):
    with atomic(db):
        relationship = _scope(db, user, patient_id)
        rows = ([_episode(db, relationship, episode_id)] if episode_id else
                [dict(r) for r in db.execute('SELECT * FROM backend_risk_episodes WHERE relationship_id=? ORDER BY created_at,id',
                                            (relationship,))])
        for row in rows:
            history = _versions(db, row['id'])
            row.update(version=VERSION, state=history[-1]['state'], revision=history[-1]['revision'],
                       history=history, clinical_ready=False, assessment='not_established')
        return rows[0] if episode_id else rows


def _validated_report(snapshot, report):
    """Rebuild citations from the stored snapshot, independent of supplied spans."""
    if (type(report) is not dict or report.get('version') != context.VERSION
            or report.get('snapshot_sha256') != snapshots.digest(snapshot)
            or report.get('status') != 'partial' or report.get('assessment') != 'not_established'
            or report.get('clinical_ready') is not False
            or report.get('prompt_sha256') != context.PROMPT_SHA256
            or snapshots.digest(report.get('structured')) != snapshots.digest(rules.evaluate(snapshot))):
        raise analyses.AnalysisError('Результат не соответствует снимку.', 409, 'invalid_episode_report')
    try:
        units = context.prepare_snapshot(snapshot)
        candidates = report['model_candidates']
        proposals = {'candidates': [{'topic': c['topic'], 'evidence': [
            {'unit_id': e['unit_id'], 'quote': e['quote']} for e in c['evidence']]} for c in candidates]}
        if snapshots.digest(context.verify(proposals, units, snapshots.digest(snapshot))) != snapshots.digest(candidates):
            raise ValueError()
        missing = [c for c in context.CATEGORIES if not any(c in u['categories'] for u in units)]
        if report['missing_categories'] != missing:
            raise ValueError()
        evaluation = report['model_evaluation']
        if evaluation == 'not_evaluated':
            if candidates or not report['errors']:
                raise ValueError()
        elif evaluation != 'candidates_only' or report['errors']:
            raise ValueError()
        metadata = report.get('model_metadata')
        provenance = {}
        if metadata is not None:
            if not isinstance(metadata, dict):
                raise ValueError()
            for key in ('provider', 'requested_model', 'returned_model', 'prompt_version',
                        'prompt_sha256', 'schema_sha256', 'test_double'):
                if key in metadata:
                    item = metadata[key]
                    if key == 'test_double':
                        if type(item) is not bool:
                            raise ValueError()
                    elif not isinstance(item, str) or not item.strip() or len(item) > 150:
                        raise ValueError()
                    provenance[key] = item
        # Persist sanitized technical reasons, never provider error text/metadata.
        errors = []
        for error in report['errors']:
            code = error['code']
            if not isinstance(code, str) or re.fullmatch(r'[a-z][a-z0-9_]{0,79}', code) is None:
                raise ValueError()
            errors.append({'code': code, 'stage': 'model_candidate_evaluation'})
    except (ValueError, TypeError, KeyError):
        raise analyses.AnalysisError('Недостоверное основание эпизода.', 409, 'invalid_episode_report') from None
    return {'version': VERSION, 'candidate_version': context.VERSION,
            'prompt_sha256': context.PROMPT_SHA256, 'snapshot_sha256': snapshots.digest(snapshot),
            'clinical_ready': False, 'status': 'partial', 'assessment': 'not_established',
            'structured': deepcopy(report['structured']), 'model_candidates': deepcopy(candidates),
            'model_evaluation': evaluation, 'model_provenance': provenance,
            'missing_categories': missing, 'errors': errors}


def _findings(snapshot, report):
    structured = report['structured']
    if structured.get('status') == 'ready':
        result = structured['result']
        facts = {f['id']: f for f in result['facts']}
        for pattern in result['output']['patterns']:
            # Only decisive rule references determine novelty. Unrelated age
            # history or a new snapshot day must not reopen a closed episode.
            decisive = facts['fact-' + pattern['id']]
            refs = decisive['evidence_refs']
            evidence = [{'source_ref': ref, 'source': snapshots.resolve(snapshot, ref)} for ref in refs]
            if any(e['source'] is None for e in evidence):
                raise analyses.AnalysisError('Нет основания правила.', 409, 'invalid_episode_report')
            yield 'rule', pattern['id'], [{'sha256': snapshots.digest(e), 'value': e} for e in evidence], {
                'pattern': pattern, 'facts': [facts[fid] for fid in pattern['fact_ids']],
                'interpretation': 'reproducible_rule_for_physician_review'}
    for candidate in report['model_candidates']:
        # A different span from the same unchanged field is not a new fact.
        # All candidate spans remain in the per-run evaluation history.
        evidence = [{'sha256': snapshots.digest([e['source_ref'], e['path'], e['field_sha256']]),
                     'value': e} for e in candidate['evidence']]
        evidence = list({e['sha256']: e for e in evidence}.values())
        yield 'model_candidate', candidate['topic'], evidence, candidate


def observe(db, user, patient_id, run_id, report):
    """Persist one internal evaluation atomically; caller performs model work first.

    A run is consumed once. A different report for the same run is a conflict.
    No inference, provider calls, analysis publication or delivery happens here.
    """
    with atomic(db):
        relationship = _scope(db, user, patient_id)
        run = db.execute('SELECT * FROM analysis_runs WHERE id=? AND patient_id=? AND relationship_id=? AND actor_id=? AND operation=\'risk\'',
                         (run_id, patient_id, relationship, user['id'])).fetchone()
        if run is None:
            raise analyses.AnalysisError('Запуск недоступен.', 404, 'not_found')
        current = analyses.read(db, user, patient_id, run_id)
        if current['status'] not in ('running', 'ready'):
            raise analyses.AnalysisError('Запуск устарел или не выполняется.', 409, 'run_unavailable')
        snapshot = json.loads(db.execute('SELECT payload_json FROM analysis_input_snapshots WHERE id=?',
                                         (run['snapshot_id'],)).fetchone()[0])
        if snapshot.get('policy') != 'synthetic-inputs-v1' or snapshot['patients'][0]['synthetic'] != 1:
            raise analyses.AnalysisError('Доступна только синтетика.', 409, 'synthetic_only')
        value = _validated_report(snapshot, report)
        sha = snapshots.digest(value)
        previous = db.execute('SELECT * FROM backend_risk_episode_evaluations WHERE run_id=?', (run_id,)).fetchone()
        if previous:
            if sha != previous['report_sha256']:
                raise analyses.AnalysisError('Запуск уже сохранён с другим ответом.', 409, 'evaluation_conflict')
            return json.loads(previous['payload_json'])
        changed = []
        for origin, topic, evidence, finding in _findings(snapshot, value):
            added = [e for e in evidence if not db.execute(
                'SELECT 1 FROM backend_risk_episode_evidence WHERE relationship_id=? AND origin=? AND topic=? AND evidence_sha256=?',
                (relationship, origin, topic, e['sha256'])).fetchone()]
            if not added:
                continue
            # One open work item per topic and origin. Historical closed items
            # remain separate; repeats from them cannot create a new episode.
            existing = db.execute('''SELECT e.id FROM backend_risk_episodes e
                WHERE e.relationship_id=? AND e.origin=? AND e.topic=? AND NOT EXISTS (
                    SELECT 1 FROM backend_risk_episode_versions v WHERE v.episode_id=e.id AND v.state='closed')''',
                (relationship, origin, topic)).fetchone()
            episode_id = existing['id'] if existing else secrets.token_hex(16)
            if not existing:
                db.execute('INSERT INTO backend_risk_episodes VALUES(?,?,?,?,?,?)',
                           (episode_id, patient_id, relationship, origin, topic, now()))
            for e in added:
                db.execute('INSERT INTO backend_risk_episode_evidence VALUES(?,?,?,?,?,?,?)',
                           (episode_id, relationship, origin, topic, e['sha256'], run_id, decisions.canonical(e['value'])))
            revision = db.execute('SELECT coalesce(max(revision),0)+1 FROM backend_risk_episode_versions WHERE episode_id=?',
                                  (episode_id,)).fetchone()[0]
            payload = {'version': VERSION, 'snapshot_id': run['snapshot_id'], 'finding': finding,
                       'added_evidence': [e['sha256'] for e in added], 'clinical_ready': False}
            db.execute('INSERT INTO backend_risk_episode_versions VALUES(?,?,?,?,?,?,?,?,?)',
                       (episode_id, revision, 'open', 'new_evidence' if existing else 'first_observation',
                        user['id'], run_id, decisions.canonical(payload), None, now()))
            changed.append({'episode_id': episode_id, 'revision': revision})
        value['changed_episodes'] = changed
        db.execute('INSERT INTO backend_risk_episode_evaluations VALUES(?,?,?,?)',
                   (run_id, sha, decisions.canonical(value), now()))
        access.audit(db, user['id'], 'risk_episodes.observed', run_id)
        return value


def close(db, user, patient_id, episode_id, expected_revision, reason, request_key):
    if (type(expected_revision) is not int or expected_revision < 1 or not isinstance(reason, str)
            or not reason.strip() or len(reason) > 1000 or '\x00' in reason
            or not isinstance(request_key, str) or re.fullmatch(r'[a-zA-Z0-9_-]{16,80}', request_key) is None):
        raise analyses.AnalysisError('Нужны точная версия, причина и ключ повтора.')
    with atomic(db):
        relationship = _scope(db, user, patient_id)
        _episode(db, relationship, episode_id)
        previous = db.execute('SELECT * FROM backend_risk_episode_versions WHERE request_key=?', (request_key,)).fetchone()
        if previous:
            if (previous['episode_id'] != episode_id or previous['revision'] != expected_revision + 1
                    or previous['reason'] != reason or previous['actor_id'] != user['id']):
                raise analyses.AnalysisError('Ключ уже использован с другими данными.', 409, 'idempotency_conflict')
            return read(db, user, patient_id, episode_id)
        latest = _versions(db, episode_id)[-1]
        if latest['revision'] != expected_revision or latest['state'] != 'open':
            raise analyses.AnalysisError('Эпизод изменился; прочитайте новую версию.', 409, 'revision_conflict')
        payload = {'version': VERSION, 'decision': 'physician_closed_review_episode', 'clinical_ready': False,
                   'limitation': 'Закрытие задачи рассмотрения не устанавливает отсутствие риска.'}
        db.execute('INSERT INTO backend_risk_episode_versions VALUES(?,?,?,?,?,?,?,?,?)',
                   (episode_id, expected_revision + 1, 'closed', reason, user['id'], None,
                    decisions.canonical(payload), request_key, now()))
        access.audit(db, user['id'], 'risk_episodes.closed', episode_id)
        return read(db, user, patient_id, episode_id)
