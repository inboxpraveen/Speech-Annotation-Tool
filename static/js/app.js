/* Shared helpers: API calls, toasts, status polling, folder picker. */
(function () {
  const SAT = window.SAT = {};

  SAT.api = async function (method, url, body, opts) {
    const init = { method, headers: {} };
    if (body instanceof FormData) {
      init.body = body;
    } else if (body !== undefined) {
      init.headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(body);
    }
    const resp = await fetch(url, init);
    let data = null;
    const ct = resp.headers.get('content-type') || '';
    if (ct.includes('application/json')) data = await resp.json();
    if (resp.status === 401) { window.location = '/login?next=' + encodeURIComponent(window.location.pathname); return; }
    if (!resp.ok) {
      const e = new Error((data && data.error) || ('request failed (' + resp.status + ')'));
      e.status = resp.status; e.data = data; throw e;
    }
    return data;
  };

  SAT.esc = function (s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  };

  SAT.toast = function (message, type, opts) {
    opts = opts || {};
    const wrap = document.getElementById('toasts');
    if (!wrap) return;
    const kind = { success: 'text-bg-success', danger: 'text-bg-danger', warning: 'text-bg-warning', info: 'text-bg-primary' }[type || 'info'] || 'text-bg-primary';
    const el = document.createElement('div');
    el.className = 'toast align-items-center border-0 ' + kind;
    el.setAttribute('role', 'status');
    el.innerHTML = '<div class="d-flex"><div class="toast-body">' + (opts.title ? '<strong>' + SAT.esc(opts.title) + '</strong><br>' : '') + SAT.esc(message) + '</div>' +
      '<button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div>';
    wrap.appendChild(el);
    const t = new bootstrap.Toast(el, { delay: opts.delay || 5000 });
    el.addEventListener('hidden.bs.toast', () => el.remove());
    t.show();
  };

  SAT.confirm = function (text, okLabel) {
    return new Promise(resolve => {
      const modalEl = document.getElementById('confirmModal');
      document.getElementById('confirmText').textContent = text;
      const ok = document.getElementById('confirmOk');
      ok.textContent = okLabel || 'Confirm';
      const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
      let done = false;
      const onOk = () => { done = true; modal.hide(); };
      ok.addEventListener('click', onOk, { once: true });
      modalEl.addEventListener('hidden.bs.modal', () => { ok.removeEventListener('click', onOk); resolve(done); }, { once: true });
      modal.show();
    });
  };

  SAT.fmtDuration = function (secs) {
    if (secs == null || isNaN(secs)) return '';
    secs = Math.round(secs);
    const h = Math.floor(secs / 3600), m = Math.floor((secs % 3600) / 60), s = secs % 60;
    if (h) return h + 'h ' + m + 'm';
    if (m) return m + 'm ' + s + 's';
    return s + 's';
  };

  SAT.fmtClock = function (secs) {
    if (secs == null || isNaN(secs)) return '';
    const m = Math.floor(secs / 60), s = Math.floor(secs % 60);
    return m + ':' + String(s).padStart(2, '0');
  };

  SAT.fmtBytes = function (n) {
    if (n == null) return '';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let i = 0;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
    return n.toFixed(i >= 2 ? 1 : 0) + ' ' + units[i];
  };

  SAT.fmtTime = function (s) {
    if (!s) return '';
    const d = new Date(s.replace(' ', 'T') + 'Z');
    if (isNaN(d)) return s;
    return d.toLocaleString();
  };

  SAT.ago = function (s) {
    if (!s) return '';
    const d = new Date(s.replace(' ', 'T') + 'Z');
    const diff = Math.max(0, (Date.now() - d.getTime()) / 1000);
    if (diff < 60) return 'just now';
    if (diff < 3600) return Math.floor(diff / 60) + ' min ago';
    if (diff < 86400) return Math.floor(diff / 3600) + ' h ago';
    return Math.floor(diff / 86400) + ' d ago';
  };

  SAT.initials = function (name) {
    return (name || '?').split(/\s+/).map(w => w[0]).join('').slice(0, 2).toUpperCase();
  };

  SAT.jobProgress = function (job) {
    const pct = job.total ? Math.min(100, Math.round(100 * (job.done + job.failed) / job.total)) : (job.status === 'completed' ? 100 : 0);
    const cls = job.status === 'failed' ? 'bg-danger' : job.status === 'paused' ? 'bg-warning' : job.status === 'completed' ? 'bg-success' : 'progress-bar-striped progress-bar-animated';
    return '<div class="progress" style="height: 8px;"><div class="progress-bar ' + cls + '" style="width:' + pct + '%"></div></div>';
  };

  SAT.statusBadge = function (status) {
    const map = { queued: 'secondary', running: 'primary', paused: 'warning', completed: 'success', failed: 'danger', cancelled: 'dark',
      pending: 'secondary', processing: 'primary', done: 'success', skipped: 'dark', none: 'light', reviewed: 'info', approved: 'success', rejected: 'danger',
      new: 'secondary', ready: 'success', changed: 'warning', missing: 'danger', error: 'danger' };
    const cls = map[status] || 'secondary';
    return '<span class="badge text-bg-' + cls + (cls === 'light' ? ' border' : '') + '">' + SAT.esc(status) + '</span>';
  };

  // Status polling -----------------------------------------------------------
  let lastNotifId = null;
  let pollTimer = null;
  let polling = false, pollAgain = false;
  SAT.pollContext = {};

  // One poll at a time. A pollNow() during a request asks for another one right after
  // it instead of starting a second timer chain. Hidden tabs only poll every 30s,
  // often enough to stay listed as online.
  async function poll() {
    clearTimeout(pollTimer);
    if (polling) { pollAgain = true; return; }
    polling = true;
    let secs = 5;
    try {
      const params = new URLSearchParams({ page: document.body.dataset.page || '' });
      const pid = SAT.pollContext.project_id || document.body.dataset.projectId;
      if (pid) params.set('project_id', pid);
      if (SAT.pollContext.record_id) params.set('record_id', SAT.pollContext.record_id);
      const data = await SAT.api('GET', '/api/status?' + params.toString());
      if (!data) return;
      renderStatus(data);
      window.dispatchEvent(new CustomEvent('sat:status', { detail: data }));
      secs = document.hidden ? 30 : Math.max(1, Number(data.poll_seconds) || 2);
    } catch (e) {
    } finally {
      polling = false;
    }
    pollTimer = setTimeout(poll, pollAgain ? 0 : secs * 1000);
    pollAgain = false;
  }

  function renderStatus(data) {
    const jobs = data.jobs || [];
    const active = jobs.filter(j => j.status === 'running' || j.status === 'queued');
    const count = document.getElementById('navJobCount');
    if (count) { count.textContent = active.length; count.classList.toggle('d-none', active.length === 0); }
    const bar = document.getElementById('jobBar');
    const items = document.getElementById('jobBarItems');
    if (bar && items) {
      const running = jobs.filter(j => j.status === 'running');
      bar.classList.toggle('d-none', running.length === 0);
      items.innerHTML = running.slice(0, 3).map(j => {
        const pct = j.total ? Math.round(100 * (j.done + j.failed) / j.total) : 0;
        return '<span class="me-3"><strong>' + SAT.esc(j.title) + '</strong> ' + (j.total ? pct + '% (' + (j.done + j.failed) + '/' + j.total + ')' : '') + ' <span class="text-secondary">' + SAT.esc(j.message || '') + '</span></span>';
      }).join('');
    }
    const badge = document.getElementById('notifBadge');
    const n = data.notifications || { unread: 0, latest: [] };
    if (badge) { badge.textContent = n.unread; badge.classList.toggle('d-none', !n.unread); }
    const list = document.getElementById('notifList');
    if (list) {
      list.innerHTML = n.latest.length ? n.latest.map(x =>
        '<a class="notif-item d-block px-3 py-2 border-bottom text-decoration-none" href="' + SAT.esc(x.link || '/jobs') + '" data-id="' + x.id + '">' +
        '<div class="d-flex justify-content-between"><strong class="text-' + ({ success: 'success', danger: 'danger', warning: 'warning' }[x.level] || 'body') + '">' + SAT.esc(x.title) + '</strong><span class="small text-secondary">' + SAT.ago(x.created_at) + '</span></div>' +
        '<div class="small text-secondary">' + SAT.esc(x.message) + '</div></a>').join('')
        : '<div class="p-3 text-secondary small">No unread notifications</div>';
    }
    if (n.latest.length) {
      const newest = n.latest[0].id;
      if (lastNotifId !== null && newest > lastNotifId) {
        n.latest.filter(x => x.id > lastNotifId).reverse().forEach(x => SAT.toast(x.message || '', x.level === 'danger' ? 'danger' : x.level === 'warning' ? 'warning' : x.level === 'success' ? 'success' : 'info', { title: x.title }));
      }
      lastNotifId = Math.max(newest, lastNotifId || 0);
    } else if (lastNotifId === null) {
      lastNotifId = 0;
    }
    const online = document.getElementById('navOnline');
    if (online) {
      online.innerHTML = (data.online || []).map(o => {
        let what = o.page ? o.page : 'online';
        if (o.project_id) what = 'project ' + o.project_id + (o.record_id ? ', record ' + o.record_id : '');
        return '<span class="avatar" title="' + SAT.esc(o.display_name + ' (' + what + ')') + '">' + SAT.esc(SAT.initials(o.display_name)) + '</span>';
      }).join('');
    }
    const lm = document.getElementById('navLoadedModel');
    if (lm) lm.textContent = data.loaded_model ? ('In memory: ' + data.loaded_model.model + ' (' + data.loaded_model.device + ')') : '';
  }

  SAT.pollNow = poll;

  document.addEventListener('DOMContentLoaded', () => {
    if (document.getElementById('topnav')) {
      poll();
      document.addEventListener('visibilitychange', () => { if (!document.hidden) poll(); });
    }
    const readAll = document.getElementById('notifReadAll');
    if (readAll) readAll.addEventListener('click', async () => { await SAT.api('POST', '/api/notifications/read', {}); SAT.pollNow(); });
    const list = document.getElementById('notifList');
    if (list) list.addEventListener('click', async (e) => {
      const a = e.target.closest('.notif-item');
      if (a) { try { await SAT.api('POST', '/api/notifications/read', { ids: [Number(a.dataset.id)] }); } catch (err) { } }
    });
    const pwSave = document.getElementById('pwSave');
    if (pwSave) pwSave.addEventListener('click', async () => {
      try {
        await SAT.api('POST', '/api/me/password', { current: document.getElementById('pwCurrent').value, password: document.getElementById('pwNew').value });
        bootstrap.Modal.getInstance(document.getElementById('passwordModal')).hide();
        SAT.toast('Password changed', 'success');
      } catch (e) { SAT.toast(e.message, 'danger'); }
    });
  });

  // Folder / file picker ---------------------------------------------------
  SAT.pickPath = function (opts) {
    opts = opts || {};
    return new Promise(resolve => {
      const modalEl = document.getElementById('fsModal');
      const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
      const pathInput = document.getElementById('fsPath');
      const listEl = document.getElementById('fsList');
      const rootsEl = document.getElementById('fsRoots');
      const hint = document.getElementById('fsHint');
      const choose = document.getElementById('fsChoose');
      document.getElementById('fsTitle').textContent = opts.title || (opts.files ? 'Choose a file' : 'Choose a folder');
      choose.classList.toggle('d-none', !!opts.files);
      let current = opts.start || '';
      let parent = null;
      let picked = null;

      async function load(path) {
        try {
          const q = new URLSearchParams({ path: path || '' });
          if (opts.files) q.set('ext', opts.files);
          const data = await SAT.api('GET', '/api/fs/list?' + q.toString());
          current = data.path; parent = data.parent;
          pathInput.value = current;
          rootsEl.innerHTML = (data.roots || []).map(r => '<button class="btn btn-sm btn-outline-secondary" data-path="' + SAT.esc(r.path) + '">' + SAT.esc(r.name) + '</button>').join('');
          const dirs = data.dirs.map(d => '<button class="list-group-item list-group-item-action d-flex align-items-center gap-2" data-dir="' + SAT.esc(d.path) + '"><i class="bi bi-folder text-warning"></i>' + SAT.esc(d.name) + '</button>');
          const files = (data.files || []).map(f => '<button class="list-group-item list-group-item-action d-flex align-items-center gap-2" data-file="' + SAT.esc(f.path) + '"><i class="bi bi-file-earmark-text text-primary"></i>' + SAT.esc(f.name) + '<span class="ms-auto small text-secondary">' + SAT.fmtBytes(f.size) + '</span></button>');
          listEl.innerHTML = dirs.concat(files).join('') || '<div class="list-group-item text-secondary">Empty folder</div>';
          hint.textContent = current ? (data.audio_count ? data.audio_count + ' audio files directly in this folder' : 'No audio files directly in this folder (subfolders are scanned too)') : 'Pick a drive or folder to start';
        } catch (e) {
          SAT.toast(e.message, 'warning');
        }
      }
      const onList = (e) => {
        const d = e.target.closest('[data-dir]');
        const f = e.target.closest('[data-file]');
        if (d) load(d.dataset.dir);
        if (f) { picked = f.dataset.file; modal.hide(); }
      };
      const onRoots = (e) => { const b = e.target.closest('[data-path]'); if (b) load(b.dataset.path); };
      const onUp = () => { if (parent !== null) load(parent); else load(''); };
      const onGo = () => load(pathInput.value.trim());
      const onKey = (e) => { if (e.key === 'Enter') { e.preventDefault(); onGo(); } };
      const onChoose = () => { picked = current; modal.hide(); };
      listEl.addEventListener('click', onList);
      rootsEl.addEventListener('click', onRoots);
      document.getElementById('fsUp').addEventListener('click', onUp);
      document.getElementById('fsGo').addEventListener('click', onGo);
      pathInput.addEventListener('keydown', onKey);
      choose.addEventListener('click', onChoose);
      modalEl.addEventListener('hidden.bs.modal', () => {
        listEl.removeEventListener('click', onList);
        rootsEl.removeEventListener('click', onRoots);
        document.getElementById('fsUp').removeEventListener('click', onUp);
        document.getElementById('fsGo').removeEventListener('click', onGo);
        pathInput.removeEventListener('keydown', onKey);
        choose.removeEventListener('click', onChoose);
        resolve(picked);
      }, { once: true });
      modal.show();
      load(current);
    });
  };

  // Engine / model picker widgets used by dashboard and project settings ---------
  SAT.engineOptions = function (engines, selectedId) {
    const local = engines.filter(e => e.kind === 'local');
    const api = engines.filter(e => e.kind === 'api');
    const opt = e => '<option value="' + e.id + '"' + (e.id === selectedId ? ' selected' : '') + (e.kind === 'local' && !e.installed ? ' disabled' : '') + '>' + SAT.esc(e.name) + (e.kind === 'local' && !e.installed ? ' (not installed)' : '') + (e.kind === 'api' && !e.has_key ? ' (no key yet)' : '') + '</option>';
    return '<optgroup label="Local models">' + local.map(opt).join('') + '</optgroup><optgroup label="API providers">' + api.map(opt).join('') + '</optgroup>';
  };

  SAT.fillModelPicker = function (engine, selectEl, customEl, currentModel) {
    const models = engine.models || [];
    const current = currentModel || engine.default_model_current || engine.default_model;
    const known = models.some(m => m.id === current);
    selectEl.innerHTML = models.map(m => '<option value="' + SAT.esc(m.id) + '"' + (m.id === current ? ' selected' : '') + '>' + SAT.esc(m.name) + (m.note ? ' (' + m.note + ')' : '') + '</option>').join('') +
      '<option value="__custom__"' + (!known ? ' selected' : '') + '>Custom model id...</option>';
    customEl.classList.toggle('d-none', known);
    customEl.value = known ? '' : (current || '');
    customEl.placeholder = engine.custom_model_hint || 'model id';
    selectEl.onchange = () => { customEl.classList.toggle('d-none', selectEl.value !== '__custom__'); if (selectEl.value === '__custom__') customEl.focus(); };
  };

  SAT.pickedModel = function (selectEl, customEl) {
    return selectEl.value === '__custom__' ? customEl.value.trim() : selectEl.value;
  };
})();
