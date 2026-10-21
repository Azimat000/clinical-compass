"""Stdlib-only check of the bundled PT fonts: Cyrillic coverage and embedded license data.
Usage: python3 -I check_fonts.py <font.ttf> [...]"""
import json, struct, sys, hashlib
from pathlib import Path

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
report = []
for f in sys.argv[1:]:
    data = Path(f).read_bytes(); cps = cmap(data); nm = names(data)
    cov = {k: sorted(set(v) - cps) for k, v in WANT.items()}
    report.append({'file': Path(f).name, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data),
                   'family': nm.get(1), 'style': nm.get(2), 'copyright': nm.get(0), 'license_in_font': ('SIL OPEN FONT LICENSE Version 1.1' in (nm.get(13) or '')), 'license_first_line': (nm.get(13) or '').split('\r')[0], 'license_url': nm.get(14),
                   'glyphs': len(cps), 'missing': {k: [hex(x) for x in v] for k, v in cov.items() if v}})
print(json.dumps(report, ensure_ascii=False, indent=1))
