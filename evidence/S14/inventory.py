"""Offline metadata, safe repository scan and reproducible route inventory."""
from pathlib import Path
import hashlib
import importlib.metadata
import json
import platform
import re
import sqlite3
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from apps.compass.web import create_app

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    out=ROOT/'evidence/S14'
    with tempfile.TemporaryDirectory() as tmp:
        app=create_app(Path(tmp)/'db.sqlite3')
        routes=[{'endpoint':r.endpoint,'rule':r.rule,'methods':sorted(r.methods)} for r in app.url_map.iter_rules()]
    tracked=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard'],cwd=ROOT,text=True).splitlines()
    patterns={'private_key':r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
              'openai_key':r'\bsk-(?:proj-)?[A-Za-z0-9_-]{40,}',
              'aws_access_key':r'\bAKIA[0-9A-Z]{16}\b'}
    findings=[]
    for name in tracked:
        p=ROOT/name
        if not p.is_file() or p.suffix.lower() in ('.pdf','.png','.jpg','.zip','.gz'):continue
        try:text=p.read_text()
        except UnicodeError:continue
        for kind,pattern in patterns.items():
            count=len(re.findall(pattern,text))
            if count:findings.append({'path':name,'kind':kind,'count':count})
    dependencies=[{'name':d.metadata['Name'],'version':d.version,
                   'license':d.metadata.get('License-Expression') or d.metadata.get('License')}
                  for d in importlib.metadata.distributions()]
    data={'platform':platform.platform(),'python':sys.version,'sqlite':sqlite3.sqlite_version,
          'routes':routes,'mutating_routes':sum('POST' in r['methods'] and r['endpoint'] not in ('login','static','healthz') for r in routes),
          'patient_routes':sum('patient_id' in r['rule'] for r in routes),
          'dependencies':sorted(dependencies,key=lambda d:d['name'].lower()),
          'tracked_files_scanned':len(tracked),'secret_pattern_findings':findings,
          'scan_limits':'Narrow pattern scan, not a guarantee of no PII/secrets. No values emitted; known public test passwords are fixtures.',
          'protected_files':{p:sha(ROOT/p) for p in tracked if p.startswith(('apps/compass/migrations/','apps/compass/resources/','data/synthetic/','.agents/')) or p=='apps/requirements.lock'}}
    (out/'inventory.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'mutating_routes':data['mutating_routes'],'patient_routes':data['patient_routes'],'secret_pattern_findings':findings},ensure_ascii=False))

if __name__=='__main__':main()
