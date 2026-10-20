#!/usr/bin/env python3
"""Administrator-only offline import of reviewed source representations."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from apps.compass.retrieval_corpus import (CorpusError, build_manifest,
                                          eligible_sources, publish_snapshot)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--archive', action='store_true')
    parser.add_argument('--at', help='Explicit aware timestamp for reproducible audit; default actual UTC time')
    args = parser.parse_args()
    at = args.at or datetime.now(timezone.utc).isoformat()
    registry = json.loads((ROOT / 'data/retrieval/source-registry.json').read_text())
    try:
        manifest, blobs = build_manifest(ROOT, registry, at, archive=args.archive)
        path, created = publish_snapshot(args.destination, manifest, blobs)
        eligibility = eligible_sources(path, registry, at)
        print(json.dumps({'snapshot': str(path.resolve()), 'created': created, 'evaluated_at': at,
                          'corpus_version': manifest['corpus_version'],
                          'admitted_count': len(eligibility['admitted']),
                          'status': eligibility['status'],
                          'decisions': [{'document_id': s['document_id'], 'disposition': s['disposition'],
                                         'reasons': s['reasons']} for s in manifest['sources']]}, ensure_ascii=False, indent=2))
    except CorpusError as exc:
        print(json.dumps({'status': 'UNAVAILABLE', 'reason': str(exc)}))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
