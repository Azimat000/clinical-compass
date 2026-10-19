# Матрица приёмки S14

Принимается ограниченный локальный синтетический инженерный срез по неизменённой карточке plan/slices/S14.md. Это не допуск клинического/внешнего сервиса и не выполнение всех конкурсных обязательств. Исходная папка была чистой, a3778b4; никаких делегированных изменений файлов. Источники — read-only s14_external; основной агент непосредственно прочитал код/diff и выполнял проверки.

## Все работы и результаты карточки

| Пункт | Конкретное доказательство | Итог |
|---|---|---|
| Работа1: полный набор, чужие сущности, клинические действия | final-checks-r3.log, docker-tests-final.log:148 app; test_security:19 POST,20 patient-URL,2 роли,5 видов действий; прежние child-ID/access/replay tests | PASS в данном контрольном наборе |
| Работа2: пустое/неверное/противоречивое/устаревшее/повторное | test_records/assessments/ages/decisions/therapy/routing/clinical_workflow/communication/extraction/security; reliability.md; новая ошибка посреди записи→откат→один успешный повтор | PASS, известные пределы B12/B15 сохранены |
| Работа3: сессии/секреты/журналы/копии/передачи/права/синтетика | security.md; inventory.json; container-inventory.json и container-copyrights.tar.gz; offline Linux; data-map/third-party; external-check.md | PASS как проверка и честный реестр, внешний допуск не присвоен |
| Результат: security.md | Карта угроз/барьеров/остатка, точные тесты и обнаруженные дефекты | Передан |
| Результат: reliability.md | Негативные входы/сбои/повторы/пределы; исходные отказы не скрыты | Передан |
| Результат: обновлённая карта данных | docs/compliance/data-map.md, реальный поток сессий/индексов/переписки/исходников/логов/копий | Передана |

## Все условия приёмки

| Неизменённое условие | Проверяемое основание | Решение |
|---|---|---|
| Нет неразрешённых изменений плана и утечек в контрольном наборе | Две роли×все patient-URL →403/404; до/после строки клинических таблиц идентичны;5 видов действий чужого/пациента отклонены; старые snapshots409. Синтетический sentinel не появляется в финальном логе/ответе. Все148 тестов в обеих средах PASS | PASS ограниченного набора; не все возможные атаки |
| Ошибка ввода/сервиса не приводит к ложному безопасному выводу; сбои перечислены | 400/403/409/413 и500/503 с неизвестным результатом, no-store, safe fallback при сбое шаблона. Отчёт/событие при ошибке транзакции откатываются. B12/B15 и промежуточные отказы перечислены в reliability.md. browser-check/PNG подтверждают видимый экран | PASS; без утверждения клинической достаточности |
| Юридическая квалификация и незакрытые вопросы честны; РФ-сервер не доказательство закона | data-map.md, external-check.md, third-party.md;152-ФЗ/323-ФЗ/квалификация ПО разобраны по фактическому режиму. Нет реальных медицинских данных/допуска/юридической сертификации, B06/B08/B11/B16 остаются | PASS честного описания, M09 остаётся partial |

## Команды основного агента

