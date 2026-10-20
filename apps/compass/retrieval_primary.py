"""Six exact DASS primary identities; offline provenance, never a web loader."""
import json

from .retrieval_corpus import CorpusError, local_file, sha

POLICY = 'data/retrieval/primary-source-policy.json'
PREFIX = 'data/retrieval/packages/DASS42/'
STORAGE = 'verified_primary_receipt'
# This is an identity allowlist, not permission for all pages on these hosts.
IDENTITIES = {
    'DASS42_RU_FORM': ('instrument_form', 'pdf_page', {'https://dass.psy.unsw.edu.au/Russian/Fattakhov/Fattakhov_DASS_rus.pdf'}),
    'DASS42_EN_KEY': ('instrument_key', 'pdf_page', {'https://dass.psy.unsw.edu.au/Download%20files/Dass_template.pdf'}),
    'DASS42_RU_TRANSLATION': ('instrument_provenance', 'html_section', {'https://dass.psy.unsw.edu.au/Russian/Fattakhov/Fattakhov%20Russian.htm'}),
    'DASS42_GUIDANCE': ('instrument_guidance', 'html_section', {'https://dass.psy.unsw.edu.au/DASSFAQ.htm'}),
    'DASS42_DOWNLOAD_TERMS': ('instrument_terms', 'html_section', {'https://dass.psy.unsw.edu.au/down.htm'}),
    'DASS42_RU_VALIDATION_2025': ('validation_study', 'html_section', {'https://www.mediasphera.ru/issues/zhurnal-nevrologii-i-psikhiatrii-im-s-s-korsakova/2025/5/1199772982025051103'}),
}
TYPES = {v[0] for v in IDENTITIES.values()}
PIN_FIELDS = {'document_id', 'document_type', 'source_url', 'source_version', 'sha256',
              'artifact_path', 'artifact_sha256', 'path', 'receipt_sha256', 'locator_kind',
              'byte_length', 'media_type', 'verified_at'}
RECEIPT_FIELDS = {'schema_version', 'document_id', 'source_url', 'source_sha256',
                  'source_version', 'checked_at', 'byte_length', 'media_type', 'locator_kind',
                  'verification_path', 'verification_sha256'}


def is_primary(item):
    return ((isinstance(item.get('document_type'), str) and item['document_type'] in TYPES)
            or (isinstance(item.get('document_id'), str) and item['document_id'] in IDENTITIES)
            or item.get('original_storage') == STORAGE)


def locator_kind(item):
    identity = IDENTITIES.get(item.get('document_id'))
    return identity[1] if identity else 'pdf_page'


def validate_primary(item, root):
    """Recheck exact pins, receipt and external audit on every eligibility read.

    A receipt proves the reviewed acquisition, not possession or a licence of the
    source text. Only independently reviewed authored cards enter a snapshot.
    """
    identity = IDENTITIES.get(item.get('document_id'))
    if not identity or item.get('document_type') != identity[0] or item.get('source_url') not in identity[2]:
        raise CorpusError('primary_identity_not_allowed')
    if item.get('representation') != 'reviewed_cards' or item.get('original_storage') != STORAGE:
        raise CorpusError('primary_representation_not_allowed')
    if item.get('locator_kind') != identity[1]:
        raise CorpusError('primary_locator_kind')
    policy = json.loads(local_file(root, POLICY, {POLICY}))
    if set(policy) != {'schema_version', 'sources'} or policy['schema_version'] != 1 or not isinstance(policy['sources'], list):
        raise CorpusError('primary_policy_schema')
    ids = [p['document_id'] for p in policy['sources']]
    if len(ids) != len(set(ids)) or any(i not in IDENTITIES for i in ids):
        raise CorpusError('primary_policy_identity')
    matches = [p for p in policy['sources'] if p['document_id'] == item['document_id']]
    if len(matches) != 1 or set(matches[0]) != PIN_FIELDS | {'status', 'resource_bindings'}:
        raise CorpusError('primary_pin_missing')
    pin = matches[0]
    if pin['status'] != 'approved' or any(pin[k] != item.get(k) for k in PIN_FIELDS):
        raise CorpusError('primary_pin_changed_or_revoked')
    for key, suffix in [('path', '.receipt.json'), ('artifact_path', '.cards.json')]:
        if pin[key] != PREFIX + item['document_id'] + suffix:
            raise CorpusError('primary_path_not_allowed')
    data = local_file(root, pin['path'], {pin['path']})
    if sha(data) != pin['receipt_sha256']:
        raise CorpusError('primary_receipt_integrity')
    receipt = json.loads(data)
    if set(receipt) != RECEIPT_FIELDS or receipt['schema_version'] != 1:
        raise CorpusError('primary_receipt_schema')
    for key in ['document_id', 'source_url', 'source_version', 'byte_length', 'media_type', 'locator_kind']:
        if receipt[key] != pin[key]:
            raise CorpusError('primary_receipt_mismatch')
    if receipt['source_sha256'] != pin['sha256'] or receipt['checked_at'] != pin['verified_at']:
        raise CorpusError('primary_receipt_mismatch')
    if type(pin['byte_length']) is not int or pin['byte_length'] <= 0:
        raise CorpusError('primary_response_metadata')
    if pin['media_type'] not in ({'application/pdf'} if identity[1] == 'pdf_page' else {'text/html'}):
        raise CorpusError('primary_response_metadata')
    proof = item['verification']
    if proof['evidence'] != [receipt['verification_path']] or proof['evidence_sha256'] != receipt['verification_sha256']:
        raise CorpusError('primary_verification_mismatch')
    report_data = local_file(root, receipt['verification_path'], {receipt['verification_path']})
    if sha(report_data) != receipt['verification_sha256']:
        raise CorpusError('primary_verification_integrity')
    row = json.loads(report_data)['primary_sources'][item['document_id']]
    expected = {k: receipt[k] for k in ['source_url', 'source_version', 'checked_at', 'byte_length', 'media_type', 'locator_kind']}
    expected['sha256'] = receipt['source_sha256']
    if any(row.get(k) != v for k, v in expected.items()) or row.get('verified') is not True or row.get('tls_verified') is not True:
        raise CorpusError('primary_acquisition_not_verified')
    if not isinstance(pin['resource_bindings'], list):
        raise CorpusError('primary_resource_binding')
    for binding in pin['resource_bindings']:
        if set(binding) != {'path', 'sha256'} or binding['path'] != 'apps/compass/resources/dass42-ru-v1.json':
            raise CorpusError('primary_resource_binding')
        body = local_file(root, binding['path'], {binding['path']})
        if sha(body) != binding['sha256']:
            raise CorpusError('primary_resource_changed')
        resource = json.loads(body)
        if resource.get('id') != 'DASS42-RU-FG-2024-demo-v1' or resource.get('code') != 'DASS-42':
            raise CorpusError('primary_resource_identity')
        if row.get('resource_match_verified') is not True or row.get('resource_sha256') != binding['sha256']:
            raise CorpusError('primary_resource_match_unverified')
        if item['document_id'] == 'DASS42_RU_FORM' and resource.get('source', {}).get('sha256') != item['sha256']:
            raise CorpusError('primary_resource_source_mismatch')
    if item['document_id'] in {'DASS42_RU_FORM', 'DASS42_EN_KEY'} and len(pin['resource_bindings']) != 1:
        raise CorpusError('primary_resource_binding')
    return data
