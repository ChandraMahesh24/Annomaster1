/**
 * projects.js — project grid/list, KPI totals, search · sort · view state
 *
 * Renders the dashboard redesign (design_handoff_dashboard_redesign): card =
 * cover + progress bar + name/% + three stat pills + "Updated …" with a
 * collaborator avatar stack, plus a ghost "New Project" tile.
 *
 * The handoff's Sort and view toggle were visual-only; here they are real
 * state, persisted to localStorage, and the top-bar search really filters.
 * KPI totals are aggregates over the SAME project array, never hardcoded.
 */
const ProjectsFeature = (() => {
  let _wsId     = null;
  let _projects = [];
  let _query    = '';
  let _sort     = localStorage.getItem('am_dash_sort') || 'recent';
  let _view     = localStorage.getItem('am_dash_view') || 'grid';

  const SORT_LABELS = { recent: 'Recent', name: 'Name', progress: 'Progress' };

  // ── Load ──────────────────────────────────────────────────────────────────

  async function load(wsId) {
    _wsId = wsId;
    window.AM_WORKSPACE_ID = wsId;
    const res = await API.get(`/api/workspaces/${wsId}/projects?workspace_id=${wsId}`);
    if (!res || !res.ok) return;
    _projects = await res.json();
    _renderKpis(_projects);
    _render();
  }

  // ── KPI row — aggregates over every project, not just the filtered view ──

  function _renderKpis(projects) {
    const total = projects.reduce((n, p) => n + (p.total || 0), 0);
    const done  = projects.reduce((n, p) => n + (p.annotated || 0), 0);
    const pct   = total ? Math.round(done / total * 100) : 0;
    _setText('kpi-total',    total.toLocaleString());
    _setText('kpi-done',     done.toLocaleString());
    _setText('kpi-pending',  (total - done).toLocaleString());
    _setText('kpi-done-pct', total ? `${pct}%` : '');
  }

  // ── Filter + sort ─────────────────────────────────────────────────────────

  function _visible() {
    const q = _query.trim().toLowerCase();
    const list = q
      ? _projects.filter(p => (p.name || '').toLowerCase().includes(q))
      : _projects.slice();

    list.sort((a, b) => {
      if (_sort === 'name')     return a.name.localeCompare(b.name);
      if (_sort === 'progress') return (b.progress || 0) - (a.progress || 0)
                                    || a.name.localeCompare(b.name);
      return (b.last_modified_ts || 0) - (a.last_modified_ts || 0)
          || a.name.localeCompare(b.name);
    });
    return list;
  }

  // ── Render ────────────────────────────────────────────────────────────────

  function _render() {
    const grid     = document.getElementById('projects-grid');
    const noProj   = document.getElementById('no-projects-state');
    const noMatch  = document.getElementById('no-match-state');
    if (!grid) return;

    KebabMenu.closeAll();

    const ws       = State.get('activeWs') || {};
    const isEditor = ws.role === 'owner' || ws.role === 'editor';
    const shown    = _visible();

    // Section label + workspace subtitle both count the FULL set.
    _setText('projects-count-label',
      _query.trim() ? `Projects · ${shown.length} of ${_projects.length}` : 'Projects');
    _renderWsStats(ws);

    grid.className = 'projects-grid' + (_view === 'list' ? ' list-view' : '');
    _syncControls();

    if (!_projects.length) {
      grid.innerHTML = '';
      if (noProj)  noProj.style.display  = 'block';
      if (noMatch) noMatch.style.display = 'none';
      return;
    }
    if (noProj) noProj.style.display = 'none';

    if (!shown.length) {
      grid.innerHTML = '';
      if (noMatch) noMatch.style.display = 'block';
      return;
    }
    if (noMatch) noMatch.style.display = 'none';

    const cards = shown.map(p => _card(p, ws, isEditor)).join('');
    const ghost = (isEditor && !_query.trim())
      ? `<button type="button" class="ghost-card" onclick="ProjectsFeature.showCreateModal()">
           <span class="ghost-card-circle"><i class="fas fa-plus"></i></span>
           <span class="ghost-card-label">New Project</span>
         </button>`
      : '';
    grid.innerHTML = cards + ghost;

    // Cards are built as an HTML string, so the ⋮ menus are wired afterwards.
    grid.querySelectorAll('.pc-menu-btn').forEach(btn =>
      KebabMenu.attach(btn, () => _menuItems(btn.dataset.project, ws)));
  }

  function _card(p, ws, isEditor) {
    const pct      = p.progress || 0;
    const name     = p.name;
    const esc      = escapeHtml(name);
    const jsName   = _jsStr(name);
    const total    = p.total       || 0;
    const done     = p.annotated   || 0;
    const pending  = p.unannotated || 0;
    const coverUrl = p.has_cover
      ? `/api/workspaces/${_wsId}/projects/${encodeURIComponent(name)}/cover?workspace_id=${_wsId}&t=${Date.now()}`
      : null;

    return `
      <div class="project-card" id="pcard-${esc}"
           onclick="ProjectsFeature.openProject(${jsName},${_wsId})">

        <div class="project-card-cover">
          ${coverUrl
            ? `<img src="${coverUrl}" alt="" onerror="this.remove()">`
            : '<span class="pc-icon"><i class="fas fa-folder-open"></i></span>'}
          <div class="proj-cover-progress">
            <div class="proj-cover-progress-fill" style="width:${pct}%"></div>
          </div>
        </div>

        <div class="project-card-actions">
          <button type="button" class="kmenu-btn pc-menu-btn" title="Project options"
                  aria-label="Project options" data-project="${esc}">
            <i class="fas fa-ellipsis-vertical"></i>
          </button>
        </div>

        <div class="project-card-body">
          <div class="pc-title-row">
            <span class="project-card-name" title="${esc}">${esc}</span>
            <span class="pc-pct">${pct}%</span>
          </div>

          <div class="project-card-stats">
            <span class="pcs-chip blue"  title="Total images">
              <i class="fas fa-images"></i>${total} images
            </span>
            <span class="pcs-chip green" title="Annotated">
              <i class="fas fa-check"></i>${done} done
            </span>
            <span class="pcs-chip amber" title="Pending">
              <i class="far fa-clock"></i>${pending} pending
            </span>
          </div>

          <div class="project-card-footer">
            <span class="project-card-date">
              <i class="far fa-clock"></i>Updated ${_relTime(p.last_modified_ts, p.last_modified)}
            </span>
            ${_avatarStack(p.contributors)}
          </div>
        </div>
      </div>`;
  }

  /**
   * The card's ⋮ menu items. Gated to match the routes exactly, so the UI never
   * offers something the API will refuse: edit → rename/duplicate/cover,
   * owner → move/merge/delete.
   *
   * Rendering and positioning are handled by KebabMenu (core/utils.js), the
   * same component the upload page's Active Work / Completed Datasets cards
   * use — one implementation, one behaviour, both pages.
   */
  function _menuItems(name, ws) {
    const canEdit = ws.role === 'owner' || ws.role === 'editor';
    const isOwner = ws.role === 'owner';
    return [
      { icon: 'fa-arrow-right', label: 'Open project',
        onClick: () => openProject(name, _wsId) },
      canEdit && { icon: 'fa-pen',   label: 'Rename…',    onClick: () => askRename(name) },
      canEdit && { icon: 'fa-copy',  label: 'Duplicate…', onClick: () => askDuplicate(name) },
      canEdit && { icon: 'fa-image', label: 'Change cover…',
                   onClick: () => _pickCover(name) },
      'sep',
      isOwner && { icon: 'fa-right-left', label: 'Move to workspace…',
                   onClick: () => askMove(name) },
      isOwner && { icon: 'fa-code-merge', label: 'Merge into…',
                   onClick: () => askMerge(name) },
      'sep',
      isOwner && { icon: 'fa-trash-alt', label: 'Delete project', danger: true,
                   onClick: () => deleteProject(name, _wsId) },
    ];
  }

  /** Cover picker. The menu closes on click, taking any <label>-wrapped input
   *  with it, so the file input is created on the fly and clicked directly. */
  function _pickCover(name) {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'image/*';
    input.addEventListener('change', () => uploadCover(name, _wsId, input));
    input.click();
  }

  /** Overlapping collaborator avatars; caps at 3 with a +N bubble. */
  function _avatarStack(people) {
    if (!people || !people.length) return '';
    const shown = people.slice(0, 3);
    const extra = people.length - shown.length;
    const items = shown.map(u => `
      <span class="avatar-stack-item" title="${escapeHtml(u.name)}"
            style="background:${_avatarColor(u.id)}">${escapeHtml(u.name[0].toUpperCase())}</span>`).join('');
    const more = extra > 0
      ? `<span class="avatar-stack-item avatar-stack-more" title="${extra} more">+${extra}</span>`
      : '';
    return `<span class="avatar-stack">${items}${more}</span>`;
  }

  /**
   * Deterministic hue per user id, so a collaborator keeps the same colour
   * across cards and reloads. Unrelated to CLASS_PALETTE — that one must stay
   * fixed because it identifies annotation classes; these are people.
   */
  function _avatarColor(id) {
    return `hsl(${(id * 137.508) % 360} 55% 45%)`;
  }

  /** "2h ago" / "yesterday" / "5d ago"; falls back to the formatted string. */
  function _relTime(ts, fallback) {
    if (!ts) return fallback && fallback !== '—' ? fallback : 'never';
    const mins = Math.floor((Date.now() / 1000 - ts) / 60);
    if (mins < 1)  return 'just now';
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24)  return `${hrs}h ago`;
    const days = Math.floor(hrs / 24);
    if (days === 1) return 'yesterday';
    if (days < 7)   return `${days}d ago`;
    const wks = Math.floor(days / 7);
    if (wks < 5)    return `${wks}w ago`;
    const mos = Math.floor(days / 30);
    return mos < 12 ? `${mos}mo ago` : `${Math.floor(days / 365)}y ago`;
  }

  function _renderWsStats(ws) {
    const el = document.getElementById('ws-stats-row');
    if (!el) return;
    const n = _projects.length;
    el.textContent = `${ws.public_id || ''} · ${n} ${n === 1 ? 'project' : 'projects'}`;
  }

  // ── Search · sort · view ──────────────────────────────────────────────────

  function setQuery(q) { _query = q || ''; _render(); }

  function setSort(key) {
    _sort = key;
    localStorage.setItem('am_dash_sort', key);
    _closeSortMenu();
    _render();
  }

  function setView(mode) {
    _view = mode;
    localStorage.setItem('am_dash_view', mode);
    _render();
  }

  function toggleSortMenu() {
    const menu = document.getElementById('sort-menu');
    if (!menu) return;
    menu.hidden ? _openSortMenu() : _closeSortMenu();
  }

  function _openSortMenu() {
    const menu = document.getElementById('sort-menu');
    if (!menu) return;
    menu.hidden = false;
    document.querySelector('.sort-btn')?.setAttribute('aria-expanded', 'true');
    // Deferred so the click that opened the menu doesn't immediately close it.
    setTimeout(() => document.addEventListener('click', _onOutside), 0);
  }

  function _closeSortMenu() {
    const menu = document.getElementById('sort-menu');
    if (menu) menu.hidden = true;
    document.querySelector('.sort-btn')?.setAttribute('aria-expanded', 'false');
    document.removeEventListener('click', _onOutside);
  }

  function _onOutside(e) {
    if (!e.target.closest('#sort-control')) _closeSortMenu();
  }

  /** Reflect current sort/view in the controls (also covers the initial load,
   *  where both come from localStorage rather than a click). */
  function _syncControls() {
    _setText('sort-label', SORT_LABELS[_sort] || SORT_LABELS.recent);
    document.querySelectorAll('.sort-opt').forEach(b =>
      b.classList.toggle('active', b.textContent.trim() === SORT_LABELS[_sort]));
    document.getElementById('view-grid')?.classList.toggle('active', _view === 'grid');
    document.getElementById('view-list')?.classList.toggle('active', _view === 'list');
  }

  function _setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
  }

  /** Project names can contain quotes/backslashes — JSON-encode before
   *  embedding in an inline handler, then escape for the HTML attribute. */
  function _jsStr(s) {
    return escapeHtml(JSON.stringify(String(s)));
  }

  // ── Project operations: rename · duplicate · move · merge ────────────────
  // Each `ask*` fills and opens a modal; each `submit*` calls the API and
  // reloads the grid. `_opTarget` is the project the open modal acts on.

  let _opTarget = null;

  function closeOpModal(id) { hideModal(id); _opTarget = null; }

  function _openOp(modalId, project, errId, focusId) {
    _opTarget = project;
    setError(errId, '');
    showModal(modalId);
    if (focusId) setTimeout(() => document.getElementById(focusId)?.focus(), 50);
  }

  function askRename(project) {
    document.getElementById('proj-rename-input').value = project;
    _openOp('modal-rename-project', project, 'proj-rename-error', 'proj-rename-input');
  }

  async function submitRename() {
    const name = document.getElementById('proj-rename-input').value.trim();
    if (!name) { setError('proj-rename-error', 'Name required'); return; }
    if (name === _opTarget) { closeOpModal('modal-rename-project'); return; }
    const res = await API.put(
      `/api/workspaces/${_wsId}/projects/${encodeURIComponent(_opTarget)}/rename`,
      { name, workspace_id: _wsId });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { setError('proj-rename-error', data.error || 'Rename failed'); return; }
    closeOpModal('modal-rename-project');
    _showToast(`Renamed to "${data.name}"`, 'success');
    await load(_wsId);
  }

  function askDuplicate(project) {
    document.getElementById('proj-duplicate-input').value = `${project}-copy`;
    _openOp('modal-duplicate-project', project, 'proj-duplicate-error', 'proj-duplicate-input');
  }

  async function submitDuplicate() {
    const name = document.getElementById('proj-duplicate-input').value.trim();
    if (!name) { setError('proj-duplicate-error', 'Name required'); return; }
    setError('proj-duplicate-error', 'Copying…');
    const res = await API.post(
      `/api/workspaces/${_wsId}/projects/${encodeURIComponent(_opTarget)}/duplicate`,
      { name, workspace_id: _wsId });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { setError('proj-duplicate-error', data.error || 'Duplicate failed'); return; }
    closeOpModal('modal-duplicate-project');
    _showToast(`Created "${data.name}"`, 'success');
    await load(_wsId);
  }

  function askMove(project) {
    const sel = document.getElementById('proj-move-target');
    const all = State.get('workspaces') || [];
    // Only workspaces you can write to, and never the one it's already in —
    // the API enforces both, this just avoids offering a guaranteed failure.
    const targets = all.filter(w => w.id !== _wsId &&
                                    (w.role === 'owner' || w.role === 'editor'));
    sel.innerHTML = targets.length
      ? targets.map(w => `<option value="${w.id}">${escapeHtml(w.name)}</option>`).join('')
      : '<option value="">No other workspace you can edit</option>';
    sel.disabled = !targets.length;
    document.getElementById('proj-move-name').textContent = project;
    _openOp('modal-move-project', project, 'proj-move-error');
  }

  async function submitMove() {
    const target = document.getElementById('proj-move-target').value;
    if (!target) { setError('proj-move-error', 'Pick a target workspace'); return; }
    const res = await API.post(
      `/api/workspaces/${_wsId}/projects/${encodeURIComponent(_opTarget)}/move`,
      { target_workspace_id: parseInt(target), workspace_id: _wsId });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { setError('proj-move-error', data.error || 'Move failed'); return; }
    closeOpModal('modal-move-project');
    _showToast(`Moved "${data.name}"`, 'success');
    await load(_wsId);
  }

  function askMerge(project) {
    const sel    = document.getElementById('proj-merge-target');
    const others = _projects.filter(p => p.name !== project);
    sel.innerHTML = others.length
      ? others.map(p => `<option value="${escapeHtml(p.name)}">${escapeHtml(p.name)}</option>`).join('')
      : '<option value="">No other project in this workspace</option>';
    sel.disabled = !others.length;
    document.getElementById('proj-merge-name').textContent   = project;
    document.getElementById('proj-merge-name-2').textContent = project;
    _openOp('modal-merge-project', project, 'proj-merge-error');
  }

  async function submitMerge() {
    const target = document.getElementById('proj-merge-target').value;
    if (!target) { setError('proj-merge-error', 'Pick a target project'); return; }
    if (!confirm(`Merge "${_opTarget}" into "${target}"?\n"${_opTarget}" will be deleted. This cannot be undone.`)) return;
    setError('proj-merge-error', 'Merging…');
    const res = await API.post(
      `/api/workspaces/${_wsId}/projects/${encodeURIComponent(_opTarget)}/merge`,
      { target, workspace_id: _wsId });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { setError('proj-merge-error', data.error || 'Merge failed'); return; }
    closeOpModal('modal-merge-project');
    const added = data.classes_added
      ? `, ${data.classes_added} new class${data.classes_added === 1 ? '' : 'es'}`
      : '';
    _showToast(`Merged ${data.images} image(s) into "${target}"${added}`, 'success');
    await load(_wsId);
  }

  // ── Open project → annotate page ─────────────────────────────────────────

  function openProject(name, wsId) {
    window.location.href = `/pages/annotate?workspace_id=${wsId}&project=${encodeURIComponent(name)}`;
  }

  // ── Cover image upload ────────────────────────────────────────────────────

  async function uploadCover(projectName, wsId, input) {
    const file = input.files[0];
    if (!file) return;

    const card  = document.getElementById(`pcard-${projectName}`);
    const cover = card?.querySelector('.project-card-cover');
    if (cover) cover.style.opacity = '0.5';

    const fd = new FormData();
    fd.append('file', file);

    const res = await API.upload(
      `/api/workspaces/${wsId}/projects/${encodeURIComponent(projectName)}/cover?workspace_id=${wsId}`,
      fd
    );

    if (cover) cover.style.opacity = '1';
    input.value = '';

    if (res && res.ok) {
      _showToast('Cover image updated ✓', 'success');
      await load(wsId);            // re-render so the new cover is picked up
    } else {
      _showToast('Cover upload failed', 'error');
    }
  }

  // ── Create project ────────────────────────────────────────────────────────

  function showCreateModal() {
    document.getElementById('project-name-input').value = '';
    setError('project-create-error', '');
    showModal('modal-create-project');
    setTimeout(() => document.getElementById('project-name-input').focus(), 50);
  }

  function hideCreateModal() { hideModal('modal-create-project'); }

  async function create() {
    const name = document.getElementById('project-name-input').value.trim();
    if (!name) { setError('project-create-error', 'Name required'); return; }
    const res  = await API.post(`/api/workspaces/${_wsId}/projects`,
                                { name, workspace_id: _wsId });
    const data = await res.json();
    if (!res.ok) { setError('project-create-error', data.error || 'Failed'); return; }
    hideCreateModal();
    await load(_wsId);
  }

  // ── Delete project ────────────────────────────────────────────────────────

  async function deleteProject(name, wsId) {
    if (!confirm(`Delete project "${name}"?\nAll images, annotations and datasets will be lost.`)) return;
    const res = await API.del(`/api/workspaces/${wsId}/projects/${encodeURIComponent(name)}`,
                              { workspace_id: wsId });
    if (res && res.ok) {
      _showToast(`Project "${name}" deleted`, 'success');
      await load(wsId);
    } else {
      _showToast('Delete failed', 'error');
    }
  }

  // ── Mini toast (independent of main.js) ──────────────────────────────────

  function _showToast(msg, type) {
    const t = document.createElement('div');
    t.className = `dash-toast dash-toast-${type}`;
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 3000);
  }

  return {
    load, openProject, uploadCover,
    showCreateModal, hideCreateModal, create, deleteProject,
    setQuery, setSort, setView, toggleSortMenu,
    closeOpModal,
    askRename, submitRename, askDuplicate, submitDuplicate,
    askMove, submitMove, askMerge, submitMerge
  };
})();
