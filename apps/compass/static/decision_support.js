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
    const form = root.querySelector('form'), doctor = root.querySelector('[data-support-doctor]');
    let busy = false, review = null, pendingSave = null, pendingAnalysis = null, page = 1, timer, enabled = false;
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
      editor.append(node('p', 'Лекарства и направление требуют отдельной сверки врача в существующей форме проекта.', 'meta'));
      let pending = null;
      editor.addEventListener('input', () => { root.dataset.unsavedPlan = 'yes'; });
      editor.onsubmit = async event => {
        event.preventDefault(); if (submit.disabled) return; submit.disabled = true;
        try {
          if (!pending) {
            const chosen = selections.filter(s => s.check.checked);
            if (!chosen.length) throw Error('Выберите хотя бы один пункт.');
            if (chosen.some(s => s.item.kind === 'routing')) throw Error('Для направления используйте собственный проект ниже: нужна отдельная оценка маршрута врачом.');
            const state = await api(`${base}/plan-review-state`);
            pending = {request_key: key(), analysis_revision: run.revision, snapshot_id: run.snapshot_id, ...state,
              items: chosen.map(s => ({id: s.item.id, due_on: s.date.value || null})), medication: null, routing: null,
              basis: basis.value, uncertainties: uncertainties.value, reviewed: reviewed.checked};
          }
          const receipt = await api(`${base}/analyses/${encodeURIComponent(run.run_id)}/plan-reviews`, pending, csrf);
          pending = null; delete root.dataset.unsavedPlan; editor.replaceChildren(node('p', 'Редакция сохранена. Текущий план ещё не изменён.'));
          editor.append(link('Открыть отдельное подтверждение врача', `${location.pathname}#decision-${encodeURIComponent(receipt.proposal_id)}`));
        } catch (error) { if (error.status === 409) pending = null; message.textContent = error.message; }
        finally { submit.disabled = false; }
      };
      article.append(editor);
    }
    async function loadDoctor() {
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
          if (kind === 'diagnosis') await loadDoctor();
        }
      } catch (error) { content.replaceChildren(); doctor?.replaceChildren(); review = null; if (form) form.querySelector('[type=submit]').disabled = true; announce(error.message); }
      finally { busy = false; root.removeAttribute('aria-busy'); }
    }
    root.querySelector('[data-support-refresh]').onclick = () => load();
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
      form.addEventListener('input', () => { if (pendingSave) { form.querySelector('[data-support-save-status]').textContent = 'Есть неподтверждённое сохранение. Повтор сначала отправит прежнюю редакцию; новые правки останутся в полях.'; } });
      form.onsubmit = async event => {
        event.preventDefault(); if (!review?.snapshot_id) return;
        const button = form.querySelector('[type=submit]'), message = form.querySelector('[data-support-save-status]'); if (button.disabled) return; button.disabled = true;
        pendingSave ||= {request_key: key(), expected_version: review.head_version, snapshot_id: review.snapshot_id, action: 'manual', run_id: null, analysis_revision: null, hypothesis_id: null, diagnosis: form.elements.diagnosis.value, diagnosis_code: null, basis: form.elements.basis.value, uncertainties: form.elements.uncertainties.value, reviewed: form.elements.reviewed.checked};
        try { const receipt = await api(`${base}/diagnosis-review`, pendingSave, csrf); pendingSave = null; message.textContent = `Сохранено сервером · версия ${receipt.version}. Текст в полях оставлен.`; await loadDoctor(); }
        catch (error) { if (error.status === 409) { pendingSave = null; review = null; } message.textContent = error.message + ' Текст сохранён в полях. При конфликте обновите сведения перед новой редакцией.'; }
        finally { button.disabled = !review?.snapshot_id; }
      };
    }
    function schedule() { clearTimeout(timer); if (!document.hidden) timer = setTimeout(async () => { if (!root.contains(document.activeElement)) await load(); schedule(); }, 30000); }
    document.addEventListener('visibilitychange', () => { if (document.hidden) clearTimeout(timer); else { load(); schedule(); } });
    load(); schedule();
  }
})();
