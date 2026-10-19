"""Offline installed package/notice snapshot; run inside the built demo image."""
import hashlib
import json
import os
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys
import tarfile

out=Path('/evidence')
packages=subprocess.check_output(['dpkg-query','-W','-f=${binary:Package}\t${Version}\t${Architecture}\n'],text=True).splitlines()
notices=sorted(Path('/usr/share/doc').glob('*/copyright'))
common=sorted(p for p in Path('/usr/share/common-licenses').glob('*') if p.is_file())
python_license=Path(sys.base_prefix)/'lib'/('python'+str(sys.version_info.major)+'.'+str(sys.version_info.minor))/'LICENSE.txt'
extra=common+([python_license] if python_license.exists() else [])
all_files=notices+extra
data={'packages':[dict(zip(['name','version','architecture'],p.split('\t'))) for p in packages],
      'copyright_files':[{'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in notices],
      'additional_license_files':[{'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in extra],
      'python':sys.version,'sqlite':sqlite3.sqlite_version,'platform':platform.platform(),'uid':os.getuid(),
      'limits':'Installed package and packaged notice snapshot; not a full SPDX SBOM, vulnerability scan or legal clearance.'}
(out/'container-inventory.json').write_text(json.dumps(data,indent=2)+'\n')
with tarfile.open(out/'container-copyrights.tar.gz','w:gz',dereference=True) as archive:
    for p in all_files:archive.add(p,arcname=str(p).lstrip('/'),recursive=False)
print(json.dumps({'packages':len(packages),'copyright_files':len(notices),'additional_licenses':len(extra),'uid':data['uid']}))
