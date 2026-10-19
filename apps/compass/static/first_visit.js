/* One server form, four presentation steps. No local/remote draft storage. */
(() => {
  const form = document.querySelector('[data-visit-form]');
  if (!form) return;
  const steps = [...form.querySelectorAll('[data-visit-step]')];
  const links = [...document.querySelectorAll('.visit-steps a')];
  const controls = form.querySelector('[data-step-controls]');
  const back = controls.querySelector('[data-step-back]');
  const next = controls.querySelector('[data-step-next]');
  const status = form.querySelector('[data-unsaved-status]');
  let current = 1, dirty = form.dataset.hasError === 'yes';
  function show(number, focus) {
    current = number;
    steps.forEach(step => { step.hidden = Number(step.dataset.visitStep) !== number; });
    links.forEach((link, i) => {
      if (i + 1 === number) link.setAttribute('aria-current', 'step');
      else link.removeAttribute('aria-current');
    });
    controls.hidden = false;
    back.disabled = number === 1;
    next.disabled = number === 4;
    if (focus) steps[number - 1].querySelector('h3').focus();
  }
  function fromHash(focus) {
    const step = steps.find(item => '#' + item.id === location.hash);
    if (step) show(Number(step.dataset.visitStep), focus);
    // A summary link must reveal step 4; historical anchors stay accessible below.
    else if (location.hash === '#visit-summary') show(4, focus);
  }
  links.forEach((link, i) => link.addEventListener('click', () => show(i + 1, true)));
  back.addEventListener('click', () => { location.hash = 'visit-step-' + (current - 1); });
  next.addEventListener('click', () => { location.hash = 'visit-step-' + (current + 1); });
  window.addEventListener('hashchange', () => fromHash(true));
  if (form.dataset.hasError !== 'yes') { show(1, false); fromHash(false); }
  // With server errors all fields remain visible, so the error cannot hide its input.
  else status.textContent = 'Ошибка: изменения не сохранены. Проверьте сведения во всех шагах.';
  function markDirty() { dirty = true; status.textContent = 'Есть несохранённые изменения. Сохраните черновик перед выходом.'; }
  form.addEventListener('input', markDirty);
  form.addEventListener('change', markDirty);
  // Native validation also works for fields in an inactive presentation step.
  form.addEventListener('invalid', event => {
    const step = event.target.closest('[data-visit-step]');
    if (step) show(Number(step.dataset.visitStep), false);
  }, true);
  form.addEventListener('submit', () => { dirty = false; });
  window.addEventListener('beforeunload', event => {
    if (dirty) { event.preventDefault(); event.returnValue = ''; }
  });
})();
