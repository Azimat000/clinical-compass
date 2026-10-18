#!/usr/bin/env python3
"""Read-only checks for scope coverage, dependencies, memory and acceptance refs."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess
from render_coverage import render

ROOT = Path(__file__).resolve().parents[1]
PDF_IDS = {f'{prefix}{i:02}' for prefix, count in [('F', 8), ('M', 10), ('E', 6), ('T', 13)] for i in range(1, count + 1)}
MIN_SUBCHECKS = {'F08': 6, 'M01': 4, 'M02': 3, 'M03': 6, 'M04': 4, 'M05': 5, 'M06': 3, 'M07': 5, 'M08': 9, 'E06': 3, 'T01': 3, 'T02': 7, 'T03': 3, 'T04': 3, 'T05': 3, 'T06': 2, 'T07': 5, 'T10': 5, 'T11': 6, 'C03': 8, 'C36': 5}


def load(root, name):
    return json.loads((root / name).read_text())


def eligible(card, state):
    if card['condition'] == 'qualified':
        return state['qualification'] == 'qualified'
    if card['condition'] == 'postcontest_authorized':
        return state['postcontest_authorized'] is True
    return True


def ready_id(cards, state):
    if state['current_slice']:
        return state['current_slice']
    for card in cards:
        if state['slices'][card['id']]['status'] != 'planned' or not eligible(card, state):
            continue
        if all(state['slices'][dep]['status'] in {'accepted', 'not_applicable'} for dep in card['depends_on']):
            if card['id'] == 'S21' and state['qualification'] == 'qualified' and state['slices']['S20']['status'] != 'accepted':
                continue
            return card['id']
    return None


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], text=True, capture_output=True)


def validate(root=ROOT, pending_tag=None, check_git=True):
    errors = []
    def require(condition, message):
        if not condition:
            errors.append(message)
    try:
        manifest = load(root, 'plan/manifest.json')
        cards = manifest['slices']
        coverage = load(root, 'plan/coverage.json')['items']
        obligations = load(root, 'plan/contest-obligations.json')
        state = load(root, 'memory/STATE.json')
        budget = load(root, 'memory/BUDGET.json')
        sources = load(root, 'research/sources/manifest.json')
        with (root / 'research/requirements.csv').open(newline='') as f:
            original = list(csv.DictReader(f))
    except (OSError, ValueError, KeyError) as e:
        return [f'Не удалось прочитать исходные файлы: {e}'], {}
    ids = [c['id'] for c in cards]
    require(len(ids) == len(set(ids)), 'Повтор ID среза')
    by_id = {c['id']: c for c in cards}
    require(set(state['slices']) == set(ids), 'STATE и manifest содержат разные срезы')
    if set(state['slices']) != set(ids):
        return errors, {}
    require({r['ID'] for r in original} == PDF_IDS and len(original) == 37, 'Из исходного реестра исчез пункт PDF')
    req_ids = [r['id'] for r in coverage]
    require(len(req_ids) == len(set(req_ids)), 'Повтор ID требования')
    require(set(req_ids) == PDF_IDS | {r['id'] for r in obligations}, 'Не все исходные требования/условия назначены срезам')
    originals = {r['ID']: r['Требование'] for r in original}
    originals.update({r['id']: r['text'] for r in obligations})
    sub_ids = []
    for item in coverage:
        rid = item['id']
        require(item['text'] == originals.get(rid), f'{rid}: формулировка отличается от источника-реестра')
        require(item['primary_slice'] in by_id, f'{rid}: нет среза реализации')
        require(bool(item['verification_slices']), f'{rid}: нет среза проверки')
        require(all(s in by_id for s in item['verification_slices']), f'{rid}: неизвестный срез проверки')
        require(len(item['subchecks']) >= MIN_SUBCHECKS.get(rid, 1), f'{rid}: потерян составной подпункт')
        sub_ids.extend(c['id'] for c in item['subchecks'])
        require(all(c['text'].strip() for c in item['subchecks']), f'{rid}: пустая подпроверка')
        require(bool(item['evidence_expected']), f'{rid}: отсутствует требуемое доказательство')
        require(item['fulfilment_status'] in {'not_verified', 'partial', 'fulfilled', 'blocked', 'not_applicable'}, f'{rid}: неизвестный статус выполнения')
        if item['fulfilment_status'] in {'fulfilled', 'not_applicable'}:
            require(bool(item['actual_evidence']), f'{rid}: выполнение/неприменимость без доказательств')
        for evidence in item['actual_evidence']:
            path = root / evidence
            require(path.is_file(), f'{rid}: не существует доказательство {evidence}')
            require(path.resolve().is_relative_to(root.resolve()), f'{rid}: доказательство вне рабочей папки')
    require(len(sub_ids) == len(set(sub_ids)), 'Повтор ID подпроверки')
    view = root / 'plan/COVERAGE.md'
    require(view.is_file() and view.read_text() == render({'items': coverage}), 'Читаемая матрица COVERAGE.md не обновлена из coverage.json')

    visiting, visited = set(), set()
    def visit(sid):
        if sid in visiting:
            errors.append(f'Цикл зависимостей: {sid}')
            return
        if sid in visited or sid not in by_id:
            return
        visiting.add(sid)
        for dep in by_id[sid]['depends_on']:
            require(dep in by_id, f'{sid}: неизвестная зависимость {dep}')
            visit(dep)
        visiting.remove(sid)
        visited.add(sid)
    for card in cards:
        visit(card['id'])
        sid = card['id']
        require((root / f'plan/slices/{sid}.md').is_file(), f'{sid}: нет карточки')
        require(bool(card['tasks']) and bool(card['outputs']) and bool(card['acceptance']), f'{sid}: неполная карточка результата')
        require(card['condition'] in {'always', 'qualified', 'postcontest_authorized'}, f'{sid}: неизвестная ветка')
        assigned = {r['id'] for r in coverage if r['primary_slice'] == sid or sid in r['verification_slices']}
        require(set(card['requirement_ids']) == assigned, f'{sid}: ID карточки расходятся с матрицей')
        entry = state['slices'][sid]
        require(entry['status'] in {'planned', 'in_progress', 'blocked', 'accepted', 'not_applicable'}, f'{sid}: неизвестный статус памяти')
        if entry['status'] in {'blocked', 'not_applicable'}:
            require(bool(entry.get('reason')), f'{sid}: блокер/неприменимость без основания')
        if entry['status'] in {'in_progress', 'accepted'}:
            require(eligible(card, state), f'{sid}: условная ветка не разрешена')
            require(all(state['slices'].get(d, {}).get('status') in {'accepted', 'not_applicable'} for d in card['depends_on']), f'{sid}: не приняты зависимости')
        if sid == 'S21' and entry['status'] in {'in_progress', 'accepted'} and state['qualification'] == 'qualified':
            require(state['slices']['S20']['status'] == 'accepted', 'Финал без подготовки/проверки S20')
        if entry['status'] == 'accepted':
            report = root / entry['handoff']
            require(report.is_file() and 'STATUS: ACCEPTED' in report.read_text(), f'{sid}: нет принятого отчёта')
            require((root / card['evidence_dir'] / 'acceptance.md').is_file(), f'{sid}: нет протокола приёмки')
            ref = entry.get('commit_ref')
            require(bool(ref) and ref.startswith(f'refs/tags/slice/{sid}'), f'{sid}: нет стабильной ссылки приёмки')
            if ref and check_git:
                rev = git(root, 'rev-parse', '--verify', ref + '^{commit}')
                if rev.returncode and pending_tag != sid:
                    errors.append(f'{sid}: тег принятия отсутствует')
                if not rev.returncode:
                    snap = git(root, 'show', f'{ref}:memory/STATE.json')
                    try:
                        recorded = json.loads(snap.stdout)['slices'][sid]
                        require(recorded['status'] == 'accepted' and recorded['commit_ref'] == ref, f'{sid}: тег указывает не на зафиксированную приёмку')
                    except (ValueError, KeyError):
                        errors.append(f'{sid}: нет корректной памяти в принятом коммите')
    current = [sid for sid, entry in state['slices'].items() if entry['status'] == 'in_progress']
    require(len(current) <= 1, 'Одновременно начато больше одного среза')
    require(state['current_slice'] == (current[0] if current else None), 'Указатель current_slice не совпадает со статусами')
    require(state['qualification'] in {'unknown', 'qualified', 'not_qualified'}, 'Неизвестный результат предзащиты')
    require(isinstance(state['postcontest_authorized'], bool), 'Некорректное разрешение postcontest')
    last = state['last_accepted_slice']
    require(last in state['slices'] and state['slices'][last]['status'] == 'accepted', 'Последний принятый срез не принят')
    require(state['next_slice'] == ready_id(cards, state), 'Следующий срез не согласован с зависимостями/состоянием')
    total = sum(t['amount'] for t in budget['transactions'])
    require(total == budget['spent'], 'Расходы не согласованы с журналом')
    require(budget['spent'] >= 0 and budget['commitments'] >= 0, 'Отрицательные расходы/обязательства')
    require(budget['limit'] <= 5000 and budget['spent'] + budget['commitments'] <= budget['limit'], 'Превышен согласованный бюджет')
    for source in sources['files']:
        path = root / source['path']
        require(path.is_file(), f'Исходный документ исчез: {path}')
        if path.is_file():
            require(hashlib.sha256(path.read_bytes()).hexdigest() == source['sha256'], f'Исходный документ изменён без фиксации версии: {path}')
    for name in ['AGENTS.md', 'START_HERE.md', 'memory/DECISIONS.md', 'memory/BLOCKERS.md', 'memory/EXTERNAL.md', 'memory/SESSION_TEMPLATE.md']:
        require((root / name).is_file(), f'Нет памяти/инструкции {name}')
    return errors, {'slices': len(cards), 'pdf_requirements': len(PDF_IDS), 'contest_conditions': len(obligations), 'subchecks': len(sub_ids), 'accepted_slices': sum(e['status'] == 'accepted' for e in state['slices'].values()), 'fulfilled_requirements': sum(r['fulfilment_status'] == 'fulfilled' for r in coverage), 'next_slice': state['next_slice']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pending-tag', help='Разрешить единственный тег текущего принятого среза, ещё не созданный до коммита')
    args = parser.parse_args()
    errors, summary = validate(pending_tag=args.pending_tag)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    for error in errors:
        print('FAIL:', error)
    if not errors:
        print('PASS: покрытие плана, зависимости и память согласованы. Это не проверка медицинской готовности.')
    return bool(errors)


if __name__ == '__main__':
    raise SystemExit(main())
