"""Contrast arithmetic for actual CSS tokens; not a full WCAG audit."""
import json
from pathlib import Path
import re
css=Path('apps/compass/static/app.css').read_text()
tokens=dict(re.findall(r'--([\w-]+):\s*(#[\da-fA-F]{3,6})',css))
tokens={k:('#'+''.join(c*2 for c in v[1:]) if len(v)==4 else v) for k,v in tokens.items()}
def luminance(h):
    values=[int(h[i:i+2],16)/255 for i in (1,3,5)]
    return sum(w*(v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4) for v,w in zip(values,[.2126,.7152,.0722]))
def ratio(a,b):
    x,y=sorted([luminance(a),luminance(b)]);return round((y+.05)/(x+.05),2)
pairs=[('ink','surface',4.5),('muted','surface',4.5),('muted','canvas',4.5),('muted','soft',4.5),('accent','surface',4.5),('surface','accent',4.5),('warning','warning-bg',4.5),('danger','danger-bg',4.5),('focus','surface',3),('control','surface',3)]
results=[{'foreground':a,'background':b,'ratio':ratio(tokens[a],tokens[b]),'minimum':minimum} for a,b,minimum in pairs]
assert all(r['ratio']>=r['minimum'] for r in results),results
Path('evidence/S13/contrast.json').write_text(json.dumps({'tokens':tokens,'pairs':results,'scope':'Arithmetic for selected actual CSS tokens, not full-page or WCAG certification'},indent=2)+'\n')
print('PASS: 10 CSS token pairs; control border corrected from 2.95:1')
