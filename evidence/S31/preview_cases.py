"""Generate disposable, dev-only review-list cases in var/s31-preview; never read/write the live DB.
Run: .venv/bin/python evidence/S31/preview_cases.py
Then: .venv/bin/python -m http.server 18031 --bind 127.0.0.1 --directory var/s31-preview
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'apps/tests')]
from test_ui04 import DoctorCabinetTests
from apps.compass.db import now


def main():
    target = ROOT / 'var/s31-preview'
    target.mkdir(exist_ok=True)
    assets = target / 'static'
    if not assets.exists():
        assets.symlink_to(ROOT / 'apps/compass/static', target_is_directory=True)
    choices = [('normal', 'Обычные'), ('worst', 'Длинные данные'), ('empty', 'Пусто'), ('one', 'Один'), ('many', '100 пациентов')]
    for kind, _ in choices:
        fixture = DoctorCabinetTests()
        fixture.setUp()
        try:
            fixture.db.execute("UPDATE patients SET code='Вера Андреевна Зорина' WHERE id='D01'")
            if kind in ('normal', 'one'):
                fixture.self_report('Обычная запись пациента', 'same')
            if kind in ('worst', 'many'):
                fixture.db.execute("UPDATE patients SET code=? WHERE id='D01'", ('Александра Иосифовна Вишневская-Ковальчук',))
                fixture.add_patient('S31-LONG', 'Константин Александрович Оберхаузер-Веттштейн', 'unknown')
                fixture.add_patient('S31-SHORT', 'Ли', 'unknown')
                fixture.add_patient('S31-ESCAPE', 'Имя <не уточнено>', 'conflicting')
                fixture.self_report('Самочувствие изменилось', 'worse', adverse_events_status='known',
                                    adverse_events_text='Головная боль повторилась после длительной поездки и недосыпания. ' * 14,
                                    complaints_status='conflicting', complaints_text='Врач и пациент сообщили разные сведения')
                fixture.self_report('Следующая отметка', 'worse')
            if kind == 'empty':
                fixture.db.execute('UPDATE care_relationships SET ends_at=?', (now(),))
            if kind == 'many':
                for index in range(96):
                    fixture.add_patient('S31-%03d' % index, 'Пациент проверки %03d' % index)
            response = fixture.clients['doc-a'].get('/')
            assert response.status_code == 200
            switches = '<nav class="fixture-switch" aria-label="Проверочные данные">' + ''.join(
                '<a href="%s.html"%s>%s</a>' % (key, ' aria-current="page"' if key == kind else '', label)
                for key, label in choices) + '</nav>'
            html = response.text.replace('</head>', '<link rel="stylesheet" href="fixture.css"></head>')
            html = html.replace('</body>', switches + '</body>')
            (target / (kind + '.html')).write_text(html)
        finally:
            fixture.tearDown()
    (target / 'fixture.css').write_text('.fixture-switch{position:fixed;bottom:8px;left:8px;right:8px;display:flex;flex-wrap:wrap;gap:4px;padding:8px;background:#fff;border:1px solid #7f8a94;z-index:100;font:14px Arial,sans-serif}.fixture-switch a{padding:4px;color:#15191d}.fixture-switch [aria-current]{font-weight:bold;text-decoration:underline}')
    print('Preview only:', target)


if __name__ == '__main__':
    main()
