/* Providers page: keys, base URLs, default models and engine options. */
(function () {
  const admin = window.IS_ADMIN;
  let engines = [];

  function optionField(e, o) {
    const cur = e.options_current && e.options_current[o.key] !== undefined ? e.options_current[o.key] : '';
    if (o.type === 'bool') {
      return '<div class="col-md-6"><label class="form-label small mb-0">' + SAT.esc(o.label) + '</label><select class="form-select form-select-sm" data-opt="' + o.key + '"><option value="">default (' + (o.default ? 'yes' : 'no') + ')</option><option value="true"' + (cur === true ? ' selected' : '') + '>yes</option><option value="false"' + (cur === false ? ' selected' : '') + '>no</option></select></div>';
    }
    const def = o.default === undefined || o.default === null || o.default === '' ? 'blank = none' : 'default: ' + o.default;
    return '<div class="col-md-6"><label class="form-label small mb-0">' + SAT.esc(o.label) + '</label><input class="form-control form-control-sm" data-opt="' + o.key + '" value="' + SAT.esc(cur === null ? '' : cur) + '" placeholder="' + SAT.esc(def) + '"></div>';
  }

  function apiCard(e) {
    const models = e.models.map(m => '<option value="' + SAT.esc(m.id) + '"' + (m.id === e.default_model_current ? ' selected' : '') + '>' + SAT.esc(m.name) + (m.note ? ' (' + m.note + ')' : '') + '</option>').join('');
    const known = e.models.some(m => m.id === e.default_model_current);
    return '<div class="col-lg-6"><div class="card h-100" data-engine="' + e.id + '"><div class="card-header bg-white d-flex justify-content-between align-items-center">' +
      '<div><strong>' + SAT.esc(e.name) + '</strong> ' + (e.has_key ? '<span class="badge text-bg-success">key set</span>' : '<span class="badge text-bg-secondary">no key</span>') + '</div>' +
      (e.docs ? '<a class="small" href="' + SAT.esc(e.docs) + '" target="_blank" rel="noopener">docs</a>' : '') + '</div>' +
      '<div class="card-body"><div class="small text-secondary mb-2">' + SAT.esc(e.description) + '</div>' +
      '<div class="row g-2">' +
      '<div class="col-12"><label class="form-label small mb-0">' + SAT.esc(e.key_label || 'API key') + '</label><input type="password" class="form-control form-control-sm" data-field="api_key" placeholder="' + (e.key_preview ? 'saved: ' + SAT.esc(e.key_preview) + ' (leave blank to keep)' : 'paste the key') + '"' + (admin ? '' : ' disabled') + '></div>' +
      '<div class="col-md-6"><label class="form-label small mb-0">Base URL</label><input type="text" class="form-control form-control-sm" data-field="base_url" value="' + SAT.esc(e.base_url_current || '') + '" placeholder="' + SAT.esc(e.base_url || '') + '"' + (admin ? '' : ' disabled') + '></div>' +
      '<div class="col-md-6"><label class="form-label small mb-0">Default model</label>' +
      (e.models.length ? '<select class="form-select form-select-sm" data-field="model_select">' + models + '<option value="__custom__"' + (known ? '' : ' selected') + '>Custom...</option></select>' : '') +
      '<input type="text" class="form-control form-control-sm mt-1 ' + (e.models.length && known ? 'd-none' : '') + '" data-field="model_custom" value="' + SAT.esc(known ? '' : (e.default_model_current || '')) + '" placeholder="model id">' +
      (e.id === 'openrouter' ? '<button class="btn btn-link btn-sm p-0 mt-1" data-load-openrouter>Load audio-capable models from OpenRouter</button>' : '') + '</div>' +
      (e.options || []).map(o => optionField(e, o)).join('') +
      '</div><div class="help mt-2">Language: ' + SAT.esc(e.language_hint || '') + (e.max_seconds ? '. Audio longer than ' + e.max_seconds + 's is split at silences before sending.' : '') + '</div></div>' +
      '<div class="card-footer bg-white d-flex gap-2">' + (admin ? '<button class="btn btn-sm btn-primary" data-save>Save</button>' : '') + '<button class="btn btn-sm btn-outline-secondary" data-test><i class="bi bi-play"></i> Test with sample clip</button></div></div></div>';
  }

  function localCard(e) {
    return '<div class="col-lg-6"><div class="card h-100" data-engine="' + e.id + '"><div class="card-header bg-white"><strong>' + SAT.esc(e.name) + '</strong> ' + (e.installed ? '<span class="badge text-bg-success">installed</span>' : '<span class="badge text-bg-secondary">not installed</span>') + '</div>' +
      '<div class="card-body"><div class="small text-secondary mb-2">' + SAT.esc(e.description) + '</div><div class="row g-2">' + (e.options || []).map(o => optionField(e, o)).join('') + '</div>' +
      (e.options && e.options.length ? '' : '<div class="text-secondary small">No options.</div>') + '</div>' +
      (admin && e.options && e.options.length ? '<div class="card-footer bg-white"><button class="btn btn-sm btn-primary" data-save>Save defaults</button></div>' : '') + '</div></div>';
  }

  async function load() {
    try {
      const data = await SAT.api('GET', '/api/engines');
      engines = data.items;
      document.getElementById('apiCards').innerHTML = engines.filter(e => e.kind === 'api').map(apiCard).join('');
      document.getElementById('localCards').innerHTML = engines.filter(e => e.kind === 'local').map(localCard).join('');
    } catch (e) { SAT.toast(e.message, 'danger'); }
  }

  function collect(card) {
    const options = {};
    card.querySelectorAll('[data-opt]').forEach(el => {
      const v = el.value;
      options[el.dataset.opt] = v === '' ? null : v === 'true' ? true : v === 'false' ? false : v;
    });
    const payload = { options: options };
    const key = card.querySelector('[data-field="api_key"]');
    if (key && key.value.trim()) payload.api_key = key.value.trim();
    const base = card.querySelector('[data-field="base_url"]');
    if (base) payload.base_url = base.value.trim();
    const sel = card.querySelector('[data-field="model_select"]');
    const custom = card.querySelector('[data-field="model_custom"]');
    if (sel || custom) payload.model = sel && sel.value !== '__custom__' ? sel.value : (custom ? custom.value.trim() : '');
    return payload;
  }

  document.addEventListener('change', (e) => {
    if (e.target.matches('[data-field="model_select"]')) {
      const custom = e.target.closest('.card').querySelector('[data-field="model_custom"]');
      custom.classList.toggle('d-none', e.target.value !== '__custom__');
    }
  });

  document.addEventListener('click', async (e) => {
    const card = e.target.closest('[data-engine]');
    if (!card) return;
    const id = card.dataset.engine;
    if (e.target.closest('[data-save]')) {
      try { await SAT.api('PUT', '/api/engines/' + id, collect(card)); SAT.toast('Saved', 'success'); load(); } catch (err) { SAT.toast(err.message, 'danger'); }
    }
    if (e.target.closest('[data-test]')) {
      const payload = collect(card);
      const bodyEl = document.getElementById('testBody');
      bodyEl.innerHTML = '<div class="d-flex align-items-center gap-2"><span class="spinner-border spinner-border-sm"></span> Sending the sample clip to ' + SAT.esc(id) + '...</div>';
      bootstrap.Modal.getOrCreateInstance(document.getElementById('testModal')).show();
      if (admin) { try { await SAT.api('PUT', '/api/engines/' + id, payload); } catch (err) { } }
      try {
        const res = await SAT.api('POST', '/api/engines/' + id + '/test', { model: payload.model || undefined });
        bodyEl.innerHTML = res.ok ? '<div class="alert alert-success mb-2">Provider works (model ' + SAT.esc(res.model) + ').</div><div class="small text-secondary">Expected: The quick brown fox jumps over the lazy dog.</div><div class="mt-1"><strong>Heard:</strong> ' + SAT.esc(res.text) + '</div>' : '<div class="alert alert-danger mb-0">' + SAT.esc(res.error) + '</div>';
        load();
      } catch (err) { bodyEl.innerHTML = '<div class="alert alert-danger mb-0">' + SAT.esc(err.message) + '</div>'; }
    }
    if (e.target.closest('[data-load-openrouter]')) {
      e.preventDefault();
      try {
        const res = await SAT.api('GET', '/api/engines/openrouter/models');
        const sel = card.querySelector('[data-field="model_select"]');
        const current = sel.value;
        sel.innerHTML = res.items.map(m => '<option value="' + SAT.esc(m.id) + '"' + (m.id === current ? ' selected' : '') + '>' + SAT.esc(m.id) + '</option>').join('') + '<option value="__custom__">Custom...</option>';
        SAT.toast(res.items.length + ' audio-capable models loaded', 'success');
      } catch (err) { SAT.toast(err.message, 'danger'); }
    }
  });

  load();
})();
