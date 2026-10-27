"""Explicit local opt-in to unvalidated synthetic diagnosis drafts.

This is not a quality receipt. It cannot change source, budget, evidence,
physician review or clinical-release gates, and never enables real patient data.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / 'var/diagnosis-preview-authorization.json'
VERSION = 'synthetic-diagnosis-preview-v1'


def configuration():
    try:
        raw = PATH.read_bytes()
        value = json.loads(raw)
        if (value.get('version') != VERSION or value.get('enabled') is not True
                or value.get('mode') != 'synthetic_unverified'
                or value.get('operations') != ['diagnosis']
                or value.get('quality_pass') is not False
                or value.get('clinical_release') is not False
                or not isinstance(value.get('patient_ids'), list)
                or not value['patient_ids']
                or any(not isinstance(item, str) for item in value['patient_ids'])):
            return None
        return value, hashlib.sha256(raw).hexdigest()
    except (OSError, ValueError, TypeError):
        return None


def release():
    config = configuration()
    return {'version': VERSION, 'enabled': config is not None,
            'authorization_sha256': config[1] if config else None,
            'code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'quality_pass': False, 'clinical_release': False}


def allowed(snapshot, operation):
    config = configuration()
    patients = snapshot.get('patients', [])
    return bool(config and operation == 'diagnosis'
        and snapshot.get('policy') == 'synthetic-inputs-v1'
        and len(patients) == 1 and patients[0].get('synthetic') == 1
        and patients[0].get('id') in config[0]['patient_ids'])
