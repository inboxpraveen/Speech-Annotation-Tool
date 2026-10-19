/* Project workspace: records table, review flow, jobs, import and export. */
(function () {
  const project = window.PROJECT;
  const engines = window.ENGINES || [];
  const me = window.ME;
  const pid = project.id;
  const state = { page: 1, perPage: 50, total: 0, records: [], selected: new Set(), claims: {}, lastRefresh: 0, activeJob: null };
  const body = document.getElementById('recordsBody');

  // Header --------------------------------------------------------------------
  function renderHeader(p) {
    const engine = engines.find(e => e.id === p.provider);
    document.getElementById('hTitle').textContent = p.name;
    document.getElementById('hName').textContent = p.name;
    document.getElementById('hRoot').textContent = p.root_path;
    document.getElementById('hEngine').innerHTML = '<span class="badge text-bg-light border">' + SAT.esc(engine ? engine.name : p.provider) + '</span> ' +
      '<span class="badge text-bg-light border">' + SAT.esc(p.model) + '</span> ' +
      '<span class="badge text-bg-light border">' + (p.language ? SAT.esc(p.language) : 'auto language') + '</span> ' +
      '<span class="badge text-bg-light border">' + (p.chunk_mode === 'none' ? 'no chunking' : p.chunk_mode + ' chunks, ~' + p.chunk_seconds + 's') + '</span>' +
      (p.watch_minutes ? ' <span class="badge text-bg-light border">rescan every ' + p.watch_minutes + ' min</span>' : '') +
      (p.auto_transcribe ? ' <span class="badge text-bg-light border">auto transcribe</span>' : '');
  }

  function renderStats(s) {
    if (!s) return;
    const item = (v, label, cls) => '<div class="stat"><div class="value ' + (cls || '') + '">' + v + '</div><div class="label">' + label + '</div></div>';
    const total = s.records || 0;
    document.getElementById('statsRow').innerHTML =
      item(s.files ? s.files.total : 0, 'files' + (s.files && s.files.missing ? ' (' + s.files.missing + ' missing)' : '')) +
      item(total, 'records') + item(s.pending || 0, 'pending') + item(s.done || 0, 'transcribed') +
      item(s.failed || 0, 'failed', s.failed ? 'text-danger' : '') + item(s.reviewed || 0, 'reviewed') +
      item(s.approved || 0, 'approved', 'text-success') + item(s.rejected || 0, 'rejected') +
      item(SAT.fmtDuration(s.seconds), 'audio');
    document.getElementById('btnTranscribe').disabled = !s.pending;
    document.getElementById('btnRetry').disabled = !s.failed;
    const job = (s.active_jobs || []).find(j => j.status === 'running') || (s.active_jobs || [])[0];
    const panel = document.getElementById('jobPanel');
    state.activeJob = job || null;
    panel.classList.toggle('d-none', !job);
    if (job) {
      document.getElementById('jobTitle').textContent = job.title + ' ';
      document.getElementById('jobMessage').textContent = (job.status === 'paused' ? 'paused. ' : job.status === 'queued' ? 'queued. ' : '') + (job.message || '') + (job.total ? ' (' + (job.done + job.failed) + '/' + job.total + (job.failed ? ', ' + job.failed + ' failed' : '') + ')' : '');
      document.getElementById('jobProgress').innerHTML = SAT.jobProgress(job);
      document.getElementById('jobSpinner').classList.toggle('d-none', job.status !== 'running');
      document.getElementById('jobPause').classList.toggle('d-none', job.status !== 'running');
      document.getElementById('jobResume').classList.toggle('d-none', job.status !== 'paused');
    }
  }

  ['jobPause', 'jobResume', 'jobCancel'].forEach(id => document.getElementById(id).addEventListener('click', async () => {
    if (!state.activeJob) return;
    const action = { jobPause: 'pause', jobResume: 'resume', jobCancel: 'cancel' }[id];
    try { await SAT.api('POST', '/api/jobs/' + state.activeJob.id + '/' + action); SAT.pollNow(); } catch (e) { SAT.toast(e.message, 'danger'); }
  }));

  // Records ----------------------------------------------------------------------
  function filters() {
    return {
      q: document.getElementById('fQuery').value.trim(),
      status: document.getElementById('fStatus').value,
      review: document.getElementById('fReview').value,
      sort: document.getElementById('fSort').value,
      edited: document.getElementById('fEdited').checked ? '1' : '',
    };
  }

  function recordParams() {
    const f = filters();
    const params = new URLSearchParams({ page: state.page, per_page: state.perPage, sort: f.sort });
    if (f.q) params.set('q', f.q);
    if (f.status) params.set('status', f.status);
    if (f.review) params.set('review', f.review);
    if (f.edited) params.set('edited', '1');
    return params;
  }

  async function loadRecords() {
    state.lastRefresh = Date.now();
    try {
      const data = await SAT.api('GET', '/api/projects/' + pid + '/records?' + recordParams().toString());
      state.reloadPending = false;
      state.records = data.items; state.total = data.total;
      renderRecords();
      const pages = Math.max(1, Math.ceil(state.total / state.perPage));
      document.getElementById('pageLabel').textContent = 'Page ' + state.page + ' of ' + pages;
      document.getElementById('pageInfo').textContent = state.total + ' records match';
      document.getElementById('pagePrev').disabled = state.page <= 1;
      document.getElementById('pageNext').disabled = state.page >= pages;
    } catch (e) { SAT.toast(e.message, 'danger'); }
  }

  function rowHtml(r, index) {
    const claimedOther = r.claimed_by && r.claimed_by !== me.id;
    const value = r.corrected_text != null ? r.corrected_text : (r.text || '');
    const timing = r.start_sec != null ? SAT.fmtClock(r.start_sec) + ' - ' + SAT.fmtClock(r.end_sec) : '';
    const missing = r.file_status === 'missing';
    return '<tr data-id="' + r.id + '" data-index="' + index + '" class="' + (state.selected.has(r.id) ? 'selected ' : '') + (claimedOther ? 'claimed-other' : '') + '">' +
      '<td><input type="checkbox" class="form-check-input sel" ' + (state.selected.has(r.id) ? 'checked' : '') + '></td>' +
      '<td>' + (missing ? '<div class="text-danger small">audio file is missing</div>' : '<audio controls preload="none" src="/api/records/' + r.id + '/audio"></audio>') +
      '<div class="path mt-1" title="' + SAT.esc(r.rel_path) + '">' + SAT.esc(r.rel_path) + (r.segment_index || r.start_sec != null ? ' <span class="text-primary">#' + r.segment_index + '</span>' : '') + '</div>' +
      '<div class="small text-secondary">' + (timing ? timing + ' · ' : '') + (r.duration ? SAT.fmtDuration(r.duration) : '') + (r.model ? ' · ' + SAT.esc(r.model) : '') + (r.detected_language ? ' · ' + SAT.esc(r.detected_language) : '') + '</div>' +
      '<div class="mt-1 d-flex flex-wrap gap-1 align-items-center">' + SAT.statusBadge(r.status) + (r.file_status === 'changed' ? SAT.statusBadge('changed') : '') +
      (claimedOther ? '<span class="badge text-bg-danger"><i class="bi bi-pencil"></i> ' + SAT.esc(r.claimed_by_name || 'someone') + ' is editing</span>' : '') +
      '<span class="btn-group btn-group-sm ms-auto"><button class="btn btn-link btn-sm p-0 px-1 text-secondary" data-act="speed" title="Playback speed">1x</button><button class="btn btn-link btn-sm p-0 px-1 text-secondary" data-act="retranscribe" title="Transcribe this record again"><i class="bi bi-arrow-repeat"></i></button><button class="btn btn-link btn-sm p-0 px-1 text-secondary" data-act="history" title="Edit history"><i class="bi bi-clock-history"></i></button></span></div>' +
      (r.error ? '<div class="small text-danger mt-1">' + SAT.esc(r.error) + '</div>' : '') + '</td>' +
      '<td><div class="machine-text">' + (r.status === 'pending' ? '<span class="text-secondary">waiting for transcription</span>' : r.status === 'processing' ? '<span class="text-primary">transcribing...</span>' : SAT.esc(r.text || '')) + '</div></td>' +
      '<td><textarea class="form-control corrected" rows="3" ' + (claimedOther ? 'readonly' : '') + '>' + SAT.esc(value) + '</textarea>' +
      '<input type="text" class="form-control form-control-sm mt-1 notes" placeholder="notes" value="' + SAT.esc(r.notes || '') + '"></td>' +
      '<td><div class="d-flex flex-wrap flex-lg-column align-items-center align-items-lg-stretch gap-1">' +
      '<div>' + SAT.statusBadge(r.review) + (r.updated_by_name ? '<div class="small text-secondary">' + SAT.esc(r.updated_by_name) + ', ' + SAT.ago(r.updated_at) + '</div>' : '') + '</div>' +
      '<button class="btn btn-sm btn-primary" data-act="save" title="Save corrected text (Ctrl+Enter)"><i class="bi bi-check-lg"></i> Save</button>' +
      '<div class="btn-group btn-group-sm"><button class="btn btn-outline-success" data-act="approve" title="Save and approve (Alt+A)"><i class="bi bi-hand-thumbs-up"></i></button><button class="btn btn-outline-danger" data-act="reject" title="Save and reject"><i class="bi bi-hand-thumbs-down"></i></button><button class="btn btn-outline-secondary" data-act="skip" title="Mark as skipped"><i class="bi bi-skip-forward"></i></button></div>' +
      '</div></td></tr>';
  }

  function renderRecords() {
    body.innerHTML = state.records.length ? state.records.map(rowHtml).join('') : '<tr><td colspan="5" class="text-secondary py-4 text-center">No records match. Scan the folder or change the filters.</td></tr>';
    updateSelection();
  }

  function rowOf(el) { return el.closest('tr[data-id]'); }
  function recordOf(tr) { return state.records.find(r => r.id === Number(tr.dataset.id)); }

  // Live updates must never re-render a row under the user: one they are typing in,
  // have focus in, or are listening to. Replacing the row would stop the audio.
  function rowBusy(tr) {
    if (tr.classList.contains('dirty') || tr.contains(document.activeElement)) return true;
    const audio = tr.querySelector('audio');
    return !!audio && !audio.paused;
  }
  function tableBusy() { return Array.from(body.querySelectorAll('tr[data-id]')).some(rowBusy); }

  async function saveRow(tr, extra) {
    const r = recordOf(tr);
    if (!r) return null;
    const text = tr.querySelector('textarea.corrected').value;
    const notes = tr.querySelector('input.notes').value;
    const payload = Object.assign({ corrected_text: text, notes: notes, version: r.version }, extra || {});
    if (!payload.review) payload.review = r.review === 'none' ? 'reviewed' : r.review;
    try {
      const updated = await SAT.api('PUT', '/api/records/' + r.id, payload);
      Object.assign(r, updated);
      tr.classList.remove('dirty');
      tr.outerHTML = rowHtml(r, Number(tr.dataset.index));
      return r;
    } catch (e) {
      if (e.status === 409 && e.data && e.data.record) {
        // Show the newer record but keep what this user typed, so nothing is lost.
        SAT.toast('Someone else saved this record while you were editing. Your text is kept; check the history and save again to replace theirs.', 'warning', { delay: 9000 });
        Object.assign(r, e.data.record);
        tr.outerHTML = rowHtml(r, Number(tr.dataset.index));
        const fresh = body.querySelector('tr[data-id="' + r.id + '"]');
        fresh.querySelector('textarea.corrected').value = text;
        fresh.querySelector('input.notes').value = notes;
        fresh.classList.add('dirty');
      } else {
        SAT.toast(e.message, 'danger');
      }
      return null;
    }
  }

  function focusRow(index) {
    const tr = body.querySelector('tr[data-index="' + index + '"]');
    if (!tr) return;
    const ta = tr.querySelector('textarea.corrected');
    if (ta) { ta.focus(); tr.scrollIntoView({ block: 'center', behavior: 'smooth' }); }
  }

  body.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-act]');
    const tr = rowOf(e.target);
    if (!tr) return;
    if (e.target.classList.contains('sel')) {
      const id = Number(tr.dataset.id);
      e.target.checked ? state.selected.add(id) : state.selected.delete(id);
      tr.classList.toggle('selected', e.target.checked);
      updateSelection();
      return;
    }
    if (!btn) return;
    const act = btn.dataset.act;
    const r = recordOf(tr);
    if (act === 'save') await saveRow(tr);
    if (act === 'approve') await saveRow(tr, { review: 'approved' });
    if (act === 'reject') await saveRow(tr, { review: 'rejected' });
    if (act === 'skip') await saveRow(tr, { status: 'skipped', review: r.review });
    if (act === 'speed') {
      const audio = tr.querySelector('audio');
      const speeds = [1, 1.25, 1.5, 2, 0.75];
      const next = speeds[(speeds.indexOf(audio.playbackRate) + 1) % speeds.length];
      audio.playbackRate = next; btn.textContent = next + 'x';
    }
    if (act === 'retranscribe') {
      try { await SAT.api('POST', '/api/projects/' + pid + '/transcribe', { record_ids: [r.id] }); SAT.toast('Queued for transcription', 'success'); } catch (err) { SAT.toast(err.message, 'danger'); }
    }
    if (act === 'history') showHistory(r.id);
  });

  // Claims expire after claim_timeout_seconds (Settings), so typing renews the claim
  // every 20 seconds; a long edit is not handed to someone else halfway through.
  async function claim(tr, input) {
    tr.dataset.claimedAt = Date.now();
    try {
      await SAT.api('POST', '/api/records/' + tr.dataset.id + '/claim');
    } catch (err) {
      if (err.status === 409) { SAT.toast((err.data && err.data.claimed_by_name || 'Someone') + ' is editing this record right now', 'warning'); if (input) input.blur(); }
    }
  }

  body.addEventListener('input', (e) => {
    const tr = rowOf(e.target);
    if (!tr || !e.target.matches('textarea, input.notes')) return;
    tr.classList.add('dirty');
    if (Date.now() - Number(tr.dataset.claimedAt || 0) > 20000) claim(tr);
  });

  body.addEventListener('focusin', (e) => {
    const tr = rowOf(e.target);
    if (!tr || !e.target.matches('textarea.corrected')) return;
    body.querySelectorAll('tr.active-row').forEach(x => x.classList.remove('active-row'));
    tr.classList.add('active-row');
    SAT.pollContext.record_id = Number(tr.dataset.id);
    claim(tr, e.target);
  });

  body.addEventListener('focusout', (e) => {
    const tr = rowOf(e.target);
    if (!tr || !e.target.matches('textarea.corrected')) return;
    if (!tr.classList.contains('dirty')) {
      SAT.pollContext.record_id = null;
      SAT.api('POST', '/api/records/' + tr.dataset.id + '/release').catch(() => { });
    }
  });

  body.addEventListener('keydown', async (e) => {
    const tr = rowOf(e.target);
    if (!tr) return;
    const index = Number(tr.dataset.index);
    if (e.ctrlKey && e.key === 'Enter') { e.preventDefault(); if (await saveRow(tr)) focusRow(index + 1); }
    else if (e.altKey && (e.key === 'a' || e.key === 'A')) { e.preventDefault(); if (await saveRow(tr, { review: 'approved' })) focusRow(index + 1); }
    else if (e.altKey && e.key === 'ArrowDown') { e.preventDefault(); focusRow(index + 1); }
    else if (e.altKey && e.key === 'ArrowUp') { e.preventDefault(); focusRow(index - 1); }
    else if (e.ctrlKey && e.code === 'Space') {
      e.preventDefault();
      const audio = tr.querySelector('audio');
      if (audio) audio.paused ? audio.play() : audio.pause();
    }
  });

  // Pause other players when one starts.
  body.addEventListener('play', (e) => { body.querySelectorAll('audio').forEach(a => { if (a !== e.target) a.pause(); }); }, true);

  // Selection and bulk actions ------------------------------------------------------
  function updateSelection() {
    document.getElementById('selCount').textContent = state.selected.size;
    document.querySelectorAll('[data-bulk]').forEach(b => b.disabled = state.selected.size === 0);
  }
  // The header checkbox on wide screens, "Select page" in the bulk bar on small ones.
  ['selAll', 'selPage'].forEach(id => document.getElementById(id).addEventListener('change', (e) => {
    // Toggle in place: re-rendering would drop unsaved text and stop playing audio.
    const on = e.target.checked;
    document.getElementById('selAll').checked = document.getElementById('selPage').checked = on;
    body.querySelectorAll('tr[data-id]').forEach(tr => {
      const rid = Number(tr.dataset.id);
      on ? state.selected.add(rid) : state.selected.delete(rid);
      tr.classList.toggle('selected', on);
      tr.querySelector('input.sel').checked = on;
    });
    updateSelection();
  }));
  document.getElementById('bulkBar').addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-bulk]');
    if (!btn || !state.selected.size) return;
    const ids = Array.from(state.selected);
    const action = btn.dataset.bulk;
    if (action === 'delete' && !(await SAT.confirm('Delete ' + ids.length + ' records? The audio files stay on disk.', 'Delete'))) return;
    try {
      if (action === 'retranscribe') await SAT.api('POST', '/api/projects/' + pid + '/transcribe', { record_ids: ids });
      else await SAT.api('POST', '/api/projects/' + pid + '/records/bulk', { ids: ids, action: action });
      state.selected.clear();
      SAT.toast('Done', 'success');
      loadRecords();
    } catch (err) { SAT.toast(err.message, 'danger'); }
  });

  // Filters and paging ----------------------------------------------------------------
  ['fStatus', 'fReview', 'fSort', 'fEdited'].forEach(id => document.getElementById(id).addEventListener('change', () => { state.page = 1; loadRecords(); }));
  document.getElementById('fPerPage').addEventListener('change', (e) => { state.perPage = Number(e.target.value); state.page = 1; loadRecords(); });
  let qTimer;
  document.getElementById('fQuery').addEventListener('input', () => { clearTimeout(qTimer); qTimer = setTimeout(() => { state.page = 1; loadRecords(); }, 350); });
  document.getElementById('pagePrev').addEventListener('click', () => { if (state.page > 1) { state.page--; loadRecords(); window.scrollTo(0, 0); } });
  document.getElementById('pageNext').addEventListener('click', () => { state.page++; loadRecords(); window.scrollTo(0, 0); });

  // Header actions --------------------------------------------------------------------
  document.getElementById('btnScan').addEventListener('click', async () => {
    try { await SAT.api('POST', '/api/projects/' + pid + '/scan', {}); SAT.toast('Scanning the folder', 'success'); SAT.pollNow(); } catch (e) { SAT.toast(e.message, 'danger'); }
  });
  document.getElementById('btnTranscribe').addEventListener('click', async () => {
    try { await SAT.api('POST', '/api/projects/' + pid + '/transcribe', {}); SAT.toast('Transcription job queued', 'success'); SAT.pollNow(); } catch (e) { SAT.toast(e.message, 'danger'); }
  });
  document.getElementById('btnRetry').addEventListener('click', async () => {
    try { await SAT.api('POST', '/api/projects/' + pid + '/transcribe', { retry_failed: true }); SAT.toast('Retrying failed records', 'success'); SAT.pollNow(); } catch (e) { SAT.toast(e.message, 'danger'); }
  });
  document.getElementById('btnDelete').addEventListener('click', async (e) => {
    e.preventDefault();
    if (!(await SAT.confirm('Delete project "' + project.name + '" and all its records? Audio files on disk are not touched.', 'Delete project'))) return;
    try { await SAT.api('DELETE', '/api/projects/' + pid); window.location = '/'; } catch (err) { SAT.toast(err.message, 'danger'); }
  });

  // Live updates ------------------------------------------------------------------------
  window.addEventListener('sat:status', (ev) => {
    const d = ev.detail;
    if (!d.project) return;
    renderStats(d.project);
    // Re-render a row only when someone else starts or stops editing it.
    const claims = {};
    (d.project.claims || []).forEach(c => claims[c.id] = c);
    const byOther = id => !!id && id !== me.id;
    state.records.forEach(r => {
      const c = claims[r.id];
      if (byOther(c && c.claimed_by) === byOther(r.claimed_by)) return;
      const tr = body.querySelector('tr[data-id="' + r.id + '"]');
      if (!tr || rowBusy(tr)) return;
      r.claimed_by = c ? c.claimed_by : null;
      r.claimed_by_name = c ? c.claimed_by_name : null;
      tr.outerHTML = rowHtml(r, Number(tr.dataset.index));
    });
    // A scan or import added or removed records, or a job finished: reload the page of rows,
    // but wait until nobody is typing or listening on it.
    const activeCount = (d.project.active_jobs || []).length;
    if (state.knownRecords !== undefined && (state.knownRecords !== d.project.records || activeCount < state.knownActive)) state.reloadPending = true;
    state.knownRecords = d.project.records;
    state.knownActive = activeCount;
    const due = Date.now() - state.lastRefresh > 4000;
    if (state.reloadPending && due && !tableBusy()) { loadRecords(); return; }
    const running = (d.project.active_jobs || []).some(j => j.status === 'running');
    const hasPending = state.records.some(r => r.status === 'pending' || r.status === 'processing');
    if (running && hasPending && due) refreshVisible();
  });

  // Fetch the rows on screen by id and update the ones a job changed, skipping busy rows.
  async function refreshVisible() {
    state.lastRefresh = Date.now();
    if (!state.records.length) return;
    const params = new URLSearchParams({ per_page: state.records.length, ids: state.records.map(r => r.id).join(',') });
    try {
      const data = await SAT.api('GET', '/api/projects/' + pid + '/records?' + params.toString());
      data.items.forEach(nr => {
        const old = state.records.find(r => r.id === nr.id);
        const tr = body.querySelector('tr[data-id="' + nr.id + '"]');
        if (old && tr && (old.status !== nr.status || old.version !== nr.version) && !rowBusy(tr)) {
          Object.assign(old, nr);
          tr.outerHTML = rowHtml(old, Number(tr.dataset.index));
        }
      });
    } catch (e) { }
  }

  // Project settings ----------------------------------------------------------------------
  const sEngine = document.getElementById('sEngine');
  const sModel = document.getElementById('sModel');
  const sModelCustom = document.getElementById('sModelCustom');

  function renderEngineOptions(engineId, current) {
    const e = engines.find(x => x.id === engineId);
    const wrap = document.getElementById('sEngineOptions');
    if (!e || !e.options || !e.options.length) { wrap.innerHTML = ''; return; }
    wrap.innerHTML = '<h6 class="mt-2">Engine options for this project</h6><div class="row g-2">' + e.options.map(o => {
      const v = current && current[o.key] !== undefined ? current[o.key] : '';
      if (o.type === 'bool') {
        return '<div class="col-md-6"><select class="form-select form-select-sm" data-opt="' + o.key + '"><option value="">' + SAT.esc(o.label) + ': default</option><option value="true"' + (v === true ? ' selected' : '') + '>' + SAT.esc(o.label) + ': yes</option><option value="false"' + (v === false ? ' selected' : '') + '>' + SAT.esc(o.label) + ': no</option></select></div>';
      }
      const def = o.default === undefined || o.default === null || o.default === '' ? '' : ' (default: ' + o.default + ')';
      return '<div class="col-md-6"><input class="form-control form-control-sm" data-opt="' + o.key + '" placeholder="' + SAT.esc(o.label + def) + '" value="' + SAT.esc(v === null ? '' : v) + '"></div>';
    }).join('') + '</div><div class="help">Blank fields use the defaults from the Providers page.</div>';
  }

  function sEngineChanged() {
    const e = engines.find(x => x.id === sEngine.value);
    if (!e) return;
    SAT.fillModelPicker(e, sModel, sModelCustom, e.id === project.provider ? project.model : null);
    document.getElementById('sEngineHelp').textContent = e.description;
    document.getElementById('sLanguageHelp').textContent = e.language_hint || '';
    renderEngineOptions(e.id, e.id === project.provider ? (project.options.engine_options || {}) : {});
  }
  sEngine.addEventListener('change', sEngineChanged);
  document.getElementById('btnSettings').addEventListener('click', (e) => {
    e.preventDefault();
    document.getElementById('sName').value = project.name;
    document.getElementById('sRoot').value = project.root_path;
    sEngine.innerHTML = SAT.engineOptions(engines, project.provider);
    sEngineChanged();
    document.getElementById('sLanguage').value = project.language || '';
    document.getElementById('sChunkMode').value = project.chunk_mode;
    document.getElementById('sChunkSeconds').value = project.chunk_seconds;
    document.getElementById('sWatch').value = project.watch_minutes;
    document.getElementById('sAuto').checked = !!project.auto_transcribe;
    document.getElementById('sDescription').value = project.description || '';
    document.getElementById('sError').classList.add('d-none');
    bootstrap.Modal.getOrCreateInstance(document.getElementById('settingsModal')).show();
  });
  document.getElementById('sBrowse').addEventListener('click', async () => {
    const p = await SAT.pickPath({ start: document.getElementById('sRoot').value });
    if (p) document.getElementById('sRoot').value = p;
  });
  document.getElementById('sSave').addEventListener('click', async () => {
    const opts = {};
    document.querySelectorAll('#sEngineOptions [data-opt]').forEach(el => {
      const v = el.value;
      if (v === '') return;
      opts[el.dataset.opt] = v === 'true' ? true : v === 'false' ? false : v;
    });
    const payload = {
      name: document.getElementById('sName').value, root_path: document.getElementById('sRoot').value,
      provider: sEngine.value, model: SAT.pickedModel(sModel, sModelCustom), language: document.getElementById('sLanguage').value,
      chunk_mode: document.getElementById('sChunkMode').value, chunk_seconds: document.getElementById('sChunkSeconds').value,
      watch_minutes: document.getElementById('sWatch').value, auto_transcribe: document.getElementById('sAuto').checked,
      description: document.getElementById('sDescription').value, options: Object.assign({}, project.options, { engine_options: opts }),
    };
    try {
      await SAT.api('PUT', '/api/projects/' + pid, payload);
      const fresh = await SAT.api('GET', '/api/projects/' + pid);
      Object.assign(project, fresh);
      renderHeader(project);
      bootstrap.Modal.getInstance(document.getElementById('settingsModal')).hide();
      SAT.toast('Project settings saved', 'success');
    } catch (e) { const el = document.getElementById('sError'); el.textContent = e.message; el.classList.remove('d-none'); }
  });

  // Import ------------------------------------------------------------------------------------
  let sniffed = null;
  document.getElementById('btnImport').addEventListener('click', (e) => { e.preventDefault(); bootstrap.Modal.getOrCreateInstance(document.getElementById('importModal')).show(); });
  document.getElementById('iBrowse').addEventListener('click', async () => {
    const p = await SAT.pickPath({ files: 'csv,tsv,xlsx,json,jsonl', start: project.root_path, title: 'Choose a data file' });
    if (p) document.getElementById('iPath').value = p;
  });
  document.getElementById('iUpload').addEventListener('change', async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    const fd = new FormData(); fd.append('file', f);
    try { const res = await SAT.api('POST', '/api/import/upload', fd); document.getElementById('iPath').value = res.path; sniff(); } catch (err) { SAT.toast(err.message, 'danger'); }
  });
  async function sniff() {
    const path = document.getElementById('iPath').value.trim();
    const errEl = document.getElementById('iError');
    errEl.classList.add('d-none');
    try {
      sniffed = await SAT.api('POST', '/api/import/sniff', { path: path });
      const opts = (sel, cols, guess, allowNone) => {
        sel.innerHTML = (allowNone ? '<option value="">(none)</option>' : '') + cols.map(c => '<option value="' + SAT.esc(c) + '"' + (c === guess ? ' selected' : '') + '>' + SAT.esc(c) + '</option>').join('');
      };
      opts(document.getElementById('iColAudio'), sniffed.columns, sniffed.guess.audio, false);
      opts(document.getElementById('iColText'), sniffed.columns, sniffed.guess.text, true);
      opts(document.getElementById('iColCorrected'), sniffed.columns, sniffed.guess.corrected, true);
      const table = document.getElementById('iPreview');
      table.innerHTML = '<thead><tr>' + sniffed.columns.map(c => '<th>' + SAT.esc(c) + '</th>').join('') + '</tr></thead><tbody>' +
        sniffed.preview.map(r => '<tr>' + sniffed.columns.map(c => '<td class="truncate" style="max-width:200px">' + SAT.esc(r[c]) + '</td>').join('') + '</tr>').join('') + '</tbody>';
      document.getElementById('iMapping').classList.remove('d-none');
      document.getElementById('iStart').disabled = false;
    } catch (e) { errEl.textContent = e.message; errEl.classList.remove('d-none'); }
  }
  document.getElementById('iSniff').addEventListener('click', sniff);
  document.getElementById('iStart').addEventListener('click', async () => {
    const payload = {
      path: document.getElementById('iPath').value.trim(),
      mapping: { audio: document.getElementById('iColAudio').value, text: document.getElementById('iColText').value, corrected: document.getElementById('iColCorrected').value },
      mode: document.getElementById('iMode').value, base_dir: document.getElementById('iBase').value.trim(), mark_reviewed: document.getElementById('iReviewed').checked,
    };
    try {
      await SAT.api('POST', '/api/projects/' + pid + '/import', payload);
      bootstrap.Modal.getInstance(document.getElementById('importModal')).hide();
      SAT.toast('Import started. You will be notified when it finishes.', 'success');
      SAT.pollNow();
    } catch (e) { const el = document.getElementById('iError'); el.textContent = e.message; el.classList.remove('d-none'); }
  });

  // Export ----------------------------------------------------------------------------------------
  document.getElementById('btnExport').addEventListener('click', (e) => {
    e.preventDefault();
    document.getElementById('eName').value = project.name;
    loadExports();
    bootstrap.Modal.getOrCreateInstance(document.getElementById('exportModal')).show();
  });
  document.getElementById('eFormat').addEventListener('change', (e) => {
    document.getElementById('eZip').disabled = document.getElementById('eWav').disabled = e.target.value !== 'audiofolder';
  });
  document.getElementById('eFormat').dispatchEvent(new Event('change'));
  async function loadExports() {
    try {
      const data = await SAT.api('GET', '/api/exports');
      const el = document.getElementById('eList');
      el.innerHTML = data.items.length ? '<ul class="list-unstyled mb-0">' + data.items.slice(0, 15).map(x =>
        '<li class="d-flex justify-content-between border-bottom py-1"><span class="font-monospace truncate">' + (x.is_dir ? '<i class="bi bi-folder"></i> ' : '<a href="/api/exports/' + encodeURIComponent(x.name) + '">') + SAT.esc(x.name) + (x.is_dir ? '' : '</a>') + '</span><span class="text-secondary">' + (x.size != null ? SAT.fmtBytes(x.size) : 'folder') + ' <button class="btn btn-link btn-sm p-0 text-danger" data-del-export="' + SAT.esc(x.name) + '" title="Delete"><i class="bi bi-trash"></i></button></span></li>').join('') + '</ul>'
        : '<span class="text-secondary">No exports yet. Files land in data/exports.</span>';
    } catch (e) { }
  }
  document.getElementById('eList').addEventListener('click', async (e) => {
    const b = e.target.closest('[data-del-export]');
    if (!b) return;
    if (!(await SAT.confirm('Delete export ' + b.dataset.delExport + '?', 'Delete'))) return;
    try { await SAT.api('DELETE', '/api/exports/' + encodeURIComponent(b.dataset.delExport)); loadExports(); } catch (err) { SAT.toast(err.message, 'danger'); }
  });
  document.getElementById('eStart').addEventListener('click', async () => {
    const payload = {
      format: document.getElementById('eFormat').value, text_source: document.getElementById('eText').value, name: document.getElementById('eName').value,
      review: Array.from(document.querySelectorAll('.eReview:checked')).map(x => x.value),
      zip: document.getElementById('eZip').checked, convert_wav: document.getElementById('eWav').checked, skip_empty: document.getElementById('eSkipEmpty').checked,
    };
    try {
      await SAT.api('POST', '/api/projects/' + pid + '/export', payload);
      SAT.toast('Export started. A notification will tell you when the file is ready.', 'success');
      bootstrap.Modal.getInstance(document.getElementById('exportModal')).hide();
      SAT.pollNow();
    } catch (e) { SAT.toast(e.message, 'danger'); }
  });

  // Files -------------------------------------------------------------------------------------------
  const fl = { page: 1 };
  async function loadFiles() {
    const params = new URLSearchParams({ page: fl.page, per_page: 100 });
    const q = document.getElementById('flQuery').value.trim();
    const st = document.getElementById('flStatus').value;
    if (q) params.set('q', q);
    if (st) params.set('status', st);
    try {
      const data = await SAT.api('GET', '/api/projects/' + pid + '/files?' + params.toString());
      document.getElementById('flBody').innerHTML = data.items.map(f => '<tr><td class="font-monospace">' + SAT.esc(f.rel_path) + '</td><td>' + SAT.statusBadge(f.status) + (f.error ? '<div class="text-danger">' + SAT.esc(f.error) + '</div>' : '') + '</td><td>' + SAT.fmtDuration(f.duration) + '</td><td>' + SAT.fmtBytes(f.size) + '</td><td>' + f.records + '</td><td><button class="btn btn-link btn-sm p-0" data-file-filter="' + f.id + '">show records</button></td></tr>').join('') || '<tr><td colspan="6" class="text-secondary">No files</td></tr>';
      document.getElementById('flInfo').textContent = data.total + ' files';
      document.getElementById('flPrev').disabled = fl.page <= 1;
      document.getElementById('flNext').disabled = fl.page * 100 >= data.total;
    } catch (e) { SAT.toast(e.message, 'danger'); }
  }
  document.getElementById('btnFiles').addEventListener('click', (e) => { e.preventDefault(); fl.page = 1; loadFiles(); bootstrap.Modal.getOrCreateInstance(document.getElementById('filesModal')).show(); });
  document.getElementById('flQuery').addEventListener('input', () => { fl.page = 1; loadFiles(); });
  document.getElementById('flStatus').addEventListener('change', () => { fl.page = 1; loadFiles(); });
  document.getElementById('flPrev').addEventListener('click', () => { fl.page--; loadFiles(); });
  document.getElementById('flNext').addEventListener('click', () => { fl.page++; loadFiles(); });
  document.getElementById('flReprepare').addEventListener('click', async () => {
    try { await SAT.api('POST', '/api/projects/' + pid + '/scan', { reprepare: true }); SAT.toast('Scan with re-preparation queued', 'success'); } catch (e) { SAT.toast(e.message, 'danger'); }
  });
  document.getElementById('flBody').addEventListener('click', (e) => {
    const b = e.target.closest('[data-file-filter]');
    if (!b) return;
    bootstrap.Modal.getInstance(document.getElementById('filesModal')).hide();
    document.getElementById('fQuery').value = b.closest('tr').querySelector('td').textContent;
    state.page = 1; loadRecords();
  });

  // History ----------------------------------------------------------------------------------------
  async function showHistory(recordId) {
    try {
      const data = await SAT.api('GET', '/api/records/' + recordId + '/history');
      document.getElementById('historyBody').innerHTML = data.items.length ? data.items.map(h =>
        '<div class="border-bottom py-2"><div class="small text-secondary">' + SAT.esc(h.user_name || 'system') + ' · ' + SAT.fmtTime(h.created_at) + (h.review ? ' · ' + SAT.esc(h.review) : '') + '</div>' +
        (h.new_text != null ? '<div class="small"><span class="text-danger">' + SAT.esc(h.old_text || '') + '</span></div><div>' + SAT.esc(h.new_text) + '</div>' : '') + '</div>').join('')
        : '<div class="text-secondary">No edits yet.</div>';
      bootstrap.Modal.getOrCreateInstance(document.getElementById('historyModal')).show();
    } catch (e) { SAT.toast(e.message, 'danger'); }
  }

  window.addEventListener('beforeunload', (e) => { if (body.querySelector('tr.dirty')) { e.preventDefault(); e.returnValue = ''; } });

  renderHeader(project);
  SAT.api('GET', '/api/projects/' + pid).then(p => { Object.assign(project, p); renderStats(p.stats); });
  loadRecords();
})();
