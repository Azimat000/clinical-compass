"""Explicit offline corpus import. No HTTP, patient context, or retrieval code.

The registry is reviewed administrator policy, never request input. Historical
snapshots prove what was imported; current registry and time govern every use.
"""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOCAL_ORIGINALS = {
    'evidence/S09/completion-review/sources/kr301.pdf': 'clinical_guideline',
    'evidence/S09/completion-review/sources/kr457.pdf': 'clinical_guideline',
    'evidence/S02/received/aviandr-patient-leaflet-2026-07-16.pdf': 'patient_leaflet',
}
RIGHTS_SCOPES = {'local_store', 'local_index', 'display_excerpt'}
OFFICIAL_HOSTS = {
    'clinical_guideline': {'apicr.minzdrav.gov.ru', 'cr.minzdrav.gov.ru'},
    'patient_leaflet': {'grls.rosminzdrav.ru'},
}


class CorpusError(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def moment(value):
    try:
        result = datetime.fromisoformat(value)
        if result.tzinfo is None:
            raise ValueError('timezone required')
        return result
    except (ValueError, TypeError):
        raise CorpusError('invalid_timestamp') from None


def local_bytes(root, relative, allowlist):
    if not isinstance(relative, str) or relative not in allowlist:
        raise CorpusError('path_not_allowed')
    path = Path(root)
    for part in Path(relative).parts:
        if part in {'.', '..'}:
            raise CorpusError('path_not_allowed')
        path = path / part
        if path.is_symlink():
            raise CorpusError('symlink_not_allowed')
    if not path.is_file() or not path.resolve().is_relative_to(Path(root).resolve()):
        raise CorpusError('source_missing')
    data = path.read_bytes()
    if not data.startswith(b'%PDF-'):
        raise CorpusError('not_pdf')
    return data


def validate_registry(registry):
    if not isinstance(registry, dict) or registry.get('schema_version') != 1:
        raise CorpusError('registry_schema')
    records = registry.get('sources')
    if not isinstance(records, list):
        raise CorpusError('registry_sources')
    ids, paths, hashes = set(), set(), set()
    for item in records:
        if not isinstance(item, dict):
            raise CorpusError('registry_record')
        for field in ('document_id', 'path', 'sha256'):
            if not isinstance(item.get(field), str) or not item[field].strip():
                raise CorpusError('registry_identity')
        if not re.fullmatch(r'[a-zA-Z0-9_-]+', item['document_id']):
            raise CorpusError('registry_identity')
        if not re.fullmatch(r'[a-f0-9]{64}', item['sha256']):
            raise CorpusError('registry_sha')
        if item['document_id'] in ids or item['path'] in paths or item['sha256'] in hashes:
            raise CorpusError('duplicate_source')
        ids.add(item['document_id']); paths.add(item['path']); hashes.add(item['sha256'])
    return records


def admission_reasons(item, at, *, evidence_root=PROJECT_ROOT):
    """Fail closed for unknown/malformed reviewed metadata; never infer rights."""
    reasons = []
    for field in ('document_family', 'publisher', 'source_url', 'source_version',
                  'document_type', 'admission_id', 'decision_origin'):
        if not isinstance(item.get(field), str) or not item[field].strip():
            reasons.append('metadata_missing:' + field)
    try:
        if not isinstance(item.get('source_url'), str):
            raise ValueError('url type')
        url = urlsplit(item.get('source_url', ''))
        document_type = item.get('document_type')
        official_url = isinstance(document_type, str) and url.scheme == 'https' and url.hostname in OFFICIAL_HOSTS.get(document_type, set()) and url.username is None and url.password is None
    except (TypeError, ValueError):
        official_url = False
    if not official_url:
        reasons.append('official_url_missing')
    if item.get('official_origin_verified') is not True:
        reasons.append('official_origin_unverified')
    if item.get('status') != 'approved':
        reasons.append('admission_' + str(item.get('status', 'unknown')))
    if item.get('official_status') != 'current':
        reasons.append('official_status_unverified')
    for field in ('population', 'indications'):
        value = item.get(field)
        if not isinstance(value, dict) or value.get('verified') is not True or not value.get('text') or not value.get('evidence'):
            reasons.append(field + '_unverified')
    rights = item.get('rights')
    scopes = rights.get('scopes') if isinstance(rights, dict) else None
    if not isinstance(rights, dict) or rights.get('status') != 'verified' or not rights.get('evidence') or not isinstance(scopes, list) or not all(isinstance(s, str) for s in scopes) or not RIGHTS_SCOPES.issubset(set(scopes)):
        reasons.append('rights_unverified')
    proof = item.get('verification')
    if not isinstance(proof, dict) or not proof.get('evidence'):
        reasons.append('verification_missing')
    else:
        for field in ('sha256', 'document_type', 'source_version', 'source_url', 'publisher'):
            if proof.get(field) != item.get(field):
                reasons.append('verification_mismatch:' + field)
        # A reviewed claim must retain its exact supporting report. Policy is
        # trusted administrator input; this checks provenance, not legal truth.
        evidence = proof.get('evidence')
        try:
            if not isinstance(evidence, list) or len(evidence) != 1 or not isinstance(evidence[0], str):
                raise ValueError('evidence list')
            relative = Path(evidence[0])
            if relative.is_absolute() or '..' in relative.parts:
                raise ValueError('evidence path')
            path = Path(evidence_root)
            for part in relative.parts:
                path = path / part
                if path.is_symlink():
                    raise ValueError('evidence symlink')
            if not path.is_file() or not path.resolve().is_relative_to(Path(evidence_root).resolve()) or sha(path.read_bytes()) != proof.get('evidence_sha256'):
                raise ValueError('evidence integrity')
        except (OSError, TypeError, ValueError):
            reasons.append('verification_evidence_integrity')
    try:
        checked, due = moment(item.get('verified_at')), moment(item.get('review_due_at'))
        if checked > at or due <= checked or at >= due:
            reasons.append('review_expired_or_invalid')
        if isinstance(proof, dict) and proof.get('checked_at') != item.get('verified_at'):
            reasons.append('verification_date_mismatch')
    except CorpusError:
        reasons.append('review_date_unknown')
    return sorted(set(reasons))


def build_manifest(root, registry, at, *, archive=False, allowlist=None):
    at = moment(at)
    allowlist = LOCAL_ORIGINALS if allowlist is None else allowlist
    decisions, blobs = [], {}
    for item in validate_registry(registry):
        reasons = admission_reasons(item, at, evidence_root=root)
        data = None
        try:
            data = local_bytes(root, item['path'], allowlist)
            if sha(data) != item['sha256']:
                raise CorpusError('sha_mismatch')
            if allowlist[item['path']] != item.get('document_type'):
                raise CorpusError('document_type_mismatch')
        except CorpusError as exc:
            reasons.append(str(exc))
            data = None
        admitted = not reasons and not archive
        if data is not None and (admitted or archive):
            blobs[item['sha256']] = data
        decisions.append({'document_id': item['document_id'], 'source': item,
                          'disposition': 'admitted' if admitted else ('archived' if archive and data is not None else 'quarantined'),
                          'reasons': sorted(set(reasons + (['archive_only'] if archive else [])))})
    payload = {'schema_version': 1, 'registry_sha256': digest(registry),
               'mode': 'archive' if archive else 'current',
               'sources': decisions, 'blob_sha256': sorted(blobs)}
    payload['corpus_version'] = digest(payload)
    return payload, blobs


def publish_snapshot(destination, manifest, blobs):
    """Exclusive, deterministic publication; repeated import must match bytes.

    A partial directory after interruption is deliberately not loadable. Retry
    fails integrity rather than repairing or silently overwriting an old version.
    """
    version = manifest.get('corpus_version', '')
    if not isinstance(version, str) or not re.fullmatch(r'[a-f0-9]{64}', version) or digest({k: v for k, v in manifest.items() if k != 'corpus_version'}) != version:
        raise CorpusError('snapshot_integrity')
    if sorted(blobs) != manifest.get('blob_sha256') or any(not re.fullmatch(r'[a-f0-9]{64}', key) or sha(data) != key for key, data in blobs.items()):
        raise CorpusError('snapshot_blob_integrity')
    destination = Path(destination).absolute()
    if destination.is_symlink():
        raise CorpusError('destination_symlink')
    target = destination / manifest['corpus_version']
    if target.is_symlink():
        raise CorpusError('snapshot_symlink')
    if target.exists():
        existing = load_snapshot(target)
        if existing != manifest:
            raise CorpusError('snapshot_collision')
        return target, False
    target.mkdir(parents=True)
    for key, data in blobs.items():
        with (target / (key + '.pdf')).open('xb') as stream:
            stream.write(data)
    with (target / 'manifest.json').open('x') as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    load_snapshot(target)
    return target, True


def load_snapshot(path):
    path = Path(path)
    try:
        if path.is_symlink() or (path / 'manifest.json').is_symlink():
            raise CorpusError('snapshot_symlink')
        manifest = json.loads((path / 'manifest.json').read_text())
        if not isinstance(manifest, dict):
            raise CorpusError('snapshot_schema')
        payload = {k: v for k, v in manifest.items() if k != 'corpus_version'}
        if digest(payload) != manifest['corpus_version'] or path.name != manifest['corpus_version']:
            raise CorpusError('snapshot_integrity')
        if manifest['schema_version'] != 1 or manifest['mode'] not in {'current', 'archive'}:
            raise CorpusError('snapshot_schema')
        permitted = {'quarantined', 'archived' if manifest['mode'] == 'archive' else 'admitted'}
        if not isinstance(manifest['sources'], list) or any(
                not isinstance(entry, dict) or entry.get('disposition') not in permitted
                or not isinstance(entry.get('reasons'), list) for entry in manifest['sources']):
            raise CorpusError('snapshot_schema')
        records = validate_registry({'schema_version': 1, 'sources': [entry['source'] for entry in manifest['sources']]})
        expected_blobs = sorted(r['sha256'] for r, entry in zip(records, manifest['sources']) if entry['disposition'] in {'admitted', 'archived'})
        if expected_blobs != manifest['blob_sha256']:
            raise CorpusError('snapshot_blob_list')
        for entry in manifest['sources']:
            if entry['document_id'] != entry['source']['document_id']:
                raise CorpusError('snapshot_identity')
        expected = {'manifest.json'} | {key + '.pdf' for key in expected_blobs}
        if {p.name for p in path.iterdir()} != expected:
            raise CorpusError('snapshot_contents')
        for key in expected_blobs:
            blob = path / (key + '.pdf')
            if blob.is_symlink() or sha(blob.read_bytes()) != key:
                raise CorpusError('snapshot_blob_integrity')
        return manifest
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise CorpusError('snapshot_invalid:' + str(exc)) from exc


def eligible_sources(snapshot_path, registry, at, *, evidence_root=PROJECT_ROOT):
    """Runtime seam for J03–J06: always pass current trusted registry and clock.

    Changes of any reviewed metadata quarantine an old snapshot until explicit
    reimport. Thus revocation is immediate without rewriting historical evidence.
    """
    manifest = load_snapshot(snapshot_path)
    at = moment(at)
    current = {s['document_id']: s for s in validate_registry(registry)}
    admitted, refused = [], {}
    for entry in manifest['sources']:
        item = current.get(entry['document_id'])
        reasons = []
        if manifest['mode'] == 'archive' or entry['disposition'] != 'admitted':
            reasons.append('snapshot_not_admitted')
        if item is None:
            reasons.append('source_removed')
        else:
            reasons.extend(admission_reasons(item, at, evidence_root=evidence_root))
            if digest(item) != digest(entry['source']):
                reasons.append('registry_changed_reimport_required')
        if reasons:
            refused[entry['document_id']] = sorted(set(reasons))
        else:
            admitted.append(item)
    return {'corpus_version': manifest['corpus_version'], 'registry_sha256': digest(registry),
            'status': 'AVAILABLE' if admitted else 'NO_ADMITTED_SOURCE',
            'admitted': admitted, 'refused': refused}