- `make check` →exit0:148 тестов приложения +17 плана/данных; настоящий HTTP smoke и перезапуск, pip check, SHA синтетики. Действующий лог final-checks-r3.log; предыдущие baseline-checks/final-checks/r2 сохранены как история.
- `docker build -f apps/Dockerfile -t hac-s14:final .` →exit0; `docker run --rm --network none hac-s14:final python -m unittest discover -s apps/tests -v` →exit0,148PASS (docker-build-final.log/docker-tests-final.log). Linux ARM64/Python3.13.11/SQLite3.46.1, uid10001; сеть продукта не требуется.
- Docker с mount verify_restarts.py в /app/evidence/S14 и --network none →exit0; linux-repeats-final.json:5 новых сценариев, каждый2 старта сервера,0 отказов. Предыдущий linux-repeats.json также5/0; эти выборки не снимают B12.
- `.venv/bin/python evidence/S13/verify_upgrade.py` →exit0, upgrade.log:59 прежних таблиц/26 непустых, строки/действие/импорты/snapshot сохранены, integrity/FK PASS. Исторические файлы S13 не переписывались.
- `.venv/bin/python evidence/S14/inventory.py` →exit0, inventory.json/log:19 POST,20 patient-URL; узкий поиск известных шаблонов ключей без совпадений; пределы сканера указаны.
- Docker --network none + collect_container.py →exit0:87 системных пакетов/87copyright+18 дополнительных лицензий, архив с разрешёнными ссылками разыменован. Это inventory/notice snapshot, не полный SPDX/CVE/юридический аудит.
- `.venv/bin/python evidence/S14/verify_preservation.py`, `python3 tools/render_coverage.py`, `python3 tools/validate_plan.py --pending-tag S14`, `git diff --check`, затем commit/tag и validate_plan без исключений — по протоколу; выводы до тега сохранены в preservation/plan-validation; после тега — в var/s14-post-tag.log вне Git и ответе сессии.

## Чего это не закрывает

B12 (причина прежних Linux404/409), B15 (известная низкая полнота извлечения), реальные люди/клиническая проверка/правовой допуск, закрытый чат/почта/команда, внешний запуск и усиление scrypt (B16), реальные backup/restore/нагрузка S15. Ни один ID не стал fulfilled/not_applicable. T03 только not_verified→partial: измерена текущая выборка и сохранён перечень сбоев. Карточка/все исходные требования/160 подпунктов сохраняются; автоматическая проверка preservation.json.

## Каждый закреплённый подпункт

| ID всех подпунктов | Конкретная проверка/артефакт | Остаток (статус partial) |
|---|---|---|
| F03.1 | test_records, test_ages, test_clinical_rules, test_extraction | Ограниченные исходниковые правила; B04/B15 и клиническая проверка не сняты |
| F06.1 | test_communication, test_critical_delivery, test_notifications | Локальные каналы; нет24/7/внешнего push |
| M01.1, M01.2, M01.3, M01.4 | test_access, test_security every_mutation/all_patient_routes | Отрицательный набор, не полный пентест |
| M02.1, M02.2, M02.3 | test_records, test_notifications, smoke_restart, linux-repeats-final.json | Доставка в текущую пару, без посредника; B12 остаётся |
| M03.1, M03.2, M03.3, M03.4, M03.5, M03.6 | test_decisions, test_security all_five_actions, test_therapy/routing/clinical_workflow | Все5 действий и отдельный врачебный шаг, клинический допуск отдельно |
| M05.1, M05.2, M05.3, M05.4, M05.5 | test_clinical_rules/workflow, test_critical_delivery/notifications | Неизвестное не отрицание; отказ не квитанция; полная клиническая оценка S16 |
| M09.1 | data-map.md, external-check.md | Соответствие законам полностью не подтверждено; правовые вопросы открыты |
| M10.1 | test_access/security/extraction/communication, inventory.json | Не заявлены полный PII-аудит/приватность ОС |
| T03.1, T03.2, T03.3 | reliability.md; baseline/security-before/final-checks-r3; linux-repeats-final.json | Измерены результаты/ошибки этой выборки; B12/B15 не скрыты |
| T13.1 | security.md, test_security/access, container-inventory.json | Защита копий описана; реальный restore S15; B16 |
| C23.1 | third-party.md, container-inventory.json, copyrights, .agents lock/S04 licenses | B06/B08: авторство и согласование не доказаны |
| C24.1 | data-map.md, external-check.md | Не было внешней передачи/публикации; закрытые условия недоступны |
| C25.1 | data-map.md, security.md | Обязательство сохраняется; локальные проверки не исчерпывают5-летний срок |
| C31.1 | third-party.md, inventory.json, external-check.md | Правовые гарантии команды не удостоверены; B06/B08 |
| C41.1 | external-check.md, third-party.md, data-map.md | Ответов организатора про ИИ/API/старый код нет; B06/B11 |

Всего15 ID /31 подпунктов. Группировка не заменяет и не удаляет их исходные формулировки в coverage.json.
