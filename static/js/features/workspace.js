/**
 * workspace.js — workspace CRUD, switching, sharing panel, members
 */
const WorkspaceFeature = (() => {

  // ── Load & render all workspaces ─────────────────────────────────────────

  async function loadAll() {
    const res  = await API.get('/api/workspaces');
    const list = await res.json();
    State.set('workspaces', list);
    _renderSidebar(list);
    if (list.length === 0) {
      document.getElementById('no-workspace-state').style.display = 'flex';
      document.getElementById('workspace-content').style.display  = 'none';
    } else {
      const lastId = parseInt(localStorage.getItem('am_last_ws')) || list[0].id;
      const ws     = list.find(w => w.id === lastId) || list[0];
      selectWorkspace(ws);
    }
  }

  function _renderSidebar(list) {
    const el = document.getElementById('workspace-list');
    if (!el) return;
    const activeId = State.get('activeWs')?.id;
    el.innerHTML = list.map(ws => `
      <div class="workspace-item ${ws.id === activeId ? 'active' : ''}"
           onclick="WorkspaceFeature.selectWorkspace(${JSON.stringify(ws).replace(/"/g,'&quot;')})">
        <span class="workspace-item-icon"></span>
        <span class="workspace-item-name">${escapeHtml(ws.name)}</span>
        ${ws.role === 'owner'
          ? `<button class="workspace-delete-btn" title="Delete"
               onclick="event.stopPropagation();WorkspaceFeature.deleteWorkspace(${ws.id},'${escapeHtml(ws.name)}')">✕</button>`
          : ''}
      </div>`).join('') || '<div class="sidebar-loading">No workspaces</div>';
  }

  function selectWorkspace(ws) {
    State.set('activeWs', ws);
    localStorage.setItem('am_last_ws', ws.id);
    window.AM_WORKSPACE_ID = ws.id;

    document.getElementById('no-workspace-state').style.display = 'none';
    // 'flex', not 'block' — dashboard.css lays the header / KPI row / projects
    // section out as a column with a 30px gap, and an inline `display:block`
    // would win over that rule and collapse the spacing.
    document.getElementById('workspace-content').style.display  = 'flex';

    // Header + top-bar breadcrumb
    document.getElementById('ws-title').textContent = ws.name;
    const crumb = document.getElementById('crumb-ws');
    if (crumb) { crumb.textContent = ws.name; crumb.title = ws.name; }
    const badge = document.getElementById('ws-role-badge');
    if (badge) { badge.className = `workspace-role badge badge-${ws.role}`; badge.textContent = ws.role; }
    // Subtitle is "WS-XXXXXX · N projects"; the project count only exists once
    // the grid has loaded, so ProjectsFeature fills it — this is the placeholder
    // that shows while that request is in flight.
    const stats = document.getElementById('ws-stats-row');
    if (stats) stats.textContent = ws.public_id || '';

    // Show/hide actions based on role
    const shareBtn   = document.getElementById('btn-share-workspace');
    const newProjBtn = document.getElementById('btn-new-project');
    const renameBtn  = document.getElementById('btn-rename-workspace');
    if (shareBtn)   shareBtn.style.display   = 'inline-flex';  // all roles can see members
    if (newProjBtn) newProjBtn.style.display  = ws.role !== 'viewer' ? 'inline-flex' : 'none';
    if (renameBtn)  renameBtn.style.display   = ws.role === 'owner'  ? 'inline-flex' : 'none';

    _renderSidebar(State.get('workspaces'));
    ProjectsFeature.load(ws.id);

    // Close share panel if open
    _closeSharePanel();
  }

  // ── Create workspace ──────────────────────────────────────────────────────

  function showCreateModal() {
    document.getElementById('ws-name-input').value = '';
    setError('ws-create-error', '');
    showModal('modal-create-workspace');
    setTimeout(() => document.getElementById('ws-name-input').focus(), 50);
  }

  function hideCreateModal() { hideModal('modal-create-workspace'); }

  async function create() {
    const name = document.getElementById('ws-name-input').value.trim();
    if (!name) { setError('ws-create-error', 'Name required'); return; }
    const res  = await API.post('/api/workspaces', { name });
    const data = await res.json();
    if (!res.ok) { setError('ws-create-error', data.error || 'Failed'); return; }
    hideCreateModal();
    await loadAll();
    selectWorkspace(data.workspace);
  }

  // ── Rename workspace ──────────────────────────────────────────────────────

  function showRenameModal() {
    const ws = State.get('activeWs');
    if (!ws) return;
    document.getElementById('ws-rename-input').value = ws.name;
    setError('ws-rename-error', '');
    showModal('modal-rename-workspace');
    setTimeout(() => document.getElementById('ws-rename-input').focus(), 50);
  }

  function hideRenameModal() { hideModal('modal-rename-workspace'); }

  async function rename() {
    const ws   = State.get('activeWs');
    const name = document.getElementById('ws-rename-input').value.trim();
    if (!name) { setError('ws-rename-error', 'Name required'); return; }
    const res  = await API.put(`/api/workspaces/${ws.id}/rename`,
                               { name, workspace_id: ws.id });
    const data = await res.json();
    if (!res.ok) { setError('ws-rename-error', data.error || 'Failed'); return; }
    hideRenameModal();
    await loadAll();
  }

  // ── Delete workspace ──────────────────────────────────────────────────────

  async function deleteWorkspace(id, name) {
    if (!confirm(`Delete workspace "${name}" and ALL its projects?\nThis cannot be undone.`)) return;
    const res = await API.del(`/api/workspaces/${id}`, { workspace_id: id });
    if (!res || !res.ok) { alert('Failed to delete workspace.'); return; }
    await loadAll();
  }

  // ── Share / Members Panel (inline, right side) ────────────────────────────

  let _shareOpen = false;

  function toggleSharePanel() {
    _shareOpen ? _closeSharePanel() : _openSharePanel();
  }

  function _openSharePanel() {
    _shareOpen = true;
    const panel = document.getElementById('share-panel');
    document.getElementById('dashboard-main')?.classList.add('panel-open');
    if (panel) {
      panel.style.display = 'flex';
      SharePanel.load(State.get('activeWs'), State.get('user'));
    }
    const btn = document.getElementById('btn-share-workspace');
    if (btn) btn.classList.add('active');
  }

  function _closeSharePanel() {
    _shareOpen = false;
    const panel = document.getElementById('share-panel');
    document.getElementById('dashboard-main')?.classList.remove('panel-open');
    if (panel) panel.style.display = 'none';
    const btn = document.getElementById('btn-share-workspace');
    if (btn) btn.classList.remove('active');
  }

  return {
    loadAll, selectWorkspace,
    showCreateModal, hideCreateModal, create,
    showRenameModal, hideRenameModal, rename,
    deleteWorkspace,
    toggleSharePanel, closeSharePanel: _closeSharePanel
  };
})();


