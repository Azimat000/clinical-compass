"""Add precisely delimited prototype components to redacted incumbent HTML."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT/'docs/design/prototypes/FE01'
STATES = {'ready':'Готово', 'queued':'В очереди', 'running':'В работе', 'partial':'Неполные данные', 'stale':'Устарело', 'conflict':'Конфликт версий', 'failed':'Ошибка', 'cancelled':'Отменено', 'offline':'Нет связи', 'access_denied':'Нет доступа', 'empty':'Нет результата', 'saving':'Сохранение', 'saved':'Ответ об успехе (макет)'}
toolbar = '<div class="fe01-tools" data-fe01-added><p><b>Прототип FE01.</b> Новые блоки — вымышленные примеры, не результаты анализа. Запись в базу отключена.</p><p><a href="/signals.html">Сигналы</a><a href="/diagnosis.html">Диагноз</a><a href="/plan.html">План</a><a href="/baseline/{name}.html">Исходный вид</a></p><label for="fe01-state">Проверить состояние <select id="fe01-state" class="select">' + ''.join(f'<option value="{k}">{v}</option>' for k,v in STATES.items()) + '</select></label></div>'
status = '<p class="fe01-status" role="status">Предложение подготовлено. Проверьте основания перед решением.</p>'
extra = '''<p data-fe01-clarify hidden>Нужно уточнить длительность и влияние жалоб, противоречивые сведения и применимость источника. Без этого полный вывод недоступен.</p>
<button class="button" type="button" data-fe01-retry data-fe01-action="retry" hidden>Повторить анализ</button>
<button class="button" type="button" data-fe01-compare data-fe01-action="compare" hidden>Сравнить версии</button>
<div class="fe01-note" data-fe01-comparison hidden><b>Сохранено в другой вкладке — пример версии 2:</b><p>Требуется уточнение жалоб на следующем приёме.</p><p>Ваш ввод ниже сохранён. Автоматического объединения нет.</p></div>'''

signals = '''<aside class="fe01-support fe01-alerts" aria-labelledby="fe01-signals" data-fe01-added>
<h2 id="fe01-signals">Критические сигналы</h2>''' + status + '''
<div data-fe01-content><div data-fe01-result><p class="fe01-reason">Требует проверки врача</p>
<p><b>Анна Сергеевна Ларина</b> · P201</p><p>Пример нового сообщения о мыслях о смерти. Не является записью из истории этого пациента.</p>
<p class="meta">Пример времени: 27.10, 10:42 МСК<br>Источник: дневник · версия 1</p>
<a class="fe01-source" href="/diagnosis.html#fe01-example-source">Открыть исходную запись примера</a>
<details><summary>Рассмотрение сигнала</summary><p>Получен → просмотрен → обработан. Открытие списка не закрывает сигнал.</p>
<label for="fe01-reason">Что проверено и сделано</label><textarea id="fe01-reason" class="textarea" placeholder="Запись врача о рассмотрении сигнала"></textarea>
<button class="button" type="button" data-fe01-write data-fe01-action="save">Сохранить обработку</button><p class="meta">Рассмотрение не меняет лечение. Новая версия требует отдельной проверки.</p></details></div>''' + extra + '''</div></aside>'''

diagnosis = '''<section class="fe01-support fe01-diagnosis" aria-labelledby="fe01-hypothesis" data-fe01-added>
<h2 id="fe01-hypothesis">Предполагаемый диагноз системы</h2>''' + status + '''<div data-fe01-content>
<div data-fe01-result><p class="fe01-diagnosis-value">Депрессивный эпизод — гипотеза для проверки</p>
<p class="meta">Пример результата · 27.10, 10:45 МСК · версия 1. Не диагноз врача.</p>
<details><summary>Основания и ограничения</summary><p>Макет структуры: жалобы и их длительность, влияние на жизнь, исключающие и противоречивые сведения. Утверждения должны вести к конкретному источнику и версии.</p>
<a class="fe01-source" href="#visit-history">Открыть историю приёмов</a> · <a class="fe01-source" href="#assessments">Анкеты и ответы</a>
<p>Критерии: подтверждено / отсутствует / неизвестно / противоречие. Процент уверенности не придумывается.</p></details></div>''' + extra + '''
<div class="fe01-doctor"><h2>Диагноз врача</h2><p class="meta">Вы вводите собственную формулировку. Новые результаты системы её не заменяют.</p>
<label for="fe01-doctor-diagnosis">Формулировка врача</label><textarea class="textarea" id="fe01-doctor-diagnosis" maxlength="2000">Требуется уточнение характера и длительности симптомов.</textarea>
<details><summary>Обоснование и неопределённости</summary><label for="fe01-diagnosis-basis">Обоснование врача</label><textarea id="fe01-diagnosis-basis" class="textarea" maxlength="4000">Нужно сопоставить сведения истории и текущие жалобы.</textarea><label for="fe01-diagnosis-unknown">Что остаётся неизвестным</label><textarea id="fe01-diagnosis-unknown" class="textarea" maxlength="4000">Длительность и влияние симптомов требуют уточнения.</textarea><label><input type="checkbox"> Исходные сведения просмотрены</label><p class="meta">В сервисе эти сведения и подтверждение просмотра обязательны.</p></details><div class="fe01-actions"><button class="button" type="button" data-fe01-write data-fe01-action="save">Сохранить диагноз врача</button><a href="/plan.html">К плану и решениям</a></div>
<p class="meta">Ввод в макете. В сервисе здесь будут автор, время и версия последней записи сервера.</p></div>
<details id="fe01-example-source"><summary>Исходная запись сигнала — только пример</summary><p>Вымышленный пример для проверки перехода: «Сегодня появились мысли о смерти». Автор: пациент; 27.10, 10:42 МСК; версия 1. В существующей истории такой записи нет.</p><a href="#records">Перейти к существующим самоотчётам</a></details>
</div></section>'''

plan = '''<section class="fe01-support fe01-plan" aria-labelledby="fe01-plan-title" data-fe01-added>
<h2 id="fe01-plan-title">Предложения системы</h2>''' + status + '''<div data-fe01-content><div data-fe01-result>
<p><b>План наблюдения:</b> обсудить динамику самочувствия и уточнить сведения на повторном приёме.</p>
<p><b>Лечение:</b> новый лекарственный вариант не предложен — требуется уточнение переносимости и сверка сведений.</p>
<p class="meta">Пример предложения · 27.10, 10:50 МСК · версия 1. Текущий подтверждённый план выше остаётся действующим.</p>
<details><summary>Основания, ограничения и состав проекта</summary><p>Основание: актуальная запись диагноза врача, исходные сведения, источники и их версии. План наблюдения и лекарственный проект проверяются отдельно.</p>
<a class="fe01-source" href="/diagnosis.html#fe01-doctor-diagnosis">Диагноз врача</a> · <a class="fe01-source" href="/diagnosis.html#visit-history">История приёмов</a>
<p>При допустимом лекарственном предложении здесь раскрываются точные препарат, форма, доза, курс и независимые проверки. Неизвестное не превращается в разрешённую дозу.</p></details>
<div class="fe01-actions"><button class="button" type="button" data-fe01-write data-fe01-action="prepare">Подготовить решение</button><a href="#current">Сопоставить с текущим планом</a></div></div>''' + extra + '''
<div class="fe01-doctor" data-fe01-review hidden><h3>Решение врача — проект</h3><p>Выбрано: обсуждение динамики на повторном приёме. Лекарственный состав не изменяется. Этот шаг не применяет предложение.</p>
<label for="fe01-plan-basis">Обоснование врача</label><textarea id="fe01-plan-basis" class="textarea" maxlength="4000"></textarea>
<label><input type="checkbox"> Сведения и изменения проекта просмотрены</label>
<div class="fe01-actions"><button class="button" type="button" data-fe01-write data-fe01-action="confirm">Подтвердить решение</button><button class="button" type="button" data-fe01-write data-fe01-action="confirm">Отклонить проект</button></div>
<p class="meta">В сервисе применение — отдельный ответ сервера. Здесь демонстрируется только переход к ожиданию.</p></div></div></section>'''

for name, block in [('signals',signals), ('diagnosis',diagnosis), ('plan',plan)]:
    html = (OUT/'baseline'/f'{name}.html').read_text()
    html = html.replace('</head>', '<link rel="stylesheet" href="/support.css" data-fe01-added>\n</head>')
    html = re.sub(r'(<body[^>]*>)', lambda m: m[1]+toolbar.replace('{name}',name), html, count=1)
    if name == 'signals':
        begin = html.index('<table class="results review-list">')
        end = html.index('</table>', begin)+len('</table>')
        html = html[:begin]+'<div class="fe01-layout" data-fe01-wrapper>'+block+'<div class="fe01-list" data-fe01-wrapper>'+html[begin:end]+'</div></div>'+html[end:]
    elif name == 'diagnosis':
        html = html.replace('<div class="sheet-pad">',block+'\n<div class="sheet-pad">',1)
    else:
        start=html.index('<section class="block" id="current"'); end=html.index('</section>',start)+len('</section>')
        html=html[:end]+block+html[end:]
    html=html.replace('</body>','<script src="/support.js" defer data-fe01-added></script></body>')
    (OUT/f'{name}.html').write_text(html)
print('PASS: 3 delimited additions; incumbent HTML retained')
