/* Два шага одного бланка. Личный черновик хранится отдельно от отправленных записей. */
(() => {
  const form = document.querySelector('[data-report-form]');
  if (!form) return;
  const draft = form.reportDraft;
  const steps = [...form.querySelectorAll('[data-report-step]')];
  const controls = form.querySelector('[data-step-controls]');
  const back = controls.querySelector('[data-step-back]');
  const next = controls.querySelector('[data-step-next]');
  const submit = form.querySelector('[data-report-submit]');
  const status = form.querySelector('[data-step-status]');
  const unsaved = form.querySelector('[data-unsaved-status]');
  const error = form.querySelector('[data-send-error]');
  const retry = form.querySelector('[data-send-retry]');
  const newReport = form.querySelector('[data-new-report]');
  const review = form.querySelector('[data-review]');
  const list = form.querySelector('[data-review-list]');
  const fields = [...steps[0].querySelectorAll('input:not([type="hidden"]),select,textarea')];
  let current = 1;
  let dirty = form.dataset.hasError === 'yes', sending = false, pending = null, needsSession = false;

  function label(field) {
    const box = field.closest('label');
    if (!box) return field.name;
    const clone = box.cloneNode(true);
    clone.querySelectorAll('select,input,textarea').forEach(item => item.remove());
    return clone.textContent.trim();
  }
  function buildReview() {
    list.replaceChildren();
    fields.forEach(field => {
      const dt = document.createElement('dt'), dd = document.createElement('dd');
      dt.textContent = label(field);
      dd.textContent = field.tagName === 'SELECT' ? field.options[field.selectedIndex].textContent.trim() : field.value.trim() || 'не заполнено';
      list.append(dt, dd);
    });
    review.hidden = false;
  }
  function show(number, focus) {
    current = number;
    steps.forEach(step => { step.hidden = Number(step.dataset.reportStep) !== number; });
    status.hidden = false;
    status.textContent = number === 1 ? 'Шаг 1 из 2. Заполнение' : 'Шаг 2 из 2. Проверка и отправка';
    controls.hidden = false;
    back.hidden = number === 1;
    next.hidden = number === 2;
    if (number === 2) buildReview();
    if (focus) steps[number - 1].querySelector('h3').focus();
  }
  back.addEventListener('click', () => show(1, true));
  next.addEventListener('click', () => {
    if (form.reportValidity()) show(2, true);
  });
  show(1, false);
  if (dirty) unsaved.textContent = 'Запись не сохранена. Введённые ответы оставлены в форме; проверьте поля во всех разделах.';
  form.addEventListener('invalid', event => {
    if (event.target.closest('[data-report-step]')?.hidden) show(1, false);
  }, true);
  function markDirty() {
    dirty = true;
    unsaved.textContent = 'Самоотчёт ещё не отправлен врачу.';
  }
  form.addEventListener('input', markDirty);
  form.addEventListener('change', markDirty);
  function lock(locked) {
    fields.forEach(field => { field.disabled = locked; });
    back.disabled = locked;
    next.disabled = locked;
  }
  function fail(message) {
    error.textContent = message;
    error.hidden = false;
    error.focus();
  }
  retry.addEventListener('click', () => form.requestSubmit(submit));
  form.addEventListener('submit', async event => {
    // Without fetch the browser keeps the ordinary server form behavior.
    if (!window.fetch || !window.AbortController) { dirty = false; return; }
    event.preventDefault();
    if (sending) return;
    if (!pending && !form.reportValidity()) return;
    if (!pending && current === 1) { show(2, true); return; }
    if (!pending) pending = new URLSearchParams(new FormData(form));
    // Retain the exact payload and request key until the server resolves this send.
    // A failed response may mean the server already committed the record.
    sending = true;
    dirty = true;
    show(2, false);
    lock(true);
    submit.disabled = true;
    retry.hidden = true;
    submit.textContent = 'Отправляем…';
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
          fail('Не удалось подтвердить сохранение черновика. Ответы оставлены в форме. Сначала сохраните черновик, затем отправьте самоотчёт.');
          return;
        }
        draft.pause();
        submit.dataset.draftReady = 'yes';
        pending.set('draft_revision', form.elements.draft_revision.value);
        pending.set('csrf', form.elements.csrf.value);
      }
      if (needsSession) {
        // A fresh login changes CSRF. Refresh only that transport token; keep the answers and request key.
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
        pending = null;
        lock(false);
        unsaved.textContent = 'Сохранено на сервере. Открываем запись.';
        // Changing only the fragment would leave the newly saved entry absent from the DOM.
        if (target.pathname === window.location.pathname && target.search === window.location.search) {
          window.location.hash = target.hash;
          window.location.reload();
        } else window.location.assign(target.href);
      } else if (response.status === 400 && data?.error) {
        pending = null;
        delete submit.dataset.draftReady;
        draft?.resume();
        lock(false);
        show(1, false);
        unsaved.textContent = 'Самоотчёт не отправлен врачу. Исправьте ответы и снова проверьте их.';
        fail(data.error + ' Введённые ответы оставлены в форме.');
      } else if (response.status === 401 || response.status === 403 || (response.redirected && new URL(response.url).pathname === '/login')) {
        needsSession = true;
        fail('Не удалось подтвердить доступ. Войдите в кабинет в другой вкладке, затем повторите отправку здесь. Ответы остались на этой странице.');
      } else if (response.status === 409 && data?.error) {
        newReport.hidden = false;
        fail(data.error + ' Ответы остались на этой странице. При необходимости скопируйте их в новую форму, открытую в другой вкладке.');
      } else {
        // Keep the payload frozen for auth/CSRF errors, conflicts and server faults too.
        fail((data?.error || 'Сервер не подтвердил сохранение.') +
          ' Ответы остались на этой странице. Повторите ту же отправку; повтор не создаст вторую такую запись.');
      }
    } catch (_) {
      fail('Не удалось подтвердить сохранение: связь прервалась или сервер не ответил. Ответы остались на этой странице. Повторите ту же отправку; повтор не создаст вторую такую запись.');
    } finally {
      clearTimeout(timer);
      sending = false;
      form.removeAttribute('aria-busy');
      submit.disabled = !newReport.hidden;
      retry.hidden = !pending || !newReport.hidden;
      submit.textContent = pending ? 'Повторить отправку' : 'Отправить самоотчёт';
      if (!newReport.hidden) unsaved.textContent = 'Сервер отклонил эту отправку. Скопируйте нужное перед открытием новой формы.';
      else if (pending) unsaved.textContent = 'Сохранение не подтверждено. До ответа сервера редактирование приостановлено. Сохранённый личный черновик можно восстановить после обновления страницы.';
    }
  });
  window.addEventListener('beforeunload', event => {
    if (dirty && (!draft || !draft.clean())) { event.preventDefault(); event.returnValue = ''; }
  });
})();