// ── SharePanel — inline share/members panel shown on dashboard ────────────────
const SharePanel = (() => {
  let _ws   = null;
  let _user = null;

  async function load(ws, user) {
    _ws   = ws;
    _user = user;

    // Panel header
    const title = document.getElementById('share-panel-title');
    if (title) title.textContent = `Share "${ws.name}"`;

    // Show invite form only for owners
    const inviteSection = document.getElementById('share-invite-section');
    if (inviteSection) inviteSection.style.display = ws.role === 'owner' ? 'block' : 'none';

    setError('share-invite-error', '');
    setSuccess('share-invite-success', '');
    await _renderMembers();
  }

  async function _renderMembers() {
    const ws  = _ws;
    const res = await API.get(`/api/workspaces/${ws.id}/members?workspace_id=${ws.id}`);
    if (!res || !res.ok) return;
    const members = await res.json();
    const el = document.getElementById('share-members-list');
    if (!el) return;

    el.innerHTML = members.map(m => {
      const isSelf  = String(m.user_id) === String(_user.id);
      const isOwner = ws.role === 'owner';

      const roleCtrl = isOwner && !isSelf
        ? `<select class="role-select" onchange="SharePanel.updateRole(${m.user_id}, this.value)">
             <option value="owner"  ${m.role==='owner'  ?'selected':''}>Owner</option>
             <option value="editor" ${m.role==='editor' ?'selected':''}>Editor</option>
             <option value="viewer" ${m.role==='viewer' ?'selected':''}>Viewer</option>
           </select>`
        : `<span class="badge badge-${m.role}">${m.role}</span>`;

      const removeBtn = isOwner && !isSelf
        ? `<button class="share-remove-btn" title="Remove" onclick="SharePanel.remove(${m.user_id},'${escapeHtml(m.username)}')">✕</button>`
        : '';

      return `
        <div class="share-member-row">
          <div class="share-avatar">${m.username[0].toUpperCase()}</div>
          <div class="share-member-info">
            <div class="share-member-name">${escapeHtml(m.username)} ${isSelf?'<span class="you-tag">you</span>':''}</div>
            <div class="share-member-email">${escapeHtml(m.email)}</div>
          </div>
          <div class="share-member-actions">${roleCtrl}${removeBtn}</div>
        </div>`;
    }).join('') || '<p class="share-empty">No members yet.</p>';
  }

  async function invite() {
    const email = document.getElementById('share-email-input').value.trim();
    const role  = document.getElementById('share-role-select').value;
    setError('share-invite-error', '');
    setSuccess('share-invite-success', '');
    if (!email) { setError('share-invite-error', 'Enter an email address'); return; }

    const btn = document.getElementById('share-invite-btn');
    if (btn) { btn.disabled = true; btn.textContent = 'Inviting…'; }

    const res  = await API.post(`/api/workspaces/${_ws.id}/invite`,
                                { email, role, workspace_id: _ws.id });
    const data = await res.json();

    if (btn) { btn.disabled = false; btn.textContent = 'Invite'; }

    if (!res.ok) { setError('share-invite-error', data.error || 'Failed'); return; }
    setSuccess('share-invite-success', `✓ ${email} added as ${role}`);
    document.getElementById('share-email-input').value = '';
    await _renderMembers();
  }

  async function updateRole(userId, role) {
    await API.put(`/api/workspaces/${_ws.id}/members/${userId}/role`,
                  { role, workspace_id: _ws.id });
    await _renderMembers();
  }

  async function remove(userId, name) {
    if (!confirm(`Remove ${name} from this workspace?`)) return;
    await API.del(`/api/workspaces/${_ws.id}/members/${userId}`,
                  { workspace_id: _ws.id });
    await _renderMembers();
  }

  return { load, invite, updateRole, remove };
})();


