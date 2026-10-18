#!/usr/bin/env python3
"""Show the next ready slice or begin/block exactly one local session."""
import argparse
from datetime import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo
from validate_plan import ROOT, eligible, git, load, ready_id, validate


def save(state):
    state['updated_on'] = datetime.now(ZoneInfo('Europe/Moscow')).isoformat(timespec='seconds')
    target = ROOT / 'memory/STATE.json'
    temp = target.with_suffix('.tmp')
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n')
    temp.replace(target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['status', 'start', 'block'])
    parser.add_argument('slice', nargs='?')
    parser.add_argument('--reason')
    args = parser.parse_args()
    cards = load(ROOT, 'plan/manifest.json')['slices']
    by_id = {c['id']: c for c in cards}
    state = load(ROOT, 'memory/STATE.json')
    if args.command == 'status':
        print('Текущий:', state['current_slice'] or 'нет')
        print('Последний принятый:', state['last_accepted_slice'])
        print('Следующий готовый:', ready_id(cards, state) or 'нет — проверить блокеры/условия')
        print('Проход в финал:', state['qualification'])
        print('Приложение и условия конкурса не считаются выполненными из-за готового плана.')
        return 0
    errors, _ = validate()
    if errors:
        parser.error('Сначала исправьте память/план: ' + '; '.join(errors))
    sid = args.slice
    if sid not in by_id:
        parser.error('Укажите существующий ID среза')
    entry = state['slices'][sid]
    if args.command == 'start':
        if state['current_slice']:
            parser.error('Уже есть начатый срез; сначала завершите/зафиксируйте его состояние')
        if entry['status'] not in {'planned', 'blocked'} or not eligible(by_id[sid], state):
            parser.error('Срез нельзя начать в текущем состоянии/ветке')
        if not all(state['slices'][d]['status'] in {'accepted', 'not_applicable'} for d in by_id[sid]['depends_on']):
            parser.error('Не приняты зависимости')
        if sid == 'S21' and state['qualification'] == 'qualified' and state['slices']['S20']['status'] != 'accepted':
            parser.error('Для финалиста необходим принятый S20')
        entry.update(status='in_progress', reason=None)
        state.update(current_slice=sid, next_slice=sid)
        report = ROOT / entry['handoff']
        if not report.exists():
            base = git(ROOT, 'rev-parse', 'HEAD').stdout.strip()
            template = (ROOT / 'memory/SESSION_TEMPLATE.md').read_text()
            template = template.replace('SXX', sid).replace('STATUS: IN_PROGRESS | ACCEPTED | BLOCKED', 'STATUS: IN_PROGRESS').replace('BASE_COMMIT: фактический git rev-parse HEAD до работы', f'BASE_COMMIT: {base}')
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(template)
        else:
            text = report.read_text().replace('STATUS: BLOCKED', 'STATUS: IN_PROGRESS')
            report.write_text(text + '\nСрез возобновлён: повторно проверить прежний блокер и записать основание снятия.\n')
        save(state)
        print('Начат', sid, '— выполните только его карточку, затем протокол завершения START_HERE.md.')
    else:
        if state['current_slice'] != sid or entry['status'] != 'in_progress' or not args.reason:
            parser.error('Блокируется только текущий срез с непустым --reason')
        entry.update(status='blocked', reason=args.reason)
        state['current_slice'] = None
        state['next_slice'] = ready_id(cards, state)
        report = ROOT / entry['handoff']
        text = report.read_text().replace('STATUS: IN_PROGRESS', 'STATUS: BLOCKED')
        report.write_text(text + '\n## Зафиксированный блокер\n' + args.reason + '\n')
        save(state)
        print('Блокер записан. Следующий независимый:', state['next_slice'] or 'нет')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
