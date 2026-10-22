# Приёмка: установка навыков дизайна и план нового интерфейса

Дата: 22.10.2026 Europe/Moscow. Исходный коммит: b0ab24b50d2f1f1cd1f0aad363fafd41ca053a49. Это настройка инструментария и плана, не срез сервиса: приложение, базы, источники и клинические правила не менялись.

| Поручение пользователя | Доказательство | Итог |
|---|---|---|
| Найти навыки в интернете | Read-only web-researcher нашёл официальные репозитории: pbakaus/impeccable, Leonxlnx/taste-skill, emilkowalski/skills (три навыка), vercel-labs/agent-skills. Источники, коммиты и лицензии — docs/design/skills.lock.json | PASS |
| Скачать и настроить для проекта | Шесть навыков в .claude/skills и .agents/skills; подагенты impeccable в .claude/agents; хуки impeccable в .claude/settings.json; побайтовое сравнение с upstream — upstream-compare.log (отличия только перечисленные в local_changes); `python3 tools/design_skills.py check` PASS | PASS |
| Чтобы можно было применять сразу | Движок impeccable 0.1.16 скачан с проверкой sha256 и отвечает; `impeccable context` видит проект; детекторы impeccable и taste-skill ловят шаблонные приёмы на тестовой странице; хук молчит на правках не-UI файлов — smoke.log | PASS |
| Разделить цель на срезы, одна сессия — один срез | UI01–UI08 в plan/manifest.json, карточки plan/slices/UI0*.md, STATE: next_slice=UI01; validate_plan PASS | PASS |
| Память между срезами | docs/design/README.md (раздел «Память между срезами»): PRODUCT.md/DESIGN.md/.impeccable/design.json читает сам impeccable, плюс STATE, отчёты, DECISIONS; бриф docs/design/BRIEF.md; AGENTS.md и START_HERE.md указывают на UI01 | PASS |
| Первый срез — варианты на выбор | Карточка UI01: три направления на двух ключевых экранах, выбор пользователя обязателен для приёмки | PASS (план) |

Не проверено и не заявляется: качество будущего интерфейса, работа навыков в Codex (там нужен перезапуск и одобрение хуков, хуки не ставились), загрузка навыков в каталог текущей сессии Claude Code (появятся со следующей сессии).
