# Собственность и сохранность

Единственный автор правок — основной агент. Изменяющих подагентов нет.
Read-only исследователь /root/diagnosis_criteria завершил работу. Делегированного
владения файлами/ledger реализационных агентов не требуется.

Точные пути результата:
- apps/compass/backend_diagnosis_criteria.py
- apps/tests/test_backend_diagnosis_criteria.py
- data/backend/diagnosis-criteria-v1.json
- docs/architecture/backend-diagnoses.md
- evidence/BE10B01/ (только доказательства этого среза)
- evidence/BE10/subdivision.md
- plan/slices/BE10B.md, BE10B01.md, BE10B02.md
- plan/manifest.json, plan/coverage.json, plan/COVERAGE.md
- plan/backend/requirements.json
- memory/sessions/BE10B.md, BE10B01.md
- memory/STATE.json, DECISIONS.md, BLOCKERS.md, EXTERNAL.md, BUDGET.json
- START_HERE.md, AGENTS.md (только актуальный указатель)

Baseline до start и кода: baseline.json. Все исходные tracked/staged diff пусты.
Четыре незакоммиченных чужих файла хешированы и сохранены; не добавлять в коммит.
Рабочая база/учётные данные/ledger не изменяются. Проверяется каждый из80table
хешей, прежние4файла/доступы, отсутствие новых модельных вызовов, неизменность
кода BE10A/очереди/API/реестра и всех83условий/160подпунктов/статусов.
Покупки/публикации/сообщения/перезапуски8000/миграции не выполняются.

Дополнительный точный путь: apps/tests/test_backend_alerts.py. Перед правкой
проверен пустойdiff/записанSHA256 вadditional_scope_baseline. Общая регрессия
обнаружила прежний nondeterministic fixture: соседний сигнал может отнять
первую из пяти попыток. Детерминированное воспроизведение до исправления —
alert-reproduction-before.log. Поправлена только изоляция очереди в этом тесте;
проверки dead/attempts5/прав/отсутствияdeliveries сохранены, код сервиса не меняется.

plan/backend/README.md — дополнительно синхронизирован текущий указатель и таблица дочерних срезов; критерии не менялись.
