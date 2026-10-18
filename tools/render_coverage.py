#!/usr/bin/env python3
"""Render the human-readable view; plan/coverage.json stays authoritative."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def render(data):
    def clean(value):
        return str(value).replace('|', '\\|').replace('\n', ' ')
    lines = ['# Покрытие требований срезами', '', 'Создано из plan/coverage.json. Назначенный срез — покрытие планом; выполнение подтверждается отдельно в actual_evidence. Этот файл обновляется командой `python3 tools/render_coverage.py`.', '', '| ID | Условие | Источник | Реализация | Проверка | Статус выполнения |', '|---|---|---|---|---|---|']
    for item in data['items']:
        values = [item['id'], item['text'], item['source'], item['primary_slice'], ', '.join(item['verification_slices']), item['fulfilment_status']]
        lines.append('| ' + ' | '.join(clean(v) for v in values) + ' |')
    lines.extend(['', '## Составные пункты: отдельные подпроверки', ''])
    for item in data['items']:
        if len(item['subchecks']) < 2:
            continue
        lines.extend([f"### {item['id']}", ''])
        lines.extend(f"- {part['id']}: {part['text']}" for part in item['subchecks'])
        lines.append('')
    return '\n'.join(lines).rstrip() + '\n'


if __name__ == '__main__':
    source = json.loads((ROOT / 'plan/coverage.json').read_text())
    (ROOT / 'plan/COVERAGE.md').write_text(render(source))
    print('Обновлён plan/COVERAGE.md')
