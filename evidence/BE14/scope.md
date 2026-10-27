# BE14 scope

Единственный автор файлов — основной агент. Исследователь /root/be14_sources
только чтение. Изменяющих агентов нет. Отдельный утверждённый план — карточка
plan/slices/BE14.md; критерии не сокращаются и не переносятся молча.

Writable: apps/compass/backend_therapy.py, apps/tests/test_backend_therapy.py,
docs/architecture/backend-therapy.md, evidence/BE14/, memory/sessions/BE14.md,
memory/STATE.json, memory/DECISIONS.md, memory/BLOCKERS.md, memory/EXTERNAL.md,
memory/BUDGET.json, plan/backend/requirements.json, plan/slices/BE14.md,
START_HERE.md, AGENTS.md, plan/backend/README.md, plan/coverage.json,
plan/COVERAGE.md (только если нужен render_coverage).

Все остальные пути read-only. Миграций/новых пакетов/изменений текущих модулей
и рабочего сервиса не планируется. var/compass.sqlite3, доступы, ledger,
четыре чужих файла baseline запрещены к изменению. Реальные медицинские
действия/публикации/организационная ветка/UI08 вне объёма.

Текущий фактический шаг: read-only проверка структурированных кандидатов из
доверенного серверного снимка. Это WIP BE14, не полная третья функция.
Полный BE14-A01 требует положительный содержательный реальный результат.
Ни отказы, ни механические тесты, ни новая справка его не принимают.
