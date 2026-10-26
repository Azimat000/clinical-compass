#!/usr/bin/env python3
"""One explicitly synthetic DeepSeek call; never reads a patient database."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from apps.compass.backend_model import Budget, Config, DeepSeek, ModelError

SCHEMA = {'type': 'object', 'properties': {
    'case_id': {'type': 'string', 'enum': ['fictional-be04']},
    'recorded_days': {'type': 'integer', 'minimum': 0},
    'diagnosis': {'type': 'null'}},
    'required': ['case_id', 'recorded_days', 'diagnosis'], 'additionalProperties': False}
INPUT = {'case_id': 'fictional-be04', 'synthetic': True,
         'note': 'Вымышленный тест: самочувствие записано в понедельник и во вторник. '
                 'Посчитай число дней recorded_days. Диагноз неизвестен: diagnosis=null.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    key_path = Path(__file__).resolve().parents[1] / 'var/deepseek-api-key'
    if key_path.exists():
        if key_path.stat().st_mode & 0o077:
            raise SystemExit('Local credential file must have mode 0600')
        os.environ['DEEPSEEK_API_KEY'] = key_path.read_text().strip()
    adapter = DeepSeek(Config(model='deepseek-flash', timeout=60, max_output_tokens=128),
                       Budget(Path(__file__).resolve().parents[1] / 'var/deepseek-budget.sqlite3'))
    try:
        result = adapter.generate(INPUT, SCHEMA, synthetic=True)
        # Independent deterministic assertion measures this narrow task's quality.
        expected = {'case_id': 'fictional-be04', 'recorded_days': 2, 'diagnosis': None}
        report = {'status': 'pass' if result['value'] == expected else 'quality_failed',
                  'timestamp_utc': datetime.now(timezone.utc).isoformat(),
                  'synthetic_input': INPUT, 'expected': expected, **result}
    except ModelError as exc:
        report = {'status': 'failed', 'error_code': exc.code,
                  'timestamp_utc': datetime.now(timezone.utc).isoformat(),
                  'billing': 'unknown; reservation retained; no automatic retry'}
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['status'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())
