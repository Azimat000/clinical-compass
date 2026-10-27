# UI09: навыки из интернета, 27.10.2026

По прямому поручению выполнен внешний read-only поиск через web-researcher,
затем пользователь выбрал «Подбор и сразу переработка интерфейса».
Проверено содержимое публичных инструкций, а не обещания каталогов или stars.
Это не аудит всего исполняемого кода и не доказательство удобства самого продукта.

| Источник | Решение для задачи |
|---|---|
| [Matthew Blode: agent-skills](https://github.com/mblode/agent-skills/tree/ff92bf5ae675e8108e7d2f14b22a523fd1303e76) | Основной внешний ориентир: product-design, ui-design, typography-audit. Минимум переходов, смысл действий, локальные раскрытия, реальные состояния, типографическая иерархия, проверка переполнений. MIT; автор Matthew Blode. |
| [Addy Osmani: frontend-ui-engineering](https://github.com/addyosmani/agent-skills/tree/main/skills/frontend-ui-engineering) | Содержательные правила responsive/accessibility/states, MIT. Ранее удалённый локальный skill не восстанавливался. |
| [Emmraan: ui-ux](https://github.com/Emmraan/agent-skills/blob/main/skills/design-ux/ui-ux/SKILL.md) | Информационная архитектура, пути ролей, мобильная навигация. MIT; полезен для более полного перепроектирования, процесс избыточен для локальных исправлений. |
| [Microsoft: frontend-design-review](https://github.com/microsoft/skills/blob/main/.github/skills/frontend-design-review/SKILL.md) | Финальная оценка понятности/доверия; MIT. Creative-советы не перенесены в медицинский кабинет. |
| [PracticalSwan: frontend-design](https://github.com/PracticalSwan/agent-skills/blob/main/frontend-design/SKILL.md) | Требует функциональности, доступности и проверки длинного текста. Корневая лицензия не подтверждена исследователем, не устанавливался. |
| [Kenzo Fujimoto: ui-ux-pro-max](https://github.com/kenzofujimoto/agent-skills/blob/main/skills/ui-ux-pro-max/SKILL.md) | Не выбран: не подтверждена лицензия, собственный поисковый скрипт и большая база не нужны этой задаче. |

Ревизия mblode: ff92bf5ae675e8108e7d2f14b22a523fd1303e76,
[лицензия MIT](https://raw.githubusercontent.com/mblode/agent-skills/ff92bf5ae675e8108e7d2f14b22a523fd1303e76/LICENSE.md).
Использованы проверенные исследователем принципы; весь пакет не установлен,
его скрипты не выполнялись. Локальный emil-design-eng применён для контроля
размеров/отклика элементов; новые библиотеки и зависимости не добавлены.

«Лишние переходы» трактуются как навигационные шаги, не как анимации.
Ключевые решения: приём/план/сообщения напрямую из списка; разделы карточки
видны без горизонтальной прокрутки; период раскрывается на месте; связь с
врачом открывает переписку, техническая проверка связи вторична. Смысл
клинических подтверждений и границы ролей не менялись.
