"""Only synthetic temporary databases and loopback HTTP; no working DB access."""
import http.cookiejar
import json
import os
from pathlib import Path
import platform
import re
import secrets
import socket
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import build_opener, HTTPCookieProcessor, urlopen
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'apps/tests'))
from apps.compass import access, clinical_rules, records
from apps.compass.db import connect, migrate, now
from apps.compass.repository import seed_demo
from test_access import PASSWORD, PASSWORD_HASH


def machine():
    import importlib.metadata as metadata
    import sqlite3
    return {'platform': platform.platform(), 'machine': platform.machine(), 'cpu_count': os.cpu_count(),
            'python': sys.version, 'sqlite': sqlite3.sqlite_version,
            'packages': {p:metadata.version(p) for p in ('Flask','Werkzeug','waitress')},
            'hardware': subprocess.check_output(['sysctl','-n','machdep.cpu.brand_string','hw.memsize']).decode().strip() if sys.platform=='darwin' else platform.processor(),
            'server': 'Waitress CLI threads=4, SQLite DELETE/FULL, local disk', 'at':now()}


def fixture(path, pairs=1):
    db = connect(path); migrate(db); seed_demo(db)
    people=[]
    for i in range(pairs):
        doctor, patient, pid = f'load-doc-{i}', f'load-pat-{i}', f'L{i:03}'
        for uid,role in ((doctor,'doctor'),(patient,'patient')):
            db.execute('INSERT INTO users VALUES(?,?,?,?,0)',(uid,role,uid,PASSWORD_HASH))
        db.execute('INSERT INTO patients VALUES(?,?,?,NULL,19,\'known\',1,?)',(pid,patient,pid,now()))
        db.execute('INSERT INTO care_relationships VALUES(?,?,?,?,NULL)',(f'rel-{i}',pid,doctor,now()))
        doc={'id':doctor,'role':'doctor'}
        clinical_rules.save_context(db,doc,pid,{'request_key':secrets.token_hex(16),'observed_on':records.today().isoformat(),
            'gad_status':'present','severity':'nonsevere','suicide_risk':'denied','psychiatric_comorbidity':'denied',
            'treatment_resistance':'denied','aviandr_prescription':'active','clinical_basis':'Synthetic fixture only',
            'prescription_basis':'Synthetic fixture only'})
        people.append((doctor,patient,pid))
    db.close()
    return people


def form(critical=False, key=None):
    data={'request_key':key or secrets.token_hex(16),'observed_on':records.today().isoformat(),
          'summary':'Синтетическая нагрузка S15','wellbeing':'same','age_status':'unknown'}
    if critical:
        data.update({'safety_form_version':'aviandr-safety-v1',**{'safety_'+f:'present' if f in ('taken','after_dose','current','rigidity') else 'denied' for f in clinical_rules.SAFETY_FIELDS}})
    return data


class Browser:
    def __init__(self,url):
        self.url=url
        self.opener=build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.token=None
    def request(self,path='/',data=None):
        start=time.perf_counter()
        try:
            with self.opener.open(self.url+path, None if data is None else urlencode(data).encode(), timeout=60) as r:
                code,body=r.status,r.read().decode()
        except HTTPError as e:
            code,body=e.code,e.read().decode()
        return code,body,(time.perf_counter()-start)*1000
    def login(self,uid):
        code,body,_=self.request('/login'); assert code==200
        token=re.search(r'name="csrf" value="([^"]+)"',body).group(1)
        code,body,ms=self.request('/login',{'csrf':token,'login':uid,'password':PASSWORD})
        assert code==200 and 'name="csrf"' in body, (uid,code)
        self.token=re.search(r'name="csrf" value="([^"]+)"',body).group(1)
        return ms
    def post(self,path,data):
        return self.request(path,{'csrf':self.token,**data})


class Server:
    def __init__(self,path,folder):
        self.path=path; self.folder=Path(folder); self.process=None
        with socket.socket() as s:
            s.bind(('127.0.0.1',0)); self.port=s.getsockname()[1]
        self.url=f'http://127.0.0.1:{self.port}'
    def start(self):
        self.log=open(self.folder/f'server-{time.time_ns()}.log','wb')
        self.process=subprocess.Popen([sys.executable,'-m','apps.compass','--db',str(self.path),'serve','--port',str(self.port)],cwd=ROOT,stdout=self.log,stderr=self.log)
        for _ in range(200):
            if self.process.poll() is not None: raise RuntimeError('server exited')
            try:
                with urlopen(self.url+'/healthz',timeout=.2) as r:
                    if r.status==200: return
            except OSError: time.sleep(.05)
        raise RuntimeError('server start timeout')
    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.kill(); self.process.wait(timeout=10)
        if hasattr(self,'log'): self.log.close()


def summary(values):
    values=sorted(values)
    import math
    return {'n':len(values),'p50_ms':values[max(0,math.ceil(len(values)*.5)-1)],
            'p95_ms':values[max(0,math.ceil(len(values)*.95)-1)],'max_ms':max(values)}
