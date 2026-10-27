"""Explicit local-copy worker launcher; secrets never enter command arguments."""
import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
p=argparse.ArgumentParser();p.add_argument('--lane',required=True,choices=['risk','generation']);p.add_argument('--live-model',action='store_true');a=p.parse_args()
target=ROOT/'var/FE02-integration.sqlite3'
assert target.is_file() and target.resolve() != (ROOT/'var/compass.sqlite3').resolve()
os.environ.pop('DEEPSEEK_API_KEY',None)
if a.live_model:
    assert (ROOT/'evidence/FE02/research.md').is_file()
    assert datetime.now(timezone.utc)<datetime.fromisoformat('2026-10-27T19:17:00+03:00'), 'Source gate expired; do not extend it here'
    key=ROOT/'var/deepseek-api-key';assert key.stat().st_mode & 0o077 == 0
    os.environ['DEEPSEEK_API_KEY']=key.read_text().strip()
sys.argv=['compass','--db',str(target),'worker','--lane',a.lane]
from apps.compass.__main__ import main
main()
