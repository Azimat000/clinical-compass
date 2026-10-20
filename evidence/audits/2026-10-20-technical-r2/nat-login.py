"""Actual HTTP logins sharing loopback IP; disposable synthetic fixture only."""
from pathlib import Path
import concurrent.futures,json,re,sys,tempfile,time
from contextlib import closing
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'evidence/S15'))
from common import Browser,Server,fixture,machine,summary,connect
OUT=ROOT/'evidence/audits/2026-10-20-technical-r2'
with tempfile.TemporaryDirectory() as tmp:
 path=Path(tmp)/'nat.sqlite3';people=fixture(path,50);server=Server(path,tmp)
 try:
  server.start();start=time.perf_counter()
  def perform(uid):
   browser=Browser(server.url)
   return {'login':uid,'duration_ms':browser.login(uid)}
  with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
   results=list(pool.map(perform,[u for doc,pat,_ in people for u in (doc,pat)]))
  with closing(connect(path)) as db:
   remaining=sum(r[0] for r in db.execute('SELECT attempts FROM login_limits'))
  assert len(results)==100 and remaining==0
  wrong=Browser(server.url)
  def fail():
   code,body,_=wrong.request('/login');assert code==200
   token=re.search(r'name="csrf" value="([^"]+)"',body).group(1)
   return wrong.request('/login',{'csrf':token,'login':'missing-synthetic-user','password':'wrong'})[0]
  codes=[fail() for _ in range(11)];assert codes==[401]*10+[429],codes
  server.stop();server.start();persisted=fail();assert persisted==429
  report={'status':'PASS','scope':'synthetic HTTP test, not human trial','machine':machine(),'same_ip':'127.0.0.1','users':100,'client_threads':20,'server_threads':4,'includes_password_check':True,'successful':len(results),'failure_reservations_after_successes':remaining,'invalid_statuses':codes,'after_restart_status':persisted,'duration_seconds':time.perf_counter()-start,'login_latency':summary([r['duration_ms'] for r in results]),'raw':results}
  (OUT/'nat-login.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:v for k,v in report.items() if k not in ('raw','machine')}))
 finally:server.stop()
