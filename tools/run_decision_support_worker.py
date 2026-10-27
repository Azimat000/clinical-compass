"""Dedicated generation lane plus persistent automatic UI updates."""
import argparse
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from apps.compass.db import connect
from apps.compass import backend_jobs, backend_ui_updates

parser = argparse.ArgumentParser()
parser.add_argument('--db', required=True)
args = parser.parse_args()
db = connect(args.db)
try:
    while True:
        backend_ui_updates.tick(db)
        if not backend_jobs.process_one(db, lane='generation'):
            time.sleep(1)
finally:
    db.close()
