"""Opt-in inactive extension sandbox. Never imported by the clinical pipeline.

Bundles are data, not executable Python. No eval, dynamic imports, clinical releases
or real alerts. Existing source/catalog version identities are append-only here.
"""
import hashlib
import json
from .db import transaction, now


def install(db, bundle):
    if bundle.get('scope') != 'synthetic_test' or bundle.get('schema_version') != 1:
        raise ValueError('Only synthetic_test schema 1 is supported')
    with transaction(db):
        for item in bundle['items']:
            if item['kind'] not in ('scale', 'drug', 'rule') or not item['id'].startswith('test-'):
                raise ValueError('Test namespace and supported kind required')
            definition = json.dumps(item['definition'], ensure_ascii=False, sort_keys=True)
            source_id = item['id'] + '-source'
            expected = (item['kind'], item['code'], item['version'], source_id, definition)
            old = db.execute('SELECT kind,code,version,source_version_id,definition_json FROM catalog_versions WHERE id=?', (item['id'],)).fetchone()
            if old:
                if tuple(old) != expected:
                    raise ValueError('Published test version cannot be overwritten')
                continue
            db.execute('INSERT INTO source_versions VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (source_id, item['code'], item['version'], 'local:synthetic-test',
                        hashlib.sha256(definition.encode()).hexdigest(), now(), '{}', 'unknown', 'unknown', 'unverified'))
            db.execute('''INSERT INTO catalog_versions(id,kind,code,version,source_version_id,definition_json,status,blocker)
                VALUES(?,?,?,?,?,?,'inactive','Synthetic extension test only; no clinical activation')''',
                       (item['id'], *expected))


def preview(db, version_id, inputs=None):
    row = db.execute('SELECT * FROM catalog_versions WHERE id=?', (version_id,)).fetchone()
    if not row or not row['id'].startswith('test-') or row['status'] != 'inactive':
        raise ValueError('Only inactive test versions can be previewed')
    definition = json.loads(row['definition_json'])
    if row['kind'] == 'scale':
        # Exercise the existing data-driven scoring engine unchanged, within its
        # supported 42-item / 0..3 contract. This is not a new medical instrument.
        from .assessments import score_answers
        return score_answers(inputs, definition)
    if row['kind'] == 'drug':
        return definition
    if definition.get('operator') != 'equals' or not isinstance(inputs, dict):
        raise ValueError('Unsupported simulation rule')
    field = definition['field']
    return {'version': row['version'], 'simulation': True,
            'result': 'unknown' if field not in inputs else ('matched' if inputs[field] == definition['value'] else 'no_match'),
            'message': definition['message']}
