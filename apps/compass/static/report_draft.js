/* Private server draft; no browser storage and no clinical submission. */
(() => {
  const form = document.querySelector('[data-report-form]');
  if (!form || !window.fetch || !window.AbortController) return;
  const status = form.querySelector('[data-draft-status]');
  const saveButton = form.querySelector('[data-draft-save]');
  const deleteButton = form.querySelector('[data-draft-delete]');
  form.querySelector('[data-draft-help]').textContent = 'Черновик сохраняется автоматически при вводе. Дождитесь подтверждения перед закрытием страницы. Врач увидит ответы только после отправки самоотчёта.';
  const currentLink = form.querySelector('[data-draft-current]');
  const controls = [...form.querySelectorAll('input,select,textarea')].filter(e => !['csrf','draft_revision'].includes(e.name));
  const snapshot = () => new URLSearchParams(controls.filter(e => e.name).map(e => [e.name,e.value]));
  let savedMessage = status.textContent;
  let saved = form.dataset.draftRestored === 'yes' ? snapshot().toString() : null;
  let pending = null, running = null, timer = null, paused = false, conflict = false, discarded = false, needsSession = false, changed = false;
  function message(text) {
    form.querySelectorAll('[data-draft-status],[data-draft-status-copy]').forEach(item => { if (item.textContent !== text) item.textContent = text; });
  }
  function schedule() {
    clearTimeout(timer);
    if (!paused && !conflict) timer = setTimeout(() => flush(), 600);
  }
  async function request(body, keepalive) {
    const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 10000);
    try {
      if (needsSession) {
        const response = await fetch(location.href, {credentials:'same-origin',cache:'no-store',signal:controller.signal});
        const doc = new DOMParser().parseFromString(await response.text(),'text/html');
        const token = doc.querySelector('input[name="csrf"]')?.value;
        if (!response.ok || new URL(response.url).pathname === '/login' || !token) throw Error('Войдите в кабинет в другой вкладке, затем сохраните черновик здесь.');
        form.elements.csrf.value = token;
        needsSession = false;
      }
      body.set('csrf',form.elements.csrf.value);
      const response = await fetch(form.dataset.draftUrl,{method:'POST',body,keepalive,credentials:'same-origin',
        headers:{Accept:'application/json'},signal:controller.signal});
      const data = response.headers.get('content-type')?.includes('application/json') ? await response.json() : null;
      if (response.status === 403 || response.status === 401 || (response.redirected && new URL(response.url).pathname === '/login')) {
        needsSession = true;
        throw Error('Войдите в кабинет в другой вкладке, затем сохраните черновик здесь.');
      }
      if (!response.ok || !Number.isInteger(data?.revision)) {
        if (response.status === 409) { conflict = true; currentLink.hidden = false; }
        throw Error(data?.error || 'Сервер не подтвердил сохранение черновика.');
      }
      form.elements.draft_revision.value = data.revision;
      return data;
    } finally { clearTimeout(timeout); }
  }
  async function flush(keepalive = false) {
    clearTimeout(timer);
    if (running) { return await running ? flush(keepalive) : false; }
    if (conflict) return false;
    if (!pending && saved === snapshot().toString()) { message(savedMessage); return true; }
    // One request at a time; an uncertain save is repeated byte-for-byte before newer edits.
    running = (async () => {
      try {
        do {
          if (!pending) {
            const body = snapshot();
            pending = {signature:body.toString(),body};
            body.set('draft_revision',form.elements.draft_revision.value);
            body.set('draft_action','save');
          }
          message('Сохраняем личный черновик…');
          const data = await request(pending.body,keepalive);
          saved = pending.signature;
          pending = null;
          changed = saved !== snapshot().toString();
          const at = new Date(data.updated_at).toLocaleTimeString('ru-RU',{timeZone:'Europe/Moscow'});
          savedMessage = 'Черновик сохранён в '+at+' МСК. Доступен после повторного входа; врачу не отправлен.';
          message(savedMessage);
        } while (saved !== snapshot().toString());
        return true;
      } catch (error) {
        message('Сохранение черновика не подтверждено: '+(error instanceof TypeError || error.name === 'AbortError' ? 'Нет связи с сервером или время ожидания истекло.' : error.message)+' Введённые ответы оставлены на странице. Не закрывайте её до подтверждения сохранения.');
        return false;
      } finally { running = null; }
    })();
    return running;
  }
  function markChanged() {
    if (conflict) { message('Черновик изменён в другой вкладке. Текущие ответы оставлены на этой странице и не сохранены.'); return; }
    changed = !!pending || saved !== snapshot().toString();
    if (!changed) { clearTimeout(timer); message(savedMessage); return; }
    message('Есть изменения черновика, которые ещё не сохранены.'); schedule();
  }
  form.addEventListener('input', markChanged);
  form.addEventListener('change', markChanged);
  saveButton.type = deleteButton.type = 'button';
  saveButton.addEventListener('click', () => flush());
  deleteButton.addEventListener('click', async () => {
    if (!window.confirm('Удалить личный черновик и очистить этот бланк? Отправленные самоотчёты останутся в истории.')) return;
    paused = true;
    clearTimeout(timer);
    saveButton.disabled = deleteButton.disabled = true;
    try {
      if (running) await running;
      if (pending && !await flush()) return;
      const body = new URLSearchParams({request_key:form.elements.request_key.value,
        draft_revision:form.elements.draft_revision.value,draft_action:'delete'});
      await request(body,false);
      discarded = true;
      message('Черновик удалён.');
      location.reload();
    } catch (error) { message('Удаление черновика не подтверждено: '+error.message+' Ответы оставлены на странице.'); }
    finally { saveButton.disabled = deleteButton.disabled = false; if (!discarded) paused = false; }
  });
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden' && !paused && !conflict && (changed || pending)) flush(true);
  });
  form.reportDraft = {
    flush,
    pause() { paused = true; clearTimeout(timer); saveButton.disabled = deleteButton.disabled = true; message('Черновик подготовлен к отправке. Ожидайте подтверждения отправки самоотчёта.'); },
    resume() { paused = false; saveButton.disabled = deleteButton.disabled = false; message(savedMessage); },
    clean() { return discarded || (!conflict && !pending && saved === snapshot().toString()); }
  };
})();
