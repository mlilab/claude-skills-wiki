const search = document.querySelector('#search');
if (search) {
  const filter = () => {
    const q = search.value.toLocaleLowerCase();
    sessionStorage.setItem('experiment-notebook-search', search.value);
    document.querySelectorAll('[data-search]').forEach(el => { el.hidden = !el.dataset.search.includes(q); });
  };
  search.value = sessionStorage.getItem('experiment-notebook-search') || '';
  search.addEventListener('input', filter);
  filter();
  const refresh = async () => {
    try {
      const response = await fetch('/api/status', {cache: 'no-store'});
      if (!response.ok) return;
      const data = await response.json();
      for (const row of data.experiments) {
        document.querySelectorAll(`[data-status="${CSS.escape(row.id)}"]`).forEach(el => {
          el.textContent = row.label;
          el.setAttribute('class', `badge ${row.observed_status}`);
          el.title = row.warning || `Recorded: ${row.recorded_status}`;
        });
        document.querySelectorAll(`[data-node-status="${CSS.escape(row.id)}"]`).forEach(el => {
          el.setAttribute('class', `graph-node ${row.observed_status}`);
        });
        document.querySelectorAll(`[data-observation="${CSS.escape(row.id)}"]`).forEach(el => {
          el.textContent = [row.summary, row.warning].filter(Boolean).join(' · ');
        });
      }
      document.querySelector('#observed-at').textContent = `${data.observed_label}: ${data.observed_at}`;
    } catch (_) { /* Static HTML also works without the server. */ }
  };
  refresh();
  setInterval(refresh, 20000);
}
