# web-design-guidelines: кабинет пациента (UI03)

22.10.2026. Правила — закреплённая копия `.claude/skills/web-design-guidelines/guidelines.pinned.md` (vercel-labs/web-interface-guidelines 434b7f9); свежая версия из сети не запрашивалась.
Файлы: apps/compass/templates/{patient_base,patient,assessment_form,assessment_receipt,invitation}.html, apps/compass/static/{app.css,questionnaire.js,self_report.js,report_draft.js}.

## Исправлено в этом проходе

patient_base.html - вкладка «Сообщения» выглядела рабочей, но не вела никуда → убрана до UI06
patient_base.html, assessment_receipt.html, patient.html - обещание «ответ придёт» → «ответа здесь может не быть; если хуже, не ждите»
app.css `.p-tabs a` - кольцо фокуса обрезалось контейнером → `outline-offset: -3px`
app.css - ссылки и сводки ниже 44px (Весь дневник, Квитанция, Что записано, Перейти к первому пропуску, листок-вкладыш) → `min-height: 44px`
patient.html - «Удалить черновик» без JS стирал сразу → подтверждающий `<details>`; в report_draft.js убран `window.confirm`
assessments.py - «00:00» следующих суток → «24:00 МСК» текущих
assessment_form.html + questionnaire.js - счётчик `role=status` зачитывался на каждый ответ; нет состояния отправки → счётчик без live-региона, отдельный `role=status` для отправки, `aria-busy`, «Отправляем…», защита от второго клика

## Без замечаний

Подписи у всех полей, `autocomplete` и `inputmode` у полей формы, `:focus-visible` вместо `outline: none` (в CSS нет), `tabular-nums` у дат и чисел, `…` вместо `...` в тексте, `touch-action: manipulation`, `scroll-margin-top` у утверждений анкеты, прилипшая полоса анкеты не закрывает поле в фокусе (`scroll-padding-bottom`), `prefers-reduced-motion`, предупреждение о несохранённых изменениях (`beforeunload`), без `transition: all`, без localStorage/sessionStorage.

## Сознательно оставлено

`autofocus` на поле кода приглашения убран (`autofocus: false`) — на телефоне клавиатура не должна открываться без просьбы.
Поля ввода и выпадающие списки 36px: размер задан в UI02 (DESIGN.md), меняется отдельным решением для всех экранов.
Строки `[...form...]` в JS — оператор расширения, не многоточие в тексте.
