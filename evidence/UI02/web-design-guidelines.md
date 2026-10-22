# web-design-guidelines: основа интерфейса UI02

22.10.2026. Правила — закреплённая копия `.claude/skills/web-design-guidelines/guidelines.pinned.md` (vercel-labs/web-interface-guidelines 434b7f9, MIT); свежая версия из сети не запрашивалась, проект направляет сеть через web-researcher.
Файлы: apps/compass/templates/{base,components,login,result}.html, apps/compass/static/app.css.

## Исправлено в этом проходе

apps/compass/static/app.css:63 - -webkit-tap-highlight-color не задан → задан из угольного 12%
apps/compass/static/app.css:72 - длинные слова без переноса (код инцидента, длинный логин) → overflow-wrap: break-word на body
apps/compass/templates/components.html:9 - название продукта без translate="no" → добавлено

## Сознательно оставлено

apps/compass/templates/login.html:19 - autofocus на «Логин» (и на «Пароль» после неудачной попытки): единственная задача страницы — ввести два поля; на телефоне клавиатура открывается сразу, это ожидаемо для страницы входа
apps/compass/templates/components.html:20 - «спиннер во время запроса»: без JS страница не знает момента отправки; aria-busy и подпись «…» готовы для экранов, где отправку ведёт скрипт (UI03+)
Title Case в заголовках и кнопках — правило английской типографики, к русскому тексту не применяется
Intl.DateTimeFormat — даты на этих экранах не выводятся; формат дат решается в UI03/UI04 на сервере

## Без замечаний

Подписи у всех полей (label for), autocomplete username/current-password, spellcheck=false у логина, нет блокировки вставки, видимый фокус :focus-visible без outline:none, ссылка «К содержанию», один h1, transition перечисляет свойства, анимация только transform, prefers-reduced-motion, нет user-scalable=no, флажки и переключатели обёрнуты в label (одна область касания), плейсхолдеры с «…», шрифт с preload и font-display: swap, нет изображений без размеров, нет inline-скриптов и onclick.
