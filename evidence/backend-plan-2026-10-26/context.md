# Основания планирования

Локальный контекст: START_HERE, memory/STATE/DECISIONS/BLOCKERS/EXTERNAL/BUDGET, S56 и его приёмка/карточка; plan/manifest/coverage, инструменты сессий и проверки; docs/architecture/ai-decision.md, service-path.md, clinical-rules.md, clinical-decisions.md, decisions.md. Последняя реализация S56, HEAD до правок: 42a09a5ef8acb8d13d782c1d0b9c489c8731769e.

Исследование предшествующего обсуждения в этом же чате выполнено read-only web-researcher /root/clinical_architecture_research, 26.10.2026. Результат использован без повторного поиска: проверяемые основания для врача, разделение технической и клинической оценки, явная неопределённость, отдельное подтверждение лечения.

- FDA, Clinical Decision Support Software: https://www.fda.gov/regulatory-information/search-fda-guidance-documents/clinical-decision-support-software
- WHO2021, Ethics and governance of AI for health: https://www.who.int/publications/i/item/9789240029200
- WHO2023, Regulatory considerations on AI for health: https://www.who.int/publications/i/item/9789240078871
- IMDRF2017, SaMD Clinical Evaluation: https://www.imdrf.org/documents/software-medical-device-samd-clinical-evaluation
- Рубрикатор КР: https://cr.minzdrav.gov.ru/clin-rec
- Официальный ГРЛС: https://rlpdev.digitalms.ru/

Это общие принципы, не российский регуляторный допуск, не доказательство клинической безопасности проекта и не проверка конкретной схемы/дозы/КР/взаимодействия. Точные первоисточники и актуальность нужных правил проверяются в соответствующих будущих срезах.

Перед правками сохранён точный baseline 14 планировочных/архитектурных файлов и индекса Git в /tmp. Содержимое всех 14 исходных файлов совпало с blob-ID индекса. Полный git status/diff зависает на dataless-файлах iCloud; стадированные отличия от HEAD/полная чистота этим не подтверждены. Индекс не сбрасывался, приложение/база не менялись.
