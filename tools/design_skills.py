#!/usr/bin/env python3
"""Check installed design skills against docs/design/skills.lock.json, or rewrite the file hashes."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'docs/design/skills.lock.json'
IGNORED = {'.DS_Store', 'hook.cache.json', 'hook.pending.json', 'config.json'}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def files(folder):
    return {p.relative_to(folder).as_posix(): digest(p) for p in sorted(folder.rglob('*'))
            if p.is_file() and p.name not in IGNORED and 'bin' not in p.relative_to(folder).parts}


def check(lock):
    errors = []
    for skill in lock['skills']:
        for install in skill['installs']:
            folder = ROOT / install['path']
            if not (folder / 'SKILL.md').is_file():
                errors.append(f"{install['path']}: нет SKILL.md")
                continue
            actual, expected = files(folder), install['files']
            for name in sorted(expected.keys() - actual.keys()):
                errors.append(f"{install['path']}/{name}: файл пропал")
            for name in sorted(actual.keys() - expected.keys()):
                errors.append(f"{install['path']}/{name}: лишний файл")
            for name in sorted(expected.keys() & actual.keys()):
                if expected[name] != actual[name]:
                    errors.append(f"{install['path']}/{name}: содержимое изменено")
        for extra in skill.get('extra_files', []):
            path = ROOT / extra['path']
            if not path.is_file() or digest(path) != extra['sha256']:
                errors.append(f"{extra['path']}: нет файла или содержимое изменено")
    return errors


def relock(lock):
    for skill in lock['skills']:
        for install in skill['installs']:
            install['files'] = files(ROOT / install['path'])
        for extra in skill.get('extra_files', []):
            extra['sha256'] = digest(ROOT / extra['path'])
    LOCK.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['check', 'relock'])
    args = parser.parse_args()
    lock = json.loads(LOCK.read_text())
    if args.command == 'relock':
        relock(lock)
        print('Записаны хеши', sum(len(i['files']) for s in lock['skills'] for i in s['installs']), 'файлов')
        return 0
    errors = check(lock)
    for error in errors:
        print('FAIL:', error)
    if not errors:
        print('PASS:', len(lock['skills']), 'навыков совпадают с замком. Это не проверка качества интерфейса.')
    return bool(errors)


if __name__ == '__main__':
    raise SystemExit(main())
