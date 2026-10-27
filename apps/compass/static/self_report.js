/* Отправка самоотчёта. Ответы остаются на странице, пока сервер не подтвердил запись.
   Повтор после обрыва отправляет то же тело с тем же ключом: второй записи не будет. Без fetch работает обычная форма. */
(() => {
  const form = document.querySelector('[data-report-form]');
  if (!form) return;
  const draft = form.reportDraft;
  const submit = form.querySelector('#report-submit');
  const unsaved = form.querySelector('[data-unsaved-status]');
  const error = form.querySelector('[data-send-error]');
  const retry = form.querySelector('[data-send-retry]');
  const newReport = form.querySelector('[data-new-report]');
  const fields = [...form.elements].filter(f => f.name && f.type !== 'hidden' && f.type !== 'button' && f.type !== 'submit' && !f.hasAttribute('data-draft-save') && !f.hasAttribute('data-draft-delete'));
  const submitLabel = submit.textContent;
  let dirty = form.dataset.hasError === 'yes', sending = false, pending = null, needsSession = false, done = false;

  if (dirty) {
    unsaved.textContent = 'Запись не сохранена. Введённые ответы оставлены в форме, проверьте поля.';
    const problem = document.getElementById('record-error');
    if (problem) { problem.tabIndex = -1; problem.focus(); }
  }
  function markDirty() { dirty = true; unsaved.textContent = 'Самоотчёт ещё не отправлен врачу.'; }
  form.addEventListener('input', markDirty);
  form.addEventListener('change', markDirty);
  function lock(locked) { fields.forEach(f => { f.disabled = locked; }); }
  function fail(text) {
    error.replaceChildren();
    const p = document.createElement('p');
    p.textContent = text;
    error.append(p);
    error.hidden = false;
    error.focus();
  }
  retry.addEventListener('click', () => form.requestSubmit(submit));
  form.addEventListener('submit', async event => {
    if (!window.fetch || !window.AbortController) { dirty = false; return; }
    event.preventDefault();
    if (sending) return;
    if (!pending && !form.reportValidity()) return;
    // Тело и ключ повтора замораживаются: сбойный ответ может значить, что сервер запись уже принял.
    if (!pending) pending = new URLSearchParams(new FormData(form));
    sending = true;
    dirty = true;
    lock(true);
    submit.disabled = true;
    retry.hidden = true;
    submit.setAttribute('aria-busy', 'true');
    form.setAttribute('aria-busy', 'true');
    error.hidden = true;
    unsaved.textContent = 'Ждём подтверждения сервера. Не закрывайте страницу.';
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 20000);
    try {
      if (draft && submit.dataset.draftReady !== 'yes') {
        if (!await draft.flush()) {
          pending = null;
          lock(false);
          unsaved.textContent = 'Самоотчёт не отправлен врачу. Ответы оставлены в форме.';
          fail('Не удалось подтвердить сохранение черновика. Сначала сохраните черновик, затем отправьте самоотчёт. Ответы остались в форме.');
          return;
        }
        draft.pause();
        submit.dataset.draftReady = 'yes';
        pending.set('draft_revision', form.elements.draft_revision.value);
        pending.set('csrf', form.elements.csrf.value);
      }
      if (needsSession) {
        // Новый вход меняет защитный токен: берём только его, ответы и ключ повтора не трогаем.
        const session = await fetch(window.location.href, {credentials: 'same-origin', cache: 'no-store', signal: controller.signal});
        if (!session.ok || new URL(session.url).pathname === '/login') {
          fail('Войдите в кабинет в другой вкладке, затем повторите отправку здесь. Ответы остались на этой странице.');
          return;
        }
        const page = new DOMParser().parseFromString(await session.text(), 'text/html');
        const csrf = page.querySelector('input[name="csrf"]')?.value;
        if (!csrf) throw new Error('No session token');
        pending.set('csrf', csrf);
        form.elements.csrf.value = csrf;
        needsSession = false;
      }
      const response = await fetch(form.action, {method: 'POST', body: pending,
        headers: {'Accept': 'application/json'}, credentials: 'same-origin', signal: controller.signal});
      const data = response.headers.get('content-type')?.includes('application/json') ? await response.json() : null;
      if (response.ok && data?.location) {
        const target = new URL(data.location, window.location.href);
        if (target.origin !== window.location.origin || !target.hash.startsWith('#entry-')) throw new Error('Unexpected receipt');
        dirty = false;
        done = true;
        pending = null;
        unsaved.textContent = 'Сохранено на сервере. Открываем запись.';
        window.location.assign(target.href);
      } else if (response.status === 400 && data?.error) {
        pending = null;
        delete submit.dataset.draftReady;
        draft?.resume();
        lock(false);
        unsaved.textContent = 'Самоотчёт не отправлен врачу. Исправьте ответы и отправьте снова.';
        fail(data.error + ' Введённые ответы оставлены в форме.');
      } else if (response.status === 401 || response.status === 403 || (response.redirected && new URL(response.url).pathname === '/login')) {
        needsSession = true;
        fail('Не удалось подтвердить доступ. Войдите в кабинет в другой вкладке, затем повторите отправку здесь. Ответы остались на этой странице.');
      } else if (response.status === 409 && data?.error) {
        newReport.hidden = false;
        fail(data.error + ' Ответы остались на этой странице. При необходимости скопируйте их, затем откройте новую форму в другой вкладке.');
      } else {
        fail((data?.error || 'Сервер не подтвердил сохранение.') +
          ' Ответы остались на этой странице. Повторите ту же отправку: вторая такая запись не создастся.');
      }
    } catch (_) {
      fail('Не удалось подтвердить сохранение: связь прервалась или сервер не ответил. Ответы остались на этой странице. Повторите ту же отправку: вторая такая запись не создастся.');
    } finally {
      clearTimeout(timer);
      sending = false;
      form.removeAttribute('aria-busy');
      submit.removeAttribute('aria-busy');
      submit.disabled = done || !newReport.hidden;
      retry.hidden = !pending || !newReport.hidden;
      submit.textContent = done ? 'Отправлено' : pending ? 'Повторить отправку' : submitLabel;
      if (!newReport.hidden) unsaved.textContent = 'Сервер отклонил эту отправку. Скопируйте нужное перед открытием новой формы.';
      else if (pending) unsaved.textContent = 'Сохранение не подтверждено. Редактирование приостановлено до ответа сервера. Сохранённый черновик можно открыть после обновления страницы.';
    }
  });
  window.addEventListener('beforeunload', event => {
    if (dirty && (!draft || !draft.clean())) { event.preventDefault(); event.returnValue = ''; }
  });
})();
