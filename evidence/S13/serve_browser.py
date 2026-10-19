"""Local synthetic browser fixture server; capture only environment metadata."""
import json
import sys
from pathlib import Path
from flask import request
from waitress import serve
from apps.compass.web import create_app

app=create_app(sys.argv[1] if len(sys.argv)>1 else 'var/s13-final.sqlite3')
@app.before_request
def capture_environment():
    target=Path('var/s13-user-agents.json')
    entries=json.loads(target.read_text()) if target.exists() else []
    ua=request.headers.get('User-Agent','')
    if ua not in entries:
        entries.append(ua);target.write_text(json.dumps(entries,indent=2))
serve(app,host='127.0.0.1',port=18013,threads=4)
