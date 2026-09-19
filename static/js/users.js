/* Users page (admin): accounts and presence. */
(function () {
  const body = document.getElementById('uBody');
  let users = [];

  function row(u) {
    const a = u.activity;
    const where = a ? (a.project_id ? 'project ' + a.project_id + (a.record_id ? ', record #' + a.record_id : '') : (a.page || 'browsing')) : '';
    return '<tr data-id="' + u.id + '"><td><span class="avatar m-0 ' + (u.online ? '' : 'offline') + '">' + SAT.esc(SAT.initials(u.display_name)) + '</span></td>' +
      '<td>' + SAT.esc(u.username) + '</td><td>' + SAT.esc(u.display_name) + '</td><td>' + SAT.statusBadge(u.role === 'admin' ? 'approved' : 'none').replace('approved', 'admin').replace('none', 'member') + '</td>' +
      '<td>' + (u.is_active ? (u.online ? '<span class="text-success">online</span>' : 'offline') : '<span class="text-secondary">deactivated</span>') + '</td>' +
      '<td class="small text-secondary">' + SAT.esc(where) + '</td><td class="small text-secondary">' + (u.last_login_at ? SAT.ago(u.last_login_at) : 'never') + '</td>' +
      '<td class="text-end"><div class="btn-group btn-group-sm"><button class="btn btn-outline-secondary" data-edit><i class="bi bi-pencil"></i></button>' + (u.id !== window.ME.id ? '<button class="btn btn-outline-danger" data-delete><i class="bi bi-trash"></i></button>' : '') + '</div></td></tr>';
  }

  async function load() {
    try { users = (await SAT.api('GET', '/api/users')).items; body.innerHTML = users.map(row).join(''); } catch (e) { SAT.toast(e.message, 'danger'); }
  }

  function openModal(u) {
    document.getElementById('uId').value = u ? u.id : '';
    document.getElementById('uTitle').textContent = u ? 'Edit ' + u.username : 'Add user';
    document.getElementById('uUsername').value = u ? u.username : '';
    document.getElementById('uUsername').disabled = !!u;
    document.getElementById('uDisplay').value = u ? u.display_name : '';
    document.getElementById('uPassword').value = '';
    document.getElementById('uPwHint').textContent = u ? '(leave blank to keep the current one)' : '';
    document.getElementById('uRole').value = u ? u.role : 'member';
    document.getElementById('uActive').checked = u ? u.is_active : true;
    document.getElementById('uError').classList.add('d-none');
    bootstrap.Modal.getOrCreateInstance(document.getElementById('userModal')).show();
  }

  document.getElementById('btnNewUser').addEventListener('click', (e) => { e.preventDefault(); openModal(null); });
  body.addEventListener('click', async (e) => {
    const tr = e.target.closest('tr[data-id]');
    if (!tr) return;
    const u = users.find(x => x.id === Number(tr.dataset.id));
    if (e.target.closest('[data-edit]')) openModal(u);
    if (e.target.closest('[data-delete]')) {
      if (!(await SAT.confirm('Delete user ' + u.username + '? Their edits stay in the history.', 'Delete'))) return;
      try { await SAT.api('DELETE', '/api/users/' + u.id); load(); } catch (err) { SAT.toast(err.message, 'danger'); }
    }
  });
  document.getElementById('uSave').addEventListener('click', async () => {
    const id = document.getElementById('uId').value;
    const payload = { username: document.getElementById('uUsername').value, display_name: document.getElementById('uDisplay').value, password: document.getElementById('uPassword').value, role: document.getElementById('uRole').value, is_active: document.getElementById('uActive').checked };
    try {
      if (id) await SAT.api('PUT', '/api/users/' + id, payload); else await SAT.api('POST', '/api/users', payload);
      bootstrap.Modal.getInstance(document.getElementById('userModal')).hide();
      SAT.toast('Saved', 'success');
      load();
    } catch (e) { const el = document.getElementById('uError'); el.textContent = e.message; el.classList.remove('d-none'); }
  });
  window.addEventListener('sat:status', load);
  load();
})();
