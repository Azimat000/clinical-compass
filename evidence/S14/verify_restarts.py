"""Five separate process scenarios, preserve each failure rather than retry to green."""
import json
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[2]
rows=[]
for i in range(5):
    result=subprocess.run([sys.executable,'apps/tests/smoke_restart.py'],cwd=ROOT,capture_output=True,text=True,timeout=120)
    rows.append({'run':i+1,'exit_code':result.returncode,'stdout':result.stdout,'stderr':result.stderr})
print(json.dumps({'runs':rows,'failures':sum(r['exit_code']!=0 for r in rows),
    'limit':'Fresh synthetic scenarios, two server starts per run; successful samples do not establish the historical B12 root cause.'},ensure_ascii=False,indent=2))
raise SystemExit(any(r['exit_code']!=0 for r in rows))
