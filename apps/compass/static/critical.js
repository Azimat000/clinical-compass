/* Visibility receipt is transport evidence, never an assertion of human reading. */
(() => {
  const banner = document.getElementById('critical-banner');
  if (!banner) return;
  let busy = false;
  const visible = element => {
    if (!element || element.hidden) return false;
    const box = element.getBoundingClientRect();
    return box.width > 0 && box.height > 0 && box.top < innerHeight && box.bottom > 0 && box.left < innerWidth && box.right > 0;
  };
  async function poll() {
    if (busy || document.visibilityState !== 'visible') return;
    busy = true;
    try {
      const response = await fetch('/api/critical', {cache: 'no-store'});
      if (!response.ok) throw new Error('unavailable');
      const events = await response.json();
      const cards = document.querySelectorAll('[data-critical-event]');
      banner.hidden = events.length === 0;
      document.getElementById('critical-connection').textContent = '';
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      if (document.visibilityState === 'visible') {
        const ids = new Set([...events.filter(e => !e.received && visible(banner)).map(e => e.id), ...[...cards].filter(visible).map(c => c.dataset.criticalEvent)]);
        for (const id of ids) {
          const receipt = await fetch(`/critical/${encodeURIComponent(id)}/received`, {
            method: 'POST', headers: {'X-CSRF-Token': banner.dataset.csrf}
          });
          if (!receipt.ok) throw new Error('receipt unavailable');
        }
      }
    } catch (_) {
      banner.hidden = false;
      document.getElementById('critical-connection').textContent = ' Связь не подтверждена. Обновите страницу. При закрытом кабинете веб-сигнала нет.';
    } finally { busy = false; }
  }
  poll();
  setInterval(poll, 3000);
  document.addEventListener('visibilitychange', poll);
})();
