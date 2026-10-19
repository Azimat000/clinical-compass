# Матрица S17 — 19.10.2026, Москва

**NO-GO: готовность к сдаче/предзащите не подтверждена. S17 BLOCKED, без тега приёмки.**

Рассмотрены все 83 требования и 160 подпунктов, в том числе не закреплённые за S17 соседние обязанности. Формулировки и статусы не изменены. Ссылки ниже — свидетельства ограниченных проверок/реестров, а не автоматический PASS требования. Отдельный протокол проверки каждого T01–T13 дан в соответствующей строке. Новые технические проверки — checks.log; повторные измерения S15/платформы S13 здесь не выдаются за новые.

Машиночитаемая полная связь с прежними доказательствами: audit.json. Отсутствующие фактические события, клиническая проверка, права и закрытые сведения остаются пробелами. Исследование публичных источников: external-check.md.

## F01 — Предлагать стандартизированные методы оценки состояния пациента

**Состояние:** partial. DASS-42, точный бланк/ключ, только врачу; test_assessments.

**Остаток:** Нет клинической проверки реализации; PHQ/GAD не включены.

**Сохранённые доказательства:** [docs/architecture/data-model.md](../../docs/architecture/data-model.md); [evidence/S04/acceptance.md](../../evidence/S04/acceptance.md); [evidence/S07/research.md](../../evidence/S07/research.md); [evidence/S07/acceptance.md](../../evidence/S07/acceptance.md); [evidence/S07/review/scale-research.md](../../evidence/S07/review/scale-research.md); [evidence/S07/review/final-checks.log](../../evidence/S07/review/final-checks.log); [apps/tests/test_assessments.py](../../apps/tests/test_assessments.py); [docs/architecture/assessments.md](../../docs/architecture/assessments.md); [evidence/audits/2026-10-19-s08a/report.json](../../evidence/audits/2026-10-19-s08a/report.json); [evidence/S08B/acceptance.md](../../evidence/S08B/acceptance.md); [evidence/S08B/final-checks.log](../../evidence/S08B/final-checks.log); [evidence/S08B/upgrade.json](../../evidence/S08B/upgrade.json); [apps/tests/test_ages.py](../../apps/tests/test_ages.py); [docs/architecture/age-reviews.md](../../docs/architecture/age-reviews.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| F01.1 Предлагать стандартизированные методы оценки состояния пациента | DASS-42, точный бланк/ключ, только врачу; test_assessments. Нет клинической проверки реализации; PHQ/GAD не включены. |

## F02 — Предоставлять рекомендации или справочную информацию по возможным вариантам терапии

**Состояние:** partial. Справка терапии и восьмиобластная врачебная сверка; test_therapy.

**Остаток:** Свободный текст врача не проверен на соответствие инструкции; автоматического назначения нет.

**Сохранённые доказательства:** [docs/architecture/data-model.md](../../docs/architecture/data-model.md); [evidence/S04/acceptance.md](../../evidence/S04/acceptance.md); [evidence/S08A/acceptance.md](../../evidence/S08A/acceptance.md); [evidence/S08A/external-check.md](../../evidence/S08A/external-check.md); [evidence/S08A/final-checks.log](../../evidence/S08A/final-checks.log); [evidence/S08A/upgrade.json](../../evidence/S08A/upgrade.json); [apps/tests/test_decisions.py](../../apps/tests/test_decisions.py); [docs/architecture/clinical-decisions.md](../../docs/architecture/clinical-decisions.md); [evidence/audits/2026-10-19-s08a/report.json](../../evidence/audits/2026-10-19-s08a/report.json); [evidence/S08/acceptance.md](../../evidence/S08/acceptance.md); [evidence/S08/external-check.md](../../evidence/S08/external-check.md); [evidence/S08/final-checks.log](../../evidence/S08/final-checks.log); [evidence/S08/upgrade.json](../../evidence/S08/upgrade.json); [apps/compass/resources/therapy-reference-v2.json](../../apps/compass/resources/therapy-reference-v2.json); [apps/tests/test_therapy.py](../../apps/tests/test_therapy.py); [docs/architecture/therapy-review.md](../../docs/architecture/therapy-review.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| F02.1 Предоставлять рекомендации или справочную информацию по возможным вариантам терапии | Справка терапии и восьмиобластная врачебная сверка; test_therapy. Свободный текст врача не проверен на соответствие инструкции; автоматического назначения нет. |

## F03 — Учитывать и оценивать индивидуальные риски и нежелательные явления

**Состояние:** partial. НЯ/unknown/conflict и ограниченное A02-v2; test_clinical_rules.

**Остаток:** Не полная оценка индивидуального риска; B04/B15.

**Сохранённые доказательства:** [docs/architecture/data-model.md](../../docs/architecture/data-model.md); [evidence/S04/acceptance.md](../../evidence/S04/acceptance.md); [evidence/S08A/acceptance.md](../../evidence/S08A/acceptance.md); [evidence/S08A/external-check.md](../../evidence/S08A/external-check.md); [evidence/S08A/final-checks.log](../../evidence/S08A/final-checks.log); [evidence/S08A/upgrade.json](../../evidence/S08A/upgrade.json); [apps/tests/test_decisions.py](../../apps/tests/test_decisions.py); [docs/architecture/clinical-decisions.md](../../docs/architecture/clinical-decisions.md); [evidence/audits/2026-10-19-s08a/report.json](../../evidence/audits/2026-10-19-s08a/report.json); [evidence/S08/acceptance.md](../../evidence/S08/acceptance.md); [evidence/S08/external-check.md](../../evidence/S08/external-check.md); [evidence/S08/final-checks.log](../../evidence/S08/final-checks.log); [evidence/S08/upgrade.json](../../evidence/S08/upgrade.json); [apps/compass/resources/therapy-reference-v2.json](../../apps/compass/resources/therapy-reference-v2.json); [apps/tests/test_therapy.py](../../apps/tests/test_therapy.py); [docs/architecture/therapy-review.md](../../docs/architecture/therapy-review.md); [evidence/S14/acceptance.md](../../evidence/S14/acceptance.md); [evidence/S14/security.md](../../evidence/S14/security.md); [evidence/S14/reliability.md](../../evidence/S14/reliability.md); [evidence/S14/final-checks-r3.log](../../evidence/S14/final-checks-r3.log); [evidence/S14/docker-tests-final.log](../../evidence/S14/docker-tests-final.log); [apps/tests/test_security.py](../../apps/tests/test_security.py); [docs/compliance/data-map.md](../../docs/compliance/data-map.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| F03.1 Учитывать и оценивать индивидуальные риски и нежелательные явления | НЯ/unknown/conflict и ограниченное A02-v2; test_clinical_rules. Не полная оценка индивидуального риска; B04/B15. |

## F04 — Мониторинг динамики состояния пациента

**Состояние:** partial. История визитов, сопоставимая DASS врачу, дневник пациенту.

**Остаток:** Человеческая/клиническая применимость не измерена.

**Сохранённые доказательства:** [docs/architecture/data-model.md](../../docs/architecture/data-model.md); [evidence/S04/acceptance.md](../../evidence/S04/acceptance.md); [docs/architecture/records.md](../../docs/architecture/records.md); [apps/tests/test_records.py](../../apps/tests/test_records.py); [evidence/S06/acceptance.md](../../evidence/S06/acceptance.md); [evidence/S06/final-checks.log](../../evidence/S06/final-checks.log); [evidence/S06/docker-restart.log](../../evidence/S06/docker-restart.log); [evidence/S06/doctor-history.png](../../evidence/S06/doctor-history.png); [evidence/S07/research.md](../../evidence/S07/research.md); [evidence/S07/acceptance.md](../../evidence/S07/acceptance.md); [evidence/S07/review/scale-research.md](../../evidence/S07/review/scale-research.md); [evidence/S07/review/final-checks.log](../../evidence/S07/review/final-checks.log); [apps/tests/test_assessments.py](../../apps/tests/test_assessments.py); [docs/architecture/assessments.md](../../docs/architecture/assessments.md); [evidence/S13/acceptance.md](../../evidence/S13/acceptance.md); [evidence/S13/platforms.md](../../evidence/S13/platforms.md); [evidence/S13/browser-check.json](../../evidence/S13/browser-check.json); [docs/architecture/interface-search-extensions.md](../../docs/architecture/interface-search-extensions.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| F04.1 Мониторинг динамики состояния пациента | История визитов, сопоставимая DASS врачу, дневник пациенту. Человеческая/клиническая применимость не измерена. |

## F05 — Интерфейс пациента для самоотчета и самостоятельного отслеживания динамики

**Состояние:** partial. Самоотчёт/история пациента и доставка ведущему врачу.

**Остаток:** Демо синтетическое; результаты DASS пациенту не выдаются.

**Сохранённые доказательства:** [docs/architecture/data-model.md](../../docs/architecture/data-model.md); [evidence/S04/acceptance.md](../../evidence/S04/acceptance.md); [docs/architecture/records.md](../../docs/architecture/records.md); [apps/tests/test_records.py](../../apps/tests/test_records.py); [evidence/S06/acceptance.md](../../evidence/S06/acceptance.md); [evidence/S06/final-checks.log](../../evidence/S06/final-checks.log); [evidence/S06/docker-restart.log](../../evidence/S06/docker-restart.log); [evidence/S06/doctor-history.png](../../evidence/S06/doctor-history.png); [evidence/S07/research.md](../../evidence/S07/research.md); [evidence/S07/acceptance.md](../../evidence/S07/acceptance.md); [evidence/S07/review/scale-research.md](../../evidence/S07/review/scale-research.md); [evidence/S07/review/final-checks.log](../../evidence/S07/review/final-checks.log); [apps/tests/test_assessments.py](../../apps/tests/test_assessments.py); [docs/architecture/assessments.md](../../docs/architecture/assessments.md); [evidence/S13/acceptance.md](../../evidence/S13/acceptance.md); [evidence/S13/platforms.md](../../evidence/S13/platforms.md); [evidence/S13/browser-check.json](../../evidence/S13/browser-check.json); [docs/architecture/interface-search-extensions.md](../../docs/architecture/interface-search-extensions.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| F05.1 Интерфейс пациента для самоотчета и самостоятельного отслеживания динамики | Самоотчёт/история пациента и доставка ведущему врачу. Демо синтетическое; результаты DASS пациенту не выдаются. |

## F06 — Каналы коммуникации для сопровождения лечебного процесса

**Состояние:** partial. Двусторонние сообщения, повторы/квитанции; test_communication.

**Остаток:** Нет внешнего канала и круглосуточного присутствия врача.

**Сохранённые доказательства:** [docs/architecture/data-model.md](../../docs/architecture/data-model.md); [evidence/S04/acceptance.md](../../evidence/S04/acceptance.md); [evidence/audits/2026-10-19-s08a/report.json](../../evidence/audits/2026-10-19-s08a/report.json); [docs/architecture/communication.md](../../docs/architecture/communication.md); [apps/tests/test_communication.py](../../apps/tests/test_communication.py); [evidence/S11/acceptance.md](../../evidence/S11/acceptance.md); [evidence/S11/final-checks.log](../../evidence/S11/final-checks.log); [evidence/S11/runtime.json](../../evidence/S11/runtime.json); [evidence/S11/upgrade.json](../../evidence/S11/upgrade.json); [evidence/S11/browser-check.json](../../evidence/S11/browser-check.json); [evidence/S14/acceptance.md](../../evidence/S14/acceptance.md); [evidence/S14/security.md](../../evidence/S14/security.md); [evidence/S14/reliability.md](../../evidence/S14/reliability.md); [evidence/S14/final-checks-r3.log](../../evidence/S14/final-checks-r3.log); [evidence/S14/docker-tests-final.log](../../evidence/S14/docker-tests-final.log); [apps/tests/test_security.py](../../apps/tests/test_security.py); [docs/compliance/data-map.md](../../docs/compliance/data-map.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| F06.1 Каналы коммуникации для сопровождения лечебного процесса | Двусторонние сообщения, повторы/квитанции; test_communication. Нет внешнего канала и круглосуточного присутствия врача. |

## F07 — Оценивать приверженность лечению и рекомендациям врача

**Состояние:** partial. Учёт выполненных/пропущенных пунктов подтверждённого плана.

**Остаток:** Это описательный учёт; полнота расписания/эффект лечения не доказаны.

**Сохранённые доказательства:** [docs/architecture/data-model.md](../../docs/architecture/data-model.md); [evidence/S04/acceptance.md](../../evidence/S04/acceptance.md); [evidence/audits/2026-10-19-s08a/report.json](../../evidence/audits/2026-10-19-s08a/report.json); [docs/architecture/communication.md](../../docs/architecture/communication.md); [apps/tests/test_communication.py](../../apps/tests/test_communication.py); [evidence/S11/acceptance.md](../../evidence/S11/acceptance.md); [evidence/S11/final-checks.log](../../evidence/S11/final-checks.log); [evidence/S11/runtime.json](../../evidence/S11/runtime.json); [evidence/S11/upgrade.json](../../evidence/S11/upgrade.json); [evidence/S11/browser-check.json](../../evidence/S11/browser-check.json).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| F07.1 Оценивать приверженность лечению и рекомендациям врача | Учёт выполненных/пропущенных пунктов подтверждённого плана. Это описательный учёт; полнота расписания/эффект лечения не доказаны. |

## F08 — Выявлять ситуации направления к психиатру для врачей других специальностей; рекомендовать дальнейшую маршрутизацию по данным с категориями обязательно и желательно в зависимости от тяжести

**Состояние:** partial. Источник КР457 §5, две категории, общий врач, отдельный confirm.

**Остаток:** Ограниченные существующие факты ГТР; тяжесть/срочность проверяет врач; B04.

**Сохранённые доказательства:** [docs/architecture/data-model.md](../../docs/architecture/data-model.md); [evidence/S04/acceptance.md](../../evidence/S04/acceptance.md); [evidence/audits/2026-10-19-s08a/report.json](../../evidence/audits/2026-10-19-s08a/report.json); [evidence/S09/acceptance.md](../../evidence/S09/acceptance.md); [evidence/S09/external-check.md](../../evidence/S09/external-check.md); [evidence/S09/final-checks.log](../../evidence/S09/final-checks.log); [evidence/S09/upgrade.json](../../evidence/S09/upgrade.json); [apps/tests/test_routing.py](../../apps/tests/test_routing.py); [docs/architecture/routing.md](../../docs/architecture/routing.md); [evidence/S09/completion-review/research.md](../../evidence/S09/completion-review/research.md); [evidence/S09/completion-review/boundary-review.md](../../evidence/S09/completion-review/boundary-review.md); [evidence/S09/completion-review/source-archive.json](../../evidence/S09/completion-review/source-archive.json); [evidence/S09/completion-review/final-checks.log](../../evidence/S09/completion-review/final-checks.log); [evidence/S09/completion-review/runtime.json](../../evidence/S09/completion-review/runtime.json); [evidence/S09/completion-review/upgrade.json](../../evidence/S09/completion-review/upgrade.json); [evidence/S09/completion-review/docker-tests.log](../../evidence/S09/completion-review/docker-tests.log); [evidence/S09/completion-review/docker-smoke.log](../../evidence/S09/completion-review/docker-smoke.log); [evidence/S09/completion-review/browser-check.json](../../evidence/S09/completion-review/browser-check.json); [apps/tests/test_clinical_rules.py](../../apps/tests/test_clinical_rules.py); [apps/tests/test_clinical_workflow.py](../../apps/tests/test_clinical_workflow.py); [docs/clinical/critical-protocol-v1.md](../../docs/clinical/critical-protocol-v1.md); [docs/architecture/clinical-rules.md](../../docs/architecture/clinical-rules.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| F08.1 Врач другой специальности | Источник КР457 §5, две категории, общий врач, отдельный confirm. Ограниченные существующие факты ГТР; тяжесть/срочность проверяет врач; B04. |
| F08.2 Выявление потребности в психиатре | Источник КР457 §5, две категории, общий врач, отдельный confirm. Ограниченные существующие факты ГТР; тяжесть/срочность проверяет врач; B04. |
| F08.3 Маршрут по данным пациента | Источник КР457 §5, две категории, общий врач, отдельный confirm. Ограниченные существующие факты ГТР; тяжесть/срочность проверяет врач; B04. |
| F08.4 Категория обязательно | Источник КР457 §5, две категории, общий врач, отдельный confirm. Ограниченные существующие факты ГТР; тяжесть/срочность проверяет врач; B04. |
| F08.5 Категория желательно | Источник КР457 §5, две категории, общий врач, отдельный confirm. Ограниченные существующие факты ГТР; тяжесть/срочность проверяет врач; B04. |
| F08.6 Учёт тяжести | Источник КР457 §5, две категории, общий врач, отдельный confirm. Ограниченные существующие факты ГТР; тяжесть/срочность проверяет врач; B04. |

## M01 — Как минимум роли Врач и Пациент с раздельными функциями и правами доступа

**Состояние:** partial. Две роли, серверные права/CSRF; test_access/test_security.

**Остаток:** Не полный аудит всех угроз внешнего сервиса.

**Сохранённые доказательства:** [docs/architecture/data-model.md](../../docs/architecture/data-model.md); [evidence/S04/acceptance.md](../../evidence/S04/acceptance.md); [docs/architecture/access.md](../../docs/architecture/access.md); [apps/tests/test_access.py](../../apps/tests/test_access.py); [evidence/S05/acceptance.md](../../evidence/S05/acceptance.md); [evidence/S05/final-checks.log](../../evidence/S05/final-checks.log); [evidence/S05/docker-final-restart.log](../../evidence/S05/docker-final-restart.log); [evidence/S14/acceptance.md](../../evidence/S14/acceptance.md); [evidence/S14/security.md](../../evidence/S14/security.md); [evidence/S14/reliability.md](../../evidence/S14/reliability.md); [evidence/S14/final-checks-r3.log](../../evidence/S14/final-checks-r3.log); [evidence/S14/docker-tests-final.log](../../evidence/S14/docker-tests-final.log); [apps/tests/test_security.py](../../apps/tests/test_security.py); [docs/compliance/data-map.md](../../docs/compliance/data-map.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| M01.1 Роль Врач | Две роли, серверные права/CSRF; test_access/test_security. Не полный аудит всех угроз внешнего сервиса. |
| M01.2 Роль Пациент | Две роли, серверные права/CSRF; test_access/test_security. Не полный аудит всех угроз внешнего сервиса. |
| M01.3 Раздельные функции | Две роли, серверные права/CSRF; test_access/test_security. Не полный аудит всех угроз внешнего сервиса. |
| M01.4 Серверные права доступа | Две роли, серверные права/CSRF; test_access/test_security. Не полный аудит всех угроз внешнего сервиса. |

## M02 — Данные пациента связаны с ведущим лечащим врачом; введенные пациентом сведения попадают в его карточку у врача без третьих лиц

**Состояние:** partial. Одноразовая связь пары, общий самоотчёт без посредника.

**Остаток:** Доставка кабинету не равна чтению человеком; B12.

**Сохранённые доказательства:** [docs/architecture/data-model.md](../../docs/architecture/data-model.md); [evidence/S04/acceptance.md](../../evidence/S04/acceptance.md); [docs/architecture/access.md](../../docs/architecture/access.md); [apps/tests/test_access.py](../../apps/tests/test_access.py); [evidence/S05/acceptance.md](../../evidence/S05/acceptance.md); [evidence/S05/final-checks.log](../../evidence/S05/final-checks.log); [evidence/S05/docker-final-restart.log](../../evidence/S05/docker-final-restart.log); [docs/architecture/records.md](../../docs/architecture/records.md); [apps/tests/test_records.py](../../apps/tests/test_records.py); [evidence/S06/acceptance.md](../../evidence/S06/acceptance.md); [evidence/S06/final-checks.log](../../evidence/S06/final-checks.log); [evidence/S06/docker-restart.log](../../evidence/S06/docker-restart.log); [evidence/S06/doctor-history.png](../../evidence/S06/doctor-history.png); [evidence/S14/acceptance.md](../../evidence/S14/acceptance.md); [evidence/S14/security.md](../../evidence/S14/security.md); [evidence/S14/reliability.md](../../evidence/S14/reliability.md); [evidence/S14/final-checks-r3.log](../../evidence/S14/final-checks-r3.log); [evidence/S14/docker-tests-final.log](../../evidence/S14/docker-tests-final.log); [apps/tests/test_security.py](../../apps/tests/test_security.py); [docs/compliance/data-map.md](../../docs/compliance/data-map.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| M02.1 Ведущий лечащий врач | Одноразовая связь пары, общий самоотчёт без посредника. Доставка кабинету не равна чтению человеком; B12. |
| M02.2 Самоотчёт попадает именно в его карточку | Одноразовая связь пары, общий самоотчёт без посредника. Доставка кабинету не равна чтению человеком; B12. |
| M02.3 Нет ручного посредника | Одноразовая связь пары, общий самоотчёт без посредника. Доставка кабинету не равна чтению человеком; B12. |

## M03 — Назначение изменение и отмена терапии; направление к психиатру; изменение плана лечения только после подтверждения врачом

**Состояние:** partial. Пять действий через отдельное подтверждение врача; test_security.

**Остаток:** Технический барьер не подтверждает правильность самого медицинского решения.

**Сохранённые доказательства:** [docs/architecture/data-model.md](../../docs/architecture/data-model.md); [evidence/S04/acceptance.md](../../evidence/S04/acceptance.md); [evidence/S08A/acceptance.md](../../evidence/S08A/acceptance.md); [evidence/S08A/external-check.md](../../evidence/S08A/external-check.md); [evidence/S08A/final-checks.log](../../evidence/S08A/final-checks.log); [evidence/S08A/upgrade.json](../../evidence/S08A/upgrade.json); [apps/tests/test_decisions.py](../../apps/tests/test_decisions.py); [docs/architecture/clinical-decisions.md](../../docs/architecture/clinical-decisions.md); [evidence/S08/acceptance.md](../../evidence/S08/acceptance.md); [evidence/S08/external-check.md](../../evidence/S08/external-check.md); [evidence/S08/final-checks.log](../../evidence/S08/final-checks.log); [evidence/S08/upgrade.json](../../evidence/S08/upgrade.json); [apps/compass/resources/therapy-reference-v2.json](../../apps/compass/resources/therapy-reference-v2.json); [apps/tests/test_therapy.py](../../apps/tests/test_therapy.py); [docs/architecture/therapy-review.md](../../docs/architecture/therapy-review.md); [evidence/S09/acceptance.md](../../evidence/S09/acceptance.md); [evidence/S09/external-check.md](../../evidence/S09/external-check.md); [evidence/S09/final-checks.log](../../evidence/S09/final-checks.log); [evidence/S09/upgrade.json](../../evidence/S09/upgrade.json); [apps/tests/test_routing.py](../../apps/tests/test_routing.py); [docs/architecture/routing.md](../../docs/architecture/routing.md); [evidence/S09/completion-review/research.md](../../evidence/S09/completion-review/research.md); [evidence/S09/completion-review/boundary-review.md](../../evidence/S09/completion-review/boundary-review.md); [evidence/S09/completion-review/source-archive.json](../../evidence/S09/completion-review/source-archive.json); [evidence/S09/completion-review/final-checks.log](../../evidence/S09/completion-review/final-checks.log); [evidence/S09/completion-review/runtime.json](../../evidence/S09/completion-review/runtime.json); [evidence/S09/completion-review/upgrade.json](../../evidence/S09/completion-review/upgrade.json); [evidence/S09/completion-review/docker-tests.log](../../evidence/S09/completion-review/docker-tests.log); [evidence/S09/completion-review/docker-smoke.log](../../evidence/S09/completion-review/docker-smoke.log); [evidence/S09/completion-review/browser-check.json](../../evidence/S09/completion-review/browser-check.json); [apps/tests/test_clinical_rules.py](../../apps/tests/test_clinical_rules.py); [apps/tests/test_clinical_workflow.py](../../apps/tests/test_clinical_workflow.py); [docs/clinical/critical-protocol-v1.md](../../docs/clinical/critical-protocol-v1.md); [docs/architecture/clinical-rules.md](../../docs/architecture/clinical-rules.md); [evidence/S14/acceptance.md](../../evidence/S14/acceptance.md); [evidence/S14/security.md](../../evidence/S14/security.md); [evidence/S14/reliability.md](../../evidence/S14/reliability.md); [evidence/S14/final-checks-r3.log](../../evidence/S14/final-checks-r3.log); [evidence/S14/docker-tests-final.log](../../evidence/S14/docker-tests-final.log); [apps/tests/test_security.py](../../apps/tests/test_security.py); [docs/compliance/data-map.md](../../docs/compliance/data-map.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| M03.1 Назначение терапии | Пять действий через отдельное подтверждение врача; test_security. Технический барьер не подтверждает правильность самого медицинского решения. |
| M03.2 Изменение терапии | Пять действий через отдельное подтверждение врача; test_security. Технический барьер не подтверждает правильность самого медицинского решения. |
| M03.3 Отмена терапии | Пять действий через отдельное подтверждение врача; test_security. Технический барьер не подтверждает правильность самого медицинского решения. |
| M03.4 Направление к психиатру | Пять действий через отдельное подтверждение врача; test_security. Технический барьер не подтверждает правильность самого медицинского решения. |
| M03.5 Изменение плана | Пять действий через отдельное подтверждение врача; test_security. Технический барьер не подтверждает правильность самого медицинского решения. |
| M03.6 Подтверждение врачом перед каждым действием | Пять действий через отдельное подтверждение врача; test_security. Технический барьер не подтверждает правильность самого медицинского решения. |

## M04 — Демонстрация на клинических сценариях с рассмотрением назначения Авиандра; каждый сценарий включает профиль пациента рекомендации по лечению и маршрутизацию

**Состояние:** partial. Шесть синтетических случаев: профиль, Авиандр, проект лечения/маршрута.

**Остаток:** Нет утверждённых врачом клинических эталонов/результатов апробации.

**Сохранённые доказательства:** [data/synthetic/cases.json](../../data/synthetic/cases.json); [docs/validation/dataset.md](../../docs/validation/dataset.md); [evidence/S03/acceptance.md](../../evidence/S03/acceptance.md); [docs/architecture/data-model.md](../../docs/architecture/data-model.md); [evidence/S04/acceptance.md](../../evidence/S04/acceptance.md); [evidence/S08A/acceptance.md](../../evidence/S08A/acceptance.md); [evidence/S08A/external-check.md](../../evidence/S08A/external-check.md); [evidence/S08A/final-checks.log](../../evidence/S08A/final-checks.log); [evidence/S08A/upgrade.json](../../evidence/S08A/upgrade.json); [apps/tests/test_decisions.py](../../apps/tests/test_decisions.py); [docs/architecture/clinical-decisions.md](../../docs/architecture/clinical-decisions.md); [evidence/S08/acceptance.md](../../evidence/S08/acceptance.md); [evidence/S08/external-check.md](../../evidence/S08/external-check.md); [evidence/S08/final-checks.log](../../evidence/S08/final-checks.log); [evidence/S08/upgrade.json](../../evidence/S08/upgrade.json); [apps/compass/resources/therapy-reference-v2.json](../../apps/compass/resources/therapy-reference-v2.json); [apps/tests/test_therapy.py](../../apps/tests/test_therapy.py); [docs/architecture/therapy-review.md](../../docs/architecture/therapy-review.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| M04.1 Рассмотрение Авиандра | Шесть синтетических случаев: профиль, Авиандр, проект лечения/маршрута. Нет утверждённых врачом клинических эталонов/результатов апробации. |
| M04.2 Профиль в каждом случае | Шесть синтетических случаев: профиль, Авиандр, проект лечения/маршрута. Нет утверждённых врачом клинических эталонов/результатов апробации. |
| M04.3 Лечебные рекомендации в каждом случае | Шесть синтетических случаев: профиль, Авиандр, проект лечения/маршрута. Нет утверждённых врачом клинических эталонов/результатов апробации. |
| M04.4 Маршрутизация в каждом случае | Шесть синтетических случаев: профиль, Авиандр, проект лечения/маршрута. Нет утверждённых врачом клинических эталонов/результатов апробации. |

## M05 — Механизм алертинга самостоятельно определяет критическое состояние по признакам выбранным командой; экстренно оповещает врача и выполняет действия выбранные командой

**Состояние:** partial. A02-v2, атомарный outbox, HTTP и местная консоль; S09/S10/S15.

**Остаток:** Квитанция клиента не чтение врача; нет внешнего резерва/24×7, B04.

**Сохранённые доказательства:** [docs/architecture/data-model.md](../../docs/architecture/data-model.md); [evidence/S04/acceptance.md](../../evidence/S04/acceptance.md); [evidence/audits/2026-10-19-s08a/report.json](../../evidence/audits/2026-10-19-s08a/report.json); [evidence/S09/acceptance.md](../../evidence/S09/acceptance.md); [evidence/S09/external-check.md](../../evidence/S09/external-check.md); [evidence/S09/final-checks.log](../../evidence/S09/final-checks.log); [evidence/S09/upgrade.json](../../evidence/S09/upgrade.json); [apps/tests/test_routing.py](../../apps/tests/test_routing.py); [docs/architecture/routing.md](../../docs/architecture/routing.md); [evidence/S09/resume-2026-10-19/plan-change.md](../../evidence/S09/resume-2026-10-19/plan-change.md); [evidence/S10A/acceptance.md](../../evidence/S10A/acceptance.md); [evidence/S10A/final-checks.log](../../evidence/S10A/final-checks.log); [evidence/S10A/delivery.json](../../evidence/S10A/delivery.json); [evidence/S10A/browser-check.json](../../evidence/S10A/browser-check.json); [evidence/S10A/upgrade.json](../../evidence/S10A/upgrade.json); [apps/tests/test_notifications.py](../../apps/tests/test_notifications.py); [docs/architecture/routine-notifications.md](../../docs/architecture/routine-notifications.md); [evidence/S09/completion-review/research.md](../../evidence/S09/completion-review/research.md); [evidence/S09/completion-review/boundary-review.md](../../evidence/S09/completion-review/boundary-review.md); [evidence/S09/completion-review/source-archive.json](../../evidence/S09/completion-review/source-archive.json); [evidence/S09/completion-review/final-checks.log](../../evidence/S09/completion-review/final-checks.log); [evidence/S09/completion-review/runtime.json](../../evidence/S09/completion-review/runtime.json); [evidence/S09/completion-review/upgrade.json](../../evidence/S09/completion-review/upgrade.json); [evidence/S09/completion-review/docker-tests.log](../../evidence/S09/completion-review/docker-tests.log); [evidence/S09/completion-review/docker-smoke.log](../../evidence/S09/completion-review/docker-smoke.log); [evidence/S09/completion-review/browser-check.json](../../evidence/S09/completion-review/browser-check.json); [apps/tests/test_clinical_rules.py](../../apps/tests/test_clinical_rules.py); [apps/tests/test_clinical_workflow.py](../../apps/tests/test_clinical_workflow.py); [docs/clinical/critical-protocol-v1.md](../../docs/clinical/critical-protocol-v1.md); [docs/architecture/clinical-rules.md](../../docs/architecture/clinical-rules.md); [evidence/S10/acceptance.md](../../evidence/S10/acceptance.md); [evidence/S10/final-checks.log](../../evidence/S10/final-checks.log); [evidence/S10/runtime.json](../../evidence/S10/runtime.json); [evidence/S10/upgrade.json](../../evidence/S10/upgrade.json); [evidence/S10/reserve.json](../../evidence/S10/reserve.json); [evidence/S10/browser-check.json](../../evidence/S10/browser-check.json); [evidence/S10/offscreen-check.json](../../evidence/S10/offscreen-check.json); [evidence/S10/docker-tests.log](../../evidence/S10/docker-tests.log); [apps/tests/test_critical_delivery.py](../../apps/tests/test_critical_delivery.py); [docs/architecture/critical-delivery.md](../../docs/architecture/critical-delivery.md); [docs/clinical/critical-protocol-v2.md](../../docs/clinical/critical-protocol-v2.md); [evidence/S10/final-browser-measurement.json](../../evidence/S10/final-browser-measurement.json); [evidence/S14/acceptance.md](../../evidence/S14/acceptance.md); [evidence/S14/security.md](../../evidence/S14/security.md); [evidence/S14/reliability.md](../../evidence/S14/reliability.md); [evidence/S14/final-checks-r3.log](../../evidence/S14/final-checks-r3.log); [evidence/S14/docker-tests-final.log](../../evidence/S14/docker-tests-final.log); [apps/tests/test_security.py](../../apps/tests/test_security.py); [docs/compliance/data-map.md](../../docs/compliance/data-map.md); [evidence/S15/acceptance.md](../../evidence/S15/acceptance.md); [evidence/S15/performance.json](../../evidence/S15/performance.json); [evidence/S15/load.json](../../evidence/S15/load.json); [evidence/S15/performance.md](../../evidence/S15/performance.md); [evidence/S15/recovery.json](../../evidence/S15/recovery.json); [evidence/S15/recovery.md](../../evidence/S15/recovery.md); [docs/operations/recovery.md](../../docs/operations/recovery.md); [apps/tests/test_backup.py](../../apps/tests/test_backup.py).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| M05.1 Самостоятельное определение критичности | A02-v2, атомарный outbox, HTTP и местная консоль; S09/S10/S15. Квитанция клиента не чтение врача; нет внешнего резерва/24×7, B04. |
| M05.2 Обоснованные признаки команды | A02-v2, атомарный outbox, HTTP и местная консоль; S09/S10/S15. Квитанция клиента не чтение врача; нет внешнего резерва/24×7, B04. |
| M05.3 Экстренное оповещение врача | A02-v2, атомарный outbox, HTTP и местная консоль; S09/S10/S15. Квитанция клиента не чтение врача; нет внешнего резерва/24×7, B04. |
| M05.4 Определённые командой действия | A02-v2, атомарный outbox, HTTP и местная консоль; S09/S10/S15. Квитанция клиента не чтение врача; нет внешнего резерва/24×7, B04. |
| M05.5 Фактически работающий механизм | A02-v2, атомарный outbox, HTTP и местная консоль; S09/S10/S15. Квитанция клиента не чтение врача; нет внешнего резерва/24×7, B04. |

## M06 — Сигналы о направлении к психиатру и безопасности терапии визуально выделены; категории обязательно и желательно различимы

**Состояние:** partial. Текст/значки/рамки категорий и безопасности; S13 снимки.

**Остаток:** Визуальная самопроверка, не исследование пользователей.

**Сохранённые доказательства:** [docs/architecture/data-model.md](../../docs/architecture/data-model.md); [evidence/S04/acceptance.md](../../evidence/S04/acceptance.md); [evidence/audits/2026-10-19-s08a/report.json](../../evidence/audits/2026-10-19-s08a/report.json); [evidence/S09/acceptance.md](../../evidence/S09/acceptance.md); [evidence/S09/external-check.md](../../evidence/S09/external-check.md); [evidence/S09/final-checks.log](../../evidence/S09/final-checks.log); [evidence/S09/upgrade.json](../../evidence/S09/upgrade.json); [apps/tests/test_routing.py](../../apps/tests/test_routing.py); [docs/architecture/routing.md](../../docs/architecture/routing.md); [evidence/S09/completion-review/research.md](../../evidence/S09/completion-review/research.md); [evidence/S09/completion-review/boundary-review.md](../../evidence/S09/completion-review/boundary-review.md); [evidence/S09/completion-review/source-archive.json](../../evidence/S09/completion-review/source-archive.json); [evidence/S09/completion-review/final-checks.log](../../evidence/S09/completion-review/final-checks.log); [evidence/S09/completion-review/runtime.json](../../evidence/S09/completion-review/runtime.json); [evidence/S09/completion-review/upgrade.json](../../evidence/S09/completion-review/upgrade.json); [evidence/S09/completion-review/docker-tests.log](../../evidence/S09/completion-review/docker-tests.log); [evidence/S09/completion-review/docker-smoke.log](../../evidence/S09/completion-review/docker-smoke.log); [evidence/S09/completion-review/browser-check.json](../../evidence/S09/completion-review/browser-check.json); [apps/tests/test_clinical_rules.py](../../apps/tests/test_clinical_rules.py); [apps/tests/test_clinical_workflow.py](../../apps/tests/test_clinical_workflow.py); [docs/clinical/critical-protocol-v1.md](../../docs/clinical/critical-protocol-v1.md); [docs/architecture/clinical-rules.md](../../docs/architecture/clinical-rules.md); [evidence/S13/acceptance.md](../../evidence/S13/acceptance.md); [evidence/S13/platforms.md](../../evidence/S13/platforms.md); [evidence/S13/browser-check.json](../../evidence/S13/browser-check.json); [docs/architecture/interface-search-extensions.md](../../docs/architecture/interface-search-extensions.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| M06.1 Заметное направление | Текст/значки/рамки категорий и безопасности; S13 снимки. Визуальная самопроверка, не исследование пользователей. |
| M06.2 Заметная безопасность терапии | Текст/значки/рамки категорий и безопасности; S13 снимки. Визуальная самопроверка, не исследование пользователей. |
| M06.3 Различимость обязательно/желательно | Текст/значки/рамки категорий и безопасности; S13 снимки. Визуальная самопроверка, не исследование пользователей. |

## M07 — Рекомендовать только препараты зарегистрированные в РФ в пределах зарегистрированных показаний противопоказаний и доз; решение вне инструкции принимает только врач

**Состояние:** partial. Официальный листок ГРЛС, ограниченная справка, ручное решение.

**Остаток:** ОХЛП отдельно не получена; полный профессиональный контроль и свободный текст не проверены.

**Сохранённые доказательства:** [docs/clinical/sources.md](../../docs/clinical/sources.md); [evidence/S02/requirements-review.md](../../evidence/S02/requirements-review.md); [evidence/S02/acceptance.md](../../evidence/S02/acceptance.md); [docs/clinical/rule-catalog.md](../../docs/clinical/rule-catalog.md); [evidence/S02/research-clinical.md](../../evidence/S02/research-clinical.md); [evidence/S02/received-review.md](../../evidence/S02/received-review.md); [evidence/S02/received-research.md](../../evidence/S02/received-research.md); [evidence/S02/received-grls-check.json](../../evidence/S02/received-grls-check.json); [evidence/S02/acceptance-review.md](../../evidence/S02/acceptance-review.md); [docs/architecture/data-model.md](../../docs/architecture/data-model.md); [evidence/S04/acceptance.md](../../evidence/S04/acceptance.md); [evidence/S08A/acceptance.md](../../evidence/S08A/acceptance.md); [evidence/S08A/external-check.md](../../evidence/S08A/external-check.md); [evidence/S08A/final-checks.log](../../evidence/S08A/final-checks.log); [evidence/S08A/upgrade.json](../../evidence/S08A/upgrade.json); [apps/tests/test_decisions.py](../../apps/tests/test_decisions.py); [docs/architecture/clinical-decisions.md](../../docs/architecture/clinical-decisions.md); [evidence/S08B/acceptance.md](../../evidence/S08B/acceptance.md); [evidence/S08B/final-checks.log](../../evidence/S08B/final-checks.log); [evidence/S08B/upgrade.json](../../evidence/S08B/upgrade.json); [apps/tests/test_ages.py](../../apps/tests/test_ages.py); [docs/architecture/age-reviews.md](../../docs/architecture/age-reviews.md); [evidence/S08/acceptance.md](../../evidence/S08/acceptance.md); [evidence/S08/external-check.md](../../evidence/S08/external-check.md); [evidence/S08/final-checks.log](../../evidence/S08/final-checks.log); [evidence/S08/upgrade.json](../../evidence/S08/upgrade.json); [apps/compass/resources/therapy-reference-v2.json](../../apps/compass/resources/therapy-reference-v2.json); [apps/tests/test_therapy.py](../../apps/tests/test_therapy.py); [docs/architecture/therapy-review.md](../../docs/architecture/therapy-review.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| M07.1 Регистрация препарата в РФ | Официальный листок ГРЛС, ограниченная справка, ручное решение. ОХЛП отдельно не получена; полный профессиональный контроль и свободный текст не проверены. |
| M07.2 Показания | Официальный листок ГРЛС, ограниченная справка, ручное решение. ОХЛП отдельно не получена; полный профессиональный контроль и свободный текст не проверены. |
| M07.3 Противопоказания | Официальный листок ГРЛС, ограниченная справка, ручное решение. ОХЛП отдельно не получена; полный профессиональный контроль и свободный текст не проверены. |
| M07.4 Режимы дозирования | Официальный листок ГРЛС, ограниченная справка, ручное решение. ОХЛП отдельно не получена; полный профессиональный контроль и свободный текст не проверены. |
| M07.5 Вне инструкции решает только врач | Официальный листок ГРЛС, ограниченная справка, ручное решение. ОХЛП отдельно не получена; полный профессиональный контроль и свободный текст не проверены. |

## M08 — Клинические рекомендации действующие и одобренные Минздравом РФ; международные только дополнение с явным источником; сведения о препаратах из действующей инструкции или ОХЛП ГРЛС; инструменты валидированные с валидированной русской версией; источник валидации и соблюдение авторских прав и лицензии

**Состояние:** partial. Версии источников, SHA, DASS/русская статья/ключ и notices.

**Остаток:** Повторная внешняя проверка имеет границы; нет клинического утверждения реализации/полного аудита прав.

**Сохранённые доказательства:** [docs/clinical/sources.md](../../docs/clinical/sources.md); [evidence/S02/requirements-review.md](../../evidence/S02/requirements-review.md); [evidence/S02/acceptance.md](../../evidence/S02/acceptance.md); [docs/clinical/scales-rights.md](../../docs/clinical/scales-rights.md); [evidence/S02/research-scales.md](../../evidence/S02/research-scales.md); [evidence/S02/received-review.md](../../evidence/S02/received-review.md); [evidence/S02/received-research.md](../../evidence/S02/received-research.md); [evidence/S02/received/manifest.json](../../evidence/S02/received/manifest.json); [docs/clinical/validation-request.md](../../docs/clinical/validation-request.md); [evidence/S02/acceptance-review.md](../../evidence/S02/acceptance-review.md); [docs/architecture/data-model.md](../../docs/architecture/data-model.md); [evidence/S04/acceptance.md](../../evidence/S04/acceptance.md); [evidence/S07/research.md](../../evidence/S07/research.md); [evidence/S07/acceptance.md](../../evidence/S07/acceptance.md); [evidence/S07/review/scale-research.md](../../evidence/S07/review/scale-research.md); [evidence/S07/review/final-checks.log](../../evidence/S07/review/final-checks.log); [apps/tests/test_assessments.py](../../apps/tests/test_assessments.py); [docs/architecture/assessments.md](../../docs/architecture/assessments.md); [evidence/S08A/acceptance.md](../../evidence/S08A/acceptance.md); [evidence/S08A/external-check.md](../../evidence/S08A/external-check.md); [evidence/S08A/final-checks.log](../../evidence/S08A/final-checks.log); [evidence/S08A/upgrade.json](../../evidence/S08A/upgrade.json); [apps/tests/test_decisions.py](../../apps/tests/test_decisions.py); [docs/architecture/clinical-decisions.md](../../docs/architecture/clinical-decisions.md); [evidence/audits/2026-10-19-s08a/report.json](../../evidence/audits/2026-10-19-s08a/report.json); [evidence/S08B/acceptance.md](../../evidence/S08B/acceptance.md); [evidence/S08B/final-checks.log](../../evidence/S08B/final-checks.log); [evidence/S08B/upgrade.json](../../evidence/S08B/upgrade.json); [apps/tests/test_ages.py](../../apps/tests/test_ages.py); [docs/architecture/age-reviews.md](../../docs/architecture/age-reviews.md); [evidence/S08/acceptance.md](../../evidence/S08/acceptance.md); [evidence/S08/external-check.md](../../evidence/S08/external-check.md); [evidence/S08/final-checks.log](../../evidence/S08/final-checks.log); [evidence/S08/upgrade.json](../../evidence/S08/upgrade.json); [apps/compass/resources/therapy-reference-v2.json](../../apps/compass/resources/therapy-reference-v2.json); [apps/tests/test_therapy.py](../../apps/tests/test_therapy.py); [docs/architecture/therapy-review.md](../../docs/architecture/therapy-review.md); [evidence/S09/acceptance.md](../../evidence/S09/acceptance.md); [evidence/S09/external-check.md](../../evidence/S09/external-check.md); [evidence/S09/final-checks.log](../../evidence/S09/final-checks.log); [evidence/S09/upgrade.json](../../evidence/S09/upgrade.json); [apps/tests/test_routing.py](../../apps/tests/test_routing.py); [docs/architecture/routing.md](../../docs/architecture/routing.md); [evidence/S09/completion-review/research.md](../../evidence/S09/completion-review/research.md); [evidence/S09/completion-review/boundary-review.md](../../evidence/S09/completion-review/boundary-review.md); [evidence/S09/completion-review/source-archive.json](../../evidence/S09/completion-review/source-archive.json); [evidence/S09/completion-review/final-checks.log](../../evidence/S09/completion-review/final-checks.log); [evidence/S09/completion-review/runtime.json](../../evidence/S09/completion-review/runtime.json); [evidence/S09/completion-review/upgrade.json](../../evidence/S09/completion-review/upgrade.json); [evidence/S09/completion-review/docker-tests.log](../../evidence/S09/completion-review/docker-tests.log); [evidence/S09/completion-review/docker-smoke.log](../../evidence/S09/completion-review/docker-smoke.log); [evidence/S09/completion-review/browser-check.json](../../evidence/S09/completion-review/browser-check.json); [apps/tests/test_clinical_rules.py](../../apps/tests/test_clinical_rules.py); [apps/tests/test_clinical_workflow.py](../../apps/tests/test_clinical_workflow.py); [docs/clinical/critical-protocol-v1.md](../../docs/clinical/critical-protocol-v1.md); [docs/architecture/clinical-rules.md](../../docs/architecture/clinical-rules.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| M08.1 Действующие КР РФ | Версии источников, SHA, DASS/русская статья/ключ и notices. Повторная внешняя проверка имеет границы; нет клинического утверждения реализации/полного аудита прав. |
| M08.2 Одобрение Минздравом | Версии источников, SHA, DASS/русская статья/ключ и notices. Повторная внешняя проверка имеет границы; нет клинического утверждения реализации/полного аудита прав. |
| M08.3 Международные только дополнение | Версии источников, SHA, DASS/русская статья/ключ и notices. Повторная внешняя проверка имеет границы; нет клинического утверждения реализации/полного аудита прав. |
| M08.4 Явный источник международных | Версии источников, SHA, DASS/русская статья/ключ и notices. Повторная внешняя проверка имеет границы; нет клинического утверждения реализации/полного аудита прав. |
| M08.5 Действующая инструкция/ОХЛП именно ГРЛС | Версии источников, SHA, DASS/русская статья/ключ и notices. Повторная внешняя проверка имеет границы; нет клинического утверждения реализации/полного аудита прав. |
| M08.6 Валидированный инструмент | Версии источников, SHA, DASS/русская статья/ключ и notices. Повторная внешняя проверка имеет границы; нет клинического утверждения реализации/полного аудита прав. |
| M08.7 Валидированная русская версия | Версии источников, SHA, DASS/русская статья/ключ и notices. Повторная внешняя проверка имеет границы; нет клинического утверждения реализации/полного аудита прав. |
| M08.8 Источник валидации | Версии источников, SHA, DASS/русская статья/ключ и notices. Повторная внешняя проверка имеет границы; нет клинического утверждения реализации/полного аудита прав. |
| M08.9 Авторские права и лицензия | Версии источников, SHA, DASS/русская статья/ключ и notices. Повторная внешняя проверка имеет границы; нет клинического утверждения реализации/полного аудита прав. |

## M09 — Соответствие требованиям законодательства РФ

**Состояние:** partial. Карта данных/режим локальной синтетики/правовые вопросы.

**Остаток:** Соответствие фактического медицинского сервиса законодательству не установлено.

**Сохранённые доказательства:** [docs/contest/contract.md](../../docs/contest/contract.md); [evidence/S01/acceptance.md](../../evidence/S01/acceptance.md); [docs/architecture/data-model.md](../../docs/architecture/data-model.md); [evidence/S04/acceptance.md](../../evidence/S04/acceptance.md); [evidence/S14/acceptance.md](../../evidence/S14/acceptance.md); [evidence/S14/security.md](../../evidence/S14/security.md); [evidence/S14/reliability.md](../../evidence/S14/reliability.md); [evidence/S14/final-checks-r3.log](../../evidence/S14/final-checks-r3.log); [evidence/S14/docker-tests-final.log](../../evidence/S14/docker-tests-final.log); [apps/tests/test_security.py](../../apps/tests/test_security.py); [docs/compliance/data-map.md](../../docs/compliance/data-map.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| M09.1 Соответствие требованиям законодательства РФ | Карта данных/режим локальной синтетики/правовые вопросы. Соответствие фактического медицинского сервиса законодательству не установлено. |

## M10 — Соблюдение конфиденциальности

**Состояние:** partial. Изоляция пары, безопасные ошибки, закрытые файлы/копии.

**Остаток:** Не шифрование/полный аудит конфиденциальности; B16.

**Сохранённые доказательства:** [docs/architecture/data-model.md](../../docs/architecture/data-model.md); [evidence/S04/acceptance.md](../../evidence/S04/acceptance.md); [docs/architecture/access.md](../../docs/architecture/access.md); [apps/tests/test_access.py](../../apps/tests/test_access.py); [evidence/S05/acceptance.md](../../evidence/S05/acceptance.md); [evidence/S05/final-checks.log](../../evidence/S05/final-checks.log); [evidence/S05/docker-final-restart.log](../../evidence/S05/docker-final-restart.log); [evidence/S14/acceptance.md](../../evidence/S14/acceptance.md); [evidence/S14/security.md](../../evidence/S14/security.md); [evidence/S14/reliability.md](../../evidence/S14/reliability.md); [evidence/S14/final-checks-r3.log](../../evidence/S14/final-checks-r3.log); [evidence/S14/docker-tests-final.log](../../evidence/S14/docker-tests-final.log); [apps/tests/test_security.py](../../apps/tests/test_security.py); [docs/compliance/data-map.md](../../docs/compliance/data-map.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| M10.1 Соблюдение конфиденциальности | Изоляция пары, безопасные ошибки, закрытые файлы/копии. Не шифрование/полный аудит конфиденциальности; B16. |

## E01 — Научная обоснованность: использование шкал клинических рекомендаций инструкций и другого; необходимо указать источники

**Состояние:** partial. Указаны источники/версии/разделы/границы применимости.

**Остаток:** Обоснованность всех будущих решений и клиническая оценка не подтверждены.

**Сохранённые доказательства:** [docs/clinical/sources.md](../../docs/clinical/sources.md); [evidence/S02/requirements-review.md](../../evidence/S02/requirements-review.md); [evidence/S02/acceptance.md](../../evidence/S02/acceptance.md); [docs/clinical/scales-rights.md](../../docs/clinical/scales-rights.md); [evidence/S02/research-scales.md](../../evidence/S02/research-scales.md); [evidence/S02/received-review.md](../../evidence/S02/received-review.md); [evidence/S02/received-research.md](../../evidence/S02/received-research.md); [evidence/S02/received/manifest.json](../../evidence/S02/received/manifest.json); [evidence/S02/acceptance-review.md](../../evidence/S02/acceptance-review.md); [evidence/S07/acceptance.md](../../evidence/S07/acceptance.md); [evidence/S07/review/scale-research.md](../../evidence/S07/review/scale-research.md); [evidence/S07/review/final-checks.log](../../evidence/S07/review/final-checks.log); [apps/tests/test_assessments.py](../../apps/tests/test_assessments.py); [docs/architecture/assessments.md](../../docs/architecture/assessments.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| E01.1 Научная обоснованность: использование шкал клинических рекомендаций инструкций и другого; необходимо указать источники | Указаны источники/версии/разделы/границы применимости. Обоснованность всех будущих решений и клиническая оценка не подтверждены. |

## E02 — Клиническая применимость

**Состояние:** not_verified. Технические сценарии и неизменяемые проекты решений.

**Остаток:** Клиническая применимость не подтверждена независимым проверяющим; B04.

**Сохранённые доказательства:** [docs/validation/dataset.md](../../docs/validation/dataset.md); [data/synthetic/manifest.json](../../data/synthetic/manifest.json); [evidence/S03/acceptance.md](../../evidence/S03/acceptance.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| E02.1 Клиническая применимость | Технические сценарии и неизменяемые проекты решений. Клиническая применимость не подтверждена независимым проверяющим; B04. |

## E03 — Удобство пользовательского интерфейса

**Состояние:** partial. Две роли/задачи/адаптивность в S13.

**Остаток:** Нет независимых пользователей; E06 отсутствует.

**Сохранённые доказательства:** [evidence/S13/acceptance.md](../../evidence/S13/acceptance.md); [evidence/S13/platforms.md](../../evidence/S13/platforms.md); [evidence/S13/browser-check.json](../../evidence/S13/browser-check.json); [docs/architecture/interface-search-extensions.md](../../docs/architecture/interface-search-extensions.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| E03.1 Удобство пользовательского интерфейса | Две роли/задачи/адаптивность в S13. Нет независимых пользователей; E06 отсутствует. |

## E04 — Наличие всех обязательных условий

**Состояние:** not_verified. Свод всех 83 требований/160 подпунктов в этом аудите.

**Остаток:** Все обязательные условия НЕ подтверждены; готовность заблокирована.

**Доказательства выполнения отсутствуют.** Свод требования не является доказательством события.

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| E04.1 Наличие всех обязательных условий | Свод всех 83 требований/160 подпунктов в этом аудите. Все обязательные условия НЕ подтверждены; готовность заблокирована. |

## E05 — Отдельно оценивается каждый пункт списка функций инструмента

**Состояние:** partial. Отдельная строка для F01–F08 с доказательствами и пробелами.

**Остаток:** Фактические оценки жюри ещё не получены.

**Сохранённые доказательства:** [docs/architecture/communication.md](../../docs/architecture/communication.md); [apps/tests/test_communication.py](../../apps/tests/test_communication.py); [evidence/S11/acceptance.md](../../evidence/S11/acceptance.md); [evidence/S11/final-checks.log](../../evidence/S11/final-checks.log); [evidence/S11/runtime.json](../../evidence/S11/runtime.json); [evidence/S11/upgrade.json](../../evidence/S11/upgrade.json); [evidence/S11/browser-check.json](../../evidence/S11/browser-check.json).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| E05.1 Отдельно оценивается каждый пункт списка функций инструмента | Отдельная строка для F01–F08 с доказательствами и пробелами. Фактические оценки жюри ещё не получены. |

## E06 — Апробация с соблюдением законодательства и сохранением конфиденциальности

**Состояние:** not_verified. Сохранена история подготовки S16 без испытаний.

**Остаток:** Фактическая апробация не проведена/результаты не получены; законность и конфиденциальность апробации не проверены.

**Сохранённые доказательства:** [evidence/audits/2026-10-19-s08a/report.json](../../evidence/audits/2026-10-19-s08a/report.json); [evidence/S16/validation-summary.md](../../evidence/S16/validation-summary.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| E06.1 Действительная апробация | Сохранена история подготовки S16 без испытаний. Фактическая апробация не проведена/результаты не получены; законность и конфиденциальность апробации не проверены. |
| E06.2 Соблюдение закона | Сохранена история подготовки S16 без испытаний. Фактическая апробация не проведена/результаты не получены; законность и конфиденциальность апробации не проверены. |
| E06.3 Сохранение конфиденциальности | Сохранена история подготовки S16 без испытаний. Фактическая апробация не проведена/результаты не получены; законность и конфиденциальность апробации не проверены. |

## T01 — Быстродействие: отклик интерфейса формирование рекомендаций доставка алерта врачу с момента поступления критических данных и другое

**Состояние:** partial. S15 performance.json/load.json: HTTP/ручной проект/critical receipt.

**Остаток:** Нет paint/чтения врача; автоматического генератора рекомендаций нет.

**Сохранённые доказательства:** [evidence/S15/acceptance.md](../../evidence/S15/acceptance.md); [evidence/S15/performance.json](../../evidence/S15/performance.json); [evidence/S15/load.json](../../evidence/S15/load.json); [evidence/S15/performance.md](../../evidence/S15/performance.md); [evidence/S15/recovery.json](../../evidence/S15/recovery.json); [evidence/S15/recovery.md](../../evidence/S15/recovery.md); [docs/operations/recovery.md](../../docs/operations/recovery.md); [apps/tests/test_backup.py](../../apps/tests/test_backup.py).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| T01.1 Отклик интерфейса | S15 performance.json/load.json: HTTP/ручной проект/critical receipt. Нет paint/чтения врача; автоматического генератора рекомендаций нет. |
| T01.2 Формирование рекомендаций | S15 performance.json/load.json: HTTP/ручной проект/critical receipt. Нет paint/чтения врача; автоматического генератора рекомендаций нет. |
| T01.3 Алерт от момента поступления критических данных | S15 performance.json/load.json: HTTP/ручной проект/critical receipt. Нет paint/чтения врача; автоматического генератора рекомендаций нет. |

## T02 — Точность и полнота извлечения ключевых сведений из историй болезни разных шаблонов: порядок разделов детализация стиль описания формат диагнозов и назначений

**Состояние:** partial. S12 extraction-results.json: holdout 31TP/12FP/38FN, precision72,1%/recall44,9%.

**Остаток:** 20 пропусков риска; известный синтетический набор, не внешняя оценка; B15.

**Сохранённые доказательства:** [docs/validation/dataset.md](../../docs/validation/dataset.md); [data/synthetic/manifest.json](../../data/synthetic/manifest.json); [evidence/S03/acceptance.md](../../evidence/S03/acceptance.md); [evidence/S12/acceptance.md](../../evidence/S12/acceptance.md); [evidence/S12/extraction-results.json](../../evidence/S12/extraction-results.json); [docs/validation/extraction-method.md](../../docs/validation/extraction-method.md); [evidence/S12/external-check.md](../../evidence/S12/external-check.md); [apps/tests/test_extraction.py](../../apps/tests/test_extraction.py); [docs/validation/extraction-method-addendum.md](../../docs/validation/extraction-method-addendum.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| T02.1 Точность извлечения | S12 extraction-results.json: holdout 31TP/12FP/38FN, precision72,1%/recall44,9%. 20 пропусков риска; известный синтетический набор, не внешняя оценка; B15. |
| T02.2 Полнота извлечения | S12 extraction-results.json: holdout 31TP/12FP/38FN, precision72,1%/recall44,9%. 20 пропусков риска; известный синтетический набор, не внешняя оценка; B15. |
| T02.3 Разный порядок | S12 extraction-results.json: holdout 31TP/12FP/38FN, precision72,1%/recall44,9%. 20 пропусков риска; известный синтетический набор, не внешняя оценка; B15. |
| T02.4 Разная детализация | S12 extraction-results.json: holdout 31TP/12FP/38FN, precision72,1%/recall44,9%. 20 пропусков риска; известный синтетический набор, не внешняя оценка; B15. |
| T02.5 Разный стиль | S12 extraction-results.json: holdout 31TP/12FP/38FN, precision72,1%/recall44,9%. 20 пропусков риска; известный синтетический набор, не внешняя оценка; B15. |
| T02.6 Разный формат диагнозов | S12 extraction-results.json: holdout 31TP/12FP/38FN, precision72,1%/recall44,9%. 20 пропусков риска; известный синтетический набор, не внешняя оценка; B15. |
| T02.7 Разный формат назначений | S12 extraction-results.json: holdout 31TP/12FP/38FN, precision72,1%/recall44,9%. 20 пропусков риска; известный синтетический набор, не внешняя оценка; B15. |

## T03 — Надежность и корректность: количество сбоев в сценариях; устойчивость к полноте и корректности входных данных

**Состояние:** partial. S14 reliability и текущий make check, S15 сбои.

**Остаток:** Исторические Linux404/409 без установленной причины; B12. Набор не исчерпывает ошибки.

**Сохранённые доказательства:** [evidence/audits/2026-10-19-s08a/report.json](../../evidence/audits/2026-10-19-s08a/report.json); [evidence/S14/acceptance.md](../../evidence/S14/acceptance.md); [evidence/S14/security.md](../../evidence/S14/security.md); [evidence/S14/reliability.md](../../evidence/S14/reliability.md); [evidence/S14/final-checks-r3.log](../../evidence/S14/final-checks-r3.log); [evidence/S14/docker-tests-final.log](../../evidence/S14/docker-tests-final.log); [apps/tests/test_security.py](../../apps/tests/test_security.py); [docs/compliance/data-map.md](../../docs/compliance/data-map.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| T03.1 Число сбоев сценариев | S14 reliability и текущий make check, S15 сбои. Исторические Linux404/409 без установленной причины; B12. Набор не исчерпывает ошибки. |
| T03.2 Неполнота ввода | S14 reliability и текущий make check, S15 сбои. Исторические Linux404/409 без установленной причины; B12. Набор не исчерпывает ошибки. |
| T03.3 Некорректность ввода | S14 reliability и текущий make check, S15 сбои. Исторические Linux404/409 без установленной причины; B12. Набор не исчерпывает ошибки. |

## T04 — Эргономика: время и количество действий пользователя в типовых сценариях

**Состояние:** partial. S13 platforms.md: действия/время автоматических проходов.

**Остаток:** Время чтения/работы реальных пользователей отсутствует; эргономика людьми не проверена.

**Сохранённые доказательства:** [evidence/S13/acceptance.md](../../evidence/S13/acceptance.md); [evidence/S13/platforms.md](../../evidence/S13/platforms.md); [evidence/S13/browser-check.json](../../evidence/S13/browser-check.json); [docs/architecture/interface-search-extensions.md](../../docs/architecture/interface-search-extensions.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| T04.1 Время пользователя | S13 platforms.md: действия/время автоматических проходов. Время чтения/работы реальных пользователей отсутствует; эргономика людьми не проверена. |
| T04.2 Число действий | S13 platforms.md: действия/время автоматических проходов. Время чтения/работы реальных пользователей отсутствует; эргономика людьми не проверена. |
| T04.3 Типовые сценарии | S13 platforms.md: действия/время автоматических проходов. Время чтения/работы реальных пользователей отсутствует; эргономика людьми не проверена. |

## T05 — Обоснованность выводов и рекомендаций релевантными источниками методами шкалами и другим на основе чего они сделаны

**Состояние:** partial. Снимок пациента/источника, DASS/КР/листок и объяснение врача.

**Остаток:** Нет проверки всех клинических выводов/свободного текста; B04.

**Сохранённые доказательства:** [evidence/S08A/acceptance.md](../../evidence/S08A/acceptance.md); [evidence/S08A/external-check.md](../../evidence/S08A/external-check.md); [evidence/S08A/final-checks.log](../../evidence/S08A/final-checks.log); [evidence/S08A/upgrade.json](../../evidence/S08A/upgrade.json); [apps/tests/test_decisions.py](../../apps/tests/test_decisions.py); [docs/architecture/clinical-decisions.md](../../docs/architecture/clinical-decisions.md); [evidence/S08B/acceptance.md](../../evidence/S08B/acceptance.md); [evidence/S08B/final-checks.log](../../evidence/S08B/final-checks.log); [evidence/S08B/upgrade.json](../../evidence/S08B/upgrade.json); [apps/tests/test_ages.py](../../apps/tests/test_ages.py); [docs/architecture/age-reviews.md](../../docs/architecture/age-reviews.md); [evidence/S08/acceptance.md](../../evidence/S08/acceptance.md); [evidence/S08/external-check.md](../../evidence/S08/external-check.md); [evidence/S08/final-checks.log](../../evidence/S08/final-checks.log); [evidence/S08/upgrade.json](../../evidence/S08/upgrade.json); [apps/compass/resources/therapy-reference-v2.json](../../apps/compass/resources/therapy-reference-v2.json); [apps/tests/test_therapy.py](../../apps/tests/test_therapy.py); [docs/architecture/therapy-review.md](../../docs/architecture/therapy-review.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| T05.1 Выводы с релевантными источниками | Снимок пациента/источника, DASS/КР/листок и объяснение врача. Нет проверки всех клинических выводов/свободного текста; B04. |
| T05.2 Методы/шкалы как основания | Снимок пациента/источника, DASS/КР/листок и объяснение врача. Нет проверки всех клинических выводов/свободного текста; B04. |
| T05.3 Связь с конкретными данными пациента | Снимок пациента/источника, DASS/КР/листок и объяснение врача. Нет проверки всех клинических выводов/свободного текста; B04. |

## T06 — Устойчивость к нагрузкам: одновременные пользователи и изменение отклика

**Состояние:** partial. S15: 10/50/100 виртуальных сессий, короткий всплеск, исходные запросы.

**Остаток:** Не 100 людей/длительная нагрузка/конкурентный HTTP-вход; NAT-лимит B16.

**Сохранённые доказательства:** [evidence/S15/acceptance.md](../../evidence/S15/acceptance.md); [evidence/S15/performance.json](../../evidence/S15/performance.json); [evidence/S15/load.json](../../evidence/S15/load.json); [evidence/S15/performance.md](../../evidence/S15/performance.md); [evidence/S15/recovery.json](../../evidence/S15/recovery.json); [evidence/S15/recovery.md](../../evidence/S15/recovery.md); [docs/operations/recovery.md](../../docs/operations/recovery.md); [apps/tests/test_backup.py](../../apps/tests/test_backup.py).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| T06.1 Одновременные пользователи | S15: 10/50/100 виртуальных сессий, короткий всплеск, исходные запросы. Не 100 людей/длительная нагрузка/конкурентный HTTP-вход; NAT-лимит B16. |
| T06.2 Отклик под нагрузкой | S15: 10/50/100 виртуальных сессий, короткий всплеск, исходные запросы. Не 100 людей/длительная нагрузка/конкурентный HTTP-вход; NAT-лимит B16. |

## T07 — Отказоустойчивость и восстановление: копии объем возможной потери время восстановления сохранность критических отправленных и полученных данных во время сбоя

**Состояние:** partial. S15 recovery.json: kill/TCP/hot journal/restore, все77таблиц.

**Остаток:** Потеря одной поздней критической записи зафиксирована; нет независимой копии/авторасписания/физического power-off.

**Сохранённые доказательства:** [evidence/S09/resume-2026-10-19/plan-change.md](../../evidence/S09/resume-2026-10-19/plan-change.md); [evidence/S10A/acceptance.md](../../evidence/S10A/acceptance.md); [evidence/S10A/final-checks.log](../../evidence/S10A/final-checks.log); [evidence/S10A/delivery.json](../../evidence/S10A/delivery.json); [evidence/S10A/browser-check.json](../../evidence/S10A/browser-check.json); [evidence/S10A/upgrade.json](../../evidence/S10A/upgrade.json); [apps/tests/test_notifications.py](../../apps/tests/test_notifications.py); [docs/architecture/routine-notifications.md](../../docs/architecture/routine-notifications.md); [evidence/S10/acceptance.md](../../evidence/S10/acceptance.md); [evidence/S10/final-checks.log](../../evidence/S10/final-checks.log); [evidence/S10/runtime.json](../../evidence/S10/runtime.json); [evidence/S10/upgrade.json](../../evidence/S10/upgrade.json); [evidence/S10/reserve.json](../../evidence/S10/reserve.json); [evidence/S10/browser-check.json](../../evidence/S10/browser-check.json); [evidence/S10/offscreen-check.json](../../evidence/S10/offscreen-check.json); [evidence/S10/docker-tests.log](../../evidence/S10/docker-tests.log); [apps/tests/test_critical_delivery.py](../../apps/tests/test_critical_delivery.py); [docs/architecture/critical-delivery.md](../../docs/architecture/critical-delivery.md); [docs/clinical/critical-protocol-v2.md](../../docs/clinical/critical-protocol-v2.md); [evidence/S10/final-browser-measurement.json](../../evidence/S10/final-browser-measurement.json); [evidence/S15/acceptance.md](../../evidence/S15/acceptance.md); [evidence/S15/performance.json](../../evidence/S15/performance.json); [evidence/S15/load.json](../../evidence/S15/load.json); [evidence/S15/performance.md](../../evidence/S15/performance.md); [evidence/S15/recovery.json](../../evidence/S15/recovery.json); [evidence/S15/recovery.md](../../evidence/S15/recovery.md); [docs/operations/recovery.md](../../docs/operations/recovery.md); [apps/tests/test_backup.py](../../apps/tests/test_backup.py).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| T07.1 Резервная копия | S15 recovery.json: kill/TCP/hot journal/restore, все77таблиц. Потеря одной поздней критической записи зафиксирована; нет независимой копии/авторасписания/физического power-off. |
| T07.2 Объём возможной потери | S15 recovery.json: kill/TCP/hot journal/restore, все77таблиц. Потеря одной поздней критической записи зафиксирована; нет независимой копии/авторасписания/физического power-off. |
| T07.3 Время восстановления | S15 recovery.json: kill/TCP/hot journal/restore, все77таблиц. Потеря одной поздней критической записи зафиксирована; нет независимой копии/авторасписания/физического power-off. |
| T07.4 Критические данные отправленные при сбое | S15 recovery.json: kill/TCP/hot journal/restore, все77таблиц. Потеря одной поздней критической записи зафиксирована; нет независимой копии/авторасписания/физического power-off. |
| T07.5 Критические данные полученные при сбое | S15 recovery.json: kill/TCP/hot journal/restore, все77таблиц. Потеря одной поздней критической записи зафиксирована; нет независимой копии/авторасписания/физического power-off. |

## T08 — Кроссплатформенность

**Состояние:** partial. S13 platforms.md: IAB Chromium155/Safari26.6.2, macOS/Linux.

**Остаток:** Физические мобильные браузеры/Windows/screenreader/точные200% не проверены.

**Сохранённые доказательства:** [evidence/S13/acceptance.md](../../evidence/S13/acceptance.md); [evidence/S13/platforms.md](../../evidence/S13/platforms.md); [evidence/S13/browser-check.json](../../evidence/S13/browser-check.json); [docs/architecture/interface-search-extensions.md](../../docs/architecture/interface-search-extensions.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| T08.1 Кроссплатформенность | S13 platforms.md: IAB Chromium155/Safari26.6.2, macOS/Linux. Физические мобильные браузеры/Windows/screenreader/точные200% не проверены. |

## T09 — Масштабируемость архитектуры

**Состояние:** partial. S04 архитектура; S13 поиск/модель; S15 рост отклика.

**Остаток:** SQLite один писатель/одна машина; горизонтальное масштабирование не доказано.

**Сохранённые доказательства:** [docs/architecture/system.md](../../docs/architecture/system.md); [docs/architecture/data-model.md](../../docs/architecture/data-model.md); [docs/architecture/decisions.md](../../docs/architecture/decisions.md); [docs/RUNBOOK.md](../../docs/RUNBOOK.md); [evidence/S04/acceptance.md](../../evidence/S04/acceptance.md); [evidence/S04/checks.log](../../evidence/S04/checks.log); [evidence/S04/docker-check.json](../../evidence/S04/docker-check.json); [evidence/S15/acceptance.md](../../evidence/S15/acceptance.md); [evidence/S15/performance.json](../../evidence/S15/performance.json); [evidence/S15/load.json](../../evidence/S15/load.json); [evidence/S15/performance.md](../../evidence/S15/performance.md); [evidence/S15/recovery.json](../../evidence/S15/recovery.json); [evidence/S15/recovery.md](../../evidence/S15/recovery.md); [docs/operations/recovery.md](../../docs/operations/recovery.md); [apps/tests/test_backup.py](../../apps/tests/test_backup.py).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| T09.1 Масштабируемость архитектуры | S04 архитектура; S13 поиск/модель; S15 рост отклика. SQLite один писатель/одна машина; горизонтальное масштабирование не доказано. |

## T10 — Гибкость архитектуры: добавление и обновление шкал препаратов правил алертинга новых функций без изменения ядра

**Состояние:** partial. S13 extensions.json/upgrade.json: версии шкалы/карточки/правила/функция.

**Остаток:** Неактивные тестовые расширения, не допуск произвольного медицинского алгоритма.

**Сохранённые доказательства:** [docs/architecture/system.md](../../docs/architecture/system.md); [docs/architecture/data-model.md](../../docs/architecture/data-model.md); [docs/architecture/decisions.md](../../docs/architecture/decisions.md); [docs/RUNBOOK.md](../../docs/RUNBOOK.md); [evidence/S04/acceptance.md](../../evidence/S04/acceptance.md); [evidence/S04/checks.log](../../evidence/S04/checks.log); [evidence/S04/docker-check.json](../../evidence/S04/docker-check.json); [evidence/S07/acceptance.md](../../evidence/S07/acceptance.md); [evidence/S07/review/scale-research.md](../../evidence/S07/review/scale-research.md); [evidence/S07/review/final-checks.log](../../evidence/S07/review/final-checks.log); [apps/tests/test_assessments.py](../../apps/tests/test_assessments.py); [docs/architecture/assessments.md](../../docs/architecture/assessments.md); [evidence/S13/acceptance.md](../../evidence/S13/acceptance.md); [evidence/S13/platforms.md](../../evidence/S13/platforms.md); [evidence/S13/browser-check.json](../../evidence/S13/browser-check.json); [docs/architecture/interface-search-extensions.md](../../docs/architecture/interface-search-extensions.md); [evidence/S13/extensibility.md](../../evidence/S13/extensibility.md); [evidence/S13/extensions.json](../../evidence/S13/extensions.json); [evidence/S13/upgrade.json](../../evidence/S13/upgrade.json); [evidence/S13/search.json](../../evidence/S13/search.json); [apps/tests/test_s13.py](../../apps/tests/test_s13.py).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| T10.1 Новые/обновлённые шкалы | S13 extensions.json/upgrade.json: версии шкалы/карточки/правила/функция. Неактивные тестовые расширения, не допуск произвольного медицинского алгоритма. |
| T10.2 Новые/обновлённые препараты | S13 extensions.json/upgrade.json: версии шкалы/карточки/правила/функция. Неактивные тестовые расширения, не допуск произвольного медицинского алгоритма. |
| T10.3 Новые правила алертинга | S13 extensions.json/upgrade.json: версии шкалы/карточки/правила/функция. Неактивные тестовые расширения, не допуск произвольного медицинского алгоритма. |
| T10.4 Новые функции | S13 extensions.json/upgrade.json: версии шкалы/карточки/правила/функция. Неактивные тестовые расширения, не допуск произвольного медицинского алгоритма. |
| T10.5 Без изменения ядра | S13 extensions.json/upgrade.json: версии шкалы/карточки/правила/функция. Неактивные тестовые расширения, не допуск произвольного медицинского алгоритма. |

## T11 — Гибкость работы с данными: структура базы скорость доступа удобство поиска фильтрации выборок и расширение модели

**Состояние:** partial. S13 search.json/upgrade.json и S15 performance.json.

**Остаток:** Проверены ограниченные синтетические объёмы; limit100/рост истории.

**Сохранённые доказательства:** [docs/architecture/system.md](../../docs/architecture/system.md); [docs/architecture/data-model.md](../../docs/architecture/data-model.md); [docs/architecture/decisions.md](../../docs/architecture/decisions.md); [docs/RUNBOOK.md](../../docs/RUNBOOK.md); [evidence/S04/acceptance.md](../../evidence/S04/acceptance.md); [evidence/S04/checks.log](../../evidence/S04/checks.log); [evidence/S04/docker-check.json](../../evidence/S04/docker-check.json); [evidence/S13/acceptance.md](../../evidence/S13/acceptance.md); [evidence/S13/platforms.md](../../evidence/S13/platforms.md); [evidence/S13/browser-check.json](../../evidence/S13/browser-check.json); [docs/architecture/interface-search-extensions.md](../../docs/architecture/interface-search-extensions.md); [evidence/S13/extensibility.md](../../evidence/S13/extensibility.md); [evidence/S13/extensions.json](../../evidence/S13/extensions.json); [evidence/S13/upgrade.json](../../evidence/S13/upgrade.json); [evidence/S13/search.json](../../evidence/S13/search.json); [apps/tests/test_s13.py](../../apps/tests/test_s13.py); [evidence/S15/acceptance.md](../../evidence/S15/acceptance.md); [evidence/S15/performance.json](../../evidence/S15/performance.json); [evidence/S15/load.json](../../evidence/S15/load.json); [evidence/S15/performance.md](../../evidence/S15/performance.md); [evidence/S15/recovery.json](../../evidence/S15/recovery.json); [evidence/S15/recovery.md](../../evidence/S15/recovery.md); [docs/operations/recovery.md](../../docs/operations/recovery.md); [apps/tests/test_backup.py](../../apps/tests/test_backup.py).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| T11.1 Структура базы | S13 search.json/upgrade.json и S15 performance.json. Проверены ограниченные синтетические объёмы; limit100/рост истории. |
| T11.2 Скорость доступа | S13 search.json/upgrade.json и S15 performance.json. Проверены ограниченные синтетические объёмы; limit100/рост истории. |
| T11.3 Поиск | S13 search.json/upgrade.json и S15 performance.json. Проверены ограниченные синтетические объёмы; limit100/рост истории. |
| T11.4 Фильтры | S13 search.json/upgrade.json и S15 performance.json. Проверены ограниченные синтетические объёмы; limit100/рост истории. |
| T11.5 Выборки | S13 search.json/upgrade.json и S15 performance.json. Проверены ограниченные синтетические объёмы; limit100/рост истории. |
| T11.6 Расширение модели | S13 search.json/upgrade.json и S15 performance.json. Проверены ограниченные синтетические объёмы; limit100/рост истории. |

## T12 — Полнота данных: модель покрывает сущности необходимые для задач инструмента

**Состояние:** partial. data-model.md, миграции, исходные данные/источники/действия/журналы.

**Остаток:** Покрытие реальных клинических процессов не подтверждено экспертно.

**Сохранённые доказательства:** [docs/architecture/system.md](../../docs/architecture/system.md); [docs/architecture/data-model.md](../../docs/architecture/data-model.md); [docs/architecture/decisions.md](../../docs/architecture/decisions.md); [docs/RUNBOOK.md](../../docs/RUNBOOK.md); [evidence/S04/acceptance.md](../../evidence/S04/acceptance.md); [evidence/S04/checks.log](../../evidence/S04/checks.log); [evidence/S04/docker-check.json](../../evidence/S04/docker-check.json); [docs/architecture/records.md](../../docs/architecture/records.md); [apps/tests/test_records.py](../../apps/tests/test_records.py); [evidence/S06/acceptance.md](../../evidence/S06/acceptance.md); [evidence/S06/final-checks.log](../../evidence/S06/final-checks.log); [evidence/S06/docker-restart.log](../../evidence/S06/docker-restart.log); [evidence/S06/doctor-history.png](../../evidence/S06/doctor-history.png); [evidence/S07/acceptance.md](../../evidence/S07/acceptance.md); [evidence/S07/review/scale-research.md](../../evidence/S07/review/scale-research.md); [evidence/S07/review/final-checks.log](../../evidence/S07/review/final-checks.log); [apps/tests/test_assessments.py](../../apps/tests/test_assessments.py); [docs/architecture/assessments.md](../../docs/architecture/assessments.md); [docs/architecture/communication.md](../../docs/architecture/communication.md); [apps/tests/test_communication.py](../../apps/tests/test_communication.py); [evidence/S11/acceptance.md](../../evidence/S11/acceptance.md); [evidence/S11/final-checks.log](../../evidence/S11/final-checks.log); [evidence/S11/runtime.json](../../evidence/S11/runtime.json); [evidence/S11/upgrade.json](../../evidence/S11/upgrade.json); [evidence/S11/browser-check.json](../../evidence/S11/browser-check.json).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| T12.1 Полнота данных: модель покрывает сущности необходимые для задач инструмента | data-model.md, миграции, исходные данные/источники/действия/журналы. Покрытие реальных клинических процессов не подтверждено экспертно. |

## T13 — Защищенность данных

**Состояние:** partial. S14 security.md/inventory, test_access/security, backup-тесты.

**Остаток:** B16: нет внешнего TLS/proxy/миграции scrypt/полного аудита/защищённой независимой копии.

**Сохранённые доказательства:** [docs/architecture/access.md](../../docs/architecture/access.md); [apps/tests/test_access.py](../../apps/tests/test_access.py); [evidence/S05/acceptance.md](../../evidence/S05/acceptance.md); [evidence/S05/final-checks.log](../../evidence/S05/final-checks.log); [evidence/S05/docker-final-restart.log](../../evidence/S05/docker-final-restart.log); [evidence/S07/acceptance.md](../../evidence/S07/acceptance.md); [evidence/S07/review/scale-research.md](../../evidence/S07/review/scale-research.md); [evidence/S07/review/final-checks.log](../../evidence/S07/review/final-checks.log); [apps/tests/test_assessments.py](../../apps/tests/test_assessments.py); [docs/architecture/assessments.md](../../docs/architecture/assessments.md); [evidence/S08B/acceptance.md](../../evidence/S08B/acceptance.md); [evidence/S08B/final-checks.log](../../evidence/S08B/final-checks.log); [evidence/S08B/upgrade.json](../../evidence/S08B/upgrade.json); [apps/tests/test_ages.py](../../apps/tests/test_ages.py); [docs/architecture/age-reviews.md](../../docs/architecture/age-reviews.md); [evidence/S14/acceptance.md](../../evidence/S14/acceptance.md); [evidence/S14/security.md](../../evidence/S14/security.md); [evidence/S14/reliability.md](../../evidence/S14/reliability.md); [evidence/S14/final-checks-r3.log](../../evidence/S14/final-checks-r3.log); [evidence/S14/docker-tests-final.log](../../evidence/S14/docker-tests-final.log); [apps/tests/test_security.py](../../apps/tests/test_security.py); [docs/compliance/data-map.md](../../docs/compliance/data-map.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| T13.1 Защищенность данных | S14 security.md/inventory, test_access/security, backup-тесты. B16: нет внешнего TLS/proxy/миграции scrypt/полного аудита/защищённой независимой копии. |

## C01 — Рабочий язык чемпионата — русский.

**Состояние:** partial. Сохранённое положение/contract/questions; безопасный статус без имитации события.

**Остаток:** Русский интерфейс/документы есть; язык фактической защиты ещё не проверен.

**Сохранённые доказательства:** [docs/contest/contract.md](../../docs/contest/contract.md); [evidence/S01/acceptance.md](../../evidence/S01/acceptance.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| C01.1 Рабочий язык чемпионата — русский. | Сохранённое положение/contract/questions; безопасный статус без имитации события. Русский интерфейс/документы есть; язык фактической защиты ещё не проверен. |

## C02 — Допуск: дееспособность, гражданство РФ или законное нахождение иностранца в РФ; возраст 18–35 лет на начало приёма заявок; установленный медицинский или технический профиль. Медицинский профиль — от 4 курса, ординатор, аспирант или врач.

**Состояние:** not_verified. Сохранённое положение/contract/questions; безопасный статус без имитации события.

**Остаток:** Нет индивидуального подтверждения допуска/профиля каждого из пяти участников.

**Сохранённые доказательства:** [docs/contest/contract.md](../../docs/contest/contract.md); [evidence/S01/acceptance.md](../../evidence/S01/acceptance.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| C02.1 Допуск: дееспособность, гражданство РФ или законное нахождение иностранца в РФ; возраст 18–35 лет на начало приёма заявок; установленный медицинский или технический профиль. Медицинский профиль — от 4 курса, ординатор, аспирант или врач. | Сохранённое положение/contract/questions; безопасный статус без имитации события. Нет индивидуального подтверждения допуска/профиля каждого из пяти участников. |

## C03 — Личная заявка, отбор, приглашение в чат и регистрация именно команды 15 октября — разные стадии. Проверить уже состоявшийся допуск, порядок отбора и командную регистрацию; не подавать заявку заново.

**Состояние:** partial. Сохранённое положение/contract/questions; безопасный статус без имитации события.

**Остаток:** Регистрация со слов капитана; приглашения/реестр/все стадии отдельно не просмотрены.

**Сохранённые доказательства:** [docs/contest/contract.md](../../docs/contest/contract.md); [evidence/S01/acceptance.md](../../evidence/S01/acceptance.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| C03.1 Заявка через онлайн-форму и уведомление по email | Сохранённое положение/contract/questions; безопасный статус без имитации события. Регистрация со слов капитана; приглашения/реестр/все стадии отдельно не просмотрены. |
| C03.2 Отбор по соответствию требованиям, достоверности, профилю, мотивации/опыту и потенциалу междисциплинарной команды | Сохранённое положение/contract/questions; безопасный статус без имитации события. Регистрация со слов капитана; приглашения/реестр/все стадии отдельно не просмотрены. |
| C03.3 Пять критериев отбора оцениваются 0–5, сумма; проходной балл/число мест до конца отбора не раскрываются | Сохранённое положение/contract/questions; безопасный статус без имитации события. Регистрация со слов капитана; приглашения/реестр/все стадии отдельно не просмотрены. |
| C03.4 Отбор окончателен по предусмотренным правилам; возможен отказ при несоответствии/ложных сведениях | Сохранённое положение/contract/questions; безопасный статус без имитации события. Регистрация со слов капитана; приглашения/реестр/все стадии отдельно не просмотрены. |
| C03.5 Приглашение в чат до 14 октября; ошибочная ссылка срока в п.3.9 не подменяет подтверждение | Сохранённое положение/contract/questions; безопасный статус без имитации события. Регистрация со слов капитана; приглашения/реестр/все стадии отдельно не просмотрены. |
| C03.6 Регистрация команды 15 октября одним очным представителем; онлайн лишь по усмотрению организатора при объективных причинах | Сохранённое положение/contract/questions; безопасный статус без имитации события. Регистрация со слов капитана; приглашения/реестр/все стадии отдельно не просмотрены. |
| C03.7 Команда считается зарегистрированной после внесения в реестр; статус проверить ретроспективно | Сохранённое положение/contract/questions; безопасный статус без имитации события. Регистрация со слов капитана; приглашения/реестр/все стадии отдельно не просмотрены. |
| C03.8 Участник без команды может быть исключён или с согласия присоединён к уже существующей команде | Сохранённое положение/contract/questions; безопасный статус без имитации события. Регистрация со слов капитана; приглашения/реестр/все стадии отдельно не просмотрены. |

## C04 — Сведения должны быть полными и достоверными. Дополнительно запрошенные сведения предоставить за три рабочих дня. Недостоверные сведения и незаконные действия могут привести к отстранению.

**Состояние:** not_verified. Сохранённое положение/contract/questions; безопасный статус без имитации события.

**Остаток:** Полнота сведений и наличие запросов с трёхдневным сроком неизвестны: почта/чат недоступны.

**Сохранённые доказательства:** [docs/contest/contract.md](../../docs/contest/contract.md); [evidence/S01/acceptance.md](../../evidence/S01/acceptance.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| C04.1 Сведения должны быть полными и достоверными. Дополнительно запрошенные сведения предоставить за три рабочих дня. Недостоверные сведения и незаконные действия могут привести к отстранению. | Сохранённое положение/contract/questions; безопасный статус без имитации события. Полнота сведений и наличие запросов с трёхдневным сроком неизвестны: почта/чат недоступны. |

## C05 — Команда сохраняет состав 2–5 человек, медицинский и технический профили, не более двух технических специалистов на протяжении конкурса.

**Состояние:** partial. Сохранённое положение/contract/questions; безопасный статус без имитации события.

**Остаток:** Пять человек со слов капитана; оба профиля/максимум двух технических/постоянство состава не подтверждены.

**Сохранённые доказательства:** [docs/contest/contract.md](../../docs/contest/contract.md); [evidence/S01/acceptance.md](../../evidence/S01/acceptance.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| C05.1 Команда сохраняет состав 2–5 человек, медицинский и технический профили, не более двух технических специалистов на протяжении конкурса. | Сохранённое положение/contract/questions; безопасный статус без имитации события. Пять человек со слов капитана; оба профиля/максимум двух технических/постоянство состава не подтверждены. |

## C06 — Команда действует под единым названием, решает один кейс; капитан представляет её интересы.

**Состояние:** partial. Сохранённое положение/contract/questions; безопасный статус без имитации события.

**Остаток:** Капитан и один кейс известны; зарегистрированное единое название не сверено.

**Сохранённые доказательства:** [docs/contest/contract.md](../../docs/contest/contract.md); [evidence/S01/acceptance.md](../../evidence/S01/acceptance.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| C06.1 Команда действует под единым названием, решает один кейс; капитан представляет её интересы. | Сохранённое положение/contract/questions; безопасный статус без имитации события. Капитан и один кейс известны; зарегистрированное единое название не сверено. |

## C07 — Одно лицо не может состоять в двух командах.

**Состояние:** not_verified. Сохранённое положение/contract/questions; безопасный статус без имитации события.

**Остаток:** Отсутствие двойного членства не проверено.

**Сохранённые доказательства:** [docs/contest/contract.md](../../docs/contest/contract.md); [evidence/S01/acceptance.md](../../evidence/S01/acceptance.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| C07.1 Одно лицо не может состоять в двух командах. | Сохранённое положение/contract/questions; безопасный статус без имитации события. Отсутствие двойного членства не проверено. |

## C08 — Состав зарегистрированной команды меняется только по согласованию с организатором.

**Состояние:** not_verified. Сохранённое положение/contract/questions; безопасный статус без имитации события.

**Остаток:** Согласование изменений состава и факт отсутствия изменений не проверены.

**Сохранённые доказательства:** [docs/contest/contract.md](../../docs/contest/contract.md); [evidence/S01/acceptance.md](../../evidence/S01/acceptance.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| C08.1 Состав зарегистрированной команды меняется только по согласованию с организатором. | Сохранённое положение/contract/questions; безопасный статус без имитации события. Согласование изменений состава и факт отсутствия изменений не проверены. |

## C09 — О выходе или невозможности дальнейшего участия сообщить не позднее одного рабочего дня. Сохраняются минимум два человека и оба профиля, иначе организатор принимает решение за два рабочих дня. Добровольный выход лишает права на сертификат и призы; существенное влияние отстранённого участника может затронуть результаты.

**Состояние:** not_verified. Сохранённое положение/contract/questions; безопасный статус без имитации события.

**Остаток:** Выход/невозможность участия и своевременность уведомлений не проверены; агент не отправлял сообщений.

**Сохранённые доказательства:** [docs/contest/contract.md](../../docs/contest/contract.md); [evidence/S01/acceptance.md](../../evidence/S01/acceptance.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| C09.1 О выходе или невозможности дальнейшего участия сообщить не позднее одного рабочего дня. Сохраняются минимум два человека и оба профиля, иначе организатор принимает решение за два рабочих дня. Добровольный выход лишает права на сертификат и призы; существенное влияние отстранённого участника может затронуть результаты. | Сохранённое положение/contract/questions; безопасный статус без имитации события. Выход/невозможность участия и своевременность уведомлений не проверены; агент не отправлял сообщений. |

## C10 — Трекер и модератор предусмотрены не позднее 16 октября. Найти контакты и порядок получения экспертной поддержки.

**Состояние:** partial. Сохранённое положение/contract/questions; безопасный статус без имитации события.

**Остаток:** Трекер со слов капитана; контакт/модератор/фактическая поддержка не проверены.

**Сохранённые доказательства:** [docs/contest/contract.md](../../docs/contest/contract.md); [evidence/S01/acceptance.md](../../evidence/S01/acceptance.md); [docs/clinical/sources.md](../../docs/clinical/sources.md); [evidence/S02/requirements-review.md](../../evidence/S02/requirements-review.md); [evidence/S02/acceptance.md](../../evidence/S02/acceptance.md); [evidence/S02/external-check.md](../../evidence/S02/external-check.md); [evidence/S02/received-review.md](../../evidence/S02/received-review.md); [evidence/S02/received-research.md](../../evidence/S02/received-research.md); [docs/clinical/validation-request.md](../../docs/clinical/validation-request.md); [evidence/S02/acceptance-review.md](../../evidence/S02/acceptance-review.md); [evidence/S16/validation-summary.md](../../evidence/S16/validation-summary.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| C10.1 Трекер и модератор предусмотрены не позднее 16 октября. Найти контакты и порядок получения экспертной поддержки. | Сохранённое положение/contract/questions; безопасный статус без имитации события. Трекер со слов капитана; контакт/модератор/фактическая поддержка не проверены. |

## C11 — Условия и метрики должны были объявить 15 октября и опубликовать в чате не позднее 16 октября. Вводные данные и ресурсы обещаны, но их состав публично не определён.

**Состояние:** not_verified. Сохранённое положение/contract/questions; безопасный статус без имитации события.

**Остаток:** Закрытые метрики/ресурсы/объявления 15–16 октября не прочитаны.

**Сохранённые доказательства:** [docs/contest/contract.md](../../docs/contest/contract.md); [evidence/S01/acceptance.md](../../evidence/S01/acceptance.md); [evidence/S07/review/contest-research.md](../../evidence/S07/review/contest-research.md); [docs/product/contest-strategy.md](../../docs/product/contest-strategy.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| C11.1 Условия и метрики должны были объявить 15 октября и опубликовать в чате не позднее 16 октября. Вводные данные и ресурсы обещаны, но их состав публично не определён. | Сохранённое положение/contract/questions; безопасный статус без имитации события. Закрытые метрики/ресурсы/объявления 15–16 октября не прочитаны. |

## C12 — Участник самостоятельно отслеживает чат и официальные ресурсы; опубликованное сообщение считается полученным. Недоступность чата фиксируется честно, проверка не имитируется.

**Состояние:** partial. Сохранённое положение/contract/questions; безопасный статус без имитации события.

**Остаток:** Публичная проверка отделена от недоступного чата; отсутствие новых требований неизвестно.

**Сохранённые доказательства:** [docs/contest/contract.md](../../docs/contest/contract.md); [evidence/S01/acceptance.md](../../evidence/S01/acceptance.md); [evidence/S07/review/contest-research.md](../../evidence/S07/review/contest-research.md); [docs/product/contest-strategy.md](../../docs/product/contest-strategy.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| C12.1 Участник самостоятельно отслеживает чат и официальные ресурсы; опубликованное сообщение считается полученным. Недоступность чата фиксируется честно, проверка не имитируется. | Сохранённое положение/contract/questions; безопасный статус без имитации события. Публичная проверка отделена от недоступного чата; отсутствие новых требований неизвестно. |

## C13 — Вопросы по кейсу задаются только по процедуре чата. Опубликованные ответы обязательны для команд и дополняют метрики, не противореча положению.

**Состояние:** not_verified. Сохранённое положение/contract/questions; безопасный статус без имитации события.

**Остаток:** Ответы и процедура закрытого чата не просмотрены; сообщений людям не было.

**Сохранённые доказательства:** [docs/contest/contract.md](../../docs/contest/contract.md); [evidence/S01/acceptance.md](../../evidence/S01/acceptance.md); [evidence/S07/review/contest-research.md](../../evidence/S07/review/contest-research.md); [docs/product/contest-strategy.md](../../docs/product/contest-strategy.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| C13.1 Вопросы по кейсу задаются только по процедуре чата. Опубликованные ответы обязательны для команд и дополняют метрики, не противореча положению. | Сохранённое положение/contract/questions; безопасный статус без имитации события. Ответы и процедура закрытого чата не просмотрены; сообщений людям не было. |

## C14 — Метрики оцениваются 1–10, итог суммируется; веса применяются при наличии. Исключительное изменение метрик сообщается минимум за три рабочих дня до предзащиты и не ухудшает положение начавших работу. При равенстве — приоритетная метрика, иначе председатель жюри.

**Состояние:** not_verified. Сохранённое положение/contract/questions; безопасный статус без имитации события.

**Остаток:** Веса/приоритет/изменения метрик/порядок фактической оценки не подтверждены закрытым источником.

**Сохранённые доказательства:** [docs/contest/contract.md](../../docs/contest/contract.md); [evidence/S01/acceptance.md](../../evidence/S01/acceptance.md); [evidence/S07/review/contest-research.md](../../evidence/S07/review/contest-research.md); [docs/product/contest-strategy.md](../../docs/product/contest-strategy.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| C14.1 Метрики оцениваются 1–10, итог суммируется; веса применяются при наличии. Исключительное изменение метрик сообщается минимум за три рабочих дня до предзащиты и не ухудшает положение начавших работу. При равенстве — приоритетная метрика, иначе председатель жюри. | Сохранённое положение/contract/questions; безопасный статус без имитации события. Веса/приоритет/изменения метрик/порядок фактической оценки не подтверждены закрытым источником. |

## C15 — Жюри публикуется минимум за три рабочих дня до предзащиты. Конфликт интересов требует самоотвода; замены уведомляются. Запрещено влиять на жюри, экспертов, трекеров и модераторов.

**Состояние:** not_verified. Сохранённое положение/contract/questions; безопасный статус без имитации события.

**Остаток:** Состав жюри/уведомления/конфликты интересов не проверены; влияние не предпринималось.

**Сохранённые доказательства:** [docs/contest/contract.md](../../docs/contest/contract.md); [evidence/S01/acceptance.md](../../evidence/S01/acceptance.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| C15.1 Жюри публикуется минимум за три рабочих дня до предзащиты. Конфликт интересов требует самоотвода; замены уведомляются. Запрещено влиять на жюри, экспертов, трекеров и модераторов. | Сохранённое положение/contract/questions; безопасный статус без имитации события. Состав жюри/уведомления/конфликты интересов не проверены; влияние не предпринималось. |

## C16 — Предзащита 28 октября проходит онлайн; допущены команды, зарегистрированные 15 октября. Форма оценки определяется организатором.

**Состояние:** not_verified. Сохранённое положение/contract/questions; безопасный статус без имитации события.

**Остаток:** Предзащита28.10 ещё не состоялась; форма/точное время/фактический допуск не установлены.

**Доказательства выполнения отсутствуют.** Свод требования не является доказательством события.

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| C16.1 Предзащита 28 октября проходит онлайн; допущены команды, зарегистрированные 15 октября. Форма оценки определяется организатором. | Сохранённое положение/contract/questions; безопасный статус без имитации события. Предзащита28.10 ещё не состоялась; форма/точное время/фактический допуск не установлены. |

## C17 — В финал проходят три лучшие команды по кейсу. Демо-день 30 октября гибридный и публичный; проход подтверждается фактическим результатом.

**Состояние:** not_verified. Сохранённое положение/contract/questions; безопасный статус без имитации события.

**Остаток:** Результата прохода нет; финал30.10 ещё не состоялся.

**Доказательства выполнения отсутствуют.** Свод требования не является доказательством события.

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| C17.1 В финал проходят три лучшие команды по кейсу. Демо-день 30 октября гибридный и публичный; проход подтверждается фактическим результатом. | Сохранённое положение/contract/questions; безопасный статус без имитации события. Результата прохода нет; финал30.10 ещё не состоялся. |

## C18 — Постер предусмотрен для каждой/всех команд; круг участников неоднозначен и требует уточнения. Подготовить постер заранее. Один человек — один балл; приз партнёра отдельный и не входит в главный фонд.

**Состояние:** not_verified. Сохранённое положение/contract/questions; безопасный статус без имитации события.

**Остаток:** Постер ещё не создан (S18); формат/круг обязанных команд/порядок голосования не уточнены.

**Доказательства выполнения отсутствуют.** Свод требования не является доказательством события.

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| C18.1 Постер предусмотрен для каждой/всех команд; круг участников неоднозначен и требует уточнения. Подготовить постер заранее. Один человек — один балл; приз партнёра отдельный и не входит в главный фонд. | Сохранённое положение/contract/questions; безопасный статус без имитации события. Постер ещё не создан (S18); формат/круг обязанных команд/порядок голосования не уточнены. |

## C19 — Сроки считаются по Москве. Электронные действия — до 23:59 последнего дня применимого срока. Нерабочий день переносится, если не установлено иное. Это не задаёт время питча или специальный дедлайн загрузки.

**Состояние:** not_verified. Сохранённое положение/contract/questions; безопасный статус без имитации события.

**Остаток:** Московское время учтено; конкретный дедлайн загрузки/питча неизвестен.

**Сохранённые доказательства:** [docs/contest/contract.md](../../docs/contest/contract.md); [evidence/S01/acceptance.md](../../evidence/S01/acceptance.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| C19.1 Сроки считаются по Москве. Электронные действия — до 23:59 последнего дня применимого срока. Нерабочий день переносится, если не установлено иное. Это не задаёт время питча или специальный дедлайн загрузки. | Сохранённое положение/contract/questions; безопасный статус без имитации события. Московское время учтено; конкретный дедлайн загрузки/питча неизвестен. |

## C20 — Точные место, время и порядок очных этапов сообщаются минимум за три рабочих дня; изменения — минимум за один рабочий день, кроме форс-мажора. Индивидуальное право удалённой финальной защиты не установлено.

**Состояние:** not_verified. Сохранённое положение/contract/questions; безопасный статус без имитации события.

**Остаток:** Точное место/время/порядок финала и основание удалённого участия не установлены.

**Сохранённые доказательства:** [docs/contest/contract.md](../../docs/contest/contract.md); [evidence/S01/acceptance.md](../../evidence/S01/acceptance.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| C20.1 Точные место, время и порядок очных этапов сообщаются минимум за три рабочих дня; изменения — минимум за один рабочий день, кроме форс-мажора. Индивидуальное право удалённой финальной защиты не установлено. | Сохранённое положение/contract/questions; безопасный статус без имитации события. Точное место/время/порядок финала и основание удалённого участия не установлены. |

## C21 — Организатор может изменить сроки/программу/формат или отменить событие по предусмотренным основаниям. Уведомление — минимум за три рабочих дня, при форс-мажоре срочно. Изменения положения публикуются в чате; ухудшающие изменения не применяются к ранее возникшим отношениям. Компенсация расходов не предусмотрена.

**Состояние:** not_verified. Сохранённое положение/contract/questions; безопасный статус без имитации события.

**Остаток:** Закрытые уведомления об изменениях/отмене не прочитаны.

**Сохранённые доказательства:** [docs/contest/contract.md](../../docs/contest/contract.md); [evidence/S01/acceptance.md](../../evidence/S01/acceptance.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| C21.1 Организатор может изменить сроки/программу/формат или отменить событие по предусмотренным основаниям. Уведомление — минимум за три рабочих дня, при форс-мажоре срочно. Изменения положения публикуются в чате; ухудшающие изменения не применяются к ранее возникшим отношениям. Компенсация расходов не предусмотрена. | Сохранённое положение/contract/questions; безопасный статус без имитации события. Закрытые уведомления об изменениях/отмене не прочитаны. |

## C22 — Участие бесплатно. Проживание, питание, транспорт и другие расходы не предоставляются и не компенсируются.

**Состояние:** not_verified. Сохранённое положение/contract/questions; безопасный статус без имитации события.

**Остаток:** Расходы0₽/обязательства0₽; транспорт/печать ещё не оценены и не компенсируются автоматически.

**Сохранённые доказательства:** [docs/contest/contract.md](../../docs/contest/contract.md); [evidence/S01/acceptance.md](../../evidence/S01/acceptance.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| C22.1 Участие бесплатно. Проживание, питание, транспорт и другие расходы не предоставляются и не компенсируются. | Сохранённое положение/contract/questions; безопасный статус без имитации события. Расходы0₽/обязательства0₽; транспорт/печать ещё не оценены и не компенсируются автоматически. |

## C23 — Академическая честность: не выдавать чужие или приобретённые вне чемпионата решения за собственные; использовать чужую ИС только с разрешением. Возможна проверка заимствований, отстранение и аннулирование призов.

**Состояние:** partial. Сохранённое положение/contract/questions; безопасный статус без имитации события.

**Остаток:** Учтены Codex/заимствования/лицензии; реальный вклад и конкурсный допуск старого кода/ИИ не подтверждены.

**Сохранённые доказательства:** [docs/contest/contract.md](../../docs/contest/contract.md); [evidence/S01/acceptance.md](../../evidence/S01/acceptance.md); [evidence/S07/review/contest-research.md](../../evidence/S07/review/contest-research.md); [docs/product/contest-strategy.md](../../docs/product/contest-strategy.md); [evidence/S14/acceptance.md](../../evidence/S14/acceptance.md); [evidence/S14/security.md](../../evidence/S14/security.md); [evidence/S14/reliability.md](../../evidence/S14/reliability.md); [evidence/S14/final-checks-r3.log](../../evidence/S14/final-checks-r3.log); [evidence/S14/docker-tests-final.log](../../evidence/S14/docker-tests-final.log); [apps/tests/test_security.py](../../apps/tests/test_security.py); [docs/compliance/data-map.md](../../docs/compliance/data-map.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| C23.1 Академическая честность: не выдавать чужие или приобретённые вне чемпионата решения за собственные; использовать чужую ИС только с разрешением. Возможна проверка заимствований, отстранение и аннулирование призов. | Сохранённое положение/contract/questions; безопасный статус без имитации события. Учтены Codex/заимствования/лицензии; реальный вклад и конкурсный допуск старого кода/ИИ не подтверждены. |

## C24 — Материалы организаторов разрешены только для участия. Нельзя передавать доступ, использовать вне целей или воспроизводить без предусмотренного согласия.

**Состояние:** partial. Сохранённое положение/contract/questions; безопасный статус без имитации события.

**Остаток:** Материалы организатора внутренние; отдельного разрешения передачи/публикации нет.

**Сохранённые доказательства:** [docs/contest/contract.md](../../docs/contest/contract.md); [evidence/S01/acceptance.md](../../evidence/S01/acceptance.md); [evidence/S14/acceptance.md](../../evidence/S14/acceptance.md); [evidence/S14/security.md](../../evidence/S14/security.md); [evidence/S14/reliability.md](../../evidence/S14/reliability.md); [evidence/S14/final-checks-r3.log](../../evidence/S14/final-checks-r3.log); [evidence/S14/docker-tests-final.log](../../evidence/S14/docker-tests-final.log); [apps/tests/test_security.py](../../apps/tests/test_security.py); [docs/compliance/data-map.md](../../docs/compliance/data-map.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| C24.1 Материалы организаторов разрешены только для участия. Нельзя передавать доступ, использовать вне целей или воспроизводить без предусмотренного согласия. | Сохранённое положение/contract/questions; безопасный статус без имитации события. Материалы организатора внутренние; отдельного разрешения передачи/публикации нет. |

## C25 — Конфиденциальность охватывает обозначенные сведения, кейсы/метрики до публикации, пациентские и коммерческие данные, переданные материалы, обсуждения/оценки до объявления и другие сведения участия. Срок — пять лет после окончания, предусмотрены санкции.

**Состояние:** partial. Сохранённое положение/contract/questions; безопасный статус без имитации события.

**Остаток:** Сохранён режим ограниченного доступа; выполнение всего пятилетнего обязательства заранее не доказать.

**Сохранённые доказательства:** [docs/contest/contract.md](../../docs/contest/contract.md); [evidence/S01/acceptance.md](../../evidence/S01/acceptance.md); [evidence/S14/acceptance.md](../../evidence/S14/acceptance.md); [evidence/S14/security.md](../../evidence/S14/security.md); [evidence/S14/reliability.md](../../evidence/S14/reliability.md); [evidence/S14/final-checks-r3.log](../../evidence/S14/final-checks-r3.log); [evidence/S14/docker-tests-final.log](../../evidence/S14/docker-tests-final.log); [apps/tests/test_security.py](../../apps/tests/test_security.py); [docs/compliance/data-map.md](../../docs/compliance/data-map.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| C25.1 Конфиденциальность охватывает обозначенные сведения, кейсы/метрики до публикации, пациентские и коммерческие данные, переданные материалы, обсуждения/оценки до объявления и другие сведения участия. Срок — пять лет после окончания, предусмотрены санкции. | Сохранённое положение/contract/questions; безопасный статус без имитации события. Сохранён режим ограниченного доступа; выполнение всего пятилетнего обязательства заранее не доказать. |

## C26 — Публичный финал и право организатора на фото/видеосъёмку не являются общим разрешением участнику самостоятельно публиковать материалы.

**Состояние:** not_verified. Сохранённое положение/contract/questions; безопасный статус без имитации события.

**Остаток:** Финал/съёмка ещё не состоялись; разрешение самостоятельной публикации не выведено из публичности события.

**Доказательства выполнения отсутствуют.** Свод требования не является доказательством события.

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| C26.1 Публичный финал и право организатора на фото/видеосъёмку не являются общим разрешением участнику самостоятельно публиковать материалы. | Сохранённое положение/contract/questions; безопасный статус без имитации события. Финал/съёмка ещё не состоялись; разрешение самостоятельной публикации не выведено из публичности события. |

## C27 — До отчуждения права принадлежат авторам. Непобедивший финалист передаёт права только по отдельному договору, не автоматически.

**Состояние:** not_verified. Сохранённое положение/contract/questions; безопасный статус без имитации события.

**Остаток:** Индивидуальное авторство/обременения не удостоверены; договоры не подписаны.

**Сохранённые доказательства:** [docs/contest/contract.md](../../docs/contest/contract.md); [evidence/S01/acceptance.md](../../evidence/S01/acceptance.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| C27.1 До отчуждения права принадлежат авторам. Непобедивший финалист передаёт права только по отдельному договору, не автоматически. | Сохранённое положение/contract/questions; безопасный статус без имитации события. Индивидуальное авторство/обременения не удостоверены; договоры не подписаны. |

## C28 — Победитель безвозмездно передаёт полные исключительные права по всему миру бессрочно: код, алгоритмы, модели, дизайн, базы, презентации, документы и носители. Допускаются коммерческое использование, переработка, регистрация и лицензирование. Личные неимущественные права сохраняются.

**Состояние:** not_verified. Сохранённое положение/contract/questions; безопасный статус без имитации события.

**Остаток:** Согласие пользователя есть; полный объём прав всех авторов/сторонние исключения и договоры не оформлены.

**Сохранённые доказательства:** [docs/contest/contract.md](../../docs/contest/contract.md); [evidence/S01/acceptance.md](../../evidence/S01/acceptance.md); [evidence/S07/review/contest-research.md](../../evidence/S07/review/contest-research.md); [docs/product/contest-strategy.md](../../docs/product/contest-strategy.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| C28.1 Победитель безвозмездно передаёт полные исключительные права по всему миру бессрочно: код, алгоритмы, модели, дизайн, базы, презентации, документы и носители. Допускаются коммерческое использование, переработка, регистрация и лицензирование. Личные неимущественные права сохраняются. | Сохранённое положение/contract/questions; безопасный статус без имитации события. Согласие пользователя есть; полный объём прав всех авторов/сторонние исключения и договоры не оформлены. |

## C29 — Каждый член победившей команды подписывает отдельный договор; отказ одного лишает команду выплаты. Авторство и соавторство должны соответствовать реальному вкладу, а не одному формальному членству.

**Состояние:** partial. Сохранённое положение/contract/questions; безопасный статус без имитации события.

**Остаток:** Готовность команды со слов пользователя; реальный вклад каждого и пять договоров не проверены.

**Сохранённые доказательства:** [docs/contest/contract.md](../../docs/contest/contract.md); [evidence/S01/acceptance.md](../../evidence/S01/acceptance.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| C29.1 Каждый член победившей команды подписывает отдельный договор; отказ одного лишает команду выплаты. Авторство и соавторство должны соответствовать реальному вкладу, а не одному формальному членству. | Сохранённое положение/contract/questions; безопасный статус без имитации события. Готовность команды со слов пользователя; реальный вклад каждого и пять договоров не проверены. |

## C30 — Права переходят при подписании договора. Факт передачи носителей и документации оформляется актом; нужен отдельный перечень результатов. Канал передачи согласовывается.

**Состояние:** not_verified. Сохранённое положение/contract/questions; безопасный статус без имитации события.

**Остаток:** Подготовлен перечень кандидатов; канал/акт/фактическая передача отсутствуют.

**Доказательства выполнения отсутствуют.** Свод требования не является доказательством события.

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| C30.1 Права переходят при подписании договора. Факт передачи носителей и документации оформляется актом; нужен отдельный перечень результатов. Канал передачи согласовывается. | Сохранённое положение/contract/questions; безопасный статус без имитации события. Подготовлен перечень кандидатов; канал/акт/фактическая передача отсутствуют. |

## C31 — Гарантии: права не отчуждены, не заложены, не переданы по лицензиям и не оспорены; нет нарушений чужих прав, неуказанных заимствований, гостайны и ПД третьих лиц, кроме обезличенных данных, выданных организатором.

**Состояние:** partial. Сохранённое положение/contract/questions; безопасный статус без имитации события.

**Остаток:** Инвентаризация не удостоверяет все правовые гарантии; B06/B08, notices/source-offer проверить при фактическом комплекте.

**Сохранённые доказательства:** [docs/contest/contract.md](../../docs/contest/contract.md); [evidence/S01/acceptance.md](../../evidence/S01/acceptance.md); [evidence/S07/review/contest-research.md](../../evidence/S07/review/contest-research.md); [docs/product/contest-strategy.md](../../docs/product/contest-strategy.md); [evidence/S14/acceptance.md](../../evidence/S14/acceptance.md); [evidence/S14/security.md](../../evidence/S14/security.md); [evidence/S14/reliability.md](../../evidence/S14/reliability.md); [evidence/S14/final-checks-r3.log](../../evidence/S14/final-checks-r3.log); [evidence/S14/docker-tests-final.log](../../evidence/S14/docker-tests-final.log); [apps/tests/test_security.py](../../apps/tests/test_security.py); [docs/compliance/data-map.md](../../docs/compliance/data-map.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| C31.1 Гарантии: права не отчуждены, не заложены, не переданы по лицензиям и не оспорены; нет нарушений чужих прав, неуказанных заимствований, гостайны и ПД третьих лиц, кроме обезличенных данных, выданных организатором. | Сохранённое положение/contract/questions; безопасный статус без имитации события. Инвентаризация не удостоверяет все правовые гарантии; B06/B08, notices/source-offer проверить при фактическом комплекте. |

## C32 — Автор содействует урегулированию претензий и возмещает предусмотренные убытки, расходы и полученные выплаты при установленном нарушении. Одностороннее расторжение договора допускается лишь по закону; прочие изменения оформляются письменно.

**Состояние:** not_verified. Сохранённое положение/contract/questions; безопасный статус без имитации события.

**Остаток:** Правовые последствия зафиксированы, фактические договорные основания/претензии не проверены.

**Сохранённые доказательства:** [docs/contest/contract.md](../../docs/contest/contract.md); [evidence/S01/acceptance.md](../../evidence/S01/acceptance.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| C32.1 Автор содействует урегулированию претензий и возмещает предусмотренные убытки, расходы и полученные выплаты при установленном нарушении. Одностороннее расторжение договора допускается лишь по закону; прочие изменения оформляются письменно. | Сохранённое положение/contract/questions; безопасный статус без имитации события. Правовые последствия зафиксированы, фактические договорные основания/претензии не проверены. |

## C33 — Общего разрешения публичного репозитория и публикации после финала нет. Сохраняются режим материалов и конфиденциальность.

**Состояние:** partial. Сохранённое положение/contract/questions; безопасный статус без имитации события.

**Остаток:** Публичного remote/публикации не создано; общего разрешения публикации нет.

**Сохранённые доказательства:** [docs/contest/contract.md](../../docs/contest/contract.md); [evidence/S01/acceptance.md](../../evidence/S01/acceptance.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| C33.1 Общего разрешения публичного репозитория и публикации после финала нет. Сохраняются режим материалов и конфиденциальность. | Сохранённое положение/contract/questions; безопасный статус без имитации события. Публичного remote/публикации не создано; общего разрешения публикации нет. |

## C34 — Главный фонд — 200 000 ₽ после налогов на команду. Распределение определяет фактический состав команды; порядок/форма выплаты — отдельное соглашение. Срок выплаты и налоговый агент не указаны.

**Состояние:** not_verified. Сохранённое положение/contract/questions; безопасный статус без имитации события.

**Остаток:** Победа/соглашение о распределении/выплата отсутствуют; фонд не доступный бюджет.

**Сохранённые доказательства:** [docs/contest/contract.md](../../docs/contest/contract.md); [evidence/S01/acceptance.md](../../evidence/S01/acceptance.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| C34.1 Главный фонд — 200 000 ₽ после налогов на команду. Распределение определяет фактический состав команды; порядок/форма выплаты — отдельное соглашение. Срок выплаты и налоговый агент не указаны. | Сохранённое положение/contract/questions; безопасный статус без имитации события. Победа/соглашение о распределении/выплата отсутствуют; фонд не доступный бюджет. |

## C35 — Онлайн-сертификат предусмотрен участникам команд, зарегистрированных 15 октября. Вышедший участник теряет право; фактическую выдачу нельзя обещать от имени организатора.

**Состояние:** not_verified. Сохранённое положение/contract/questions; безопасный статус без имитации события.

**Остаток:** Фактическая выдача сертификатов не подтверждена.

**Сохранённые доказательства:** [docs/contest/contract.md](../../docs/contest/contract.md); [evidence/S01/acceptance.md](../../evidence/S01/acceptance.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| C35.1 Онлайн-сертификат предусмотрен участникам команд, зарегистрированных 15 октября. Вышедший участник теряет право; фактическую выдачу нельзя обещать от имени организатора. | Сохранённое положение/contract/questions; безопасный статус без имитации события. Фактическая выдача сертификатов не подтверждена. |

## C36 — Каждый участник подписывает отдельное согласие на ПД при регистрации или открытии. Веб-согласие и политики относятся к данным участников, а не заменяют документы медицинского сервиса.

**Состояние:** partial. Сохранённое положение/contract/questions; безопасный статус без имитации события.

**Остаток:** Индивидуальные согласия только со слов капитана; политики участника не легализуют пациентский сервис.

**Сохранённые доказательства:** [docs/contest/contract.md](../../docs/contest/contract.md); [evidence/S01/acceptance.md](../../evidence/S01/acceptance.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| C36.1 Отдельное письменное индивидуальное согласие каждого участника | Сохранённое положение/contract/questions; безопасный статус без имитации события. Индивидуальные согласия только со слов капитана; политики участника не легализуют пациентский сервис. |
| C36.2 Цели и получатели данных веб-согласия/политик проверены отдельно от пациентского сервиса | Сохранённое положение/contract/questions; безопасный статус без имитации события. Индивидуальные согласия только со слов капитана; политики участника не легализуют пациентский сервис. |
| C36.3 Веб-согласие рассчитано на пять лет; политика допускает предусмотренных получателей/обработчиков | Сохранённое положение/contract/questions; безопасный статус без имитации события. Индивидуальные согласия только со слов капитана; политики участника не легализуют пациентский сервис. |
| C36.4 Разрешённые политикой операции не означают автоматического разрешения передавать пациентские данные | Сохранённое положение/contract/questions; безопасный статус без имитации события. Индивидуальные согласия только со слов капитана; политики участника не легализуют пациентский сервис. |
| C36.5 Участник может проверить применимый порядок обращения по ПД; прямое рекламное согласие не установлено | Сохранённое положение/contract/questions; безопасный статус без имитации события. Индивидуальные согласия только со слов капитана; политики участника не легализуют пациентский сервис. |

## C37 — Оценки окончательны, кроме технической ошибки подсчёта и подтверждённого конфликта интересов. Заявление об ошибке — за один рабочий день; опубликованные результаты нужно сохранить.

**Состояние:** not_verified. Сохранённое положение/contract/questions; безопасный статус без имитации события.

**Остаток:** Оценки/итоги ещё не опубликованы; при событии проверить срок заявления один рабочий день.

**Доказательства выполнения отсутствуют.** Свод требования не является доказательством события.

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| C37.1 Оценки окончательны, кроме технической ошибки подсчёта и подтверждённого конфликта интересов. Заявление об ошибке — за один рабочий день; опубликованные результаты нужно сохранить. | Сохранённое положение/contract/questions; безопасный статус без имитации события. Оценки/итоги ещё не опубликованы; при событии проверить срок заявления один рабочий день. |

## C38 — Общая претензия содержит ФИО, телефон, email и суть. Рассмотрение — десять рабочих дней; повторная претензия — за пять рабочих дней после ответа. Судебный порядок задан положением; это не общий способ оспаривать содержательную оценку жюри.

**Состояние:** not_verified. Сохранённое положение/contract/questions; безопасный статус без имитации события.

**Остаток:** Претензий/переписки нет; не считать сроки процесса исполненными заранее.

**Сохранённые доказательства:** [docs/contest/contract.md](../../docs/contest/contract.md); [evidence/S01/acceptance.md](../../evidence/S01/acceptance.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| C38.1 Общая претензия содержит ФИО, телефон, email и суть. Рассмотрение — десять рабочих дней; повторная претензия — за пять рабочих дней после ответа. Судебный порядок задан положением; это не общий способ оспаривать содержательную оценку жюри. | Сохранённое положение/contract/questions; безопасный статус без имитации события. Претензий/переписки нет; не считать сроки процесса исполненными заранее. |

## C39 — Уточнения — через процедуру чата, модератора/трекера. Контакт положения: Анна Поляк, anmediv@gmail.com; претензии: ivashchenko_a_a@staff.sechenov.ru. Агент не пишет людям без поручения пользователя.

**Состояние:** partial. Сохранённое положение/contract/questions; безопасный статус без имитации события.

**Остаток:** Контакты/правила сохранены; новые ответы не получены, писем агент не отправлял.

**Сохранённые доказательства:** [docs/contest/contract.md](../../docs/contest/contract.md); [evidence/S01/acceptance.md](../../evidence/S01/acceptance.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| C39.1 Уточнения — через процедуру чата, модератора/трекера. Контакт положения: Анна Поляк, anmediv@gmail.com; претензии: ivashchenko_a_a@staff.sechenov.ru. Агент не пишет людям без поручения пользователя. | Сохранённое положение/contract/questions; безопасный статус без имитации события. Контакты/правила сохранены; новые ответы не получены, писем агент не отправлял. |

## C40 — Фактический старт — 15 октября, работа до 30 октября. Начало онлайн-этапа 15/16 октября различается по источникам; устаревший блок сайта не переносит конкурс.

**Состояние:** not_verified. Сохранённое положение/contract/questions; безопасный статус без имитации события.

**Остаток:** Публичный график отдельно проверяется исследователем; фактическое участие в будущих этапах не подтверждено.

**Сохранённые доказательства:** [docs/contest/contract.md](../../docs/contest/contract.md); [evidence/S01/acceptance.md](../../evidence/S01/acceptance.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| C40.1 Фактический старт — 15 октября, работа до 30 октября. Начало онлайн-этапа 15/16 октября различается по источникам; устаревший блок сайта не переносит конкурс. | Сохранённое положение/contract/questions; безопасный статус без имитации события. Публичный график отдельно проверяется исследователем; фактическое участие в будущих этапах не подтверждено. |

## C41 — Специальных публичных норм о Codex/ИИ, собственном старом коде, open source, SaaS и внешних API нет. Требуются уточнения, проверка лицензий и отсутствие самовольной передачи материалов. Состав доступных данных/ресурсов не гарантирован.

**Состояние:** partial. Сохранённое положение/contract/questions; безопасный статус без имитации события.

**Остаток:** Нет персонального ответа об ИИ/старом коде/API; продукт без внешнего ИИ, разработка с Codex раскрыта.

**Сохранённые доказательства:** [docs/contest/contract.md](../../docs/contest/contract.md); [evidence/S01/acceptance.md](../../evidence/S01/acceptance.md); [docs/clinical/sources.md](../../docs/clinical/sources.md); [evidence/S02/requirements-review.md](../../evidence/S02/requirements-review.md); [evidence/S02/acceptance.md](../../evidence/S02/acceptance.md); [docs/clinical/scales-rights.md](../../docs/clinical/scales-rights.md); [evidence/S02/research-scales.md](../../evidence/S02/research-scales.md); [evidence/S02/external-check.md](../../evidence/S02/external-check.md); [evidence/S02/received-review.md](../../evidence/S02/received-review.md); [evidence/S02/received-research.md](../../evidence/S02/received-research.md); [evidence/S02/received/manifest.json](../../evidence/S02/received/manifest.json); [evidence/S02/acceptance-review.md](../../evidence/S02/acceptance-review.md); [docs/architecture/system.md](../../docs/architecture/system.md); [docs/architecture/data-model.md](../../docs/architecture/data-model.md); [docs/architecture/decisions.md](../../docs/architecture/decisions.md); [docs/RUNBOOK.md](../../docs/RUNBOOK.md); [evidence/S04/acceptance.md](../../evidence/S04/acceptance.md); [evidence/S04/checks.log](../../evidence/S04/checks.log); [evidence/S04/docker-check.json](../../evidence/S04/docker-check.json); [evidence/S07/review/contest-research.md](../../evidence/S07/review/contest-research.md); [docs/product/contest-strategy.md](../../docs/product/contest-strategy.md); [evidence/S14/acceptance.md](../../evidence/S14/acceptance.md); [evidence/S14/security.md](../../evidence/S14/security.md); [evidence/S14/reliability.md](../../evidence/S14/reliability.md); [evidence/S14/final-checks-r3.log](../../evidence/S14/final-checks-r3.log); [evidence/S14/docker-tests-final.log](../../evidence/S14/docker-tests-final.log); [apps/tests/test_security.py](../../apps/tests/test_security.py); [docs/compliance/data-map.md](../../docs/compliance/data-map.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| C41.1 Специальных публичных норм о Codex/ИИ, собственном старом коде, open source, SaaS и внешних API нет. Требуются уточнения, проверка лицензий и отсутствие самовольной передачи материалов. Состав доступных данных/ресурсов не гарантирован. | Сохранённое положение/contract/questions; безопасный статус без имитации события. Нет персонального ответа об ИИ/старом коде/API; продукт без внешнего ИИ, разработка с Codex раскрыта. |

## C42 — Веса/приоритет, входные форматы/поля, критерии апробации, питч/Q&A, слайды/видео, загрузка, размеры постера и инфраструктура публично не конкретизированы. Получить ответы или сохранить явные пробелы, не придумывать разрешения.

**Состояние:** partial. Сохранённое положение/contract/questions; безопасный статус без имитации события.

**Остаток:** Закрытые форматы/веса/питч/загрузка/постер/апробация неизвестны; допущения не заменяют ответа.

**Сохранённые доказательства:** [docs/contest/contract.md](../../docs/contest/contract.md); [evidence/S01/acceptance.md](../../evidence/S01/acceptance.md); [evidence/S07/review/contest-research.md](../../evidence/S07/review/contest-research.md); [docs/product/contest-strategy.md](../../docs/product/contest-strategy.md); [evidence/S12/acceptance.md](../../evidence/S12/acceptance.md); [evidence/S12/extraction-results.json](../../evidence/S12/extraction-results.json); [docs/validation/extraction-method.md](../../docs/validation/extraction-method.md); [evidence/S12/external-check.md](../../evidence/S12/external-check.md); [apps/tests/test_extraction.py](../../apps/tests/test_extraction.py); [docs/validation/extraction-method-addendum.md](../../docs/validation/extraction-method-addendum.md); [evidence/S16/validation-summary.md](../../evidence/S16/validation-summary.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| C42.1 Веса/приоритет, входные форматы/поля, критерии апробации, питч/Q&A, слайды/видео, загрузка, размеры постера и инфраструктура публично не конкретизированы. Получить ответы или сохранить явные пробелы, не придумывать разрешения. | Сохранённое положение/contract/questions; безопасный статус без имитации события. Закрытые форматы/веса/питч/загрузка/постер/апробация неизвестны; допущения не заменяют ответа. |

## C43 — Сохранить версии и хеши PDF/положения. Новые дополнения чата учитывать отдельным слоем, не заменять исходные формулировки молча.

**Состояние:** partial. Сохранённое положение/contract/questions; безопасный статус без имитации события.

**Остаток:** Исходные файлы/SHA сохранены; новый DOCX/закрытые дополнения не объявлены неизменными без фактической сверки.

**Сохранённые доказательства:** [docs/contest/contract.md](../../docs/contest/contract.md); [evidence/S01/acceptance.md](../../evidence/S01/acceptance.md); [evidence/S07/review/contest-research.md](../../evidence/S07/review/contest-research.md); [docs/product/contest-strategy.md](../../docs/product/contest-strategy.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| C43.1 Сохранить версии и хеши PDF/положения. Новые дополнения чата учитывать отдельным слоем, не заменять исходные формулировки молча. | Сохранённое положение/contract/questions; безопасный статус без имитации события. Исходные файлы/SHA сохранены; новый DOCX/закрытые дополнения не объявлены неизменными без фактической сверки. |

## C44 — Стажировки, поддержка дальнейшего развития и постерный приз без подробных условий не являются гарантированным доходом или внедрением.

**Состояние:** not_verified. Сохранённое положение/contract/questions; безопасный статус без имитации события.

**Остаток:** Стажировка/поддержка/постерный приз не подтверждены как полученные результаты.

**Сохранённые доказательства:** [docs/contest/contract.md](../../docs/contest/contract.md); [evidence/S01/acceptance.md](../../evidence/S01/acceptance.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| C44.1 Стажировки, поддержка дальнейшего развития и постерный приз без подробных условий не являются гарантированным доходом или внедрением. | Сохранённое положение/contract/questions; безопасный статус без имитации события. Стажировка/поддержка/постерный приз не подтверждены как полученные результаты. |

## C45 — Различать роли: организатор — НМИЦ Сербского, соорганизатор — Сеченовский университет, партнёр — Авинейро; координатор — Берёзовая роща. Не отождествлять площадки открытия/финала и не придумывать скрытые критерии.

**Состояние:** not_verified. Сохранённое положение/contract/questions; безопасный статус без имитации события.

**Остаток:** Роли организаций записаны в contract.md; скрытые критерии/площадка финала не выводятся из них.

**Сохранённые доказательства:** [docs/contest/contract.md](../../docs/contest/contract.md); [evidence/S01/acceptance.md](../../evidence/S01/acceptance.md).

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| C45.1 Различать роли: организатор — НМИЦ Сербского, соорганизатор — Сеченовский университет, партнёр — Авинейро; координатор — Берёзовая роща. Не отождествлять площадки открытия/финала и не придумывать скрытые критерии. | Сохранённое положение/contract/questions; безопасный статус без имитации события. Роли организаций записаны в contract.md; скрытые критерии/площадка финала не выводятся из них. |

## C46 — После отчуждения развитие возможно в согласованной роли относительно правообладателя. Медицинский пилот и регистрация не считаются выполненными хакатонным демо.

**Состояние:** not_verified. Сохранённое положение/contract/questions; безопасный статус без имитации события.

**Остаток:** Postcontest не разрешён; поручение/правообладатель/пилот/регистрация не установлены.

**Доказательства выполнения отсутствуют.** Свод требования не является доказательством события.

| Подпункт (без сокращений) | Основание и результат сверки |
|---|---|
| C46.1 После отчуждения развитие возможно в согласованной роли относительно правообладателя. Медицинский пилот и регистрация не считаются выполненными хакатонным демо. | Сохранённое положение/contract/questions; безопасный статус без имитации события. Postcontest не разрешён; поручение/правообладатель/пилот/регистрация не установлены. |
