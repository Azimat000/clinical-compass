/* Server-owned history; polling reads only. No clinical data in browser storage. */
(() => {
  'use strict';
  const states = {queued: 'В очереди', running: 'Анализ выполняется', ready: 'Предложение подготовлено', stale: 'Устарело — появились новые данные', insufficient_data: 'Недостаточно данных', partial: 'Частичный результат', unsupported: 'Случай не поддерживается', failed: 'Анализ не выполнен', cancelled: 'Анализ отменён'};
  const key = () => Array.from(crypto.getRandomValues(new Uint8Array(16)), n => n.toString(16).padStart(2, '0')).join('');
  function node(tag, text, className) { const el = document.createElement(tag); if (text != null) el.textContent = text; if (className) el.className = className; return el; }
  function link(text, href) { const el = node('a', text); el.href = href; return el; }
  async function api(url, body, csrf) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(url, {method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin', cache: 'no-store', signal: controller.signal,
        headers: {Accept: 'application/json', ...(body === undefined ? {} : {'Content-Type': 'application/json', 'X-CSRF-Token': csrf})}, ...(body === undefined ? {} : {body: JSON.stringify(body)})});
      const data = response.headers.get('content-type')?.includes('application/json') ? await response.json() : null;
      if (!response.ok || !data) { const error = Error(response.status === 401 || response.status === 403 || response.redirected ? 'Доступ недоступен. Войдите в кабинет заново.' : data?.error || 'Сервер не предоставил данные. Повторите загрузку.'); error.status = response.status; throw error; }
      return data;
    } catch (error) { if (error.name === 'AbortError') throw Error('Сервер не ответил вовремя. Повторите загрузку.'); throw error; }
    finally { clearTimeout(timer); }
  }
  for (const root of document.querySelectorAll('[data-support]')) {
    const kind = root.dataset.support, patient = root.dataset.patient, csrf = root.dataset.csrf;
    const base = patient ? `/api/v1/patients/${encodeURIComponent(patient)}` : '/api/v1/physician';
    const status = root.querySelector('[data-support-status]'), content = root.querySelector('[data-support-content]');
    const form = root.querySelector('[data-support-diagnosis-form]'), doctor = root.querySelector('[data-support-doctor]');
    let busy = false, review = null, pendingSave = null, pendingAnalysis = null, page = 1, timer, enabled = false, therapyLoaded = false;
    const productNames = new Map();
    const announce = text => { if (status.textContent !== text) status.textContent = text; };
    function details(title, value, target = content) {
      if (value == null) return;
      const fold = node('details'), summary = node('summary', title);
      fold.append(summary);
      function render(value, parent) {
        if (Array.isArray(value)) { const list = node('ul'); for (const item of value) { const li = node('li'); render(item, li); list.append(li); } parent.append(list); }
        else if (value && typeof value === 'object') { const list = node('dl', null, 'facts'); for (const [name, item] of Object.entries(value)) { list.append(node('dt', labels[name] || name)); const dd = node('dd'); render(item, dd); list.append(dd); } parent.append(list); }
        else parent.append(node('span', value === true ? 'Да' : value === false ? 'Нет' : value == null ? 'Не указано' : String(value)));
      }
      render(value, fold); target.append(fold);
    }
    const labels = {text: 'Содержание', basis: 'Основание', uncertainties: 'Что уточнить', recorded_at: 'Записано', actor_id: 'Автор', origin: 'Происхождение', status: 'Состояние', fact_ids: 'Факты', source_ids: 'Источники', evidence: 'Сведения', evidence_refs: 'Ссылки на сведения', source_ref: 'Исходная запись', path: 'Поле', quote: 'Цитата', reason: 'Причина', kind: 'Вид', goal: 'Цель', necessity: 'Необходимость', missing: 'Недостающие данные', contradictions: 'Противоречия', report: 'Разбор', structured: 'Проверка правил', model_candidates: 'Предположения модели', model_evaluation: 'Оценка предположений'};
    function showRun(run, target = content) {
      const article = node('article');
      article.append(node('p', states[run.status] || run.status), node('p', `${run.updated_at} · версия ${run.revision}`, 'meta'));
      if (run.stale_reason) article.append(node('p', run.stale_reason));
      for (const error of run.errors || []) article.append(node('p', error.message));
      const output = run.result?.output;
      if (output?.leading) { article.append(node('p', output.leading.text, 'finding')); for (const alternative of output.alternatives || []) article.append(node('p', 'Альтернатива: ' + alternative.text)); }
      for (const item of output?.items || []) article.append(node('p', item.text));
      if(run.diagnosis_context) details('Разбор диагностических оснований',run.diagnosis_context,article);
      if (run.result?.facts) details('Основания, противоречия и недостающие сведения', run.result.facts, article);
      if (run.care_plan_context?.report) details('Обследования, наблюдение и основания плана', run.care_plan_context.report, article);
      if (run.care_plan_context?.therapy) details('Предложение лечения и ограничения', run.care_plan_context.therapy, article);
      article.append(link('Исходные данные этой версии', `${base}/analyses/${encodeURIComponent(run.run_id)}/inputs`));
      target.append(article);
      if (kind === 'plan' && run.status === 'ready' && target === content) planReview(run, article);
    }
    function planReview(run, article) {
      const items = run.care_plan_context?.report?.items;
      if (!items?.length) return;
      const editor = node('form');
      editor.append(node('h3', 'Подготовить редакцию для подтверждения'));
      const selections = [];
      for (const item of items) {
        const label = node('label'), check = node('input'); check.type = 'checkbox';
        check.checked = true;
        check.disabled = item.necessity === 'required_evaluation';
        label.append(check, document.createTextNode(' ' + item.text));
        const dateLabel = node('label', 'Срок выполнения (необязательно)'), date = node('input'); date.type = 'date'; dateLabel.append(date);
        editor.append(label, dateLabel); selections.push({item, check, date});
      }
      function field(title, name, required = true) {
        const label = node('label', title), input = node('textarea'); input.name = name; input.className = 'input'; input.maxLength = 4000; input.required = required; label.append(input); editor.append(label); return input;
      }
      const basis = field('Обоснование врача', 'basis'), uncertainties = field('Что остаётся уточнить', 'uncertainties');
      const reviewLabel = node('label'), reviewed = node('input'); reviewed.type = 'checkbox'; reviewed.required = true;
      reviewLabel.append(reviewed, document.createTextNode(' Сведения и выбранные пункты просмотрены'));
      const submit = node('button', 'Сохранить редакцию на подтверждение', 'button'); submit.type = 'submit';
      const message = node('p'); message.setAttribute('role', 'status');
      editor.append(reviewLabel, submit, message);
      const options = run.care_plan_context?.therapy?.report?.recommendations || [];
      const medicationLabel = node('label', 'Лекарственный вариант'), medicationChoice = node('select'); medicationChoice.className = 'select';
      const none = node('option', 'Без лекарственного назначения'); none.value = ''; medicationChoice.append(none);
      for (const rec of options) { const option = node('option', `${productNames.get(rec.candidate.product_id) || rec.candidate.product_id} · ${rec.candidate.daily_dose_mg} мг/сут`); option.value = rec.id; medicationChoice.append(option); }
      medicationLabel.append(medicationChoice); editor.insertBefore(medicationLabel, reviewLabel);
      const medicationFields = node('fieldset'); medicationFields.hidden = true; medicationFields.disabled = true;
      medicationFields.append(node('legend','Редакция лекарственного варианта врача'));
      function medInput(title, type, min, max, step) { const label = node('label',title), input = node('input'); input.type = type; input.className = 'input'; input.required = true; if(min != null) input.min = min; if(max != null) input.max = max; if(step) input.step = step; label.append(input); medicationFields.append(label); return input; }
      const strength = medInput('Содержание в таблетке, мг','number',0,null,'any');
      const dose = medInput('Суточная доза, мг','number',0,null,'any');
      const count = medInput('Приёмов в сутки','number',1,4,'1');
      const start = medInput('Дата начала','date');
      const days = medInput('Длительность, дней — выбирает врач','number',1,366,'1');
      const clocks = node('div'); medicationFields.append(clocks);
      const medSource = node('p'); medicationFields.append(medSource);
      let times = [];
      function timeFields() { times = []; clocks.replaceChildren(); for(let n = 0; n < Math.min(4,Number(count.value)||0); n++) { const label = node('label',`Время приёма ${n+1}`), input = node('input'); input.type = 'time'; input.required = true; label.append(input); clocks.append(label); times.push(input); } }
      count.onchange = timeFields;
      medicationChoice.onchange = () => { const rec = options.find(r => r.id === medicationChoice.value); medicationFields.hidden = !rec; medicationFields.disabled = !rec; if(!rec) return; strength.value = rec.candidate.strength_mg; dose.value = rec.candidate.daily_dose_mg; count.value = rec.candidate.times_per_day; timeFields(); medSource.replaceChildren(node('p',rec.basis),node('p',rec.administration)); if(rec.source?.url?.startsWith('https://')) medSource.append(link('Источник лекарственного варианта',rec.source.url)); };
      editor.insertBefore(medicationFields,reviewLabel);
      const routeFields = node('fieldset'); routeFields.append(node('legend','Направление: отдельная оценка врача'));
      const routeControls = {};
      function routeSelect(title,name,values) { const label = node('label',title), input = node('select'); input.className = 'select'; for(const [v,t] of values) { const option = node('option',t); option.value = v; input.append(option); } label.append(input); routeFields.append(label); routeControls[name] = input; }
      routeSelect('Категория','category',[['unknown','Не определена'],['mandatory','Обязательно'],['desirable','Желательно']]);
      routeSelect('Срочность','urgency',[['unknown','Не определена'],['emergency','Экстренно'],['urgent','Срочно'],['planned','Планово']]);
      for(const [name,title] of [['severity_status','Сведения о тяжести'],['population_status','Применимость к пациенту']]) routeSelect(title,name,[['unknown','Неизвестно'],['known','Данные представлены'],['conflicting','Противоречие']]);
      for(const [name,title] of [['specialty','Специалист'],['severity','Тяжесть состояния'],['population','Применимость'],['evidence','Основание направления'],['unavailable','Действие при недоступности помощи'],['age_years','Проверенный возраст, лет']]) { const label = node('label',title), input = node('input'); input.className = 'input'; input.required = true; input.maxLength = 2000; if(name === 'age_years') { input.type = 'number'; input.min = '18'; input.max = '120'; input.step = '1'; } label.append(input); routeFields.append(label); routeControls[name] = input; }
      function updateRouting() { const selected = selections.some(s => s.check.checked && s.item.kind === 'routing'); routeFields.hidden = !selected; routeFields.disabled = !selected; }
      for(const selection of selections) selection.check.addEventListener('change',updateRouting);
      updateRouting(); editor.insertBefore(routeFields,reviewLabel);
      if(!options.length) editor.insertBefore(node('p','Проверенного лекарственного варианта в этом результате нет. Сверьте сведения в форме выше; причины уточнения приведены в разборе лечения.','meta'),reviewLabel);
      let pending = null;
      editor.addEventListener('input', () => { root.dataset.unsavedPlan = 'yes'; });
      editor.onsubmit = async event => {
        event.preventDefault(); if (submit.disabled) return; submit.disabled = true;
        try {
          if (!pending) {
            const chosen = selections.filter(s => s.check.checked);
            if (!chosen.length) throw Error('Выберите хотя бы один пункт.');
            const rec = options.find(r => r.id === medicationChoice.value);
            const medication = rec ? {recommendation_id:rec.id,candidate:{...rec.candidate,strength_mg:Number(strength.value),daily_dose_mg:Number(dose.value),times_per_day:Number(count.value)},start:start.value,days:Number(days.value),times:times.map(t => t.value)} : null;
            const routing = chosen.some(s => s.item.kind === 'routing') ? Object.fromEntries(Object.entries(routeControls).map(([k,v]) => [k,v.value])) : null;
            const state = await api(`${base}/plan-review-state`);
            pending = {request_key: key(), analysis_revision: run.revision, snapshot_id: run.snapshot_id, ...state,
              items: chosen.map(s => ({id: s.item.id, due_on: s.date.value || null})), medication, routing,
              basis: basis.value, uncertainties: uncertainties.value, reviewed: reviewed.checked};
          }
          const receipt = await api(`${base}/analyses/${encodeURIComponent(run.run_id)}/plan-reviews`, pending, csrf);
          pending = null; delete root.dataset.unsavedPlan; editor.replaceChildren(node('p', 'Редакция сохранена. Текущий план ещё не изменён.'),node('p',receipt.payload.content,'entry-text'));
          editor.append(link('Открыть отдельное подтверждение врача', `${location.pathname}?support_review=${encodeURIComponent(receipt.proposal_id)}#decision-${encodeURIComponent(receipt.proposal_id)}`));
        } catch (error) { if (error.status === 409) pending = null; message.textContent = error.message; }
        finally { submit.disabled = false; }
      };
      article.append(editor);
    }
    async function therapyEditor() {
      const host = root.querySelector('[data-therapy-content]');
      const data = await api(`${base}/therapy-editor`);
      for(const product of data.products) productNames.set(product.id,product.name);
      const saved = data.context.current?.payload || {};
      const editor = node('form');
      host.replaceChildren(editor);
      if (data.context.current) editor.append(node('p', `Сверка от ${data.context.current.recorded_at}${data.context.current.fresh ? '' : ' · устарела, просмотрите сведения заново'}`, 'meta'));
      const controls = {};
      function select(title, name, options, value) {
        const label = node('label', title), input = node('select'); input.className = 'select'; input.name = name;
        for (const [code, text] of options) { const option = node('option', text); option.value = code; input.append(option); }
        input.value = value; label.append(input); editor.append(label); controls[name] = input; return input;
      }
      select('Цель сверки', 'goal', [['initiation','Начало терапии'],['maintenance','Продолжение'],['change','Изменение — требуется индивидуальная схема'],['stop','Отмена — требуется индивидуальная схема']], saved.goal || 'initiation');
      const tri = [['unknown','Неизвестно'],['yes','Да'],['no','Нет'],['conflicting','Противоречие']];
      const encode = value => value === true ? 'yes' : value === false ? 'no' : value === 'conflicting' ? 'conflicting' : 'unknown';
      const decode = value => value === 'yes' ? true : value === 'no' ? false : value === 'conflicting' ? 'conflicting' : null;
      const facts = node('details'); facts.append(node('summary','Индивидуальные ограничения'));
      for (const item of data.facts) { const control = select(item.label, item.id, tri, encode(saved.facts?.[item.id])); facts.append(control.parentElement); }
      editor.append(facts);
      function textarea(title, name, value, required = false) { const label = node('label', title), input = node('textarea'); input.name = name; input.value = value || ''; input.className = 'input'; input.maxLength = 4000; input.required = required; label.append(input); editor.append(label); controls[name] = input; return input; }
      textarea('Аллергии: по одной на строку, включая действующие и вспомогательные вещества', 'allergies', (saved.allergies || []).join('\n'));
      select('Полнота сверки аллергий', 'allergies_complete', tri.slice(0,3), encode(saved.allergies_complete));
      const medHost = node('div'); editor.append(node('h3','Назначенные, фактически принимаемые и недавно отменённые лекарства'), medHost);
      const meds = [];
      function addMedication(initial = {}) {
        if (meds.filter(row => !row.removed).length >= 30) return;
        const row = node('fieldset'), legend = node('legend','Препарат'); row.append(legend); const fields = {};
        function input(title, name, type = 'text', value = '') { const label = node('label', title), el = node('input'); el.type = type; el.className = 'input'; if (type === 'number') { el.min = name === 'times_per_day' ? '1' : '0'; el.step = name === 'times_per_day' ? '1' : 'any'; } el.value = value ?? ''; label.append(el); row.append(label); fields[name] = el; return el; }
        function choice(title, name, options, value) { const label = node('label', title), el = node('select'); el.className = 'select'; for (const [id, text] of options) { const option = node('option', text); option.value = id; el.append(option); } el.value = value; label.append(el); row.append(label); fields[name] = el; return el; }
        const product = choice('Препарат', 'product_id', [['','Другой / не установлен'], ...data.products.map(p => [p.id,p.name])], initial.product_id || '');
        input('Действующее вещество', 'ingredient', 'text', initial.ingredient);
        choice('Состояние', 'state', [['current','Принимается сейчас'],['recently_stopped','Недавно отменён']], initial.state || 'current');
        input('Суточная доза, мг (пусто — неизвестно)', 'daily_dose_mg','number',initial.daily_dose_mg);
        input('Содержание в таблетке, мг (пусто — неизвестно)', 'strength_mg','number',initial.strength_mg);
        input('Приёмов в сутки (пусто — неизвестно)', 'times_per_day','number',initial.times_per_day);
        choice('Лекарственная форма', 'form', [['','Не установлена'],['film_coated_tablet','Таблетки, покрытые плёнкой'],['other','Другая форма']], initial.form || '');
        for (const [name,title] of [['prescribed','Назначен врачом'],['actual','Фактически принимается']]) { const label = node('label',title), el = node('select'); el.className = 'select'; el.required = true; for(const [v,t] of [['','Не сверено'],['yes','Да'],['no','Нет']]) { const option = node('option',t); option.value = v; el.append(option); } el.value = initial[name] === true ? 'yes' : initial[name] === false ? 'no' : ''; label.append(el); row.append(label); fields[name] = el; }
        product.onchange = () => { const found = data.products.find(p => p.id === product.value); if (found) { fields.ingredient.value = found.ingredient; fields.form.value = found.form; } };
        const entry = {row, fields, removed:false}; meds.push(entry);
        const remove = node('button','Убрать из новой сверки','button'); remove.type = 'button'; remove.onclick = () => { entry.removed = true; row.remove(); }; row.append(remove); medHost.append(row);
      }
      for (const med of saved.medications || []) addMedication(med);
      const add = node('button','Добавить препарат','button'); add.type = 'button'; add.onclick = () => addMedication(); editor.append(add);
      select('Полнота сверки лекарств, включая безрецептурные', 'medications_complete', tri.slice(0,3), encode(saved.medications_complete));
      select('Ответ на лечение', 'response', [['unknown','Неизвестно'],['effective','Достаточный'],['partial','Частичный'],['none','Нет эффекта']], saved.response || 'unknown');
      select('Переносимость', 'tolerability', [['unknown','Неизвестно'],['good','Хорошая'],['adverse','Нежелательные явления']], saved.tolerability || 'unknown');
      select('Предыдущая первая линия терапии', 'prior_first_line', [['unknown','Неизвестно'],['not_tried','Не применялась'],['ineffective','Неэффективна'],['intolerant','Непереносимость']], saved.prior_first_line || 'unknown');
      textarea('Основания сверки врача', 'basis', saved.basis, true);
      const label = node('label'), reviewed = node('input'); reviewed.type = 'checkbox'; reviewed.required = true; label.append(reviewed, document.createTextNode(' Я сверил эти сведения. Неизвестное оставлено неизвестным.')); editor.append(label);
      const submit = node('button','Сохранить сверку врача','button'); submit.type = 'submit'; const message = node('p'); message.setAttribute('role','status'); editor.append(submit,message);
      const refresh = node('button','Обновить основание сверки, сохранив ввод','button'); refresh.type = 'button'; editor.append(refresh);
      let state = data.context, pending = null;
      refresh.onclick = async () => { try { state = await api(`${base}/therapy-context`); pending = null; reviewed.checked = false; message.textContent = 'Основание обновлено. Просмотрите сведения и подтвердите сверку заново.'; } catch(error) { message.textContent = error.message; } };
      editor.onsubmit = async event => {
        event.preventDefault(); if (submit.disabled) return; submit.disabled = true;
        try {
          if (!pending) {
            const medications = meds.filter(m => !m.removed).map(({fields:f}) => ({product_id:f.product_id.value || null,ingredient:f.ingredient.value, state:f.state.value, prescribed:f.prescribed.value === 'yes', actual:f.actual.value === 'yes',
              daily_dose_mg:f.daily_dose_mg.value === '' ? null : Number(f.daily_dose_mg.value), strength_mg:f.strength_mg.value === '' ? null : Number(f.strength_mg.value), times_per_day:f.times_per_day.value === '' ? null : Number(f.times_per_day.value), unit:'mg',form:f.form.value}));
            pending = {request_key:key(),expected_version:state.expected_version,base_sha256:state.base_sha256,goal:controls.goal.value,
              facts:Object.fromEntries(data.facts.map(f => [f.id,decode(controls[f.id].value)])),allergies:controls.allergies.value.split(/\n/).map(v => v.trim()).filter(Boolean), allergies_complete:decode(controls.allergies_complete.value), medications, medications_complete:decode(controls.medications_complete.value),response:controls.response.value,tolerability:controls.tolerability.value,prior_first_line:controls.prior_first_line.value,basis:controls.basis.value,reviewed:reviewed.checked};
          }
          const receipt = await api(`${base}/therapy-context`,pending,csrf); pending = null;
          message.textContent = `Сверка сохранена · версия ${receipt.version}. План обновится сервером после выполнения условий. Назначение не изменено.`;
          state = await api(`${base}/therapy-context`); reviewed.checked = false;
        } catch(error) { if(error.status === 409) pending = null; message.textContent = error.message + ' Ввод оставлен в форме.'; }
        finally { submit.disabled = false; }
      };
    }
    async function loadDoctor() {
      if (root.dataset.dirtyDiagnosis && review) return;
      review = await api(`${base}/diagnosis-review`);
      doctor.replaceChildren();
      if (review.current) {
        const r = review.current.receipt;
        doctor.append(node('p', r.diagnosis?.text || 'Предложение отклонено'), node('p', `${r.recorded_at} · версия ${r.version}${review.current.fresh ? '' : ' · основание устарело'}`, 'meta'));
      } else doctor.append(node('p', 'Диагноз врача ещё не записан.'));
      for (const r of review.history || []) details(`Версия ${r.version} · ${r.recorded_at}`, {diagnosis: r.diagnosis?.text, basis: r.basis, uncertainties: r.uncertainties, actor_id: r.actor_id}, doctor);
      if (review.page_count > 1) doctor.append(link('Вся история диагнозов', `${base}/diagnosis-review?page=${review.page_count}`));
      form.querySelector('[type=submit]').disabled = !review.snapshot_id;
    }
    async function load() {
      if (busy || document.hidden) return;
      if (root.dataset.unsavedPlan) { announce('В редакции есть несохранённые изменения. Сохраните её перед обновлением сведений.'); return; }
      busy = true; root.setAttribute('aria-busy', 'true');
      try {
        const availability = await api(kind === 'alerts' ? '/api/v1/physician/decision-support' : `${base}/decision-support`);
        enabled = availability.available;
        if (kind === 'plan' && enabled && !therapyLoaded) { await therapyEditor(); therapyLoaded = true; }
        root.querySelector('[data-support-analyze]')?.toggleAttribute('disabled', !enabled || !availability.enabled);
        if (!enabled) {
          content.replaceChildren(); doctor?.replaceChildren();
          if (form) form.querySelector('[type=submit]').disabled = true;
          announce('Серверные блоки пока не подключены к этой базе. История и текущий план сохранены.');
          return;
        }
        if (kind === 'alerts') {
          const inbox = await api(`${base}/alerts?page=${page}`);
          const rows = await Promise.all(inbox.items.map(item => api(`${base}/alerts/${encodeURIComponent(item.id)}`)));
          content.replaceChildren();
          for (const item of rows) {
            const e = item.episode, article = node('article');
            article.append(link(e.patient_id, `/demo/${encodeURIComponent(e.patient_id)}`), node('p', e.topic, 'ds-alert-reason'), node('p', `${item.created_at} · версия ${e.revision}`, 'meta'));
            article.append(node('p', e.origin === 'rule' ? 'Основание: проверка правила' : 'Основание: предположение модели; требует проверки'));
            details('Основания и история сигнала', e.history, article);
            for (const version of e.history || []) if (version.run_id) article.append(link('Исходные данные версии ' + version.revision, `/api/v1/patients/${encodeURIComponent(e.patient_id)}/analyses/${encodeURIComponent(version.run_id)}/inputs`));
            const action = item.state === 'processed' ? null : item.state === 'seen' ? 'processed' : item.state === 'received' ? 'seen' : 'received';
            if (action && e.state === 'open') {
              const actionForm = node('form'), button = node('button', {received: 'Подтвердить получение', seen: 'Отметить просмотр', processed: 'Завершить рассмотрение'}[action], 'button'); button.type = 'submit';
              const reason = node('textarea'); reason.className = 'input'; reason.maxLength = 1000; reason.required = true; reason.setAttribute('aria-label', 'Итог рассмотрения'); if (action === 'processed') actionForm.append(reason);
              actionForm.append(button); let body;
              actionForm.addEventListener('submit', async event => { event.preventDefault(); button.disabled = true; body ||= {action, expected_revision: item.episode_revision, reason: action === 'processed' ? reason.value : '', request_key: key()}; try { await api(`${base}/alerts/${encodeURIComponent(item.id)}/actions`, body, csrf); await load(); } catch (error) { announce(error.message); } finally { button.disabled = false; } });
              article.append(actionForm);
            }
            content.append(article);
          }
          announce(rows.length ? 'Сигналы для рассмотрения врачом.' : 'Сигналов на этой странице нет. Это не означает отсутствия риска.');
          for (const [label, next] of [['Предыдущие', page > 1 ? page - 1 : null], ['Следующие', inbox.next_page]]) if (next) { const b = node('button', label, 'button'); b.type = 'button'; b.onclick = () => { page = next; load(); }; content.append(b); }
        } else {
          const history = await api(`${base}/analyses?operation=${kind}`);
          content.replaceChildren();
          if (history.items.length) { showRun(history.items[0]); for (const run of history.items.slice(1)) { const fold = node('details'); fold.append(node('summary', `${run.updated_at} · ${states[run.status] || run.status}`)); showRun(run, fold); content.append(fold); } }
          if (history.page_count > 1) content.append(link('Предыдущие анализы', `${base}/analyses?operation=${kind}&page=2`));
          announce(!availability.enabled ? 'Очередь анализа выключена. Доступны сохранённые результаты.' : history.items.length ? 'Показаны сохранённые сервером результаты.' : 'Анализ ещё не выполнен.');
          const automatic = availability.automatic?.find(item => item.operation === kind);
          if (automatic) announce(status.textContent + ' ' + automatic.message);
          if (availability.diagnosis_preview && kind === 'diagnosis') announce(status.textContent + ' Генерация включена для вымышленных историй; качество не проверено. Гипотезу оценивает врач.');
          if (kind === 'diagnosis') await loadDoctor();
        }
      } catch (error) { content.replaceChildren(); doctor?.replaceChildren(); review = null; if (form) form.querySelector('[type=submit]').disabled = true; announce(error.message); }
      finally { busy = false; root.removeAttribute('aria-busy'); }
    }
    root.querySelector('[data-support-refresh]').onclick = () => { if(form) { delete root.dataset.dirtyDiagnosis; form.elements.reviewed.checked = false; } load(); };
    const analyze = root.querySelector('[data-support-analyze]');
    if (analyze) analyze.onclick = async () => {
      if (busy || !enabled) return;
      analyze.disabled = true;
      pendingAnalysis ||= {contract_version: '1.0', operation: kind, request_key: key()};
      try { await api(`${base}/analyses`, pendingAnalysis, csrf); pendingAnalysis = null; await load(); }
      catch (error) { announce(error.message); }
      finally { analyze.disabled = false; }
    };
    if (form) {
      form.addEventListener('input', () => { root.dataset.dirtyDiagnosis = 'yes'; if (pendingSave) { form.querySelector('[data-support-save-status]').textContent = 'Есть неподтверждённое сохранение. Повтор сначала отправит прежнюю редакцию; новые правки останутся в полях.'; } });
      form.onsubmit = async event => {
        event.preventDefault(); if (!review?.snapshot_id) return;
        const button = form.querySelector('[type=submit]'), message = form.querySelector('[data-support-save-status]'); if (button.disabled) return; button.disabled = true;
        pendingSave ||= {request_key: key(), expected_version: review.head_version, snapshot_id: review.snapshot_id, action: 'manual', run_id: null, analysis_revision: null, hypothesis_id: null, diagnosis: form.elements.diagnosis.value, diagnosis_code: form.elements.diagnosis_code.value || null, basis: form.elements.basis.value, uncertainties: form.elements.uncertainties.value, reviewed: form.elements.reviewed.checked};
        try { const receipt = await api(`${base}/diagnosis-review`, pendingSave, csrf); pendingSave = null; delete root.dataset.dirtyDiagnosis; message.textContent = `Сохранено сервером · версия ${receipt.version}. Текст в полях оставлен.`; await loadDoctor(); }
        catch (error) { if (error.status === 409) { pendingSave = null; review = null; } message.textContent = error.message + ' Текст сохранён в полях. При конфликте обновите сведения перед новой редакцией.'; }
        finally { button.disabled = !review?.snapshot_id; }
      };
    }
    function schedule() { clearTimeout(timer); if (!document.hidden) timer = setTimeout(async () => { if (!root.contains(document.activeElement)) await load(); schedule(); }, 30000); }
    document.addEventListener('visibilitychange', () => { if (document.hidden) clearTimeout(timer); else { load(); schedule(); } });
    load(); schedule();
  }
})();
