"""Check bundled interface fonts against docs/design/fonts.lock.json (stdlib only).

Verifies size, sha256, embedded SIL OFL 1.1 notice and Cyrillic coverage.
Usage: python3 tools/check_fonts.py [--json]
"""
import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'docs/design/fonts.lock.json'
def tables(data):
    n = struct.unpack('>H', data[4:6])[0]
    return {data[12+16*i:16+16*i].decode(): struct.unpack('>II', data[20+16*i:28+16*i]) for i in range(n)}

def cmap(data):
    off, _ = tables(data)['cmap']
    count = struct.unpack('>H', data[off+2:off+4])[0]
    cps = set()
    for i in range(count):
        plat, enc, sub = struct.unpack('>HHI', data[off+4+8*i:off+12+8*i])
        base = off + sub
        fmt = struct.unpack('>H', data[base:base+2])[0]
        if fmt == 4 and (plat, enc) in ((3, 1), (0, 3), (0, 4)):
            segx2 = struct.unpack('>H', data[base+6:base+8])[0]; seg = segx2 // 2
            ends = struct.unpack('>%dH' % seg, data[base+14:base+14+segx2])
            starts = struct.unpack('>%dH' % seg, data[base+16+segx2:base+16+2*segx2])
            for s, e in zip(starts, ends):
                if s != 0xFFFF: cps.update(range(s, e + 1))
    return cps

def names(data):
    off, _ = tables(data)['name']
    count, stro = struct.unpack('>HH', data[off+2:off+6]); out = {}
    for i in range(count):
        plat, enc, lang, nid, ln, so = struct.unpack('>6H', data[off+6+12*i:off+18+12*i])
        raw = data[off+stro+so:off+stro+so+ln]
        text = raw.decode('utf-16-be' if plat in (0, 3) else 'latin-1', 'replace')
        if (plat == 3 and lang == 0x409) or (plat == 1 and nid not in out): out.setdefault(nid, text)
    return out

WANT = {
 'заглавные А-Я': range(0x410, 0x430), 'строчные а-я': range(0x430, 0x450), 'Ё': [0x401], 'ё': [0x451],
 'цифры 0-9': range(0x30, 0x3A), 'латиница A-Za-z': list(range(0x41, 0x5B)) + list(range(0x61, 0x7B)),
 'кавычки «»': [0xAB, 0xBB], 'тире —': [0x2014], 'средняя точка ·': [0xB7], 'номер №': [0x2116],
 'многоточие …': [0x2026], 'минус −': [0x2212], '≥': [0x2265], '×': [0xD7], 'неразрывный пробел': [0xA0],
 'рубль ₽': [0x20BD], '⚠': [0x26A0], '◇': [0x25C7],
}
MUST_HAVE = [k for k in WANT if k not in ('⚠', '◇')]


def check():
    lock = json.loads(LOCK.read_text())
    report, problems = [], []
    for item in lock['files']:
        path = ROOT / item['path']
        data = path.read_bytes() if path.exists() else b''
        entry = {'path': item['path'], 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        if not data:
            problems.append(item['path'] + ': missing')
        elif (entry['bytes'], entry['sha256']) != (item['bytes'], item['sha256']):
            problems.append(item['path'] + ': differs from lock')
        if data and path.suffix == '.ttf':
            cps, nm = cmap(data), names(data)
            entry.update(family=nm.get(1), style=nm.get(2),
                         license_in_font='SIL OPEN FONT LICENSE Version 1.1' in (nm.get(13) or ''),
                         missing={k: [hex(x) for x in sorted(set(v) - cps)] for k, v in WANT.items() if set(v) - cps})
            if not entry['license_in_font']:
                problems.append(item['path'] + ': no OFL notice in font')
            problems += [item['path'] + ': missing ' + k for k in MUST_HAVE if k in entry['missing']]
        if data and path.suffix == '.txt' and b'SIL OPEN FONT LICENSE Version 1.1' not in data:
            problems.append(item['path'] + ': not the OFL 1.1 text')
        report.append(entry)
    return report, problems


if __name__ == '__main__':
    report, problems = check()
    if '--json' in sys.argv:
        print(json.dumps({'files': report, 'problems': problems}, ensure_ascii=False, indent=1))
    print(('FAIL: ' + '; '.join(problems)) if problems else 'PASS: %d файлов совпадают с замком, OFL и кириллица на месте' % len(report))
    sys.exit(1 if problems else 0)
