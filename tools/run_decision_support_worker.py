"""Dedicated generation lane plus persistent automatic UI updates."""
import argparse
import os
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from apps.compass.db import connect
from apps.compass import backend_jobs, backend_ui_updates, backend_diagnosis_preview

parser = argparse.ArgumentParser()
parser.add_argument('--db', required=True)
args = parser.parse_args()
# The local opt-in does not put credentials in arguments, files of evidence or logs.
if backend_diagnosis_preview.configuration() and not os.environ.get('DEEPSEEK_API_KEY'):
    secret = Path(__file__).resolve().parents[1] / 'var/deepseek-api-key'
    if secret.stat().st_mode & 0o077:
        raise RuntimeError('Existing model credential must be private')
    os.environ['DEEPSEEK_API_KEY'] = secret.read_text().strip()
db = connect(args.db)
try:
    while True:
        backend_ui_updates.tick(db)
        if not backend_jobs.process_one(db, lane='generation'):
            time.sleep(1)
finally:
    db.close()
