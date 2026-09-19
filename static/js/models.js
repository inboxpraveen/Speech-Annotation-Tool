/* Local models page: catalog, downloads, cache. */
(function () {
  const cards = document.getElementById('engineCards');
  let data = null;

  function engineCard(e) {
    const rows = e.models.map(m => '<li class="list-group-item d-flex align-items-center gap-2">' +
      '<div class="flex-grow-1"><div><strong>' + SAT.esc(m.name) + '</strong> <span class="text-secondary small">' + SAT.esc(m.id) + '</span></div><div class="small text-secondary">' + SAT.esc(m.note || '') + '</div></div>' +
      (m.downloaded ? '<span class="badge text-bg-success">downloaded</span>' : '') +
      '<div class="btn-group btn-group-sm">' +
      (e.installed ? '<button class="btn btn-outline-primary" data-download="' + SAT.esc(m.id) + '" data-engine="' + e.id + '" title="Download now"><i class="bi bi-download"></i></button>' +
        '<button class="btn btn-outline-secondary" data-test="' + SAT.esc(m.id) + '" data-engine="' + e.id + '" title="Transcribe the sample clip with this model"><i class="bi bi-play"></i> Test</button>' : '') +
      '</div></li>').join('');
    return '<div class="card model-card mb-3"><div class="card-header bg-white d-flex justify-content-between align-items-center">' +
      '<div><strong>' + SAT.esc(e.name) + '</strong> ' + (e.installed ? '<span class="badge text-bg-success">installed</span>' : '<span class="badge text-bg-secondary">not installed</span>') + '<div class="small text-secondary">' + SAT.esc(e.description) + '</div></div></div>' +
      (e.installed ? '' : '<div class="card-body py-2 small">Install it in the app environment: <code>' + SAT.esc(e.pip_hint) + '</code>, then restart the app.</div>') +
      '<ul class="list-group list-group-flush">' + rows + '</ul>' +
      (e.installed && e.custom_model ? '<div class="card-body py-2"><div class="input-group input-group-sm"><input type="text" class="form-control" placeholder="' + SAT.esc(e.custom_model_hint || 'custom model id') + '" data-custom-input="' + e.id + '"><button class="btn btn-outline-primary" data-custom-download="' + e.id + '"><i class="bi bi-download"></i> Download custom</button><button class="btn btn-outline-secondary" data-custom-test="' + e.id + '"><i class="bi bi-play"></i> Test</button></div><div class="help mt-1">' + SAT.esc(e.language_hint || '') + '</div></div>' : '') +
      '</div>';
  }

  function render() {
    cards.innerHTML = data.engines.map(engineCard).join('');
    const c = data.capabilities;
    document.getElementById('capabilities').innerHTML =
      row('ffmpeg', c.ffmpeg ? (c.ffmpeg_version || 'found') : 'missing', c.ffmpeg) +
      row('torch', c.torch_version ? c.torch_version + (c.torch_cuda ? ' with CUDA' : ' (CPU)') : 'not installed', !!c.torch_version) +
      row('GPU', c.gpu_name || (c.torch_cuda || c.ctranslate2_cuda || c.onnx_cuda ? 'available' : 'none, running on CPU'), c.torch_cuda || c.ctranslate2_cuda || c.onnx_cuda) +
      row('faster-whisper', c.faster_whisper ? 'installed' + (c.ctranslate2_cuda ? ', CUDA' : ', CPU') : 'missing', c.faster_whisper) +
      row('onnx-asr', c.onnx_asr ? 'installed' + (c.onnx_cuda ? ', CUDA' : ', CPU') : 'missing', c.onnx_asr) +
      row('transformers', c.transformers ? 'installed' : 'missing', c.transformers) +
      row('qwen-asr', c.qwen_asr ? 'installed' : 'optional, not installed', c.qwen_asr);
    const lm = data.loaded;
    document.getElementById('loadedInfo').innerHTML = lm ? '<strong>' + SAT.esc(lm.model) + '</strong><div class="text-secondary">' + SAT.esc(lm.engine) + ' on ' + SAT.esc(lm.device) + ', idle for ' + SAT.fmtDuration(lm.idle_seconds) + '</div>' : 'Nothing loaded';
    document.getElementById('downloads').innerHTML = data.downloads.length ? data.downloads.map(j => '<div class="mb-2"><div class="d-flex justify-content-between"><span>' + SAT.esc(j.title) + '</span>' + SAT.statusBadge(j.status) + '</div>' + SAT.jobProgress(j) + '<div class="text-secondary">' + SAT.esc(j.message || '') + '</div><button class="btn btn-link btn-sm p-0 text-danger" data-cancel-job="' + j.id + '">cancel</button></div>').join('') : 'None running';
    document.getElementById('cacheList').innerHTML = data.cache.length ? data.cache.map(r => '<li class="list-group-item d-flex justify-content-between align-items-center"><span class="truncate" title="' + SAT.esc(r.repo) + '">' + SAT.esc(r.repo) + '</span><span class="text-nowrap">' + SAT.fmtBytes(r.size) + (window.IS_ADMIN ? ' <button class="btn btn-link btn-sm p-0 text-danger" data-delete-repo="' + SAT.esc(r.repo) + '" title="Delete from disk"><i class="bi bi-trash"></i></button>' : '') + '</span></li>').join('') : '<li class="list-group-item text-secondary">Nothing downloaded yet</li>';
    const hf = document.getElementById('hfState');
    if (hf) hf.textContent = data.hf_token_set ? 'A token is saved.' : 'No token saved.';
  }

  function row(k, v, ok) {
    return '<div class="d-flex justify-content-between border-bottom py-1"><span>' + SAT.esc(k) + '</span><span class="' + (ok ? 'text-success' : 'text-secondary') + '">' + SAT.esc(v) + '</span></div>';
  }

  async function load() {
    try { data = await SAT.api('GET', '/api/models'); render(); } catch (e) { SAT.toast(e.message, 'danger'); }
  }

  async function download(engine, model) {
    try {
      const res = await SAT.api('POST', '/api/models/download', { engine: engine, model: model });
      SAT.toast(res.already ? 'That download is already running' : 'Download started: ' + model, 'success');
      setTimeout(load, 1000);
    } catch (e) { SAT.toast(e.message, 'danger'); }
  }

  async function test(engine, model) {
    const bodyEl = document.getElementById('testBody');
    bodyEl.innerHTML = '<div class="d-flex align-items-center gap-2"><span class="spinner-border spinner-border-sm"></span> Loading ' + SAT.esc(model) + ' and transcribing the sample clip. The first run downloads the model, so this can take a while.</div>';
    bootstrap.Modal.getOrCreateInstance(document.getElementById('testModal')).show();
    try {
      const res = await SAT.api('POST', '/api/engines/' + engine + '/test', { model: model });
      bodyEl.innerHTML = res.ok ? '<div class="alert alert-success mb-2">Model works.</div><div class="small text-secondary">Expected: The quick brown fox jumps over the lazy dog.</div><div class="mt-1"><strong>Heard:</strong> ' + SAT.esc(res.text) + '</div>' : '<div class="alert alert-danger mb-0">' + SAT.esc(res.error) + '</div>';
      load();
    } catch (e) { bodyEl.innerHTML = '<div class="alert alert-danger mb-0">' + SAT.esc(e.message) + '</div>'; }
  }

  cards.addEventListener('click', async (e) => {
    const d = e.target.closest('[data-download]');
    const t = e.target.closest('[data-test]');
    const cd = e.target.closest('[data-custom-download]');
    const ct = e.target.closest('[data-custom-test]');
    if (d) download(d.dataset.engine, d.dataset.download);
    if (t) test(t.dataset.engine, t.dataset.test);
    if (cd || ct) {
      const engine = (cd || ct).dataset.customDownload || (cd || ct).dataset.customTest;
      const input = cards.querySelector('[data-custom-input="' + engine + '"]');
      const model = input.value.trim();
      if (!model) { SAT.toast('Type a model id first', 'warning'); return; }
      cd ? download(engine, model) : test(engine, model);
    }
  });

  document.addEventListener('click', async (e) => {
    const del = e.target.closest('[data-delete-repo]');
    const cancel = e.target.closest('[data-cancel-job]');
    if (del) {
      if (!(await SAT.confirm('Delete ' + del.dataset.deleteRepo + ' from disk?', 'Delete'))) return;
      try { await SAT.api('POST', '/api/models/delete', { repo: del.dataset.deleteRepo }); SAT.toast('Deleted', 'success'); load(); } catch (err) { SAT.toast(err.message, 'danger'); }
    }
    if (cancel) {
      try { await SAT.api('POST', '/api/jobs/' + cancel.dataset.cancelJob + '/cancel'); setTimeout(load, 800); } catch (err) { SAT.toast(err.message, 'danger'); }
    }
  });

  document.getElementById('btnUnload').addEventListener('click', async () => {
    try { await SAT.api('POST', '/api/models/unload'); SAT.toast('Model unloaded', 'success'); load(); } catch (e) { SAT.toast(e.message, 'danger'); }
  });

  const hfSave = document.getElementById('hfSave');
  if (hfSave) hfSave.addEventListener('click', async () => {
    try { await SAT.api('PUT', '/api/settings', { hf_token: document.getElementById('hfToken').value.trim() }); SAT.toast('Token saved', 'success'); document.getElementById('hfToken').value = ''; load(); } catch (e) { SAT.toast(e.message, 'danger'); }
  });

  window.addEventListener('sat:status', (ev) => {
    const dl = (ev.detail.jobs || []).filter(j => j.type === 'download');
    if (dl.length || (data && data.downloads.length)) load();
  });

  load();
})();
