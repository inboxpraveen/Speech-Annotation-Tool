/* Projects overview and the new project dialog. */
(function () {
  const engines = window.ENGINES || [];
  const grid = document.getElementById('projectGrid');
  let projects = [];

  function card(p) {
    const s = p.stats;
    const total = s.records || 0;
    const donePct = total ? Math.round(100 * (s.done || 0) / total) : 0;
    const reviewPct = total ? Math.round(100 * ((s.reviewed || 0) + (s.approved || 0) + (s.rejected || 0)) / total) : 0;
    const job = (s.active_jobs || [])[0];
    const engine = engines.find(e => e.id === p.provider);
    return '<div class="col-md-6 col-xxl-4"><div class="card project-card h-100">' +
      '<div class="card-body d-flex flex-column">' +
      '<div class="d-flex justify-content-between align-items-start gap-2">' +
      '<div class="flex-grow-1" style="min-width:0"><a href="/projects/' + p.id + '" class="h5 text-decoration-none d-block mb-1">' + SAT.esc(p.name) + '</a>' +
      '<div class="small text-secondary font-monospace truncate" title="' + SAT.esc(p.root_path) + '">' + SAT.esc(p.root_path) + '</div></div>' +
      '<span class="badge text-bg-light border flex-shrink-0">' + SAT.esc(engine ? engine.name.split(' (')[0] : p.provider) + '</span></div>' +
      '<div class="small text-secondary mt-1">' + SAT.esc(p.model) + (p.language ? ' · ' + SAT.esc(p.language) : ' · auto language') + (p.chunk_mode !== 'none' ? ' · ' + p.chunk_mode + ' chunks' : '') + (p.watch_minutes ? ' · rescans every ' + p.watch_minutes + ' min' : '') + '</div>' +
      '<div class="d-flex gap-3 mt-3 flex-wrap">' +
      stat(s.files ? s.files.total : 0, 'files') + stat(total, 'records') + stat(s.done || 0, 'transcribed') + stat(s.failed || 0, 'failed', s.failed ? 'text-danger' : '') + stat((s.approved || 0), 'approved') +
      '</div>' +
      '<div class="mt-3"><div class="d-flex justify-content-between small text-secondary"><span>Transcribed ' + donePct + '%</span><span>Reviewed ' + reviewPct + '%</span></div>' +
      '<div class="progress progress-thin mt-1"><div class="progress-bar" style="width:' + donePct + '%"></div></div>' +
      '<div class="progress progress-thin mt-1"><div class="progress-bar bg-success" style="width:' + reviewPct + '%"></div></div></div>' +
      (job ? '<div class="small mt-2"><span class="spinner-border spinner-border-sm text-primary me-1"></span>' + SAT.esc(job.title) + ': ' + SAT.esc(job.message || job.status) + '</div>' : '') +
      '<div class="mt-auto pt-3 d-flex gap-2">' +
      '<a class="btn btn-sm btn-primary" href="/projects/' + p.id + '"><i class="bi bi-pencil-square"></i> Open</a>' +
      '<button class="btn btn-sm btn-outline-secondary" data-scan="' + p.id + '"><i class="bi bi-arrow-repeat"></i> Scan</button>' +
      '<button class="btn btn-sm btn-outline-secondary" data-transcribe="' + p.id + '"' + (s.pending ? '' : ' disabled') + '><i class="bi bi-play-fill"></i> Transcribe ' + (s.pending || 0) + '</button>' +
      '</div></div></div></div>';
  }

  function stat(v, label, cls) {
    return '<div class="stat"><div class="value ' + (cls || '') + '">' + v + '</div><div class="label">' + label + '</div></div>';
  }

  async function load() {
    try {
      const data = await SAT.api('GET', '/api/projects');
      projects = data.items;
      grid.innerHTML = projects.length ? projects.map(card).join('') :
        '<div class="col-12"><div class="card"><div class="card-body text-center py-5 text-secondary">No projects yet. Create one and point it at a folder of audio.</div></div></div>';
    } catch (e) { SAT.toast(e.message, 'danger'); }
  }

  grid.addEventListener('click', async (e) => {
    const scan = e.target.closest('[data-scan]');
    const tr = e.target.closest('[data-transcribe]');
    try {
      if (scan) { await SAT.api('POST', '/api/projects/' + scan.dataset.scan + '/scan', {}); SAT.toast('Scan started', 'success'); }
      if (tr) { await SAT.api('POST', '/api/projects/' + tr.dataset.transcribe + '/transcribe', {}); SAT.toast('Transcription started', 'success'); }
      if (scan || tr) setTimeout(load, 800);
    } catch (err) { SAT.toast(err.message, 'danger'); }
  });

  window.addEventListener('sat:status', (ev) => {
    const d = ev.detail;
    const online = document.getElementById('onlineList');
    online.innerHTML = (d.online || []).length ? d.online.map(o => {
      const p = o.project_id ? projects.find(x => x.id === o.project_id) : null;
      const where = p ? ('in ' + p.name + (o.record_id ? ', record #' + o.record_id : '')) : (o.page || 'browsing');
      return '<li class="list-group-item d-flex align-items-center gap-2"><span class="avatar m-0">' + SAT.esc(SAT.initials(o.display_name)) + '</span><div><div>' + SAT.esc(o.display_name) + '</div><div class="small text-secondary">' + SAT.esc(where) + '</div></div></li>';
    }).join('') : '<li class="list-group-item text-secondary small">Nobody yet</li>';
    const jobs = document.getElementById('activeJobs');
    jobs.innerHTML = (d.jobs || []).length ? d.jobs.map(j => '<li class="list-group-item"><div class="d-flex justify-content-between small"><strong class="truncate">' + SAT.esc(j.title) + '</strong>' + SAT.statusBadge(j.status) + '</div>' + SAT.jobProgress(j) + '<div class="small text-secondary mt-1">' + SAT.esc(j.message || '') + '</div></li>').join('')
      : '<li class="list-group-item text-secondary small">No active jobs</li>';
    if (d.jobs && d.jobs.some(j => j.status === 'running')) load();
  });

  // New project dialog ------------------------------------------------------------
  const modalEl = document.getElementById('projectModal');
  const engineSel = document.getElementById('pEngine');
  const modelSel = document.getElementById('pModel');
  const modelCustom = document.getElementById('pModelCustom');

  function engineChanged() {
    const e = engines.find(x => x.id === engineSel.value);
    if (!e) return;
    SAT.fillModelPicker(e, modelSel, modelCustom);
    document.getElementById('pEngineHelp').textContent = e.description;
    document.getElementById('pLanguageHelp').textContent = e.language_hint || '';
  }

  document.getElementById('newProjectBtn').addEventListener('click', () => {
    engineSel.innerHTML = SAT.engineOptions(engines, engines.find(e => e.kind === 'local' && e.installed) ? 'faster_whisper' : engines[0].id);
    engineChanged();
    document.getElementById('pError').classList.add('d-none');
    bootstrap.Modal.getOrCreateInstance(modalEl).show();
  });
  engineSel.addEventListener('change', engineChanged);
  document.getElementById('pBrowse').addEventListener('click', async () => {
    const path = await SAT.pickPath({ start: document.getElementById('pRoot').value });
    if (path) {
      document.getElementById('pRoot').value = path;
      if (!document.getElementById('pName').value) document.getElementById('pName').value = path.split(/[\\/]/).filter(Boolean).pop() || '';
    }
  });
  document.getElementById('pSave').addEventListener('click', async () => {
    const btn = document.getElementById('pSave');
    btn.disabled = true;
    const body = {
      name: document.getElementById('pName').value,
      root_path: document.getElementById('pRoot').value,
      provider: engineSel.value,
      model: SAT.pickedModel(modelSel, modelCustom),
      language: document.getElementById('pLanguage').value,
      chunk_mode: document.getElementById('pChunkMode').value,
      chunk_seconds: document.getElementById('pChunkSeconds').value,
      watch_minutes: document.getElementById('pWatch').value,
      auto_transcribe: document.getElementById('pAuto').checked,
      transcribe_after_scan: document.getElementById('pTranscribeNow').checked,
      description: document.getElementById('pDescription').value,
    };
    try {
      const res = await SAT.api('POST', '/api/projects', body);
      bootstrap.Modal.getInstance(modalEl).hide();
      SAT.toast('Project created, scanning the folder now', 'success');
      window.location = '/projects/' + res.id;
    } catch (e) {
      const el = document.getElementById('pError');
      el.textContent = e.message; el.classList.remove('d-none');
    } finally { btn.disabled = false; }
  });

  load();
})();
