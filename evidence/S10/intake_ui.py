"""Actual HTTP synthetic intake while doctor browser is open; only fixed fixture credentials."""
import http.cookiejar,json,re,secrets,sys,time
from pathlib import Path
from urllib.request import build_opener,HTTPCookieProcessor
from urllib.parse import urlencode
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from apps.compass.records import today
from apps.compass.db import connect
origin='http://127.0.0.1:8030'
c=build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
html=c.open(origin+'/login').read().decode(); token=re.search(r'name="csrf" value="([^"]+)"',html).group(1)
c.open(origin+'/login',urlencode({'csrf':token,'login':'pat-a','password':'synthetic-test-password-2026'}).encode()).read()
html=c.open(origin+'/').read().decode();token=re.search(r'name="csrf" value="([^"]+)"',html).group(1)
form={'csrf':token,'request_key':secrets.token_hex(16),'observed_on':today().isoformat(),'safety_form_version':'aviandr-safety-v1','safety_taken':'present','safety_after_dose':'present','safety_current':'present','safety_rigidity':'present'}
start=time.perf_counter();body=urlencode(form).encode()
c.open(origin+'/patients/D01/self-reports',body).read();c.open(origin+'/patients/D01/self-reports',body).read()
db=connect(ROOT/'var/s10-ui.sqlite3');row=dict(db.execute('SELECT * FROM critical_events ORDER BY created_at DESC LIMIT 1').fetchone())
print(json.dumps({'event':row,'intake_and_duplicate_http_seconds':time.perf_counter()-start,'note':'Worker intentionally stopped; event pending, no browser receipt.'},ensure_ascii=False,indent=2))
