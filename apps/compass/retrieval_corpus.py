"""Explicit offline corpus import. No HTTP, patient context, or retrieval code.

The registry is reviewed administrator policy, never request input. Historical
snapshots prove what was imported; current registry and time govern every use.
"""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import os
import tempfile
from urllib.parse import urlsplit


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOCAL_ORIGINALS = {
    'evidence/S09/completion-review/sources/kr301.pdf': 'clinical_guideline',
    'evidence/S09/completion-review/sources/kr457.pdf': 'clinical_guideline',
    'evidence/S02/received/aviandr-patient-leaflet-2026-07-16.pdf': 'patient_leaflet',
}
LOCAL_REFERENCE_CARDS = {
    'data/retrieval/reference-cards/KR301_3.json': 'KR301_3',
    'data/retrieval/reference-cards/KR457_3.json': 'KR457_3',
    'data/retrieval/reference-cards/AVIANDR_LEAFLET_160726.json': 'AVIANDR_LEAFLET_160726',
}
RIGHTS_SCOPES = {'local_store', 'local_index', 'display_excerpt'}
OFFICIAL_HOSTS = {
    'clinical_guideline': {'apicr.minzdrav.gov.ru', 'cr.minzdrav.gov.ru'},
    'patient_leaflet': {'grls.rosminzdrav.ru', 'grls.rosminzdrav.gov.ru'},
    'medication_instruction': {'grls.rosminzdrav.ru', 'grls.rosminzdrav.gov.ru'},
    'sm_pc': {'grls.rosminzdrav.ru', 'grls.rosminzdrav.gov.ru'},
    'safety_update': {'roszdravnadzor.gov.ru', 'www.roszdravnadzor.gov.ru'},
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


def local_file(root, relative, allowlist):
    if not isinstance(relative, str) or Path(relative).is_absolute() or relative not in allowlist:
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
    return path.read_bytes()


def local_bytes(root, relative, allowlist):
    data = local_file(root, relative, allowlist)
    if not data.startswith(b'%PDF-'):
        raise CorpusError('not_pdf')
    return data


def evidence_matches(root, relative, expected):
    try:
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or '..' in Path(relative).parts:
            return False
        return sha(local_file(root, relative, {relative})) == expected
    except (OSError, CorpusError, TypeError, ValueError):
        return False


def reference_reasons(item, data):
    """Validate only the explicitly reviewed collection, never the whole PDF."""
    try:
        bundle = json.loads(data)
        required = {'schema_version', 'representation', 'document_id', 'source_sha256',
                    'source_version', 'source_url', 'document_type', 'attribution', 'fragments'}
        if not isinstance(bundle, dict) or set(bundle) != required or bundle['schema_version'] != 1 or bundle['representation'] != 'reviewed_cards':
            return ['citation_schema']
        for key in ('document_id', 'source_version', 'source_url', 'document_type'):
            if bundle[key] != item[key]:
                return ['citation_source_mismatch']
        if bundle['source_sha256'] != item['sha256']:
            return ['citation_source_mismatch']
        attribution = bundle['attribution']
        if not isinstance(attribution, dict) or set(attribution) != {'title', 'authors', 'source', 'locator'} or not all(isinstance(v, str) and v.strip() for v in attribution.values()):
            return ['citation_attribution_missing']
        fragments = bundle['fragments']
        if not isinstance(fragments, list) or not fragments:
            return ['citation_empty']
        ids = []
        for fragment in fragments:
            if not isinstance(fragment, dict) or set(fragment) != {'fragment_id', 'page', 'section', 'claim_type', 'paraphrase', 'quote', 'required_context', 'purpose', 'volume_justification'}:
                return ['citation_fragment_schema']
            from .retrieval_primary import is_primary, locator_kind
            html_locator = is_primary(item) and locator_kind(item) == 'html_section'
            page_valid = fragment['page'] is None if html_locator else type(fragment['page']) is int and fragment['page'] > 0
            if not page_valid or not all(isinstance(fragment[k], str) and fragment[k].strip() for k in ('fragment_id', 'section', 'paraphrase', 'purpose', 'volume_justification')):
                return ['citation_fragment_schema']
            if not isinstance(fragment['required_context'], list) or not all(isinstance(v, str) and v.strip() for v in fragment['required_context']):
                return ['citation_context_schema']
            if fragment['claim_type'] == 'fact':
                if fragment['quote'] is not None or fragment['required_context']:
                    return ['fact_contains_verbatim']
            elif fragment['claim_type'] == 'fact_with_quote':
                if not isinstance(fragment['quote'], str) or not fragment['quote'].strip() or attribution['authors'] == 'NOT_STATED_IN_DOCUMENT' or fragment['paraphrase'] == fragment['quote']:
                    return ['citation_attribution_missing']
            else:
                return ['citation_fragment_schema']
            ids.append(fragment['fragment_id'])
        review = item['rights']['content_review']
        if not isinstance(review, dict):
            return ['citation_rights_unverified']
        from .retrieval_primary import is_primary
        if is_primary(item) and any(f['claim_type'] != 'fact' for f in fragments):
            return ['primary_quotes_not_allowed']
        if sum(f['claim_type'] == 'fact_with_quote' for f in fragments) > 1:
            return ['citation_collection_limit']
        total = sum(len(f['quote'] or '') + sum(len(c) for c in f['required_context']) for f in fragments)
        basis = 'GK1259_5_FACTS_AND_GK1274_1_1_CITATIONS' if total else 'GK1259_5_FACTS'
        if review.get('basis') != basis or item['rights'].get('index_fields') != ['paraphrase']:
            return ['citation_basis_mismatch']
        if len(ids) != len(set(ids)) or sorted(ids) != sorted(review['fragment_ids']) or total != review['quoted_characters']:
            return ['citation_review_mismatch']
        if review['artifact_sha256'] != sha(data) or item['artifact_sha256'] != sha(data):
            return ['citation_review_mismatch']
    except (ValueError, TypeError, KeyError, UnicodeError):
        return ['citation_schema']
    return []


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
    from .retrieval_primary import is_primary, validate_primary
    if is_primary(item):
        try:
            validate_primary(item, evidence_root)
            official_url = True
        except (CorpusError, OSError, ValueError, KeyError, TypeError) as exc:
            official_url = False
            reasons.append('primary_admission:' + str(exc))
    elif item.get('original_storage') is not None:
        reasons.append('original_storage_not_allowed')
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
    representation = item.get('representation', 'full_pdf')
    rights = item.get('rights')
    scopes = rights.get('scopes') if isinstance(rights, dict) else None
    required_scopes = RIGHTS_SCOPES if representation != 'reviewed_cards' else {'local_store','local_index','display_reference'}
    if isinstance(rights, dict) and isinstance(rights.get('content_review'), dict) and rights['content_review'].get('quoted_characters'):
        required_scopes = required_scopes | {'display_excerpt'}
    if not isinstance(rights, dict) or rights.get('status') != 'verified' or not rights.get('evidence') or not isinstance(scopes, list) or not all(isinstance(s, str) for s in scopes) or not required_scopes.issubset(set(scopes)):
        reasons.append('rights_unverified')
    if representation not in ('full_pdf', 'reviewed_cards'):
        reasons.append('representation_unknown')
    if isinstance(rights, dict) and rights.get('representation', 'full_pdf') != representation:
        reasons.append('rights_representation_mismatch')
    if representation == 'reviewed_cards':
        review = rights.get('content_review') if isinstance(rights, dict) else None
        evidence = rights.get('evidence_sha256') if isinstance(rights, dict) else None
        if not isinstance(review, dict) or review.get('purpose_and_volume_reviewed') is not True or review.get('attribution_reviewed') is not True or review.get('basis') not in ('GK1259_5_FACTS_AND_GK1274_1_1_CITATIONS','GK1259_5_FACTS') or not isinstance(review.get('fragment_ids'), list) or not all(isinstance(v, str) for v in review['fragment_ids']) or type(review.get('quoted_characters')) is not int:
            reasons.append('citation_rights_unverified')
        paths = rights.get('evidence') if isinstance(rights, dict) else None
        if not isinstance(evidence, dict) or not evidence or not isinstance(paths, list) or not all(isinstance(p, str) for p in paths) or set(evidence) != set(paths) or not all(evidence_matches(evidence_root, p, h) for p, h in evidence.items()):
            reasons.append('citation_rights_evidence_integrity')
        try:
            record_path = review['record_path']
            report = local_file(evidence_root, record_path, evidence)
            if sha(report) != evidence[record_path]:
                raise CorpusError('review_changed')
            decision = json.loads(report)['documents'][item['document_id']]
            expected = {'source_sha256':item['sha256'], 'artifact_sha256':item['artifact_sha256'],
                        'fragment_ids':review['fragment_ids'], 'quoted_characters':review['quoted_characters'],
                        'basis':review['basis']}
            if not isinstance(decision, dict) or any(decision.get(k) != v for k, v in expected.items()) or decision.get('text_and_context_verified') is not True:
                raise CorpusError('review_mismatch')
        except (OSError, CorpusError, TypeError, KeyError, ValueError):
            reasons.append('citation_approval_record_mismatch')
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


def build_manifest(root, registry, at, *, archive=False, allowlist=None, reference_allowlist=None):
    at = moment(at)
    allowlist = LOCAL_ORIGINALS if allowlist is None else allowlist
    reference_allowlist = LOCAL_REFERENCE_CARDS if reference_allowlist is None else reference_allowlist
    decisions, blobs = [], {}
    for item in validate_registry(registry):
        reasons = admission_reasons(item, at, evidence_root=root)
        data = None
        try:
            from .retrieval_primary import is_primary, validate_primary
            if is_primary(item):
                if item['path'] not in allowlist:
                    raise CorpusError('path_not_allowed')
                data = validate_primary(item, root)
            else:
                data = local_bytes(root, item['path'], allowlist)
                if sha(data) != item['sha256']:
                    raise CorpusError('sha_mismatch')
            if allowlist[item['path']] != item.get('document_type'):
                raise CorpusError('document_type_mismatch')
            if item.get('representation') == 'reviewed_cards':
                if not isinstance(item.get('artifact_path'), str) or reference_allowlist.get(item['artifact_path']) != item['document_id']:
                    raise CorpusError('citation_path_not_allowed')
                data = local_file(root, item['artifact_path'], reference_allowlist)
                errors = reference_reasons(item, data)
                if errors:
                    raise CorpusError(errors[0])
        except (CorpusError, OSError) as exc:
            reasons.append(str(exc))
            data = None
        if archive and any(r.startswith(('rights_', 'citation_rights_', 'citation_approval_', 'citation_basis_')) for r in reasons):
            # Historical originals already held are preserved in place. Archive
            # mode is not authority to create a new copy with unknown rights.
            reasons.append('archive_storage_not_authorized')
            data = None
        admitted = not reasons and not archive
        if data is not None and (admitted or archive):
            blobs[item.get('artifact_sha256') if item.get('representation') == 'reviewed_cards' else item['sha256']] = data
        decisions.append({'document_id': item['document_id'], 'source': item,
                          'disposition': 'admitted' if admitted else ('archived' if archive and data is not None else 'quarantined'),
                          'reasons': sorted(set(reasons + (['archive_only'] if archive else [])))})
    formats = {key: ('json' if data.lstrip().startswith(b'{') else 'pdf') for key, data in blobs.items()}
    payload = {'schema_version': 2, 'registry_sha256': digest(registry),
               'mode': 'archive' if archive else 'current',
               'sources': decisions, 'blob_sha256': sorted(blobs), 'blob_formats': formats}
    payload['corpus_version'] = digest(payload)
    return payload, blobs


def publish_snapshot(destination, manifest, blobs):
    """Validate in staging, then atomically publish an immutable version."""
    version = manifest.get('corpus_version', '')
    if not isinstance(version, str) or not re.fullmatch(r'[a-f0-9]{64}', version) or digest({k: v for k, v in manifest.items() if k != 'corpus_version'}) != version:
        raise CorpusError('snapshot_integrity')
    if sorted(blobs) != manifest.get('blob_sha256') or any(not re.fullmatch(r'[a-f0-9]{64}', key) or sha(data) != key for key, data in blobs.items()):
        raise CorpusError('snapshot_blob_integrity')
    formats = blob_formats(manifest)
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
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.building-', dir=destination) as staging:
        prepared = Path(staging) / version
        prepared.mkdir()
        for key, data in blobs.items():
            with (prepared / (key + '.' + formats[key])).open('xb') as stream:
                stream.write(data)
        with (prepared / 'manifest.json').open('x') as stream:
            json.dump(manifest, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        load_snapshot(prepared)
        try:
            os.rename(prepared, target)
        except OSError:
            if not target.exists() or load_snapshot(target) != manifest:
                raise
            return target, False
    return target, True


def blob_formats(manifest):
    keys = manifest['blob_sha256']
    formats = manifest.get('blob_formats') if manifest['schema_version'] == 2 else {k: 'pdf' for k in keys}
    if not isinstance(formats, dict) or set(formats) != set(keys) or any(v not in ('pdf', 'json') for v in formats.values()):
        raise CorpusError('snapshot_blob_formats')
    return formats


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
        if manifest['schema_version'] not in (1, 2) or manifest['mode'] not in {'current', 'archive'}:
            raise CorpusError('snapshot_schema')
        permitted = {'quarantined', 'archived' if manifest['mode'] == 'archive' else 'admitted'}
        if not isinstance(manifest['sources'], list) or any(
                not isinstance(entry, dict) or entry.get('disposition') not in permitted
                or not isinstance(entry.get('reasons'), list) for entry in manifest['sources']):
            raise CorpusError('snapshot_schema')
        records = validate_registry({'schema_version': 1, 'sources': [entry['source'] for entry in manifest['sources']]})
        expected_blobs = sorted((r.get('artifact_sha256') if r.get('representation') == 'reviewed_cards' else r['sha256']) for r, entry in zip(records, manifest['sources']) if entry['disposition'] in {'admitted', 'archived'})
        if expected_blobs != manifest['blob_sha256']:
            raise CorpusError('snapshot_blob_list')
        for entry in manifest['sources']:
            if entry['document_id'] != entry['source']['document_id']:
                raise CorpusError('snapshot_identity')
        formats = blob_formats(manifest)
        expected = {'manifest.json'} | {key + '.' + formats[key] for key in expected_blobs}
        if {p.name for p in path.iterdir()} != expected:
            raise CorpusError('snapshot_contents')
        for key in expected_blobs:
            blob = path / (key + '.' + formats[key])
            if blob.is_symlink() or sha(blob.read_bytes()) != key:
                raise CorpusError('snapshot_blob_integrity')
        for entry in manifest['sources']:
            if entry['disposition'] not in {'admitted', 'archived'}:
                continue
            item = entry['source']
            bounded = item.get('representation') == 'reviewed_cards'
            key = item['artifact_sha256'] if bounded else item['sha256']
            if formats[key] != ('json' if bounded else 'pdf'):
                raise CorpusError('snapshot_representation_mismatch')
            if bounded and reference_reasons(item, (path/(key+'.json')).read_bytes()):
                raise CorpusError('snapshot_citation_invalid')
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


def indexable_cards(snapshot_path, registry, at, *, evidence_root=PROJECT_ROOT):
    """The only bounded-corpus projection for future J04 index builders.

    This is an offline export, not search or an HTTP route. Quotes and original
    PDFs cannot become index text by being passed through this interface.
    """
    eligibility = eligible_sources(snapshot_path, registry, at, evidence_root=evidence_root)
    cards = []
    for item in eligibility['admitted']:
        if item.get('representation') != 'reviewed_cards':
            raise CorpusError('unsupported_index_representation')
        try:
            data = (Path(snapshot_path)/(item['artifact_sha256']+'.json')).read_bytes()
        except OSError as exc:
            raise CorpusError('citation_unavailable_before_projection') from exc
        if reference_reasons(item, data):
            raise CorpusError('citation_changed_before_projection')
        for fragment in json.loads(data)['fragments']:
            cards.append({'document_id': item['document_id'], 'fragment_id': fragment['fragment_id'],
                          'text': fragment['paraphrase']})
    return {'corpus_version': eligibility['corpus_version'], 'status': eligibility['status'],
            'cards': cards, 'refused': eligibility['refused']}
