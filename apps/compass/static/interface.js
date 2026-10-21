/* Progressive section navigation. No medical writes or remote storage. */
(() => {
  const kind = document.querySelector('select[name="kind"]');
  if (kind) {
    const update = () => document.querySelectorAll('[data-decision-fields]').forEach(group => {
      group.hidden = group.dataset.decisionFields === 'therapy' ? !kind.value.startsWith('therapy_') : kind.value !== 'referral';
    });
    kind.addEventListener('change', update);
    update();
  }
  const error = document.querySelector('[role="alert"]:not([hidden])');
  if (error && error.id !== 'critical-banner') { error.tabIndex = -1; error.focus(); }
  function openLinkedDetails() {
    let element;
    try { element = document.getElementById(decodeURIComponent(location.hash.slice(1))); } catch (_) { return; }
    for (let item = element; item; item = item.parentElement) {
      if (item.tagName === 'DETAILS') item.open = true;
    }
  }
  window.addEventListener('hashchange', openLinkedDetails);
  openLinkedDetails();
  const container = document.querySelector('.patient-panels');
  if (!container) return;
  const panels = [...container.querySelectorAll(':scope > [data-panel]')];
  const navigation = document.querySelector('[data-panel-nav]');
  function reveal(focus = false) {
    let anchor = '';
    try { anchor = decodeURIComponent(location.hash.slice(1)); } catch (_) { /* malformed fragment */ }
    const target = document.getElementById(anchor);
    const requested = target?.closest('[data-panel]');
    const name = requested?.dataset.panel || (anchor === 'main' ? container.dataset.currentPanel : null) || container.dataset.defaultPanel;
    container.dataset.currentPanel = name;
    const primary = document.querySelector('[data-today-primary]');
    if (primary) primary.hidden = name !== 'overview';
    panels.forEach(panel => { panel.hidden = panel.dataset.panel !== name; });
    navigation.querySelectorAll('a[href*="#"]').forEach(link => {
      const dest = document.getElementById(link.hash.slice(1));
      if (dest?.closest('[data-panel]')?.dataset.panel === name) link.setAttribute('aria-current', 'location');
      else link.removeAttribute('aria-current');
    });
    if (target) {
      let ancestor = target.parentElement;
      while (ancestor && ancestor !== container) {
        if (ancestor.tagName === 'DETAILS') ancestor.open = true;
        ancestor = ancestor.parentElement;
      }
    }
    if (focus) {
      const heading = (requested || panels.find(panel => !panel.hidden))?.querySelector('h2');
      if (heading) { heading.tabIndex = -1; heading.focus({preventScroll: true}); }
      (target || container).scrollIntoView({block:'start'});
    }
  }
  window.addEventListener('hashchange', () => reveal(true));
  reveal(false);
  const failure = container.querySelector('[role="alert"]');
  if (failure) { failure.tabIndex = -1; failure.focus(); failure.scrollIntoView({block:'start'}); }
})();
