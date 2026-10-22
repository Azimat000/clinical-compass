# Установка навыков дизайна и план UI01–UI08

STATUS: COMPLETE
DATE: 22.10.2026 Europe/Moscow
BASE_COMMIT: b0ab24b50d2f1f1cd1f0aad363fafd41ca053a49
ACCEPTANCE_REF: refs/tags/setup/design-skills-2026-10-22

Прямое поручение: скачать и настроить impeccable, design-taste-frontend, emil-design-eng, review-animations, break-ui, web-design-guidelines; разделить построение нового интерфейса на срезы (одна сессия — один срез), настроить память и коммиты; первый срез — варианты дизайна на выбор пользователя.

Исследование источников — read-only web-researcher; репозитории склонированы во временную папку, прочитаны (SKILL.md, скрипты, хуки, лицензии) и скопированы без изменений, кроме записанных в docs/design/skills.lock.json. Для impeccable взяты официальные сборки под Claude Code (.claude) и Codex (.agents). Навык Vercel получил закреплённую копию правил и заметку о ней в конце SKILL.md, потому что проектные правила направляют сеть через web-researcher. Хуки impeccable включены только для Claude Code; в Codex не ставились.

Проверки: `python3 tools/design_skills.py check` PASS; `python3 tools/validate_plan.py` PASS (next_slice=UI01); plan-тесты; `git diff --check`; smoke impeccable/taste — evidence/design-skills-setup-2026-10-22. make check и браузер не запускались: приложение не менялось. Прежние незакоммиченные evidence/audits/2026-10-20-cycles/ и tools/run_synthetic_cycles.py не тронуты и в коммит не входят.

Внешнее: движок impeccable (бинарный файл) скачан в ~/.impeccable/bin/0.1.16 с GitHub Releases pbakaus/impeccable, лаунчер проверил sha256. Расходы 0 ₽. Публикаций, покупок, сообщений нет.

Следующий старт: «Начни срез UI01» → START_HERE.md → docs/design/README.md → plan/slices/UI01.md.
