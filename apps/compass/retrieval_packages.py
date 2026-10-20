"""Administrator policy for registered offline packages; never request input."""
import json
from pathlib import Path
import re

from .retrieval_corpus import (CorpusError, LOCAL_ORIGINALS, LOCAL_REFERENCE_CARDS, digest,
                               local_file, validate_registry)

POLICY_PATH = 'data/retrieval/admission-packages.json'
PACKAGE_CATALOG = 'data/retrieval/packages'


def read_json(root, relative):
    try:
        return json.loads(local_file(root, relative, {relative}))
    except (OSError, ValueError, TypeError) as exc:
        raise CorpusError('package_json_invalid:' + str(relative)) from exc


def package_registry(root, package_ids=None):
    """Only registered IDs, narrow roots, exact files and no symlinks/URLs.

    Registration grants permission to read a package, never admission or rights.
    Legacy singleton keeps its exact registry digest and manifest unchanged.
    """
    policy = read_json(root, POLICY_PATH)
    if not isinstance(policy, dict) or policy.get('schema_version') != 1:
        raise CorpusError('package_policy_schema')
    packages = policy.get('packages')
    if not isinstance(packages, list) or not packages:
        raise CorpusError('package_policy_empty')
    by_id, roots = {}, set()
    for package in packages:
        if not isinstance(package, dict) or set(package) - {'id', 'root', 'registry', 'replaces'} or not {'id', 'root', 'registry'} <= set(package):
            raise CorpusError('package_registration_schema')
        pid = package['id']
        if not isinstance(pid, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', pid) or pid in by_id:
            raise CorpusError('package_identity')
        if pid == 'J02':
            if package['root'] is not None or package['registry'] != 'data/retrieval/source-registry.json':
                raise CorpusError('legacy_package_changed')
        else:
            expected = PACKAGE_CATALOG + '/' + pid
            if package['root'] != expected or package['registry'] != expected + '/registry.json':
                raise CorpusError('package_root_not_trusted')
            if expected in roots:
                raise CorpusError('package_root_duplicate')
            roots.add(expected)
        by_id[pid] = package
        replacements = package.get('replaces', {})
        if not isinstance(replacements, dict) or not all(isinstance(k, str) and isinstance(v, str) and re.fullmatch(r'[a-f0-9]{64}', v) for k, v in replacements.items()):
            raise CorpusError('package_replacement_schema')
        if pid == 'J02' and replacements:
            raise CorpusError('legacy_package_changed')
    selected = policy.get('enabled') if package_ids is None else package_ids
    if not isinstance(selected, list) or not selected or not all(isinstance(p, str) for p in selected):
        raise CorpusError('package_selection_empty')
    if len(set(selected)) != len(selected) or any(p not in by_id for p in selected):
        raise CorpusError('package_not_registered')
    registries, originals, cards, candidates = [], {}, {}, {}
    trusted_roots = [p['root'] + '/' for p in by_id.values() if p['root'] is not None]
    for pid in selected:
        package = by_id[pid]
        registry = read_json(root, package['registry'])
        records = validate_registry(registry)
        for item in records:
            original, artifact = item['path'], item.get('artifact_path')
            if pid == 'J02':
                if original not in LOCAL_ORIGINALS or (artifact is not None and LOCAL_REFERENCE_CARDS.get(artifact) != item['document_id']):
                    raise CorpusError('legacy_path_not_allowed')
            else:
                prefix = package['root'] + '/'
                for relative in [original] + ([artifact] if artifact is not None else []):
                    if not isinstance(relative, str) or '..' in Path(relative).parts or Path(relative).is_absolute():
                        raise CorpusError('package_path_not_allowed')
                # Reuse already held originals explicitly; never copy a full PDF
                # merely to extend its bounded reviewed representation.
                if original not in LOCAL_ORIGINALS and not any(original.startswith(p) for p in trusted_roots):
                    raise CorpusError('package_path_not_allowed')
                if artifact is not None and not artifact.startswith(prefix):
                    raise CorpusError('package_path_not_allowed')
                if original == package['registry'] or artifact in (original, package['registry']):
                    raise CorpusError('package_path_collision')
            original_type = LOCAL_ORIGINALS.get(original, item.get('document_type'))
            if original in originals and originals[original] != original_type:
                raise CorpusError('package_original_type_conflict')
            originals[original] = original_type
            if artifact is not None:
                if artifact in cards or artifact in originals:
                    raise CorpusError('package_path_collision')
                cards[artifact] = item['document_id']
            candidates.setdefault(item['document_id'], []).append((pid, item))
        if set(package.get('replaces', {})) - {r['document_id'] for r in records}:
            raise CorpusError('package_replacement_missing_source')
        registries.append(registry)
    resolved = []
    for document_id, entries in candidates.items():
        declared = [(pid, item) for pid, item in entries if document_id in by_id[pid].get('replaces', {})]
        if len(entries) == 1:
            if declared:
                raise CorpusError('package_replacement_previous_missing')
            resolved.append(entries[0][1])
        elif len(entries) == 2 and len(declared) == 1:
            pid, replacement = declared[0]
            previous = next(item for owner, item in entries if owner != pid)
            if by_id[pid]['replaces'][document_id] != digest(previous):
                raise CorpusError('package_replacement_previous_changed')
            resolved.append(replacement)
        else:
            raise CorpusError('package_replacement_ambiguous')
    combined = registries[0] if len(registries) == 1 else {
        'schema_version': 1, 'package_ids': sorted(selected),
        'replacements': {pid: by_id[pid].get('replaces', {}) for pid in sorted(selected)},
        'sources': sorted(resolved, key=lambda item: item['document_id'])}
    validate_registry(combined)
    if set(originals) & set(cards):
        raise CorpusError('package_path_collision')
    return combined, originals, cards