// ── MembersFeature — used on /workspace/<id>/members page ────────────────────
const MembersFeature = (() => {
  let _wsId   = null;
  let _myRole = null;

  async function load(wsId, currentUser) {
    _wsId = wsId;
    window.AM_WORKSPACE_ID = wsId;
    const wsRes  = await API.get('/api/workspaces');
    const wsList = await wsRes.json();
    const ws     = wsList.find(w => String(w.id) === String(wsId));
    if (!ws) {
      document.body.innerHTML = '<p style="padding:2rem;color:#ff4060">Workspace not found or access denied.</p>';
      return;
    }
    _myRole = ws.role;
    document.getElementById('ws-members-title').textContent    = `${ws.name} – Members`;
    document.getElementById('ws-members-subtitle').textContent = `Your role: ${ws.role}`;
    if (_myRole === 'owner') document.getElementById('invite-card').style.display = 'block';
    await _renderMembers(wsId, currentUser);
  }

  async function _renderMembers(wsId, currentUser) {
    const res     = await API.get(`/api/workspaces/${wsId}/members?workspace_id=${wsId}`);
    const members = await res.json();
    const el      = document.getElementById('members-list');
    if (!el) return;
    el.innerHTML = members.map(m => {
      const isSelf  = String(m.user_id) === String(currentUser.id);
      const isOwner = _myRole === 'owner';
      const roleCtrl = isOwner && !isSelf
        ? `<select class="role-select" onchange="MembersFeature.updateRole(${m.user_id},this.value)">
             <option value="owner"  ${m.role==='owner'  ?'selected':''}>Owner</option>
             <option value="editor" ${m.role==='editor' ?'selected':''}>Editor</option>
             <option value="viewer" ${m.role==='viewer' ?'selected':''}>Viewer</option>
           </select>`
        : roleBadge(m.role);
      const removeBtn = isOwner && !isSelf
        ? `<button class="btn btn-danger btn-sm" onclick="MembersFeature.remove(${m.user_id},'${escapeHtml(m.username)}')">Remove</button>`
        : '';
      return `
        <div class="member-row">
          <div class="member-avatar">${m.username[0].toUpperCase()}</div>
          <div class="member-info">
            <div class="member-name">${escapeHtml(m.username)} ${isSelf?'(you)':''}</div>
            <div class="member-email">${escapeHtml(m.email)}</div>
          </div>
          <div class="member-actions">${roleCtrl} ${removeBtn}</div>
        </div>`;
    }).join('') || '<p class="text-muted">No members found.</p>';
  }

  async function invite() {
    const email = document.getElementById('invite-email').value.trim();
    const role  = document.getElementById('invite-role').value;
    setError('invite-error', '');
    setSuccess('invite-success', '');
    if (!email) { setError('invite-error', 'Enter an email address'); return; }
    const res  = await API.post(`/api/workspaces/${_wsId}/invite`, { email, role, workspace_id: _wsId });
    const data = await res.json();
    if (!res.ok) { setError('invite-error', data.error); return; }
    setSuccess('invite-success', `✓ ${email} added as ${role}`);
    document.getElementById('invite-email').value = '';
    await _renderMembers(_wsId, State.get('user'));
  }

  async function updateRole(userId, role) {
    await API.put(`/api/workspaces/${_wsId}/members/${userId}/role`, { role, workspace_id: _wsId });
    await _renderMembers(_wsId, State.get('user'));
  }

  async function remove(userId, name) {
    if (!confirm(`Remove ${name} from this workspace?`)) return;
    await API.del(`/api/workspaces/${_wsId}/members/${userId}`, { workspace_id: _wsId });
    await _renderMembers(_wsId, State.get('user'));
  }

  return { load, invite, updateRole, remove };
})();
