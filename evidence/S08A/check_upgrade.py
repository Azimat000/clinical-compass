"""Build an S07 database in a temporary folder, upgrade, compare every old table."""
from pathlib import Path
import json
import secrets
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'apps/tests')]
from test_access import setup_identities
from apps.compass.db import connect,migrate,MIGRATIONS
from apps.compass.repository import seed_demo
from apps.compass import access,records,assessments
with tempfile.TemporaryDirectory() as folder:
    directory=Path(folder)/'migrations';directory.mkdir()
    for p in MIGRATIONS.glob('*.sql'):
        if p.name<'005':(directory/p.name).write_bytes(p.read_bytes())
    db=connect(Path(folder)/'upgrade.sqlite3');migrate(db,directory);seed_demo(db);setup_identities(db)
    access.accept_invite(db,'pat-a',access.invite(db,'doc-a','D01'))
    assessments.install_form(db)
    records.save(db,{'id':'pat-a','role':'patient'},'D01','self_report',
                 {'observed_on':'2026-10-18','request_key':secrets.token_hex(16),'adverse_events_status':'known','adverse_events_text':'Синтетическое НЯ'})
    form=assessments.definition()
    rid=assessments.assign(db,{'id':'doc-a','role':'doctor'},'D01',
        {'assignment_key':secrets.token_hex(16),'form_version_id':form['id'],'age_status':'known','age_years':'35','age_basis':'Синтетический профиль D01'})
    assessments.submit(db,{'id':'pat-a','role':'patient'},rid,{'form_version_id':form['id'],**{f'answer_{i}':'1' for i in range(1,43)}})
    tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name!='schema_migrations'")]
    before={t:sorted([list(r) for r in db.execute('SELECT * FROM '+t)],key=str) for t in tables}
    migrate(db)
    for table,rows in before.items():assert rows==sorted([list(r) for r in db.execute('SELECT * FROM '+table)],key=str),table
    assert not db.execute('PRAGMA foreign_key_check').fetchall()
    assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    print(json.dumps({'old_tables_preserved':len(tables),'old_nonempty_tables':{t:len(rows) for t,rows in before.items() if rows},'schema':db.execute('SELECT max(version) FROM schema_migrations').fetchone()[0],'integrity':'ok'},ensure_ascii=False,indent=2))
