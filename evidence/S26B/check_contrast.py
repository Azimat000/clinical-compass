"""WCAG 2.x contrast of the Blank palette, computed from the CSS tokens. Run: python check_contrast.py"""
import json, re
from pathlib import Path
css = (Path(__file__).resolve().parents[2] / 'apps/compass/static/app.css').read_text()
tok = {k: ('#' + ''.join(ch * 2 for ch in v) if len(v) == 3 else '#' + v) for k, v in re.findall(r'--([a-z-]+):#([0-9a-fA-F]{3,6})\b', css.split('*{box-sizing')[0])}
def lum(h):
    h = h.lstrip('#'); c = [int(h[i:i+2], 16) / 255 for i in (0, 2, 4)]
    f = lambda v: v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2])
def cr(a, b):
    x, y = sorted([lum(a), lum(b)], reverse=True); return round((x + 0.05) / (y + 0.05), 2)
pairs = [  # (name, fg, bg, minimum)
 ('основной текст на бумаге', 'ink', 'paper', 4.5), ('основной текст на белом', 'ink', 'white', 4.5),
 ('вторичный текст на бумаге', 'muted', 'paper', 4.5), ('вторичный текст на белом', 'muted', 'white', 4.5),
 ('ссылка на бумаге', 'blue', 'paper', 4.5), ('ссылка на белом', 'blue', 'white', 4.5),
 ('текст кнопки', 'white', 'blue', 4.5), ('текст кнопки при наведении', 'white', 'blue-dark', 4.5),
 ('красный на бумаге', 'red', 'paper', 4.5), ('красный на белом', 'red', 'white', 4.5), ('красный на розовом', 'red', 'red-bg', 4.5),
 ('текст кнопки сигнала', 'white', 'red', 4.5), ('текст кнопки сигнала при наведении', 'white', 'red-dark', 4.5),
 ('предупреждение', 'warn', 'warn-bg', 4.5), ('текст на тёмной панели пропуска', 'white', 'ink', 4.5),
 ('граница поля на белом (не текст, 3:1)', 'field', 'white', 3.0), ('граница поля на бумаге (3:1)', 'field', 'paper', 3.0),
 ('нижняя линия поля (3:1)', 'ink', 'white', 3.0), ('обводка фокуса на бумаге (3:1)', 'focus', 'paper', 3.0), ('обводка фокуса на белом (3:1)', 'focus', 'white', 3.0),
]
rows = []
for name, a, b, need in pairs:
    v = cr(tok[a], tok[b]); rows.append({'pair': name, 'fg': tok[a], 'bg': tok[b], 'ratio': v, 'minimum': need, 'pass': v >= need})
Path(__file__).with_name('contrast.json').write_text(json.dumps({'tokens': tok, 'pairs': rows}, ensure_ascii=False, indent=1) + '\n')
for r in rows: print(f"{r['ratio']:6.2f} / {r['minimum']}  {'OK ' if r['pass'] else 'FAIL'}  {r['pair']}")
raise SystemExit(0 if all(r['pass'] for r in rows) else 1)
