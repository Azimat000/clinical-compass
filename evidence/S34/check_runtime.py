"""Read-only comparison of service data against the private pre-update backup."""
import hashlib
import json
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[2]
BACKUP = ROOT/'var/backups/S34-before-questionnaires.sqlite3'

def encoded(rows):
    return json.dumps(sorted([list(r) for r in rows], key=lambda r: repr(r)), ensure_ascii=False,
                      sort_keys=True, default=lambda b: {'blob_hex': b.hex()}).encode()

old = sqlite3.connect('file:'+str(BACKUP)+'?mode=ro', uri=True)
new = sqlite3.connect('file:'+str(ROOT/'var/compass.sqlite3')+'?mode=ro', uri=True)
tables = [r[0] for r in old.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'")]
manifest = {'backup': 'var/backups/S34-before-questionnaires.sqlite3', 'mode':oct(BACKUP.stat().st_mode&0o777),
            'integrity': old.execute('pragma integrity_check').fetchone()[0], 'foreign_keys':list(old.execute('pragma foreign_key_check')), 'tables':{}}
checks = []
for table in tables:
    before=list(old.execute('select * from "'+table+'"'))
    after=list(new.execute('select * from "'+table+'"'))
    manifest['tables'][table]={'rows':len(before),'sha256':hashlib.sha256(encoded(before)).hexdigest()}
    if table in ('source_versions','catalog_versions','assessment_form_releases'):
        preserved=set(before)<=set(after)
        added=[r for r in after if r not in before]
        expected = {('GAD7-RU-Z-2023-demo-v1' + ('-source' if table=='source_versions' else '')),
                    ('PHQ9-RU-Z-2023-demo-v1' + ('-source' if table=='source_versions' else ''))}
        valid=preserved and {r[0] for r in added} == expected and len(added)==2
    else:
        preserved=encoded(before)==encoded(after);valid=preserved;added=[]
    checks.append({'table':table,'old_rows':len(before),'new_rows':len(after),'prior_rows_unchanged':preserved,'expected_change_only':valid})
report={'checks':checks,'all_prior_rows_preserved':all(c['prior_rows_unchanged'] for c in checks),
        'only_two_new_form_releases':all(c['expected_change_only'] for c in checks),
        'integrity':new.execute('pragma integrity_check').fetchone()[0], 'foreign_keys':list(new.execute('pragma foreign_key_check'))}
(ROOT/'evidence/S34/backup.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
(ROOT/'evidence/S34/runtime.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k!='checks'},ensure_ascii=False))
if not report['all_prior_rows_preserved'] or not report['only_two_new_form_releases'] or report['integrity']!='ok' or report['foreign_keys']:
    raise SystemExit(1)
