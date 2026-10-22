/* Личный черновик на сервере. Без localStorage/sessionStorage, без отправки врачу.
   Автосохранение при вводе; неподтверждённое сохранение повторяется тем же телом до новых правок. */
(() => {
  const form = document.querySelector('[data-report-form]');
  if (!form || !window.fetch || !window.AbortController) return;
  const status = form.querySelector('[data-draft-status]');
  const saveButton = form.querySelector('[data-draft-save]');
  const deleteButton = form.querySelector('[data-draft-delete]');
  const currentLink = form.querySelector('[data-draft-current]');
  form.querySelector('[data-draft-help]').textContent = 'Черновик сохраняется при вводе. Дождитесь подтверждения перед закрытием страницы. Врач увидит ответы только после отправки.';
  const SKIP = ['csrf', 'draft_revision', 'draft_action'];
  // Читаем поля сами, а не через FormData: во время отправки поля отключены, а черновик должен остаться полным.
  const snapshot = () => {
    const pairs = [];
    for (const field of form.elements) {
      if (!field.name || SKIP.includes(field.name) || field.type === 'button' || field.type === 'submit' || field.type === 'fieldset') continue;
      if ((field.type === 'radio' || field.type === 'checkbox') && !field.checked) continue;
      pairs.push([field.name, field.value]);
    }
    return new URLSearchParams(pairs);
  };
  let savedMessage = status.textContent;
  let saved = form.dataset.draftRestored === 'yes' ? snapshot().toString() : null;
  let pending = null, running = null, timer = null, paused = false, conflict = false, discarded = false, needsSession = false, changed = false;

  function message(text) { if (status.textContent !== text) status.textContent = text; }
  function schedule() {
    clearTimeout(timer);
    if (!paused && !conflict) timer = setTimeout(() => flush(), 600);
  }
  async function request(body, keepalive) {
    const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 10000);
    try {
      if (needsSession) {
        // Новый вход меняет защитный токен: берём только его, ответы не трогаем.
        const response = await fetch(location.href, {credentials: 'same-origin', cache: 'no-store', signal: controller.signal});
        const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
        const token = doc.querySelector('input[name="csrf"]')?.value;
        if (!response.ok || new URL(response.url).pathname === '/login' || !token) throw Error('Войдите в кабинет в другой вкладке, затем сохраните черновик здесь.');
        form.elements.csrf.value = token;
        needsSession = false;
      }
      body.set('csrf', form.elements.csrf.value);
      const response = await fetch(form.dataset.draftUrl, {method: 'POST', body, keepalive, credentials: 'same-origin',
        headers: {Accept: 'application/json'}, signal: controller.signal});
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
    // Один запрос за раз; неподтверждённый повторяется байт в байт раньше новых правок.
    running = (async () => {
      try {
        do {
          if (!pending) {
            const body = snapshot();
            pending = {signature: body.toString(), body};
            body.set('draft_revision', form.elements.draft_revision.value);
            body.set('draft_action', 'save');
          }
          message('Сохраняем личный черновик…');
          const data = await request(pending.body, keepalive);
          saved = pending.signature;
          pending = null;
          changed = saved !== snapshot().toString();
          const at = new Date(data.updated_at).toLocaleTimeString('ru-RU', {timeZone: 'Europe/Moscow', hour: '2-digit', minute: '2-digit'});
          savedMessage = 'Черновик сохранён в ' + at + ' МСК. Доступен после повторного входа; врачу не отправлен.';
          message(savedMessage);
        } while (saved !== snapshot().toString());
        return true;
      } catch (error) {
        message('Сохранение черновика не подтверждено: ' + (error instanceof TypeError || error.name === 'AbortError' ? 'нет связи с сервером или время ожидания истекло.' : error.message) + ' Ответы остались на странице. Не закрывайте её до подтверждения.');
        return false;
      } finally { running = null; }
    })();
    return running;
  }
  function markChanged() {
    if (conflict) { message('Черновик изменён в другой вкладке. Текущие ответы остались на этой странице и не сохранены.'); return; }
    changed = !!pending || saved !== snapshot().toString();
    if (!changed) { clearTimeout(timer); message(savedMessage); return; }
    message('Есть изменения, которые ещё не сохранены.');
    schedule();
  }
  form.addEventListener('input', markChanged);
  form.addEventListener('change', markChanged);
  saveButton.type = deleteButton.type = 'button';
  saveButton.addEventListener('click', () => flush());
  deleteButton.addEventListener('click', async () => {
    paused = true;
    clearTimeout(timer);
    saveButton.disabled = deleteButton.disabled = true;
    try {
      if (running) await running;
      if (pending && !await flush()) return;
      const body = new URLSearchParams({request_key: form.elements.request_key.value,
        draft_revision: form.elements.draft_revision.value, draft_action: 'delete'});
      await request(body, false);
      discarded = true;
      message('Черновик удалён.');
      location.reload();
    } catch (error) { message('Удаление черновика не подтверждено: ' + error.message + ' Ответы остались на странице.'); }
    finally { saveButton.disabled = deleteButton.disabled = false; if (!discarded) paused = false; }
  });
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden' && !paused && !conflict && (changed || pending)) flush(true);
  });
  form.reportDraft = {
    flush,
    pause() { paused = true; clearTimeout(timer); saveButton.disabled = deleteButton.disabled = true; message('Черновик подготовлен к отправке. Ждём подтверждения сервера.'); },
    resume() { paused = false; saveButton.disabled = deleteButton.disabled = false; message(savedMessage); },
    clean() { return discarded || (!conflict && !pending && saved === snapshot().toString()); }
  };
})();
