# BE11 — техническая приёмка решения врача

27.10.2026, Europe/Moscow. Только сервер, авторская синтетика,
clinical_release=blocked. Основной агент реализовал и непосредственно прочитал
код/SQL/маршрут/тесты, выполнил проверки. Изменяющих подагентов нет.
Исходное состояние: baseline.json; точные пути: scope.md.

| Требование | Конкретное доказательство | Результат |
|---|---|---|
| Работа1: принять/изменить/отклонить, различить происхождение | backend_diagnosis_review.record; test_accept_exact_model_provenance_and_original_remains_unreviewed, test_manual_modify_reject_separate_origins_and_full_version_chain. Собственный диагноз/код только врачу; исходник модели неизменён. | PASS |
| Работа2: автор, основание, снимок, источники, прежние решения и устаревание плана | Квитанция с previous_id/actor_id/relationship_id/basis/uncertainties/snapshot_id/sources/run_id/analysis_revision/model_context. Снимок immutable; decisions.snapshot включает diagnosis_review. Тесты version_chain/data_and_diagnosis/backend_plan_snapshot. | PASS |
| Работа3: текущая связь, повторы/конфликт отдельно от лечения | authorize + BEGIN IMMEDIATE + expected_version + UNIQUE, квитанция и аудит в одной транзакции. Ни одной записи care_actions. | PASS |
| BE11-A01: нет принятия чужим, устаревшей гипотезы, перезаписи | Тесты patient_foreign_doctor_disabled_ended_and_real_case_denied, stale_hypothesis_snapshot_revision_missing_and_wrong_operation, wrong_operation_and_not_ready, age_unknown_or_child, immutable_sql_author_sequence_and_foreign_keys; SQL защищает роль/связь/версию/parent/UPDATE/DELETE. Реальный HTTP: anonymous401, patient/foreign denied, CSRF403, history200. | PASS |
| BE11-A02: одинаковый повтор/две одновременные отправки | test_identical_retry_after_new_data_and_later_decision_is_exact_receipt; test_two_real_connections_same_version_only_one_current_and_retry: два настоящих SQLite соединения и barrier, один200+один409 при разных решениях; одна запись и одинаковая квитанция при одинаковых. Реальный HTTP accept/retry/conflicting_tab/restart. | PASS |
| BE11-A03: диагноз не применяет лечение | test_accept сравнивает все прочие таблицы, кроме служебной сессии/аудита; test_data_and_diagnosis отказывает confirm устаревшего проекта; backend_plan_snapshot помечает прежний backend plan stale. HTTP проверяет care_actions=0. Рабочие лекарства/направления/планы сохранены по80таблицам. | PASS |
| Сбой/восстановление | test_audit_failure_rolls_back_entire_manual_review_and_input; test_source_unavailable_keeps_history_but_cannot_authorize_new_review; restart_preserves_receipt. Реальный HTTP после нового create_app возвращает прежнюю квитанцию. | PASS |
| Миграция и сохранность | verify.py: backup рабочей базы только во временную копию;020 additive,80старых таблиц/старые объекты схемы сохранены, повтор migrate без изменений, integrity/FK PASS. В копии после новой ручной записи31прежнее подтверждённое действие/остальные клинические таблицы неизменны. Рабочая база не мигрировалась. | PASS |

## Матрица B01–B16

| ID | Сохранённый статус | Фактическая граница BE11 |
|---|---|---|
| B01 | partial | Точные4входа и версии сохраняются в снимке; работа BE02/BE10 сохранена. |
| B02 | partial | Правила риска не менялись; общая регрессия. |
| B03 | partial | Решение по диагнозу не закрывает и не подавляет риск. |
| B04 | partial | Канал врача прежний; без внешних сообщений. |
| B05 | partial | Предложения BE10 прежние, неизменённый runtime SHA проверен. |
| B06 | partial | Новые явные решения врача, основания/снимки/история; независимая проверка впереди. |
| B07 | planned | Генерация плана — следующийBE12, здесь не начата. |
| B08 | planned | Предложения лекарств не реализуются этим срезом. |
| B09 | planned | Решение по диагнозу отделено от будущего подтверждения лечения. |
| B10 | partial | Добавлен врачебный GET/POST API, интерфейс не менялся. |
| B11 | partial | Проверены текущие КР; research.md. Срок19:17непродлён, праваfulltextunknown. |
| B12 | partial | Новых вызовов модели0; тестовая модель только для механики, прежняя настоящая оценкаBE10неподменена. |
| B13 | partial | Права/CSRF/связь/история, рабочие данные/доступы сохранены. |
| B14 | partial | Конкуренция/повторы/перезапуск, прежнийledger145/730308microUSD. |
| B15 | planned | Общая приёмка трёх функцийBE18впереди. |
| B16 | planned | Независимый клинический допускBE19впереди. |

M01/M02/M03/T03/T13 получают доказательства BE11 со статусами partial.
Все83исходныхтребования,160подпунктов, тексты и статусы неизменны;
verify.py сравнивает хеши инвариантов. ОстальныеF/M/E/T/Cнеповышены.
Организационные задачи отложены; закрытые каналы/состав/подписи/согласия
заново не проверены. ПрежниеBE18/BE19/B04/B18/B19/E02/E06иостальныеблокеры сохранены.

Проверки и итог полной регрессии см. memory/sessions/BE11.md и логи этого каталога.


## Окончательный результат

Основной агент:make check exit0,854тестаPASS/286.402с,70тестовPASS/18.143с,
restart smoke/pip check/validate_syntheticPASS. После усиления SQL-теста
51целевойPASS/25.411с,targeted-final.log; код приложения после полной регрессии
не менялся. Первый общий FAILсохранён make-check-initial.log: порядок проверки
доступа исправлен до успешного общего прогона. VerificationPASS:9реальныхHTTP,
80рабочихтаблиц/доступы/4чужихфайла/ledgerнеизменны; копия020сохраняет174старых
объекта схемы и31подтверждённое действие после новой ручной записи.
BE11-A01–A03приняты технически; следующийBE12вотдельнойсессии.
