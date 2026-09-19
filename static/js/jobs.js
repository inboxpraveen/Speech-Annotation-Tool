/* Jobs page: list, controls and live logs. */
(function () {
  const st = { page: 1, logJob: null, logAfter: 0, logTimer: null };
  const body = document.getElementById('jBody');

  function row(j) {
    const pct = j.total ? Math.round(100 * (j.done + j.failed) / j.total) : (j.status === 'completed' ? 100 : 0);
    const controls = [];
    if (j.status === 'running' || j.status === 'queued') controls.push('<button class="btn btn-outline-secondary" data-action="pause" title="Pause"><i class="bi bi-pause-fill"></i></button>');
    if (j.status === 'paused' || j.status === 'failed' || j.status === 'cancelled') controls.push('<button class="btn btn-outline-primary" data-action="resume" title="Resume or retry"><i class="bi bi-play-fill"></i></button>');
    if (j.status === 'running' || j.status === 'queued' || j.status === 'paused') controls.push('<button class="btn btn-outline-danger" data-action="cancel" title="Stop"><i class="bi bi-x-lg"></i></button>');
    if (j.status === 'completed' || j.status === 'failed' || j.status === 'cancelled') controls.push('<button class="btn btn-outline-secondary" data-action="delete" title="Remove from list"><i class="bi bi-trash"></i></button>');
    const download = j.result && j.result.download ? '<a class="btn btn-sm btn-outline-success ms-1" href="/api/exports/' + encodeURIComponent(j.result.download) + '"><i class="bi bi-download"></i> file</a>' : '';
    return '<tr data-id="' + j.id + '"><td class="text-secondary">' + j.id + '</td>' +
      '<td><div>' + SAT.esc(j.title) + '</div><div class="small text-secondary">' + SAT.esc(j.message || '') + '</div></td>' +
      '<td>' + (j.project_id ? '<a href="/projects/' + j.project_id + '">' + SAT.esc(j.project_name || '') + '</a>' : '') + '</td>' +
      '<td>' + SAT.jobProgress(j) + '<div class="small text-secondary">' + (j.total ? pct + '% (' + (j.done + j.failed) + '/' + j.total + (j.failed ? ', ' + j.failed + ' failed' : '') + ')' : (j.done ? j.done + ' done' : '')) + '</div></td>' +
      '<td>' + SAT.statusBadge(j.status) + '</td><td>' + SAT.esc(j.created_by_name || 'system') + '</td>' +
      '<td class="small text-secondary">' + SAT.ago(j.created_at) + (j.finished_at ? '<br>finished ' + SAT.ago(j.finished_at) : '') + '</td>' +
      '<td class="text-nowrap"><div class="btn-group btn-group-sm">' + controls.join('') + '<button class="btn btn-outline-secondary" data-action="log" title="Log"><i class="bi bi-journal-text"></i></button></div>' + download + '</td></tr>';
  }

  async function load() {
    const params = new URLSearchParams({ page: st.page, per_page: 30 });
    const f = document.getElementById('jFilter').value;
    if (f) params.set('status', f);
    try {
      const data = await SAT.api('GET', '/api/jobs?' + params.toString());
      body.innerHTML = data.items.length ? data.items.map(row).join('') : '<tr><td colspan="8" class="text-secondary">No jobs</td></tr>';
      document.getElementById('jInfo').textContent = data.total + ' jobs';
      document.getElementById('jPrev').disabled = st.page <= 1;
      document.getElementById('jNext').disabled = st.page * 30 >= data.total;
    } catch (e) { SAT.toast(e.message, 'danger'); }
  }

  body.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-action]');
    if (!btn) return;
    const id = btn.closest('tr').dataset.id;
    const action = btn.dataset.action;
    try {
      if (action === 'log') { openLog(id); return; }
      if (action === 'delete') await SAT.api('DELETE', '/api/jobs/' + id);
      else await SAT.api('POST', '/api/jobs/' + id + '/' + action);
      setTimeout(load, 500);
    } catch (err) { SAT.toast(err.message, 'danger'); }
  });

  async function openLog(id) {
    st.logJob = id; st.logAfter = 0;
    document.getElementById('logView').innerHTML = '';
    document.getElementById('logTitle').textContent = 'Job #' + id;
    const modalEl = document.getElementById('logModal');
    bootstrap.Modal.getOrCreateInstance(modalEl).show();
    modalEl.addEventListener('hidden.bs.modal', () => { st.logJob = null; clearTimeout(st.logTimer); }, { once: true });
    pollLog();
  }

  async function pollLog() {
    if (!st.logJob) return;
    try {
      const job = await SAT.api('GET', '/api/jobs/' + st.logJob);
      document.getElementById('logMeta').textContent = job.title + ' · ' + job.status + ' · ' + (job.message || '') + (job.total ? ' · ' + (job.done + job.failed) + '/' + job.total : '');
      const data = await SAT.api('GET', '/api/jobs/' + st.logJob + '/logs?after=' + st.logAfter);
      const view = document.getElementById('logView');
      data.items.forEach(l => {
        st.logAfter = l.id;
        const div = document.createElement('div');
        div.className = l.level;
        div.textContent = SAT.fmtTime(l.created_at) + ' [' + l.level + '] ' + l.message;
        view.appendChild(div);
      });
      if (data.items.length) view.scrollTop = view.scrollHeight;
      if (job.status === 'running' || job.status === 'queued') st.logTimer = setTimeout(pollLog, 2000);
    } catch (e) { }
  }

  document.getElementById('jFilter').addEventListener('change', () => { st.page = 1; load(); });
  document.getElementById('jPrev').addEventListener('click', () => { st.page--; load(); });
  document.getElementById('jNext').addEventListener('click', () => { st.page++; load(); });
  document.getElementById('jClear').addEventListener('click', async () => {
    if (!(await SAT.confirm('Remove all finished jobs from the list?', 'Clear'))) return;
    try { await SAT.api('POST', '/api/jobs/clear'); load(); } catch (e) { SAT.toast(e.message, 'danger'); }
  });
  window.addEventListener('sat:status', (ev) => { if ((ev.detail.jobs || []).some(j => j.status === 'running') || document.getElementById('jFilter').value.includes('running')) load(); });
  load();
})();
