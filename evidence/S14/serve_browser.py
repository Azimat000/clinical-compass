"""Isolated loopback synthetic UI fault fixture. Never a production route."""
from pathlib import Path
import sqlite3
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'apps/tests'))
from waitress import serve
from test_access import setup_identities
from apps.compass import access
from apps.compass.db import connect,migrate
from apps.compass.repository import seed_demo
from apps.compass.web import create_app
path=ROOT/(sys.argv[1] if len(sys.argv)>1 else 'var/s14-browser.sqlite3')
if path.exists():raise SystemExit('Existing fixture refused')
db=connect(path);migrate(db);seed_demo(db);setup_identities(db)
access.accept_invite(db,'pat-a',access.invite(db,'doc-a','D01'))
db.close()
app=create_app(path)
@app.get('/s14-fixture-service-fault')
def synthetic_fault():
    raise sqlite3.OperationalError('synthetic private path omitted from log')
serve(app,host='127.0.0.1',port=18014,threads=4)
