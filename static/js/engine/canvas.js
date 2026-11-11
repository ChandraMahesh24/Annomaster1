/*  AnnoMaster Pro – script.js
    Full annotation engine: virtual scroll, canvas, zoom, undo/redo,
    class management, import/export, keyboard shortcuts.
*/
'use strict';

/* ═══════════════════════════════════════════════════════════════
   CONSTANTS & STATE
══════════════════════════════════════════════════════════════════ */
const ITEM_H      = 52;   // virtual list item height px
const HANDLE_R    = 7;    // resize handle radius px
const MAX_UNDO    = 80;
const MIN_ZOOM    = 0.05;
const MAX_ZOOM    = 20;
const ZOOM_STEP   = 0.12;

const CLASS_PALETTE = [
  [255,59,59],[255,142,30],[255,211,30],[74,222,128],[34,197,225],
  [99,102,241],[168,85,247],[236,72,153],[20,184,166],[249,115,22],
  [139,92,246],[6,182,212],[132,204,22],[245,158,11],[239,68,68],
];

/* ═══════════════════════════════════════════════════════════════
   THEME BRIDGE
   ───────────────────────────────────────────────────────────────
   Canvas pixels are painted by JS, so CSS custom properties never
   reach them. The annotator's chrome — grid, crosshair, guides,
   handle fills — was therefore hardcoded to dark-theme values:
   the grid was rgba(255,255,255,0.15), i.e. a white grid that
   disappears completely on a light background, and the crosshair
   was fixed teal regardless of the active accent.

   This reads the real token values off the document element so the
   canvas follows the theme like everything else.

   NOTE: CLASS_PALETTE above is deliberately NOT themed. Those
   colours identify annotation classes; they must stay stable
   across themes or a saved box would appear to change class.

   Values are cached because getComputedStyle forces style
   recalculation and this is called inside the render loop.
══════════════════════════════════════════════════════════════════ */
const ThemeColors = {
  _cache: null,

  _read() {
    const cs = getComputedStyle(document.documentElement);
    const v  = (name, fallback) => (cs.getPropertyValue(name) || '').trim() || fallback;
    return {
      accent:   v('--accent', '#00e5b0'),
      grid:     v('--ink-a15', 'rgba(255,255,255,0.15)'),
      // Foreground that contrasts with a saturated fill — used for
      // handle centres and label text drawn over a class colour.
      onFill:   v('--on-fill', '#000'),
      surface:  v('--surface', '#0d0d16'),
      text:     v('--tx', '#f0f0f8'),
      // Handle contrast: white pips read well on the dark theme but
      // vanish on the light one, so this flips with the surface.
      handle:   v('--surface', '#ffffff'),
    };
  },

  get() {
    if (!this._cache) this._cache = this._read();
    return this._cache;
  },

  /* Invalidate after a theme switch so the next frame repaints with
     the new palette. */
  refresh() {
    this._cache = null;
    return this.get();
  },

  /* Same accent at an arbitrary alpha, for guides and glows. */
  accentAlpha(a) {
    const c = this.get().accent;
    if (c.startsWith('#')) {
      const h = c.length === 4
        ? c.slice(1).split('').map(x => x + x).join('')
        : c.slice(1);
      const n = parseInt(h, 16);
      return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
    }
    // Already a colour function — let the browser blend it.
    return `color-mix(in srgb, ${c} ${Math.round(a * 100)}%, transparent)`;
  },
};

/* Repaint when the theme changes. ThemeEngine.setThemeMode toggles
   these classes on <html>, so observing the attribute covers the
   light/dark/custom switch and the compact toggle alike. */
if (typeof MutationObserver !== 'undefined') {
  new MutationObserver(() => {
    ThemeColors.refresh();
    if (typeof Canvas !== 'undefined' && Canvas.render) Canvas.render();
  }).observe(document.documentElement, {
    attributes: true, attributeFilter: ['class', 'style'],
  });
}

const state = {
  // project
  project:  window.APP_DATA?.currentProject || 'default',
  projects: window.APP_DATA?.projects        || {},

  // media list
  media:           [],   // [{path, name, split, annotated}]
  filteredMedia:   [],
  currentIdx:      -1,
  searchText:      '',
  filterSplit:     'all',
  filterAnno:      'all',  // all | annotated | empty
  annotatedPaths:  new Set(),
  nullPaths:       new Set(),
  isCurrentNull:   false,   // true when current image is marked __null__

  // classes
  classes:     (window.APP_DATA?.classes || []).map(c => ({...c})),
  selectedCls: 0,

  // canvas
  imgEl:      null,
  imgW:       0,
  imgH:       0,
  bboxes:     [],     // [{id, cls, x,y,w,h}] pixel coords on image
  selectedId: null,

  // drawing
  mode:       'bbox', // bbox | edit | pan
  drawing:    false,
  drawStart:  null,
  pendingBox: null,

  // drag/resize
  dragging:   false,
  dragBox:    null,
  dragOffX:   0,
  dragOffY:   0,
  resizing:   false,
  resizeBox:  null,
  resizeHandle: null,

  // zoom/pan
  zoom:       1,
  panX:       0,
  panY:       0,
  zoomLocked: false,
  lockedZoom: 1,
  lockedPanX: 0,
  lockedPanY: 0,
  panning:    false,
  panStart:   null,

  // undo/redo
  undoStack:  [],
  redoStack:  [],

  // auto-save
  autoSave:   true,
  savePending:false,
  saveTimer:  null,

  // NEW: copy/paste
  copiedBox:  null,

  // NEW: class visibility (set of hidden class IDs)
  hiddenClasses: new Set(),

  // NEW: display settings
  showLabels:   true,
  showGrid:     false,
  gridSize:     50,
  brightness:   100,
  contrast:     100,
  labelOpacity: 0.80,
  boxLineWidth: 1.8,

  // NEW: SPA routing
  currentPage: 'annotate',

  // NEW: Dataset page state
  dsFilter:  'all',   // split filter
  dsAnnoFilter: 'all',
  dsSearch:  '',
  dsPage:    1,
  dsPerPage: 40,
  dsSearch:  '',
  dsFilter:  'all',
  dsAnnoFilter: 'all',
  dsClassFilter: '',
  dsSelectedPaths: null,
  dsSelectMode: false,

  // NEW: Media list pagination
  listPage:       1,
  listPerPage:    50,
  listTotal:      0,
  listTotalPages: 1,
  listTotalAnnotated: 0,   // full project annotated count (from /api/media/count)
  listTotalDatasetImages: 0, // total images in completed datasets (for nav badge)

  // Job lock — when set, the annotator shows ONLY images from this job.
  // nextImage/prevImage will NOT cross into other jobs.
  // Cleared when user loads all images (no job filter).
  activeJobId:      null,  // upload_id of the locked batch, or null = all jobs
  activeJobTotal:   0,     // total images in locked job
  activeJobName:    '',    // display name for the locked job

  // NEW: Versions
  versions: [],
  selectedVersionId: null,

  // NEW: Comments per image path
  imageComments: {},  // { path: [{text, time}] }

  // NEW: Classes page
  clsPageStats: {},   // { id: {count, images} }

  // Polygon drawing state
  polygonPoints:  [],   // [{x,y}] image coords
  polygonPreview: null, // {x,y} current mouse position

  // Repeat mode (skip class popup, use last used class)
  repeatMode:  false,
  lastUsedCls: null,
};

/* ═══════════════════════════════════════════════════════════════
   VIRTUAL SCROLLER
══════════════════════════════════════════════════════════════════ */
class VirtualScroller {
  constructor(vpEl, innerEl, renderRow) {
    this.vp = vpEl;
    this.inner = innerEl;
    this.renderRow = renderRow;
    this.items = [];
    this.rendered = new Map();
    this.vp.addEventListener('scroll', () => this.update(), {passive:true});
    if (window.ResizeObserver) {
      this.resizeObserver = new ResizeObserver(() => this.update());
      this.resizeObserver.observe(this.vp);
    }
  }
  setItems(items) {
    this.items = items;
    this.inner.style.height = items.length * ITEM_H + 'px';
    this.rendered.forEach(el => el.remove());
    this.rendered.clear();
    this.update();
  }
  update() {
    const scrollTop = this.vp.scrollTop;
    const vpH = this.vp.clientHeight;
    const start = Math.max(0, Math.floor(scrollTop / ITEM_H) - 3);
    const end   = Math.min(this.items.length, Math.ceil((scrollTop + vpH) / ITEM_H) + 3);

    // remove out-of-view
    this.rendered.forEach((el, i) => {
      if (i < start || i >= end) { el.remove(); this.rendered.delete(i); }
    });
    // add in-view
    for (let i = start; i < end; i++) {
      if (!this.rendered.has(i)) {
        const el = this.renderRow(this.items[i], i);
        el.style.top = i * ITEM_H + 'px';
        this.inner.appendChild(el);
        this.rendered.set(i, el);
      }
    }
  }
  scrollTo(idx) {
    const y = idx * ITEM_H;
    this.vp.scrollTop = y - this.vp.clientHeight / 2 + ITEM_H / 2;
  }
  refresh() { this.update(); }
}

/* ═══════════════════════════════════════════════════════════════
   APP OBJECT
══════════════════════════════════════════════════════════════════ */
const app = {

  /* ── INIT ── */
  init() {
    this.canvas = document.getElementById('annoCanvas');
    this.ctx    = this.canvas.getContext('2d');

    this.scroller = new VirtualScroller(
      document.getElementById('imgListVp'),
      document.getElementById('imgListInner'),
      (item, i) => this._renderListItem(item, i)
    );

    this._bindUI();
    this._bindKeys();
    this._bindCanvas();
    this._bindSidebars();
    this._bindRightNav();
    this._bindRightPanelTabs();
    this._bindUploadPage();

    this._populateClassList();
    this._loadMedia();

    // sync project across all dropdowns
    this._syncProjectDropdowns(state.project);

    // Restore the section from the URL hash (e.g. #upload, #dataset)
    const VALID_PAGES = new Set(['upload','annotate','dataset','versions','classes','projects']);
    const hashPage = location.hash.replace('#', '');
    if (VALID_PAGES.has(hashPage)) this.showPage(hashPage);
  },

  /* ── MEDIA LOADING (paginated) ─────────────────────────────────────────────
     page=null → reload current page; page=N → go to page N.
     Only 50 images are fetched per page; label files are only read for that
     page's images, making large-dataset loads O(50) not O(N).
     Calling _loadMedia always clears the job lock — it loads all jobs.      */
  async _loadMedia(page = null) {
    // ── Clear job lock: _loadMedia loads all jobs, not a single one ──────────
    state.activeJobId   = null;
    state.activeJobName = '';
    this._updateJobStatusBar();  // hide the job status bar

    try {
      // ── Save the image we're leaving (captured before any state changes) ───
      const prevPath    = state.currentIdx >= 0 ? state.media[state.currentIdx]?.path : null;
      const prevProject = state.project;
      if (prevPath && state.autoSave && state.imgW > 0 && state.imgH > 0) {
        await this._saveToPath(prevPath, prevProject);
      }

      // ── Show loading indicator in the sidebar list ─────────────────────────
      this._setListLoading(true);

      // ── Which page to load ─────────────────────────────────────────────────
      const targetPage = (page != null) ? Math.max(1, page) : Math.max(1, state.listPage);

      // ── Fetch paginated media ──────────────────────────────────────────────
      const url = `/api/media?project=${encodeURIComponent(state.project)}`
                + `&page=${targetPage}&per_page=${state.listPerPage}`;
      const r = await fetch(url);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();

      // Update pagination state FIRST
      const pg = d.pagination || {};
      state.listPage       = pg.page        || targetPage;
      state.listPerPage    = pg.per_page    || state.listPerPage;
      state.listTotal      = pg.total       || (d.media || []).length;
      state.listTotalPages = pg.total_pages || 1;

      state.media          = d.media        || [];
      state.annotatedPaths = new Set(d.annotated  || []);
      state.nullPaths      = new Set(d.null_paths || []);

      if (d.classes && Array.isArray(d.classes)) {
        state.classes = d.classes;
        this._populateClassList();
        if (typeof this._renderClassesTable === 'function') this._renderClassesTable();
      }

      // Reset canvas state since we have a new page of images
      state.currentIdx = -1;
      state.bboxes     = [];
      state.selectedId = null;
      state.imgW = 0; state.imgH = 0; state.imgEl = null;

      this._setListLoading(false);
      this._applyFilter();
      this._updateTotals();
      this._updatePagination();
      this._updateNavBadges();
      this._updateHeaderBreadcrumb();

      // Fetch full project counts in background for accurate badges (debounced)
      this._scheduleFullCounts();

      if (state.media.length > 0) {
        if (state.currentPage === 'annotate' || state.currentPage === 'upload') {
          // If reloading same page, try to restore position
          const sameIdx = prevPath && page == null
            ? state.media.findIndex(m => m.path === prevPath)
            : -1;
          try { this.loadImage(sameIdx >= 0 ? sameIdx : 0, true); }
          catch(e) { console.warn('loadImage failed:', e); }
        }
        // ── Prefetch next page in background ────────────────────────────────
        if (state.listPage < state.listTotalPages) {
          this._prefetchPage(state.listPage + 1);
        }
      } else {
        try { this._render(); } catch(e) {}
        try { this._updateAnnoList(); } catch(e) {}
        this._updateHeaderImage('', -1, 0);
        const canvasEmpty = document.getElementById('canvasEmpty');
        const canvasWrap  = document.getElementById('canvasWrap');
        if (canvasEmpty) canvasEmpty.style.removeProperty('display');
        if (canvasWrap)  canvasWrap.style.display = 'none';
      }
    } catch(e) {
      this._setListLoading(false);
      console.error('_loadMedia error:', e);
      this._toast('Failed to load project media', 'error');
    }
  },

  // Show/hide a skeleton loading state in the image list
  _setListLoading(on) {
    const vp = document.getElementById('imgListVp');
    if (!vp) return;
    if (on) {
      vp.classList.add('list-loading');
    } else {
      vp.classList.remove('list-loading');
    }
    const bar = document.getElementById('listPageBar');
    if (bar) {
      const prevBtn = bar.querySelector('.lp-prev');
      const nextBtn = bar.querySelector('.lp-next');
      const pills   = bar.querySelectorAll('.lp-pill');
      [prevBtn, nextBtn, ...pills].forEach(b => { if (b) b.disabled = on; });
    }
  },

  // Prefetch a page into the browser cache without touching state
  _prefetchPage(page) {
    const url = `/api/media?project=${encodeURIComponent(state.project)}`
              + `&page=${page}&per_page=${state.listPerPage}`;
    fetch(url, { priority: 'low' }).catch(() => {});
  },

  // Debounced full-count refresh — only fires once per 3 s to avoid hammering
  // the server when the user navigates rapidly through pages.
  _scheduleFullCounts() {
    clearTimeout(this._fullCountTimer);
    this._fullCountTimer = setTimeout(() => this._refreshFullCounts(), 800);
  },

  // Fetch full project annotation count + current job stats in background
  async _refreshFullCounts() {
    try {
      // Project-wide counts
      const r = await fetch(`/api/media/count?project=${encodeURIComponent(state.project)}`);
      if (!r.ok) return;
      const d = await r.json();
      state.listTotal          = d.total     ?? state.listTotal;
      state.listTotalAnnotated = d.annotated ?? 0;
      this._updateTotals();
      this._updateNavBadges();
      this._updatePagination();

      // Per-job stats — use most-recent batch from uploads API
      const ru = await fetch(`/api/uploads?project=${encodeURIComponent(state.project)}`);
      if (!ru.ok) return;
      const batches = await ru.json();
      if (batches && batches.length > 0) {
        // Most recent job = last in list (sorted by upload_id ascending)
        const latest = batches[batches.length - 1];
        this._updateJobStats(
          latest.job_name || '',
          latest.total      || 0,
          latest.annotated  || 0,
          latest.unannotated || 0
        );
      } else {
        this._updateJobStats('', 0, 0, 0);
      }
    } catch(e) { /* silent */ }
  },

  // Save annotations directly to a specific path — used by _loadMedia so
  // it can save before state.media is replaced with a new list.
  async _saveToPath(path, project) {
    if (!path || !project) return;
    const W = state.imgW || 0;
    const H = state.imgH || 0;
    if (W <= 0 || H <= 0) return;

    const bboxesNorm = state.bboxes
      .filter(b => b.type === 'polygon' || (b.w > 0 && b.h > 0))
      .map(b => {
        if (b.type === 'polygon') {
          return { class_id: b.cls, type: 'polygon',
            points: (b.points || []).map(p => ({ x: p.x / W, y: p.y / H })) };
        }
        return { class_id: b.cls, type: 'bbox',
          x_center: (b.x + b.w / 2) / W, y_center: (b.y + b.h / 2) / H,
          width: b.w / W, height: b.h / H };
      })
      .filter(b => b.type === 'polygon' ||
        (isFinite(b.x_center) && isFinite(b.y_center) && b.width > 0 && b.height > 0));

    try {
      await fetch('/api/annotations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path, project, bboxes: bboxesNorm })
      });
    } catch(e) { /* silent — best effort */ }
  },

  _applyFilter() {
    const q  = state.searchText.toLowerCase();
    const sp = state.filterSplit;
    const an = state.filterAnno;

    state.filteredMedia = state.media.filter(m => {
      if (q  && !m.name.toLowerCase().includes(q)) return false;
      if (sp !== 'all' && m.split !== sp)            return false;
      if (an === 'annotated' && !state.annotatedPaths.has(m.path)) return false;
      if (an === 'empty'     &&  state.annotatedPaths.has(m.path)) return false;
      return true;
    });

    this.scroller.setItems(state.filteredMedia);
    // Show global total in the badge, not just this page's count
    const totalEl = document.getElementById('totalCount');
    if (totalEl) totalEl.textContent = state.listTotal || state.filteredMedia.length;
    document.getElementById('listEmpty').style.display =
      state.filteredMedia.length ? 'none' : '';
  },

  _updateTotals() {
    // Page-level counts (what's currently loaded)
    const pageAnnotated = state.media.filter(m => state.annotatedPaths.has(m.path)).length;

    // Full project counts (from _refreshFullCounts background fetch)
    const fullTotal     = state.listTotal      || state.media.length;
    const fullAnnotated = state.listTotalAnnotated > 0
                          ? state.listTotalAnnotated
                          : pageAnnotated;
    const fullPending   = fullTotal - fullAnnotated;
    const pct           = fullTotal > 0 ? Math.round(fullAnnotated / fullTotal * 100) : 0;

    const el = document.getElementById('totalCount');
    if (el) el.textContent = fullTotal;
    const acoT = document.getElementById('acoTotal');
    const acoA = document.getElementById('acoAnnotated');
    const acoE = document.getElementById('acoEmpty');
    if (acoT) acoT.textContent = fullTotal;
    if (acoA) acoA.textContent = fullAnnotated;
    if (acoE) acoE.textContent = fullPending;

    // Header inline progress bar
    const fill = document.getElementById('hdrProgressFill');
    const pctEl = document.getElementById('hdrProgressPct');
    if (fill)  fill.style.width  = pct + '%';
    if (pctEl) pctEl.textContent = pct + '%';
  },

  // Update the per-job stats bar in the left sidebar (called from _renderUploadBatches / _refreshFullCounts)
  _updateJobStats(jobName, total, annotated, unannotated) {
    const bar = document.getElementById('jobStatsBar');
    if (!bar) return;
    if (!jobName || total === 0) { bar.style.display = 'none'; return; }
    bar.style.display = '';
    const nameEl = document.getElementById('jobStatsName');
    if (nameEl) nameEl.textContent = jobName.replace(/^job_/, '');
    const t = document.getElementById('jobStatTotal');
    const a = document.getElementById('jobStatAnnotated');
    const p = document.getElementById('jobStatPending');
    const f = document.getElementById('jobStatFill');
    if (t) t.textContent = total;
    if (a) a.textContent = annotated;
    if (p) p.textContent = unannotated;
    const pct = total > 0 ? Math.round(annotated / total * 100) : 0;
    if (f) f.style.width = pct + '%';
  },

  // Show the locked-job status bar at the top of the left sidebar when
  // the annotator is scoped to a single batch/job.
  _updateJobStatusBar() {
    const bar = document.getElementById('jobLockBar');
    if (!bar) return;

    if (!state.activeJobId) {
      bar.style.display = 'none';
      return;
    }
    bar.style.display = '';

    // Job name (strip "job_" prefix for readability)
    const nameEl = bar.querySelector('.jlb-name');
    if (nameEl) {
      const display = state.activeJobName.replace(/^job_/, '');
      nameEl.textContent = display;
    }

    // Annotated vs pending counts from current state.annotatedPaths
    const total     = state.media.length;
    const annotated = state.media.filter(m => state.annotatedPaths.has(m.path)).length;
    const pending   = total - annotated;
    const pct       = total > 0 ? Math.round(annotated / total * 100) : 0;

    const annEl  = bar.querySelector('.jlb-annotated');
    const penEl  = bar.querySelector('.jlb-pending');
    const totEl  = bar.querySelector('.jlb-total');
    const fillEl = bar.querySelector('.jlb-fill');
    const pctEl  = bar.querySelector('.jlb-pct');

    if (annEl)  annEl.textContent  = annotated;
    if (penEl)  penEl.textContent  = pending;
    if (totEl)  totEl.textContent  = total;
    if (fillEl) fillEl.style.width = pct + '%';
    if (pctEl)  pctEl.textContent  = pct + '%';
  },

  _updatePagination() {
    const bar   = document.getElementById('listPageBar');
    if (!bar) return;
    const total = state.listTotal;
    const pages = state.listTotalPages;
    const cur   = state.listPage;

    // Sync the per-page select to the current state so it always matches
    // what was actually fetched (e.g. after a project switch or job reload).
    const perpageSel = document.getElementById('lpPerPage');
    if (perpageSel && perpageSel.value !== String(state.listPerPage)) {
      perpageSel.value = state.listPerPage;
    }

    // Keep the bar visible even for single-page jobs so the per-page
    // selector remains accessible; hide only the navigation elements.
    bar.style.display = total > 0 ? '' : 'none';
    if (pages <= 1) {
      const prevBtn = bar.querySelector('.lp-prev');
      const nextBtn = bar.querySelector('.lp-next');
      const pills   = bar.querySelector('.lp-pills');
      const info    = bar.querySelector('.lp-info');
      if (prevBtn) prevBtn.style.display = 'none';
      if (nextBtn) nextBtn.style.display = 'none';
      if (pills)   pills.innerHTML = '';
      if (info)    info.textContent = `${total} images`;
      return;
    }
    // Multi-page: show navigation
    const prevBtn2 = bar.querySelector('.lp-prev');
    const nextBtn2 = bar.querySelector('.lp-next');
    if (prevBtn2) { prevBtn2.style.display = ''; prevBtn2.disabled = (cur <= 1); }
    if (nextBtn2) { nextBtn2.style.display = ''; nextBtn2.disabled = (cur >= pages); }

    // Page info label
    const info = bar.querySelector('.lp-info');
    if (info) {
      const start = (cur - 1) * state.listPerPage + 1;
      const end   = Math.min(cur * state.listPerPage, total);
      info.textContent = `${start}–${end} of ${total}`;
    }

    // Page number pills
    const pills = bar.querySelector('.lp-pills');
    if (!pills) return;
    pills.innerHTML = '';
    const maxPills = 5;
    let pStart = Math.max(1, cur - Math.floor(maxPills / 2));
    let pEnd   = Math.min(pages, pStart + maxPills - 1);
    if (pEnd - pStart < maxPills - 1) pStart = Math.max(1, pEnd - maxPills + 1);

    if (pStart > 1) {
      pills.appendChild(this._makePill(1, cur));
      if (pStart > 2) {
        const ell = document.createElement('span');
        ell.className = 'lp-ellipsis'; ell.textContent = '…';
        pills.appendChild(ell);
      }
    }
    for (let p = pStart; p <= pEnd; p++) pills.appendChild(this._makePill(p, cur));
    if (pEnd < pages) {
      if (pEnd < pages - 1) {
        const ell = document.createElement('span');
        ell.className = 'lp-ellipsis'; ell.textContent = '…';
        pills.appendChild(ell);
      }
      pills.appendChild(this._makePill(pages, cur));
    }
  },

  _makePill(page, current) {
    const btn = document.createElement('button');
    btn.className = 'lp-pill' + (page === current ? ' active' : '');
    btn.textContent = page;
    btn.addEventListener('click', () => this._loadMedia(page));
    return btn;
  },

  _renderListItem(item, i) {
    const isActive    = state.media[state.currentIdx]?.path === item.path;
    const isAnnotated = state.annotatedPaths.has(item.path);
    // Global index = (page - 1) * perPage + local index (1-based)
    const globalIdx   = (state.listPage - 1) * state.listPerPage + i + 1;
    const div = document.createElement('div');
    div.className = 'img-item' + (isActive ? ' active' : '');
    div.dataset.path = item.path;

    const thumb = document.createElement('img');
    thumb.className = 'img-thumb';
    thumb.loading = 'lazy';
    thumb.src = `/api/thumbnail?path=${encodeURIComponent(item.path)}&project=${encodeURIComponent(state.project)}`;
    thumb.onerror = () => {
      thumb.style.display = 'none';
      const ph = document.createElement('div');
      ph.className = 'img-thumb-placeholder';
      ph.innerHTML = '<i class="fas fa-image"></i>';
      div.insertBefore(ph, div.children[1]);
    };

    const meta = document.createElement('div');
    meta.className = 'img-meta';
    meta.innerHTML = `<div class="img-name" title="${item.name}">${item.name}</div>
      <div class="img-sub">${item.split || '—'} &nbsp;#${globalIdx}</div>`;

    const dot = document.createElement('span');
    dot.className = 'anno-status ' + (isAnnotated ? 'full' : 'empty');

    div.append(thumb, meta, dot);
    div.addEventListener('click', () => {
      const realIdx = state.media.findIndex(m => m.path === item.path);
      if (realIdx >= 0) this.loadImage(realIdx);
    });
    return div;
  },

  /* ── IMAGE LOADING ── */
  async loadImage(idx, skipSave = false) {
    // ── Guard: save annotations for the image we're LEAVING ──────────────────
    // Only save if dimensions are known (image was fully loaded) and we have
    // something to save. Capture the item NOW before state changes.
    if (!skipSave && state.currentIdx >= 0 && state.autoSave &&
        state.imgW > 0 && state.imgH > 0) {
      await this._saveCurrentAnnotations();
    }

    // ── Cancel any in-flight load from a previous call ────────────────────────
    // Each call gets a unique generation number. img.onload and _loadAnnotations
    // check their captured generation before applying any state — if it's stale
    // they discard the result silently. This prevents race conditions when the
    // user navigates quickly.
    if (!state._loadGen) state._loadGen = 0;
    const gen = ++state._loadGen;

    // ── Also cancel any pending autosave timer ────────────────────────────────
    clearTimeout(state.saveTimer);

    state.currentIdx = idx;
    const item = state.media[idx];
    if (!item) return;

    // Reset dimensions immediately — blocks any save triggered before onload
    state.imgW = 0;
    state.imgH = 0;
    // Clear boxes immediately so the canvas goes blank during load
    state.bboxes     = [];
    state.selectedId = null;
    // Reset null state for the new image
    state.isCurrentNull = false;
    this._syncNullBtn();

    // show canvas
    document.getElementById('canvasEmpty').style.display = 'none';
    document.getElementById('canvasWrap').style.display  = '';

    // ── Update header bar ────────────────────────────────────────────────────
    this._updateHeaderImage(item.name, idx, state.media.length);
    this._updateImageStatusBadge(item);

    // highlight in list
    const filteredIdx = state.filteredMedia.findIndex(m => m.path === item.path);
    if (filteredIdx >= 0) this.scroller.scrollTo(filteredIdx);
    this._refreshListHighlight();

    // load image
    const img = new Image();
    img.onload = () => {
      // Stale check — a newer loadImage call has already started
      if (gen !== state._loadGen) return;

      state.imgEl = img;
      state.imgW  = img.naturalWidth;
      state.imgH  = img.naturalHeight;

      this._resetCanvas();
      if (state.zoomLocked) {
        state.zoom = state.lockedZoom;
        state.panX = state.lockedPanX;
        state.panY = state.lockedPanY;
      } else {
        this._fitImage();
      }
      this._loadAnnotations(item.path, gen);
      this._updateStatusBar();
      this._updateImageInfo(item);
    };
    img.onerror = () => {
      if (gen !== state._loadGen) return;
      this._toast('Failed to load image — file may be corrupted', 'error');
    };
    img.src = `/api/image?path=${encodeURIComponent(item.path)}&project=${encodeURIComponent(state.project)}`;
  },

  _updateImageStatusBadge(item) {
    const el = document.getElementById('hdrImageStatus');
    if (!el) return;
    const isAnnotated = state.annotatedPaths.has(item.path);
    const hasBoxes    = state.bboxes && state.bboxes.length > 0;
    let cls, html;
    if (isAnnotated) {
      cls  = 'hdr-status-badge annotated';
      html = '<i class="fas fa-check-circle"></i> Annotated';
    } else if (hasBoxes) {
      cls  = 'hdr-status-badge inprogress';
      html = '<i class="fas fa-pencil-alt"></i> In Progress';
    } else {
      cls  = 'hdr-status-badge unannotated';
      html = '<i class="fas fa-circle"></i> Unannotated';
    }
    el.className = cls;
    el.innerHTML = html;
  },

  async _loadAnnotations(path, gen) {
    // Initialise boxes empty immediately (canvas clears before fetch completes)
    state.bboxes     = [];
    state.selectedId = null;
    state.undoStack  = [];
    state.redoStack  = [];
    this._updateUndoRedo();
    this._updateAnnoList();

    try {
      const r = await fetch(`/api/annotations?path=${encodeURIComponent(path)}&project=${encodeURIComponent(state.project)}`);
      // Stale check — user navigated away while this fetch was in flight
      if (gen !== undefined && gen !== state._loadGen) return;

      const d = await r.json();
      // Double-check generation after the second await
      if (gen !== undefined && gen !== state._loadGen) return;

      if (d.bboxes && state.imgW > 0 && state.imgH > 0) {
        state.bboxes = d.bboxes
          .map(b => {
            if (b.type === 'polygon') {
              const pts = (b.points || []).map(p => ({
                x: p.x * state.imgW, y: p.y * state.imgH
              }));
              const xs = pts.map(p => p.x), ys = pts.map(p => p.y);
              const bx = Math.min(...xs), by = Math.min(...ys);
              const bw = Math.max(...xs) - bx,  bh = Math.max(...ys) - by;
              return {
                id: Math.random().toString(36).slice(2),
                cls: b.class_id, type: 'polygon',
                points: pts, x: bx, y: by, w: bw, h: bh
              };
            } else {
              const x = Math.round((b.x_center - b.width  / 2) * state.imgW);
              const y = Math.round((b.y_center - b.height / 2) * state.imgH);
              const w = Math.round(b.width  * state.imgW);
              const h = Math.round(b.height * state.imgH);
              return {
                id:  Math.random().toString(36).slice(2),
                cls: b.class_id, type: 'bbox', x, y, w, h
              };
            }
          })
          // Drop any box that came out with bad pixel dimensions
          .filter(b => b.w > 0 && b.h > 0);
      }
    } catch(e) { /* no label file — leave bboxes = [] */ }

    // Final stale check before applying to canvas
    if (gen !== undefined && gen !== state._loadGen) return;

    // Sync null button state — button is active when the current image is marked null
    state.isCurrentNull = !!(d && d.is_null);
    this._syncNullBtn();

    this._render();
    this._updateAnnoList();
    this._updateClassCounts();
    this._statusObjects();
    this._updateRawData();
    this._updateUnusedClasses();
  },
  // ── Null mark ─────────────────────────────────────────────────────────────
  // "Null" means: the image has been reviewed and confirmed to contain nothing
  // to annotate. A __null__ marker is written to the labels/ folder so the
  // batch-counter can distinguish "not yet looked at" from "deliberately empty".
  async toggleNullMark() {
    if (state.currentIdx < 0) return;
    const item = state.media[state.currentIdx];
    if (!item) return;

    const willBeNull = !state.isCurrentNull;

    if (willBeNull) {
      // Mark as null: clear any bboxes, write __null__ to disk
      state.bboxes     = [];
      state.selectedId = null;
      clearTimeout(state.saveTimer);
      try {
        await fetch('/api/null', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ project: state.project, path: item.path }),
        });
        state.isCurrentNull = true;
        state.nullPaths.add(item.path);
        state.annotatedPaths.delete(item.path);
        this._toast('Marked as Null — no annotations for this image', 'info');
      } catch(e) {
        this._toast('Failed to mark as null', 'error'); return;
      }
    } else {
      // Un-mark: delete the __null__ file so image becomes unannotated again
      try {
        await fetch('/api/null', {
          method: 'DELETE',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ project: state.project, path: item.path }),
        });
        state.isCurrentNull = false;
        state.nullPaths.delete(item.path);
        this._toast('Null mark removed', 'info');
      } catch(e) {
        this._toast('Failed to remove null mark', 'error'); return;
      }
    }

    this._syncNullBtn();
    this._render();
    this._updateAnnoList();
    this._updateTotals();
    this._refreshFullCounts?.();
  },

  _syncNullBtn() {
    const btn = document.getElementById('nullMarkBtn');
    if (!btn) return;
    if (state.isCurrentNull) {
      btn.classList.add('active');
      btn.title = 'Remove Null mark (N)';
    } else {
      btn.classList.remove('active');
      btn.title = 'Mark as Null — image has nothing to annotate (N)';
    }
  },

  _resetCanvas() {
    const area  = document.getElementById('canvasArea');
    const W = area.clientWidth;
    const H = area.clientHeight;
    this.canvas.width  = W;
    this.canvas.height = H;
    this._fitImage();
  },

  _fitImage() {
    if (!state.imgEl) return;
    const cW = this.canvas.width;
    const cH = this.canvas.height;
    const scale = Math.min(cW / state.imgW, cH / state.imgH) * 0.92;
    state.zoom = scale;
    state.panX = (cW - state.imgW * scale) / 2;
    state.panY = (cH - state.imgH * scale) / 2;
    this._updateZoomDisplay();
    this._render();
  },

  // Convert canvas px → image px
  _toImg(cx, cy) {
    return { x: (cx - state.panX) / state.zoom, y: (cy - state.panY) / state.zoom };
  },
  // Convert image px → canvas px
  _toCanvas(ix, iy) {
    return { x: ix * state.zoom + state.panX, y: iy * state.zoom + state.panY };
  },

  /* ── RENDER ── */
  _render() {
    if (!state.imgEl) return;
    const ctx = this.ctx;
    const W = this.canvas.width, H = this.canvas.height;

    ctx.clearRect(0, 0, W, H);

    // apply brightness/contrast filter
    ctx.filter = `brightness(${state.brightness}%) contrast(${state.contrast}%)`;
    // draw image
    ctx.drawImage(state.imgEl,
      state.panX, state.panY,
      state.imgW * state.zoom, state.imgH * state.zoom
    );
    ctx.filter = 'none';

    // draw grid overlay
    if (state.showGrid) this._drawGrid();

    // draw boxes
    for (const box of state.bboxes) {
      if (state.hiddenClasses.has(box.cls)) continue;
      if (box.type === 'polygon') this._drawPolygon(box, box.id === state.selectedId);
      else this._drawBox(box, box.id === state.selectedId);
    }

    // draw pending (in-progress drawing)
    if (state.pendingBox) {
      this._drawBox(state.pendingBox, false, true);
      // draw crosshair guide lines through current mouse position
      if (state.drawing && state._mouseCanvas) {
        this._drawCrosshair(state._mouseCanvas.cx, state._mouseCanvas.cy);
      }
    }

    // draw in-progress polygon
    if (state.mode === 'polygon' && state.polygonPoints.length > 0) {
      this._drawPolygonInProgress();
    }
  },

  _drawGrid() {
    const ctx = this.ctx;
    const gs  = state.gridSize * state.zoom;
    const {x: ox, y: oy} = this._toCanvas(0, 0);
    const iw  = state.imgW * state.zoom;
    const ih  = state.imgH * state.zoom;

    ctx.save();
    // Was a fixed white grid — invisible on the light theme.
    ctx.strokeStyle = ThemeColors.get().grid;
    ctx.lineWidth   = 0.5;
    ctx.setLineDash([3, 3]);

    // vertical lines
    for (let x = ox; x < ox + iw; x += gs) {
      ctx.beginPath(); ctx.moveTo(x, oy); ctx.lineTo(x, oy + ih); ctx.stroke();
    }
    // horizontal lines
    for (let y = oy; y < oy + ih; y += gs) {
      ctx.beginPath(); ctx.moveTo(ox, y); ctx.lineTo(ox + iw, y); ctx.stroke();
    }
    ctx.setLineDash([]);
    ctx.restore();
  },

  _drawCrosshair(cx, cy) {
    const ctx = this.ctx;
    const W   = this.canvas.width;
    const H   = this.canvas.height;
    // Image bounds in canvas coords
    const {x: imgLeft, y: imgTop}    = this._toCanvas(0, 0);
    const {x: imgRight, y: imgBot}   = this._toCanvas(state.imgW, state.imgH);

    ctx.save();
    ctx.setLineDash([4, 4]);
    ctx.lineWidth   = 1;
    ctx.strokeStyle = ThemeColors.accentAlpha(0.45);

    // Horizontal line across image width only
    ctx.beginPath();
    ctx.moveTo(imgLeft,  cy);
    ctx.lineTo(imgRight, cy);
    ctx.stroke();

    // Vertical line across image height only
    ctx.beginPath();
    ctx.moveTo(cx, imgTop);
    ctx.lineTo(cx, imgBot);
    ctx.stroke();

    // Bright intersection dot
    ctx.setLineDash([]);
    ctx.fillStyle = ThemeColors.accentAlpha(0.8);
    ctx.beginPath();
    ctx.arc(cx, cy, 3, 0, Math.PI * 2);
    ctx.fill();

    ctx.restore();
  },

  _drawBox(box, selected, isPending = false) {
    const ctx = this.ctx;
    const cls = state.classes.find(c => c.id === box.cls) || {color:[180,180,180], name:'?'};
    const [r,g,b] = cls.color;
    const color = `rgb(${r},${g},${b})`;

    const {x:cx, y:cy} = this._toCanvas(box.x, box.y);
    const cw = box.w * state.zoom;
    const ch = box.h * state.zoom;

    const alpha = isPending ? 0.08 : state.labelOpacity * 0.2;
    // fill
    ctx.fillStyle = `rgba(${r},${g},${b},${alpha})`;
    ctx.fillRect(cx, cy, cw, ch);

    // border
    if (isPending) {
      // The pending-box outline signals "AI suggestion, unconfirmed"
      // using the app accent, so it must track the active accent
      // rather than staying fixed teal.
      ctx.strokeStyle  = ThemeColors.accentAlpha(0.9);
      ctx.lineWidth    = 1.5;
      ctx.setLineDash([6, 4]);
      ctx.shadowColor  = ThemeColors.accentAlpha(0.4);
      ctx.shadowBlur   = 6;
    } else if (selected) {
      ctx.strokeStyle  = color;
      ctx.lineWidth    = state.boxLineWidth * 1.6;
      ctx.shadowColor  = color;
      ctx.shadowBlur   = 5;
    } else {
      ctx.strokeStyle  = color;
      ctx.lineWidth    = state.boxLineWidth;
    }
    ctx.strokeRect(cx, cy, cw, ch);
    ctx.setLineDash([]);
    ctx.shadowBlur = 0;

    if (isPending) return;

    // label
    if (state.showLabels) {
      const label    = `${cls.name} #${state.bboxes.indexOf(box)+1}`;
      const fontSize = Math.max(10, Math.min(14, 13 * state.zoom));
      ctx.font = `600 ${fontSize}px 'Outfit', sans-serif`;
      const tw = ctx.measureText(label).width;
      const lh = fontSize + 6;

      ctx.fillStyle = color;
      const lx = cx, ly = cy - lh;
      const dlx = Math.max(0, lx), dly = Math.max(0, ly);
      ctx.fillRect(dlx, dly, tw + 8, lh);

      ctx.fillStyle = '#000';
      ctx.fillText(label, dlx + 4, dly + lh - 4);
    }

    // resize handles — shown whenever selected, regardless of mode
    if (selected) {
      const HR = HANDLE_R + 1;   // slightly larger for easier grabbing
      const corners = [
        [cx,    cy],    // nw
        [cx+cw, cy],    // ne
        [cx,    cy+ch], // sw
        [cx+cw, cy+ch], // se
      ];
      const mids = [
        [cx+cw/2, cy],    // n
        [cx+cw/2, cy+ch], // s
        [cx,      cy+ch/2], // w
        [cx+cw,   cy+ch/2], // e
      ];

      // Corner handles — larger, filled white with class-colour ring
      ctx.shadowColor = 'rgba(0,0,0,0.5)';
      ctx.shadowBlur  = 4;
      for (const [hx, hy] of corners) {
        ctx.fillStyle   = '#fff';
        ctx.strokeStyle = color;
        ctx.lineWidth   = 2;
        ctx.beginPath();
        ctx.arc(hx, hy, HR, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
      }
      // Edge mid-point handles — smaller, tinted
      ctx.shadowBlur = 0;
      for (const [hx, hy] of mids) {
        ctx.fillStyle   = color;
        ctx.strokeStyle = '#fff';
        ctx.lineWidth   = 1.2;
        ctx.beginPath();
        ctx.arc(hx, hy, HR * 0.6, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
      }
      ctx.shadowBlur = 0;
    }
  },

  _drawPolygon(box, selected, isPending = false) {
    if (!box.points || box.points.length < 2) return;
    const ctx = this.ctx;
    const cls = state.classes.find(c => c.id === box.cls) || {color:[180,180,180], name:'?'};
    const [r,g,b] = cls.color;
    const color   = `rgb(${r},${g},${b})`;

    ctx.beginPath();
    const first = this._toCanvas(box.points[0].x, box.points[0].y);
    ctx.moveTo(first.x, first.y);
    for (let i = 1; i < box.points.length; i++) {
      const p = this._toCanvas(box.points[i].x, box.points[i].y);
      ctx.lineTo(p.x, p.y);
    }
    ctx.closePath();

    const alpha = isPending ? 0.08 : state.labelOpacity * 0.18;
    ctx.fillStyle = `rgba(${r},${g},${b},${alpha})`;
    ctx.fill();

    ctx.strokeStyle = isPending ? `rgba(${r},${g},${b},0.5)` : color;
    ctx.lineWidth   = selected ? state.boxLineWidth * 1.4 : state.boxLineWidth;
    if (isPending) ctx.setLineDash([6,4]);
    ctx.stroke();
    ctx.setLineDash([]);

    // vertex handles
    if (selected || isPending) {
      box.points.forEach(p => {
        const c = this._toCanvas(p.x, p.y);
        ctx.fillStyle = selected ? '#fff' : `rgba(${r},${g},${b},0.8)`;
        ctx.strokeStyle = color;
        ctx.lineWidth = 1.2;
        ctx.beginPath();
        ctx.arc(c.x, c.y, HANDLE_R * 0.8, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
      });
    }

    // Label
    if (state.showLabels && !isPending) {
      const label = `${cls.name} #${state.bboxes.indexOf(box)+1}`;
      const fontSize = Math.max(10, Math.min(14, 13 * state.zoom));
      ctx.font = `600 ${fontSize}px 'Outfit', sans-serif`;
      const tw = ctx.measureText(label).width;
      const lh = fontSize + 6;
      const cx2 = first.x, cy2 = first.y - lh;
      const dlx = Math.max(0, cx2), dly = Math.max(0, cy2);
      ctx.fillStyle = color;
      ctx.fillRect(dlx, dly, tw + 8, lh);
      ctx.fillStyle = '#000';
      ctx.fillText(label, dlx + 4, dly + lh - 4);
    }
  },

  _drawPolygonInProgress() {
    const ctx = this.ctx;
    const pts  = state.polygonPoints;
    const prev = state.polygonPreview;
    const cls  = state.classes.find(c => c.id === state.selectedCls);
    const [r,g,b] = cls?.color || [99,102,241];
    const color = `rgb(${r},${g},${b})`;

    if (pts.length === 0) return;

    // Draw path so far
    ctx.beginPath();
    const f = this._toCanvas(pts[0].x, pts[0].y);
    ctx.moveTo(f.x, f.y);
    for (let i = 1; i < pts.length; i++) {
      const p = this._toCanvas(pts[i].x, pts[i].y);
      ctx.lineTo(p.x, p.y);
    }
    // Preview line to current mouse
    if (prev) {
      const m = this._toCanvas(prev.x, prev.y);
      ctx.lineTo(m.x, m.y);
      // closing line preview
      ctx.setLineDash([4,4]);
      ctx.lineTo(f.x, f.y);
    }
    ctx.strokeStyle = color;
    ctx.lineWidth   = 1.5;
    ctx.stroke();
    ctx.setLineDash([]);

    // Vertex dots
    pts.forEach((p, i) => {
      const c = this._toCanvas(p.x, p.y);
      ctx.fillStyle = i === 0 ? '#fff' : color;
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(c.x, c.y, i === 0 ? HANDLE_R : HANDLE_R * 0.7, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
    });

    // Hint: count + instruction
    if (pts.length >= 3) {
      ctx.fillStyle = `rgba(${r},${g},${b},0.9)`;
      ctx.font = `500 11px 'Outfit', sans-serif`;
      const hint = `${pts.length} pts · DblClick or Enter to finish`;
      const tw = ctx.measureText(hint).width + 12;
      const hx = f.x, hy = f.y - 24;
      ctx.fillRect(Math.max(0, hx - 4), Math.max(0, hy - 14), tw, 18);
      ctx.fillStyle = '#000';
      ctx.fillText(hint, Math.max(4, hx), Math.max(6, hy));
    }
  },

  /* ── CANVAS EVENTS ── */
  _bindCanvas() {
    const c = this.canvas;

    c.addEventListener('mousedown',  e => this._onMouseDown(e));
    c.addEventListener('mousemove',  e => this._onMouseMove(e));
    c.addEventListener('mouseup',    e => this._onMouseUp(e));
    c.addEventListener('dblclick',   e => this._onDblClick(e));
    c.addEventListener('wheel',      e => this._onWheel(e), {passive:false});
    c.addEventListener('contextmenu',e => { e.preventDefault(); this.setMode('bbox'); });

    // touch pan (mobile)
    let lastTouch = null;
    c.addEventListener('touchstart', e => { lastTouch = e.touches[0]; e.preventDefault(); }, {passive:false});
    c.addEventListener('touchmove',  e => {
      if (!lastTouch) return;
      const t = e.touches[0];
      state.panX += t.clientX - lastTouch.clientX;
      state.panY += t.clientY - lastTouch.clientY;
      lastTouch = t;
      this._render();
      e.preventDefault();
    }, {passive:false});
    c.addEventListener('touchend', () => { lastTouch = null; });

    // window resize
    new ResizeObserver(() => {
      if (state.imgEl) { this._resetCanvas(); this._render(); }
    }).observe(document.getElementById('canvasArea'));
  },

  _canvasPos(e) {
    const r = this.canvas.getBoundingClientRect();
    return { cx: e.clientX - r.left, cy: e.clientY - r.top };
  },

  _onMouseDown(e) {
    const {cx, cy} = this._canvasPos(e);
    const img = this._toImg(cx, cy);

    if (e.button === 1 || (e.button === 0 && state.mode === 'pan') || (e.button === 0 && e.altKey)) {
      state.panning  = true;
      state.panStart = {cx, cy, ox: state.panX, oy: state.panY};
      this.canvas.style.cursor = 'grabbing';
      return;
    }

    if (e.button === 2) {
      // Right-click: cancel polygon drawing if active, otherwise switch to bbox
      if (state.mode === 'polygon' && state.polygonPoints.length > 0) {
        state.polygonPoints = [];
        state.polygonPreview = null;
        this._render();
      } else {
        this.setMode('bbox');
      }
      return;
    }

    if (e.button !== 0) return;

    state._prevSelectedId = state.selectedId;

    if (state.mode === 'polygon') {
      // Add polygon point on single click
      // If click near first point and have ≥3 points → finish
      if (state.polygonPoints.length >= 3) {
        const first = state.polygonPoints[0];
        const fc = this._toCanvas(first.x, first.y);
        if (Math.hypot(cx - fc.x, cy - fc.y) < HANDLE_R * 2) {
          this._finishPolygon(e);
          return;
        }
      }
      state.polygonPoints.push({x: img.x, y: img.y});
      this._render();
      return;
    }

    if (state.mode === 'bbox') {
      // ── Priority 1: resize handle on selected box (if a box is currently selected) ──────
      if (state.selectedId) {
        const hRes = this._hitHandle(cx, cy);
        if (hRes && hRes.box.id === state.selectedId) {
          this._pushHistory();
          state.resizing     = true;
          state.resizeBox    = hRes.box;
          state.resizeHandle = hRes.handle;
          return;
        }
      }

      // ── Priority 2: drag the currently selected box if clicking inside it ────────────
      if (state.selectedId) {
        const selBox = state.bboxes.find(b => b.id === state.selectedId);
        if (selBox) {
          const hit = this._hitBox(img);
          if (hit && hit.id === state.selectedId) {
            this._pushHistory();
            state.dragging  = true;
            state.dragBox   = selBox;
            state.dragOffX  = img.x - selBox.x;
            state.dragOffY  = img.y - selBox.y;
            state._wasDragged = false;
            return;
          }
        }
      }

      // ── Priority 3: start drawing new box (drag-to-draw, click-to-deselect on mouseup) ──────
      this._pushHistory();
      state.drawing    = true;
      state.drawStart  = img;
      state.pendingBox = {
        id:'pending', cls: state.selectedCls, type: 'bbox',
        x: img.x, y: img.y, w: 0, h: 0
      };
    }

    if (state.mode === 'edit') {
      // check resize handle first
      const hRes = this._hitHandle(cx, cy);
      if (hRes) {
        this._pushHistory();
        state.resizing     = true;
        state.resizeBox    = hRes.box;
        state.resizeHandle = hRes.handle;
        return;
      }
      // check box hit
      const hit = this._hitBox(img);
      if (hit) {
        state.selectedId = hit.id;
        this._pushHistory();
        state.dragging  = true;
        state.dragBox   = hit;
        state.dragOffX  = img.x - hit.x;
        state.dragOffY  = img.y - hit.y;
        state._wasDragged = false;   // will be set true if mouse moves during drag
      } else {
        state.selectedId = null;
      }
      this._render();
      this._updateProps();
      this._updateAnnoList();
    }
  },

  _onMouseMove(e) {
    const {cx, cy} = this._canvasPos(e);
    const img = this._toImg(cx, cy);

    // Always track raw canvas position for crosshair drawing
    state._mouseCanvas = {cx, cy};

    // status bar cursor
    document.getElementById('sbCursor').innerHTML =
      `<i class="fas fa-crosshairs"></i> ${Math.round(img.x)}, ${Math.round(img.y)}`;

    if (state.panning) {
      state.panX = state.panStart.ox + (cx - state.panStart.cx);
      state.panY = state.panStart.oy + (cy - state.panStart.cy);
      this._render();
      return;
    }

    // Polygon preview line
    if (state.mode === 'polygon' && state.polygonPoints.length > 0) {
      state.polygonPreview = {x: img.x, y: img.y};
      this._render();
      return;
    }

    if (state.drawing && state.drawStart) {
      const sx = state.drawStart.x, sy = state.drawStart.y;
      const w  = Math.abs(img.x - sx);
      const h  = Math.abs(img.y - sy);
      state.pendingBox = {
        id:'pending', cls: state.selectedCls, type: 'bbox',
        x: Math.min(sx, img.x), y: Math.min(sy, img.y), w, h,
      };
      this._render();

      // Update live dimension badge
      const badge = document.getElementById('drawDimBadge');
      if (badge && w > 4 && h > 4) {
        badge.textContent = `${Math.round(w)} × ${Math.round(h)}`;
        badge.classList.add('visible');
        // Position badge above the current mouse, in page-relative space inside canvasWrap
        const wrapRect = document.getElementById('canvasWrap').getBoundingClientRect();
        badge.style.left = (e.clientX - wrapRect.left) + 'px';
        badge.style.top  = (e.clientY - wrapRect.top)  + 'px';
      } else if (badge) {
        badge.classList.remove('visible');
      }
      return;
    }

    // Hide badge when not drawing
    document.getElementById('drawDimBadge')?.classList.remove('visible');

    if (state.dragging && state.dragBox) {
      state.dragBox.x = Math.max(0, Math.min(img.x - state.dragOffX, state.imgW - state.dragBox.w));
      state.dragBox.y = Math.max(0, Math.min(img.y - state.dragOffY, state.imgH - state.dragBox.h));
      state._wasDragged = true;   // mouse has actually moved — this is a real drag
      this._render();
      this._updateProps();
      return;
    }

    if (state.resizing && state.resizeBox) {
      this._applyResize(state.resizeBox, state.resizeHandle, img);
      this._render();
      this._updateProps();
      return;
    }

    // cursor
    this._updateCursor(cx, cy, img, e.shiftKey);
  },

  _onMouseUp(e) {
    if (state.panning) {
      state.panning = false;
      this.canvas.style.cursor = state.mode === 'bbox' ? 'crosshair' : 'default';
      if (state.zoomLocked) { state.lockedPanX = state.panX; state.lockedPanY = state.panY; }
      return;
    }

    if (state.drawing && state.pendingBox) {
      state.drawing = false;
      document.getElementById('drawDimBadge')?.classList.remove('visible');
      const pb = state.pendingBox;
      if (pb.w > 5 && pb.h > 5) {
        // clamp to image
        pb.x = Math.max(0, pb.x); pb.y = Math.max(0, pb.y);
        pb.w = Math.min(pb.w, state.imgW - pb.x);
        pb.h = Math.min(pb.h, state.imgH - pb.y);
        if (state.repeatMode && state.lastUsedCls !== null) {
          // Skip popup — use last used class
          pb.id  = Math.random().toString(36).slice(2);
          pb.cls = state.lastUsedCls;
          state.bboxes.push(pb);
          state.selectedId  = pb.id;
          state.pendingBox  = null;
          this._render();
          this._updateAnnoList();
          this._updateClassCounts();
          this._statusObjects();
          this._triggerSave();
        } else {
          this._showClassPopup(pb, e);
        }
      } else {
        state.pendingBox = null;
        if (state.mode === 'bbox') {
          state.selectedId = null;
          this._render();
          this._updateProps();
          this._updateAnnoList();
        } else {
          const {cx, cy} = this._canvasPos(e);
          const img = this._toImg(cx, cy);
          const hits = this._hitBoxes(img);
          if (hits.length > 0) {
            let targetBox;
            if (state._prevSelectedId === state.selectedId && hits.find(h => h.id === state.selectedId)) {
              const currentSelIdx = hits.findIndex(b => b.id === state.selectedId);
              targetBox = hits[(currentSelIdx + 1) % hits.length];
            } else {
              targetBox = hits[0];
            }
            state.selectedId = targetBox.id;
            this._render();
            this._updateProps();
            this._updateAnnoList();
            this._showClassPopupForEdit(targetBox, e);
          } else {
            state.selectedId = null;
            this._render();
            this._updateProps();
            this._updateAnnoList();
          }
        }
      }
      return;
    }

    if (state.dragging || state.resizing) {
      const wasDragged  = state._wasDragged;
      const wasResizing = state.resizing;
      state.dragging    = false;
      state.resizing    = false;
      state.dragBox     = null;
      state.resizeBox   = null;
      state._wasDragged = false;
      this._triggerSave();
      this._updateAnnoList();

      // Show popup if user actually moved/resized (not a pure click)
      // OR if this is a pure click-select (no movement) in edit mode
      if (state.selectedId) {
        const box = state.bboxes.find(b => b.id === state.selectedId);
        if (box && (wasDragged || wasResizing)) {
          // After move/resize → show popup to allow class change or delete
          this._showClassPopupForEdit(box, e);
        } else if (box && !wasDragged) {
          // Pure click-select (no drag)
          let targetBox = box;
          if (state._prevSelectedId === state.selectedId) {
            const {cx, cy} = this._canvasPos(e);
            const img = this._toImg(cx, cy);
            const hits = this._hitBoxes(img);
            if (hits.length > 1) {
              const currentSelIdx = hits.findIndex(b => b.id === state.selectedId);
              if (currentSelIdx !== -1) {
                targetBox = hits[(currentSelIdx + 1) % hits.length];
                state.selectedId = targetBox.id;
                this._render();
                this._updateProps();
                this._updateAnnoList();
              }
            }
          }
          this._showClassPopupForEdit(targetBox, e);
        }
      }
      return;
    }
  },

  _onDblClick(e) {
    const {cx, cy} = this._canvasPos(e);
    const img = this._toImg(cx, cy);

    // Double-click finishes polygon drawing (if 3+ points)
    if (state.mode === 'polygon' && state.polygonPoints.length >= 3) {
      // Remove the extra point added by mousedown just before dblclick
      if (state.polygonPoints.length > 3) state.polygonPoints.pop();
      this._finishPolygon(e);
      return;
    }

    // double-click on box → change class
    const hit = this._hitBox(img);
    if (hit) {
      state.selectedId = hit.id;
      this._render();
      this._showClassPopupForEdit(hit, e);
      return;
    }
    // double-click on empty → reset zoom
    this._fitImage();
  },

  _finishPolygon(mouseEvent) {
    const pts = state.polygonPoints.slice();
    state.polygonPoints  = [];
    state.polygonPreview = null;
    if (pts.length < 3) { this._render(); return; }

    const xs = pts.map(p => p.x), ys = pts.map(p => p.y);
    const bx = Math.min(...xs), by = Math.min(...ys);
    const bw = Math.max(...xs) - bx, bh = Math.max(...ys) - by;

    const pendingPoly = {
      id: 'pending', cls: state.selectedCls, type: 'polygon',
      points: pts, x: bx, y: by, w: bw, h: bh
    };

    if (state.repeatMode && state.lastUsedCls !== null) {
      pendingPoly.id  = Math.random().toString(36).slice(2);
      pendingPoly.cls = state.lastUsedCls;
      this._pushHistory();
      state.bboxes.push(pendingPoly);
      state.selectedId = pendingPoly.id;
      this._render();
      this._updateAnnoList();
      this._updateClassCounts();
      this._statusObjects();
      this._triggerSave();
    } else {
      state.pendingBox = pendingPoly;
      this._showClassPopup(pendingPoly, mouseEvent);
    }
  },

  _onWheel(e) {
    e.preventDefault();
    const {cx, cy} = this._canvasPos(e);
    const factor = e.deltaY < 0 ? (1 + ZOOM_STEP) : (1 - ZOOM_STEP);
    const newZoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, state.zoom * factor));
    // zoom centered on cursor
    state.panX = cx - (cx - state.panX) * (newZoom / state.zoom);
    state.panY = cy - (cy - state.panY) * (newZoom / state.zoom);
    state.zoom = newZoom;
    if (state.zoomLocked) {
      state.lockedZoom = state.zoom;
      state.lockedPanX = state.panX;
      state.lockedPanY = state.panY;
    }
    this._updateZoomDisplay();
    this._render();
  },

  /* ── HIT TESTING ── */
  _hitBox(img) {
    // reverse order so topmost drawn box is picked first
    for (let i = state.bboxes.length - 1; i >= 0; i--) {
      const b = state.bboxes[i];
      if (img.x >= b.x && img.x <= b.x + b.w && img.y >= b.y && img.y <= b.y + b.h) return b;
    }
    return null;
  },

  _hitBoxes(img) {
    const hits = [];
    for (let i = state.bboxes.length - 1; i >= 0; i--) {
      const b = state.bboxes[i];
      if (img.x >= b.x && img.x <= b.x + b.w && img.y >= b.y && img.y <= b.y + b.h) {
        hits.push(b);
      }
    }
    return hits;
  },

  _hitHandle(cx, cy) {
    for (const box of state.bboxes) {
      if (box.id !== state.selectedId) continue;
      const {x:bx,y:by} = this._toCanvas(box.x, box.y);
      const bw = box.w * state.zoom, bh = box.h * state.zoom;
      const handles = {
        'nw':[bx,by], 'ne':[bx+bw,by], 'sw':[bx,by+bh], 'se':[bx+bw,by+bh],
        'n':[bx+bw/2,by], 's':[bx+bw/2,by+bh],
        'w':[bx,by+bh/2], 'e':[bx+bw,by+bh/2]
      };
      for (const [handle, [hx,hy]] of Object.entries(handles)) {
        if (Math.hypot(cx-hx, cy-hy) <= HANDLE_R + 5) return {box, handle};
      }
    }
    return null;
  },

  _applyResize(box, handle, img) {
    const ox = box.x, oy = box.y, ow = box.w, oh = box.h;
    const r = ox + ow, b = oy + oh;
    const nx = Math.max(0, Math.min(img.x, state.imgW));
    const ny = Math.max(0, Math.min(img.y, state.imgH));

    if (handle.includes('w')) { box.x = Math.min(nx, r-2); box.w = r - box.x; }
    if (handle.includes('e')) { box.w = Math.max(2, nx - ox); }
    if (handle.includes('n')) { box.y = Math.min(ny, b-2); box.h = b - box.y; }
    if (handle.includes('s')) { box.h = Math.max(2, ny - oy); }
  },

  _updateCursor(cx, cy, img, shiftKey) {
    if (state.mode === 'pan') { this.canvas.style.cursor = 'grab'; return; }

    if (state.mode === 'bbox' && shiftKey) {
      this.canvas.style.cursor = 'crosshair';
      return;
    }

    // In both bbox and edit modes: handles + selected-box take priority over crosshair/default
    const hRes = this._hitHandle(cx, cy);
    if (hRes) {
      const map = {nw:'nw-resize',ne:'ne-resize',sw:'sw-resize',se:'se-resize',
                   n:'n-resize',s:'s-resize',w:'w-resize',e:'e-resize'};
      this.canvas.style.cursor = map[hRes.handle] || 'nwse-resize';
      return;
    }

    // Selected box interior → move cursor
    if (state.selectedId) {
      const hit = this._hitBox(img);
      if (hit && hit.id === state.selectedId) {
        this.canvas.style.cursor = 'move';
        return;
      }
    }

    // Any unselected box in edit mode → move cursor
    if (state.mode === 'edit') {
      const hit = this._hitBox(img);
      this.canvas.style.cursor = hit ? 'move' : 'default';
      return;
    }

    // Default for bbox mode: crosshair (drawing cursor)
    this.canvas.style.cursor = 'crosshair';
  },

  /* ── CLASS POPUP ── */
  _showClassPopup(box, mouseEvent) {
    state.pendingBox   = box;
    this._cpKbdIdx     = -1;   // reset arrow-key cursor

    // Populate first so we know real rendered height
    this._populatePopupList('');

    const popup  = document.getElementById('clsPopup');
    popup.style.display = 'flex';   // must be visible to measure

    const area   = document.getElementById('canvasArea').getBoundingClientRect();
    const me     = mouseEvent || {};
    const popW   = popup.offsetWidth  || 264;
    const popH   = popup.offsetHeight || 320;

    let px = (me.clientX != null ? me.clientX : area.left + area.width  / 2) - area.left;
    let py = (me.clientY != null ? me.clientY : area.top  + area.height / 2) - area.top;

    // Prefer appearing to the RIGHT of cursor, flip left if it would overflow
    const OFFSET = 12;
    if (px + OFFSET + popW > area.width)  px = px - popW - OFFSET;
    else                                   px = px + OFFSET;

    // Prefer BELOW cursor, flip above if overflow
    if (py + OFFSET + popH > area.height) py = py - popH - OFFSET;
    else                                   py = py + OFFSET;

    // Hard clamp to canvas bounds
    px = Math.max(4, Math.min(px, area.width  - popW - 4));
    py = Math.max(4, Math.min(py, area.height - popH - 4));

    popup.style.left = px + 'px';
    popup.style.top  = py + 'px';

    // Pre-select last-used class or first in list
    const firstSel = popup.querySelector('.cp-item.sel') || popup.querySelector('.cp-item');
    if (firstSel) {
      this._cpKbdIdx = Array.from(popup.querySelectorAll('.cp-item')).indexOf(firstSel);
      this._cpScrollToKbd();
    }

    const search = document.getElementById('cpSearch');
    search.value = '';
    search.focus();
  },

  _showClassPopupForEdit(box, mouseEvent) {
    state.selectedCls = box.cls;           // pre-select the box's current class
    state.pendingBox  = {...box};
    state.pendingBox._editId = box.id;
    this._showClassPopup(state.pendingBox, mouseEvent);
  },

  _populatePopupList(query) {
    const list = document.getElementById('cpList');
    list.innerHTML = '';
    const q        = query.toLowerCase().trim();
    const filtered = state.classes.filter(c => !q || c.name.toLowerCase().includes(q));

    if (!filtered.length) {
      list.innerHTML = '<div style="padding:14px;color:var(--tx3);text-align:center;font-size:12px"><i class="fas fa-search" style="display:block;margin-bottom:6px;font-size:18px;opacity:.3"></i>No matches</div>';
      this._cpKbdIdx = -1;
      return;
    }

    filtered.forEach((cls, i) => {
      const [r,g,b] = cls.color;
      const isSel   = cls.id === state.selectedCls;
      const el      = document.createElement('div');
      el.className  = 'cp-item' + (isSel ? ' sel' : '');
      el.dataset.clsId = cls.id;
      el.innerHTML  = `
        <span class="cpd" style="background:rgb(${r},${g},${b})"></span>
        <span class="cpn">${this._escHtml(cls.name)}</span>
        ${i < 9 ? `<span class="cpk">${i+1}</span>` : ''}`;

      // Click → select (highlight) this class. Confirm button or Enter applies it.
      el.addEventListener('mousedown', ev => {
        ev.preventDefault();  // prevent search input blur
        document.querySelectorAll('.cp-item').forEach(x => x.classList.remove('sel', 'kbd-focus'));
        el.classList.add('sel');
        state.selectedCls = cls.id;
        this._cpKbdIdx = i;
        // Double-click OR click on already-selected item → confirm immediately
        if (ev.detail === 2 || el.dataset.wasSelected === '1') {
          this._confirmPopup();
        }
        el.dataset.wasSelected = '1';
        setTimeout(() => { el.dataset.wasSelected = '0'; }, 400);
      });

      list.append(el);
    });

    // Keep keyboard cursor in range after re-populate
    const items = list.querySelectorAll('.cp-item');
    if (this._cpKbdIdx >= items.length) this._cpKbdIdx = items.length - 1;
    if (this._cpKbdIdx >= 0) this._cpHighlightKbd();
  },

  // Move keyboard highlight up/down
  _cpMove(dir) {
    const items = Array.from(document.querySelectorAll('#cpList .cp-item'));
    if (!items.length) return;
    this._cpKbdIdx = Math.max(0, Math.min(this._cpKbdIdx + dir, items.length - 1));
    this._cpHighlightKbd();
    this._cpScrollToKbd();
    // Update selectedCls to follow keyboard
    const focused = items[this._cpKbdIdx];
    if (focused) state.selectedCls = parseInt(focused.dataset.clsId, 10);
  },

  _cpHighlightKbd() {
    const items = Array.from(document.querySelectorAll('#cpList .cp-item'));
    items.forEach((el, i) => {
      el.classList.toggle('kbd-focus', i === this._cpKbdIdx);
    });
  },

  _cpScrollToKbd() {
    const items = Array.from(document.querySelectorAll('#cpList .cp-item'));
    const el = items[this._cpKbdIdx];
    if (el) el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  },

  _confirmPopup() {
    const pb = state.pendingBox;
    if (!pb) return;

    // If nothing explicitly selected, take kbd-focused or first item
    if (state.selectedCls === null || state.selectedCls === undefined) {
      const first = document.querySelector('#cpList .cp-item');
      if (first) state.selectedCls = parseInt(first.dataset.clsId, 10);
    }

    this.closePopup();
    state.lastUsedCls = state.selectedCls;

    if (pb._editId) {
      const box = state.bboxes.find(b => b.id === pb._editId);
      if (box) box.cls = state.selectedCls;
    } else {
      pb.id  = Math.random().toString(36).slice(2);
      pb.cls = state.selectedCls;
      if (!pb.type) pb.type = 'bbox';
      state.bboxes.push(pb);
      state.selectedId = pb.id;
    }

    state.pendingBox = null;
    this._render();
    this._updateAnnoList();
    this._updateClassCounts();
    this._statusObjects();
    const curItem = state.media[state.currentIdx];
    if (curItem) this._updateImageStatusBadge(curItem);
    this._triggerSave();
    // Box stays selected → handles remain visible → user can resize immediately
    // (stays in bbox mode; next click on empty space will start a new box)
  },

  closePopup() {
    const popup = document.getElementById('clsPopup');
    if (popup) popup.style.display = 'none';
    state.pendingBox = null;
    state.drawing    = false;
    this._render();
  },

  // Delete the annotation referenced by the popup (new OR existing), then close
  _deleteFromPopup() {
    const pb = state.pendingBox;
    if (pb) {
      if (pb._editId) {
        // existing box — remove it
        this._pushHistory();
        state.bboxes    = state.bboxes.filter(b => b.id !== pb._editId);
        state.selectedId = null;
      }
      // new box (no _editId) — just discard, don't push to state.bboxes
    }
    const popup = document.getElementById('clsPopup');
    if (popup) popup.style.display = 'none';
    state.pendingBox = null;
    state.drawing    = false;
    this._render();
    this._updateAnnoList();
    this._updateClassCounts();
    this._statusObjects();
    const curItem = state.media[state.currentIdx];
    if (curItem) this._updateImageStatusBadge(curItem);
    this._triggerSave();
  },

  /* ── SAVE ── */
  _triggerSave() {
    if (!state.autoSave) return;
    clearTimeout(state.saveTimer);
    // Capture the index NOW — if the user navigates before the timer fires,
    // the saved index won't match state.currentIdx and the save will be skipped.
    const savedIdx = state.currentIdx;
    this._setSaveStatus('saving');
    state.saveTimer = setTimeout(() => {
      // Only fire if we're still on the same image
      if (state.currentIdx === savedIdx) {
        this._saveCurrentAnnotations();
      }
    }, 600);
  },

  async _saveCurrentAnnotations() {
    if (state.currentIdx < 0) return;
    const item = state.media[state.currentIdx];
    if (!item) return;

    // Capture dimensions at the moment of the call.
    // If imgW/imgH are 0, the image hasn't loaded yet — do NOT save empty boxes
    // over a file that may already contain real annotations.
    const W = state.imgW || 0;
    const H = state.imgH || 0;
    if (W <= 0 || H <= 0) {
      // Image not loaded — skip entirely. Annotations are still on disk from
      // the last successful save; do not overwrite with empty.
      return;
    }

    // Capture the boxes and path right now — state may change during the await
    const capturedPath    = item.path;
    const capturedProject = state.project;
    const capturedIdx     = state.currentIdx;

    const bboxesNorm = state.bboxes
      .filter(b => {
        if (b.type !== 'polygon') {
          if (!b.w || !b.h || b.w <= 0 || b.h <= 0) return false;
        }
        return true;
      })
      .map(b => {
        if (b.type === 'polygon') {
          return {
            class_id: b.cls,
            type: 'polygon',
            points: (b.points || []).map(p => ({
              x: W > 0 ? p.x / W : 0,
              y: H > 0 ? p.y / H : 0,
            }))
          };
        }
        return {
          class_id: b.cls,
          type: 'bbox',
          x_center: (b.x + b.w / 2) / W,
          y_center: (b.y + b.h / 2) / H,
          width:    b.w / W,
          height:   b.h / H,
        };
      })
      .filter(b => {
        if (b.type === 'polygon') return true;
        return isFinite(b.x_center) && isFinite(b.y_center) &&
               isFinite(b.width)    && isFinite(b.height) &&
               b.width > 0          && b.height > 0;
      });

    // ── Skip POST if nothing to save and image was never annotated ──────────
    // This prevents creating empty .txt files for unannotated images.
    const wasAnnotated = state.annotatedPaths.has(capturedPath);
    if (bboxesNorm.length === 0 && !wasAnnotated) {
      // Nothing to write — update UI state silently and return
      this._setSaveStatus('saved');
      return;
    }

    try {
      const resp = await fetch('/api/annotations', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({
          path:    capturedPath,
          project: capturedProject,
          bboxes:  bboxesNorm,
        })
      });
      const rd = await resp.json();

      // Only update state if we're still on the same image
      if (state.currentIdx !== capturedIdx) return;

      if (rd.new_path) {
        item.path   = rd.new_path;
        item.folder = bboxesNorm.length ? 'Annotated' : 'unAnnotated';
      }
      if (bboxesNorm.length) state.annotatedPaths.add(item.path);
      else                   state.annotatedPaths.delete(item.path);
      this._applyFilter();
      this._updateTotals();
      this._updateNavBadges();
      this._updateJobStatusBar();   // keep job-lock bar counts live
      this._updateAddToDatasetBtn();
      const curItem = state.media[state.currentIdx];
      if (curItem) this._updateImageStatusBadge(curItem);
      this._setSaveStatus('saved');
    } catch(e) { this._setSaveStatus('error'); }
  },

  _setSaveStatus(s) {
    // Status bar
    const el = document.getElementById('sbSave');
    // Header save indicator
    const hdr = document.getElementById('hdrSaveStatus');
    if (s === 'saving') {
      if (el) { el.className = 'sb-save saving'; el.innerHTML = '<i class="fas fa-sync-alt fa-spin"></i> Saving…'; }
      if (hdr) { hdr.className = 'hdr-save saving'; hdr.innerHTML = '<i class="fas fa-sync-alt fa-spin"></i> Saving…'; }
    } else if (s === 'saved') {
      if (el) { el.className = 'sb-save'; el.innerHTML = '<i class="fas fa-check-circle"></i> Saved'; }
      if (hdr) { hdr.className = 'hdr-save saved'; hdr.innerHTML = '<i class="fas fa-check-circle"></i> Saved'; }
    } else {
      if (el) { el.className = 'sb-save'; el.innerHTML = '<i class="fas fa-exclamation-circle" style="color:var(--danger)"></i> Error'; }
      if (hdr) { hdr.className = 'hdr-save error'; hdr.innerHTML = '<i class="fas fa-exclamation-circle"></i> Error'; }
    }
  },

  /* ── UNDO / REDO ── */
  _pushHistory() {
    state.undoStack.push(JSON.stringify(state.bboxes));
    if (state.undoStack.length > MAX_UNDO) state.undoStack.shift();
    state.redoStack = [];
    this._updateUndoRedo();
  },

  undo() {
    if (!state.undoStack.length) return;
    state.redoStack.push(JSON.stringify(state.bboxes));
    state.bboxes     = JSON.parse(state.undoStack.pop());
    state.selectedId = null;
    this._render(); this._updateAnnoList(); this._updateClassCounts();
    this._updateUndoRedo(); this._statusObjects(); this._triggerSave();
  },

  redo() {
    if (!state.redoStack.length) return;
    state.undoStack.push(JSON.stringify(state.bboxes));
    state.bboxes     = JSON.parse(state.redoStack.pop());
    state.selectedId = null;
    this._render(); this._updateAnnoList(); this._updateClassCounts();
    this._updateUndoRedo(); this._statusObjects(); this._triggerSave();
  },

  _updateUndoRedo() {
    document.getElementById('undoBtn').disabled = !state.undoStack.length;
    document.getElementById('redoBtn').disabled = !state.redoStack.length;
  },

  /* ── DELETE SELECTED ── */
  deleteSelected() {
    if (!state.selectedId) return;
    this._pushHistory();
    state.bboxes = state.bboxes.filter(b => b.id !== state.selectedId);
    state.selectedId = null;
    this._render(); this._updateAnnoList(); this._updateClassCounts();
    this._statusObjects(); this._triggerSave();
  },

  /* ── COPY / PASTE ── */
  copySelected() {
    if (!state.selectedId) return;
    const box = state.bboxes.find(b => b.id === state.selectedId);
    if (!box) return;
    state.copiedBox = {...box};
    this._toast('Box copied', 'info');
  },

  pasteBox() {
    if (!state.copiedBox) return;
    this._pushHistory();
    const offset = 15;
    const newBox = {
      ...state.copiedBox,
      id: Math.random().toString(36).slice(2),
      x: Math.min(state.copiedBox.x + offset, state.imgW - state.copiedBox.w),
      y: Math.min(state.copiedBox.y + offset, state.imgH - state.copiedBox.h),
    };
    state.bboxes.push(newBox);
    state.selectedId = newBox.id;
    // shift clipboard so repeated paste cascades
    state.copiedBox = {...state.copiedBox, x: newBox.x, y: newBox.y};
    this._render(); this._updateAnnoList(); this._updateClassCounts();
    this._statusObjects(); this._triggerSave();
    this._toast('Box pasted', 'info');
  },

  /* ── CLASS VISIBILITY ── */
  toggleClassVisibility(id) {
    if (state.hiddenClasses.has(id)) {
      state.hiddenClasses.delete(id);
    } else {
      state.hiddenClasses.add(id);
    }
    // update eye icon
    const row = document.querySelector(`.cls-row[data-id="${id}"]`);
    if (row) {
      const eyeBtn = row.querySelector('.cc-eye');
      if (eyeBtn) {
        const hidden = state.hiddenClasses.has(id);
        eyeBtn.innerHTML = `<i class="fas fa-eye${hidden ? '-slash' : ''}"></i>`;
        row.classList.toggle('cls-hidden', hidden);
      }
    }
    this._render();
  },

  showAllClasses() {
    state.hiddenClasses.clear();
    document.querySelectorAll('.cls-row').forEach(row => {
      row.classList.remove('cls-hidden');
      const eyeBtn = row.querySelector('.cc-eye');
      if (eyeBtn) eyeBtn.innerHTML = '<i class="fas fa-eye"></i>';
    });
    this._render();
  },

  /* ── LABELS VISIBILITY ── */
  toggleShowLabels() {
    state.showLabels = !state.showLabels;
    const btn = document.getElementById('toggleLabelsBtn');
    if (btn) {
      btn.classList.toggle('active', state.showLabels);
      btn.title = state.showLabels ? 'Hide labels (T)' : 'Show labels (T)';
      btn.querySelector('i').className = state.showLabels ? 'fas fa-tag' : 'fas fa-tag';
    }
    this._render();
    this._toast(state.showLabels ? 'Labels visible' : 'Labels hidden', 'info');
  },

  /* ── GRID OVERLAY ── */
  toggleGrid() {
    state.showGrid = !state.showGrid;
    const btn = document.getElementById('toggleGridBtn');
    if (btn) btn.classList.toggle('active', state.showGrid);
    this._render();
    this._toast(state.showGrid ? 'Grid on' : 'Grid off', 'info');
  },

  /* ── IMAGE ADJUSTMENTS ── */
  applyImageAdjustments() {
    const b = parseInt(document.getElementById('brightnessSlider')?.value ?? 100);
    const c = parseInt(document.getElementById('contrastSlider')?.value ?? 100);
    state.brightness = b;
    state.contrast   = c;
    const bv = document.getElementById('brightnessVal');
    const cv = document.getElementById('contrastVal');
    if (bv) bv.textContent = b + '%';
    if (cv) cv.textContent = c + '%';
    this._render();
  },

  resetImageAdjustments() {
    state.brightness = 100;
    state.contrast   = 100;
    const bs = document.getElementById('brightnessSlider');
    const cs = document.getElementById('contrastSlider');
    if (bs) bs.value = 100;
    if (cs) cs.value = 100;
    const bv = document.getElementById('brightnessVal');
    const cv = document.getElementById('contrastVal');
    if (bv) bv.textContent = '100%';
    if (cv) cv.textContent = '100%';
    this._render();
  },

  /* ── SETTINGS ── */
  openSettings() {
    // sync current values into settings modal
    document.getElementById('settingLabelOpacity').value  = state.labelOpacity;
    document.getElementById('settingLabelOpacityVal').textContent = Math.round(state.labelOpacity * 100) + '%';
    document.getElementById('settingLineWidth').value     = state.boxLineWidth;
    document.getElementById('settingLineWidthVal').textContent = state.boxLineWidth + 'px';
    document.getElementById('settingGridSize').value      = state.gridSize;
    document.getElementById('settingGridSizeVal').textContent = state.gridSize + 'px';
    document.getElementById('brightnessSlider').value     = state.brightness;
    document.getElementById('brightnessVal').textContent  = state.brightness + '%';
    document.getElementById('contrastSlider').value       = state.contrast;
    document.getElementById('contrastVal').textContent    = state.contrast + '%';
    this.openModal('settingsModal');
  },

  applySettings() {
    state.labelOpacity  = parseFloat(document.getElementById('settingLabelOpacity').value);
    state.boxLineWidth  = parseFloat(document.getElementById('settingLineWidth').value);
    state.gridSize      = parseInt(document.getElementById('settingGridSize').value);
    state.brightness    = parseInt(document.getElementById('brightnessSlider').value);
    state.contrast      = parseInt(document.getElementById('contrastSlider').value);
    this.closeModal('settingsModal');
    this._render();
    this._toast('Settings applied', 'success');
  },

  /* ── STATISTICS ── */
  async openStats() {
    this.openModal('statsModal');
    const body = document.getElementById('statsBody');
    body.innerHTML = '<div style="text-align:center;padding:20px;"><div class="spinner"></div><p style="margin-top:10px;color:var(--tx2)">Computing stats…</p></div>';

    try {
      const r = await fetch(`/api/stats?project=${encodeURIComponent(state.project)}`);
      const d = await r.json();
      this._renderStats(d);
    } catch(e) {
      // fallback: compute from local state
      this._renderStatsLocal();
    }
  },

  _renderStats(d) {
    const body = document.getElementById('statsBody');
    const total     = d.total_images || 0;
    const annotated = d.annotated_images || 0;
    const pct       = total ? Math.round(annotated / total * 100) : 0;

    let clsRows = '';
    (d.class_counts || []).forEach(cc => {
      const [r,g,b] = cc.color || [180,180,180];
      clsRows += `<tr>
        <td><span class="stat-dot" style="background:rgb(${r},${g},${b})"></span>${cc.name}</td>
        <td class="mono">${cc.count}</td>
        <td class="mono">${cc.images}</td>
      </tr>`;
    });

    body.innerHTML = `
      <div class="stats-overview">
        <div class="stat-card">
          <div class="sc-val">${total}</div><div class="sc-lbl">Total Images</div>
        </div>
        <div class="stat-card accent">
          <div class="sc-val">${annotated}</div><div class="sc-lbl">Annotated</div>
        </div>
        <div class="stat-card">
          <div class="sc-val">${total - annotated}</div><div class="sc-lbl">Remaining</div>
        </div>
        <div class="stat-card">
          <div class="sc-val">${d.total_boxes || 0}</div><div class="sc-lbl">Total Boxes</div>
        </div>
      </div>

      <div class="stats-progress-wrap">
        <div class="spw-label">
          <span>Annotation Progress</span>
          <span class="mono">${pct}%</span>
        </div>
        <div class="stats-progress-bar">
          <div class="stats-progress-fill" style="width:${pct}%"></div>
        </div>
      </div>

      <div class="stats-split-row">
        ${['train','valid','test'].map(sp => `
          <div class="stat-split-card">
            <span class="split-badge ${sp}">${sp}</span>
            <div class="ss-num">${d.splits?.[sp] || 0}</div>
            <div class="ss-lbl">images</div>
          </div>`).join('')}
      </div>

      <div class="stats-classes">
        <table class="cls-stat-table">
          <thead><tr><th>Class</th><th>Boxes</th><th>Images</th></tr></thead>
          <tbody>${clsRows || '<tr><td colspan="3" style="text-align:center;color:var(--tx3);padding:12px;">No classes yet</td></tr>'}</tbody>
        </table>
      </div>`;
  },

  _renderStatsLocal() {
    // compute from state.media + state.bboxes (current image only)
    const total     = state.media.length;
    const annotated = state.annotatedPaths.size;
    const pct       = total ? Math.round(annotated / total * 100) : 0;
    const splits    = {train:0, valid:0, test:0};
    state.media.forEach(m => { if (splits[m.split] !== undefined) splits[m.split]++; });

    const classCounts = {};
    state.classes.forEach(c => { classCounts[c.id] = {count:0, images:0, cls:c}; });
    state.bboxes.forEach(b => {
      if (classCounts[b.cls]) classCounts[b.cls].count++;
    });

    const body = document.getElementById('statsBody');
    const clsRows = state.classes.map(c => {
      const cc = classCounts[c.id] || {count:0};
      const [r,g,b] = c.color;
      return `<tr>
        <td><span class="stat-dot" style="background:rgb(${r},${g},${b})"></span>${c.name}</td>
        <td class="mono">${cc.count}</td>
        <td class="mono">—</td>
      </tr>`;
    }).join('');

    body.innerHTML = `
      <div class="stats-overview">
        <div class="stat-card"><div class="sc-val">${total}</div><div class="sc-lbl">Total Images</div></div>
        <div class="stat-card accent"><div class="sc-val">${annotated}</div><div class="sc-lbl">Annotated</div></div>
        <div class="stat-card"><div class="sc-val">${total - annotated}</div><div class="sc-lbl">Remaining</div></div>
        <div class="stat-card"><div class="sc-val">${state.bboxes.length}</div><div class="sc-lbl">Curr. Boxes</div></div>
      </div>
      <div class="stats-progress-wrap">
        <div class="spw-label"><span>Annotation Progress</span><span class="mono">${pct}%</span></div>
        <div class="stats-progress-bar"><div class="stats-progress-fill" style="width:${pct}%"></div></div>
      </div>
      <div class="stats-split-row">
        ${['train','valid','test'].map(sp => `
          <div class="stat-split-card">
            <span class="split-badge ${sp}">${sp}</span>
            <div class="ss-num">${splits[sp]}</div>
            <div class="ss-lbl">images</div>
          </div>`).join('')}
      </div>
      <div class="stats-classes">
        <table class="cls-stat-table">
          <thead><tr><th>Class</th><th>Boxes (curr.)</th><th>Images</th></tr></thead>
          <tbody>${clsRows || '<tr><td colspan="3" style="text-align:center;color:var(--tx3);padding:12px;">No classes yet</td></tr>'}</tbody>
        </table>
      </div>`;
  },

  /* ── MODE ── */
  setMode(mode) {
    // Cancel any in-progress polygon
    if (state.mode === 'polygon' && state.polygonPoints.length > 0) {
      state.polygonPoints  = [];
      state.polygonPreview = null;
    }
    state.mode = mode;
    // Update toolbar button active states
    document.querySelectorAll('.dt-btn[data-mode], .ft-btn[data-mode]').forEach(b => {
      b.classList.toggle('active', b.dataset.mode === mode);
    });
    document.querySelectorAll('.tb-btn.mode').forEach(b => {
      b.classList.toggle('active', b.dataset.mode === mode);
    });
    const cursors = {bbox:'crosshair', edit:'default', pan:'grab', polygon:'crosshair'};
    this.canvas.style.cursor = cursors[mode] || 'default';

    // Update coloured mode chip in the status bar
    const chip = document.getElementById('sbMode');
    if (chip) {
      const cfg = {
        bbox:    { icon: 'fa-vector-square',  label: 'Draw',    cls: '' },
        edit:    { icon: 'fa-mouse-pointer',  label: 'Select',  cls: 'edit-mode' },
        pan:     { icon: 'fa-hand-paper',     label: 'Pan',     cls: 'pan-mode' },
        polygon: { icon: 'fa-draw-polygon',   label: 'Polygon', cls: 'poly-mode' },
      };
      const c = cfg[mode] || cfg.bbox;
      chip.className = 'sb-mode-chip' + (c.cls ? ' ' + c.cls : '');
      chip.innerHTML = `<i class="fas ${c.icon}"></i> ${c.label}`;
    }
    this._render();
  },

  toggleRepeatMode() {
    state.repeatMode = !state.repeatMode;
    const btn = document.getElementById('repeatModeBtn');
    if (btn) btn.classList.toggle('active', state.repeatMode);
    this._toast(state.repeatMode ? '🔁 Repeat mode ON — skips class popup' : 'Repeat mode OFF', 'info');
  },

  /* ── ZOOM ── */
  zoomIn()  { this._zoomBy(1 + ZOOM_STEP); },
  zoomOut() { this._zoomBy(1 - ZOOM_STEP); },
  _zoomBy(factor) {
    const cx = this.canvas.width/2, cy = this.canvas.height/2;
    const nz = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, state.zoom * factor));
    state.panX = cx - (cx - state.panX) * (nz / state.zoom);
    state.panY = cy - (cy - state.panY) * (nz / state.zoom);
    state.zoom = nz;
    this._updateZoomDisplay();
    this._render();
  },

  _updateZoomDisplay() {
    const pct = Math.round(state.zoom * 100) + '%';
    document.getElementById('zoomDisplay').textContent = pct;
    document.getElementById('sbZoom').innerHTML = `<i class="fas fa-search"></i> ${pct}`;
  },

  toggleZoomLock() {
    state.zoomLocked = !state.zoomLocked;
    const btn = document.getElementById('zoomLockBtn');
    const ico = document.getElementById('zoomLockIcon');
    btn.classList.toggle('toggle', state.zoomLocked);
    ico.className = state.zoomLocked ? 'fas fa-lock' : 'fas fa-lock-open';
    if (state.zoomLocked) {
      state.lockedZoom = state.zoom;
      state.lockedPanX = state.panX;
      state.lockedPanY = state.panY;
    }
    this._toast(state.zoomLocked ? 'Zoom locked' : 'Zoom unlocked', 'info');
  },

  /* ── CLASS MANAGEMENT ── */
  selectClass(id) {
    state.selectedCls = id;
    document.querySelectorAll('.cls-row').forEach(r => {
      r.classList.toggle('sel', parseInt(r.dataset.id) === id);
    });
    // update selected box class
    if (state.selectedId) {
      const box = state.bboxes.find(b => b.id === state.selectedId);
      if (box) { this._pushHistory(); box.cls = id; this._render(); this._triggerSave(); }
    }
  },

  async addClassFromInput() {
    const inp = document.getElementById('newClassName');
    const name = inp.value.trim();
    if (!name) return;

    const used = state.classes.map(c => c.id);
    const newId = used.length ? Math.max(...used) + 1 : 0;
    const color = CLASS_PALETTE[newId % CLASS_PALETTE.length];

    try {
      const r = await fetch('/api/classes', {
        method: 'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({project: state.project, name, color, id: newId})
      });
      const d = await r.json();
      if (d.success) {
        state.classes.push({id: newId, name, color});
        inp.value = '';
        this._populateClassList();
        this._toast(`Class "${name}" added`, 'success');
      }
    } catch(e) { this._toast('Failed to add class', 'error'); }
  },

  async deleteClass(id) {
    if (!confirm(`Delete class ${state.classes.find(c=>c.id===id)?.name}? Annotations with this class will be deleted.`)) return;
    try {
      await fetch('/api/classes', {
        method: 'DELETE',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({project: state.project, id})
      });
      state.classes = state.classes.filter(c => c.id !== id);
      state.bboxes  = state.bboxes.filter(b => b.cls !== id);
      this._populateClassList();
      this._render();
      this._updateAnnoList();
      this._triggerSave();
      this._toast('Class deleted', 'success');
    } catch(e) { this._toast('Failed to delete class', 'error'); }
  },

  _populateClassList() {
    const list  = document.getElementById('clsList');
    const empty = document.getElementById('clsEmpty');
    list.innerHTML = '';
    document.getElementById('clsCount').textContent = state.classes.length;

    if (!state.classes.length) {
      if (empty) { empty.style.display = ''; list.appendChild(empty); }
      return;
    }

    state.classes.forEach((cls, i) => {
      const [r,g,b] = cls.color;
      const sel    = cls.id === state.selectedCls;
      const hidden = state.hiddenClasses.has(cls.id);
      const div = document.createElement('div');
      div.className = 'cls-row' + (sel ? ' sel' : '') + (hidden ? ' cls-hidden' : '');
      div.dataset.id = cls.id;
      div.style.setProperty('--cc', `rgb(${r},${g},${b})`);
      div.innerHTML = `
        <span class="cc-dot"></span>
        <span class="cc-name">${cls.name}</span>
        ${i<9?`<span class="cc-key">${i+1}</span>`:''}
        <span class="cc-cnt" id="cnt${cls.id}">0</span>
        <button class="cc-eye" title="Toggle visibility"><i class="fas fa-eye${hidden?'-slash':''}"></i></button>
        <button class="cc-del" title="Delete class"><i class="fas fa-times"></i></button>`;
      div.addEventListener('click', () => this.selectClass(cls.id));
      div.querySelector('.cc-del').addEventListener('click', ev => {
        ev.stopPropagation(); this.deleteClass(cls.id);
      });
      div.querySelector('.cc-eye').addEventListener('click', ev => {
        ev.stopPropagation(); this.toggleClassVisibility(cls.id);
      });
      list.appendChild(div);
    });

    // populate propClass select
    const propSel = document.getElementById('propClass');
    propSel.innerHTML = state.classes.map(c => `<option value="${c.id}">${c.name}</option>`).join('');
    this._updateClassCounts();
  },

  _updateClassCounts() {
    const counts = {};
    state.classes.forEach(c => counts[c.id] = 0);
    state.bboxes.forEach(b => { if (counts[b.cls] !== undefined) counts[b.cls]++; });
    state.classes.forEach(c => {
      const el = document.getElementById(`cnt${c.id}`);
      if (el) el.textContent = counts[c.id] || 0;
    });
  },

  /* ── ANNOTATION LIST ── */
  _updateAnnoList() {
    const list  = document.getElementById('annoList');
    const badge = document.getElementById('annoBadge');
    badge.textContent = state.bboxes.length;
    list.innerHTML = '';

    if (!state.bboxes.length) {
      list.innerHTML = '<div class="props-placeholder"><p>No annotations</p></div>';
      return;
    }

    state.bboxes.forEach((box, i) => {
      const cls = state.classes.find(c => c.id === box.cls) || {color:[180,180,180],name:'?'};
      const [r,g,b] = cls.color;
      const sel = box.id === state.selectedId;
      const el = document.createElement('div');
      el.className = 'anno-item' + (sel ? ' sel' : '');
      el.innerHTML = `
        <span class="ai-dot" style="background:rgb(${r},${g},${b})"></span>
        <span class="ai-name">${cls.name}</span>
        <span class="ai-size mono">${Math.round(box.w)}×${Math.round(box.h)}</span>
        <div class="ai-actions">
          <button class="ai-act ai-back" title="Send to Back"><i class="fas fa-angle-double-down"></i></button>
          <button class="ai-act ai-front" title="Bring to Front"><i class="fas fa-angle-double-up"></i></button>
          <button class="ai-act ai-del" title="Delete"><i class="fas fa-times"></i></button>
        </div>`;
      el.addEventListener('click', () => {
        state.selectedId = box.id;
        this._render(); this._updateAnnoList(); this._updateProps();
      });
      el.querySelector('.ai-back').addEventListener('click', ev => {
        ev.stopPropagation();
        this._pushHistory();
        state.bboxes = [box].concat(state.bboxes.filter(b => b.id !== box.id));
        this._render(); this._updateAnnoList(); this._triggerSave();
      });
      el.querySelector('.ai-front').addEventListener('click', ev => {
        ev.stopPropagation();
        this._pushHistory();
        state.bboxes = state.bboxes.filter(b => b.id !== box.id).concat(box);
        this._render(); this._updateAnnoList(); this._triggerSave();
      });
      el.querySelector('.ai-del').addEventListener('click', ev => {
        ev.stopPropagation();
        this._pushHistory();
        state.bboxes = state.bboxes.filter(b => b.id !== box.id);
        if (state.selectedId === box.id) state.selectedId = null;
        this._render(); this._updateAnnoList(); this._updateClassCounts();
        this._statusObjects(); this._triggerSave();
      });
      list.appendChild(el);
    });
  },

  /* ── PROPERTIES PANEL ── */
  _updateProps() {
    const form  = document.getElementById('propsForm');
    const empty = document.getElementById('propsEmpty');
    const delBtn = document.getElementById('delSelBtn');

    const box = state.bboxes.find(b => b.id === state.selectedId);
    if (!box) {
      form.style.display = 'none'; empty.style.display = '';
      delBtn.style.display = 'none';
      return;
    }
    empty.style.display = 'none'; form.style.display = '';
    delBtn.style.display = '';

    document.getElementById('propClass').value = box.cls;
    document.getElementById('propX').value = Math.round(box.x);
    document.getElementById('propY').value = Math.round(box.y);
    document.getElementById('propW').value = Math.round(box.w);
    document.getElementById('propH').value = Math.round(box.h);
  },

  applyPropClass() {
    const box = state.bboxes.find(b => b.id === state.selectedId);
    if (!box) return;
    this._pushHistory();
    box.cls = parseInt(document.getElementById('propClass').value);
    this._render(); this._updateAnnoList(); this._updateClassCounts(); this._triggerSave();
  },

  applyProps() {
    const box = state.bboxes.find(b => b.id === state.selectedId);
    if (!box) return;
    this._pushHistory();
    box.x = Math.max(0, parseFloat(document.getElementById('propX').value)||0);
    box.y = Math.max(0, parseFloat(document.getElementById('propY').value)||0);
    box.w = Math.max(1, parseFloat(document.getElementById('propW').value)||1);
    box.h = Math.max(1, parseFloat(document.getElementById('propH').value)||1);
    this._render(); this._triggerSave();
  },

  /* ── STATUS BAR ── */
  _updateStatusBar() {
    const item = state.media[state.currentIdx];
    if (!item) return;
    document.getElementById('sbFile').innerHTML = `<i class="fas fa-file-image"></i> ${item.name}`;
    // Global index across all pages
    const globalIdx   = (state.listPage - 1) * state.listPerPage + state.currentIdx + 1;
    const globalTotal = state.listTotal || state.media.length;
    document.getElementById('sbIdx').innerHTML =
      `<i class="fas fa-list-ol"></i> ${globalIdx} / ${globalTotal}`;
  },

  _statusObjects() {
    const objs = document.getElementById('sbObjs');
    if (objs) objs.innerHTML = `<i class="fas fa-draw-polygon"></i> ${state.bboxes.length} objects`;
    // Prev: disabled at first image of first page
    const prev = document.getElementById('prevImgBtn');
    if (prev) prev.disabled = (state.currentIdx <= 0 && state.listPage <= 1);
    // Next: disabled at last image of last page
    const next = document.getElementById('nextImgBtn');
    if (next) next.disabled = (
      state.currentIdx >= state.media.length - 1 &&
      state.listPage >= state.listTotalPages
    );
    this._updateAddToDatasetBtn();
  },

  _updateAddToDatasetBtn() {
    const hasAnnotated = state.annotatedPaths.size > 0;
    const wrap = document.getElementById('atdFabWrap');
    if (wrap) wrap.style.display = hasAnnotated ? '' : 'none';
    // Close panel if it was open and annotations are gone
    if (!hasAnnotated && this._atdClosePanel) this._atdClosePanel();
    // Legacy compat
    const floatBtn = document.getElementById('addToDatasetBtn');
    if (floatBtn) floatBtn.style.display = 'none';
    const hdrBtn = document.getElementById('addToDatasetHdrBtn');
    if (hdrBtn) hdrBtn.style.display = (hasAnnotated && state.activeJobId != null) ? '' : 'none';
  },

  _updateImageInfo(item) {
    document.getElementById('iFile').textContent  = item.name;
    document.getElementById('iSize').textContent  = `${state.imgW} × ${state.imgH}`;
    document.getElementById('iSplit').textContent = item.split || '—';
    // Show global index across all pages
    const globalIdx   = (state.listPage - 1) * state.listPerPage + state.currentIdx + 1;
    const globalTotal = state.listTotal || state.media.length;
    document.getElementById('iIdx').textContent = `${globalIdx} / ${globalTotal}`;
    // Enable / reset the Set as Cover button whenever a new image loads
    const btn = document.getElementById('setCoverBtn');
    if (btn) {
      btn.disabled = false;
      btn.className = 'set-cover-btn';
      btn.innerHTML = '<i class="fas fa-image"></i><span>Set as Project Cover</span>';
    }
  },

  // ── Set current annotation image as the project cover ─────────────────────
  async _setCurrentImageAsCover() {
    const item = state.media[state.currentIdx];
    if (!item) { this._toast('No image loaded', 'warn'); return; }
    const btn = document.getElementById('setCoverBtn');
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i><span>Setting cover…</span>';
    }
    try {
      const r = await fetch(
        `/api/projects/${encodeURIComponent(state.project)}/cover-from-path`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: item.path })
        }
      );
      const d = await r.json();
      if (!r.ok || d.error) {
        this._toast(d.error || 'Failed to set cover', 'error');
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = '<i class="fas fa-image"></i><span>Set as Project Cover</span>';
        }
        return;
      }
      // Success feedback
      if (btn) {
        btn.className = 'set-cover-btn cover-success';
        btn.innerHTML = '<i class="fas fa-check-circle"></i><span>Cover Updated!</span>';
        setTimeout(() => {
          btn.className = 'set-cover-btn';
          btn.innerHTML = '<i class="fas fa-image"></i><span>Set as Project Cover</span>';
          btn.disabled = false;
        }, 2500);
      }
      this._toast(`Cover set to "${item.name}"`, 'success');
    } catch(e) {
      this._toast('Network error — cover not saved', 'error');
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-image"></i><span>Set as Project Cover</span>';
      }
    }
  },

  _refreshListHighlight() {
    document.querySelectorAll('.img-item').forEach(el => {
      const path = el.dataset.path;
      const cur  = state.media[state.currentIdx]?.path;
      el.classList.toggle('active', path === cur);
    });
  },

  /* ── IMPORT ── */
  openImport() {
    this.openModal('importModal');
    document.getElementById('importPreview').style.display   = 'none';
    document.getElementById('startImportBtn').disabled       = true;
    document.getElementById('chosenFile').textContent        = '';
    document.getElementById('splitWarnBox').style.display    = 'none';
    document.getElementById('importFileInput').value         = '';
    state._importPreviewData = null;
  },

  async previewImport(file) {
    if (!file) return;
    document.getElementById('chosenFile').textContent = file.name;
    document.getElementById('startImportBtn').disabled = false;

    try {
      const fd = new FormData();
      fd.append('file', file);
      const r = await fetch(`/api/import/preview?project=${encodeURIComponent(state.project)}`, {method:'POST', body:fd});
      const d = await r.json();
      state._importPreviewData = d;

      if (d.success) {
        const grid = document.getElementById('previewGrid');
        grid.innerHTML = `
          <span class="pg-k">Images</span><span class="pg-v">${d.total_images||0}</span>
          <span class="pg-k">Labels</span><span class="pg-v">${d.total_labels||0}</span>
          <span class="pg-k">Classes</span><span class="pg-v">${d.classes||0}</span>
          <span class="pg-k">Train</span><span class="pg-v">${d.train||0}</span>
          <span class="pg-k">Valid</span><span class="pg-v">${d.valid||0}</span>
          <span class="pg-k">Test</span><span class="pg-v">${d.test||0}</span>`;

        // Show split warning if dataset has no split structure
        const needsSplit = (d.train === 0 && d.valid === 0 && d.test === 0 && d.total_images > 0);
        document.getElementById('splitWarnBox').style.display = needsSplit ? '' : 'none';

        document.getElementById('importPreview').style.display = '';
      }
    } catch(e) { /* proceed without preview */ }
  },

  async startImport() {
    const fileInp = document.getElementById('importFileInput');
    if (!fileInp.files[0]) return;

    // Remember if user wants to split after
    const wantsSplit = document.getElementById('splitAfterImport')?.checked &&
                       document.getElementById('splitWarnBox').style.display !== 'none';

    this.closeModal('importModal');
    this.openModal('progressModal');
    document.getElementById('progTitle').textContent = 'Importing Dataset…';
    document.getElementById('progText').textContent  = 'Extracting ZIP…';

    const fd = new FormData();
    fd.append('file',          fileInp.files[0]);
    fd.append('project',       state.project);
    fd.append('merge_mode',    document.getElementById('mergeSel').value);
    fd.append('import_images', document.getElementById('impImgs').checked);
    fd.append('import_labels', document.getElementById('impLbls').checked);

    try {
      const r = await fetch('/api/import', {method:'POST', body:fd});
      const d = await r.json();
      this.closeModal('progressModal');

      if (d.success) {
        await this._loadMedia();

        if (wantsSplit || d.needs_split) {
          // Show split prompt instead of result modal
          this._showSplitPrompt(d);
        } else {
          document.getElementById('resultGrid').innerHTML = `
            <span class="pg-k">Images imported</span><span class="pg-v">${d.images_imported||0}</span>
            <span class="pg-k">Labels imported</span><span class="pg-v">${d.labels_imported||0}</span>
            <span class="pg-k">Skipped</span><span class="pg-v">${d.skipped||0}</span>
            <span class="pg-k">Classes merged</span><span class="pg-v">${d.classes_merged||0}</span>`;
          document.getElementById('resultTitle').textContent = 'Import Complete';
          this.openModal('resultModal');
        }
      } else {
        this._toast(d.error || 'Import failed', 'error');
      }
    } catch(e) { this.closeModal('progressModal'); this._toast('Import failed', 'error'); }
  },

  _showSplitPrompt(importData) {
    const stats = document.getElementById('splitPromptStats');
    stats.innerHTML = `
      <span class="pg-k">Images imported</span><span class="pg-v">${importData.images_imported||0}</span>
      <span class="pg-k">Labels imported</span><span class="pg-v">${importData.labels_imported||0}</span>
      <span class="pg-k">Classes</span><span class="pg-v">${importData.classes_merged||0} merged</span>`;
    this.openModal('splitPromptModal');
  },

  _skipSplit() {
    this.closeModal('splitPromptModal');
    this._toast('Import complete. You can split later with the Split button.', 'info');
  },

  _goToSplitFromPrompt() {
    this.closeModal('splitPromptModal');
    this.openSplit();
  },

  /* ── EXPORT ── */
  async startExport() {
    this.openModal('progressModal');
    document.getElementById('progTitle').textContent = 'Exporting Dataset…';
    document.getElementById('progText').textContent  = 'Building YOLO dataset ZIP…';

    try {
      const r = await fetch('/api/export', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({project: state.project, format:'yolov8'})
      });
      if (!r.ok) throw new Error();
      const blob = await r.blob();
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement('a');
      a.href = url; a.download = `${state.project}_yolo_dataset.zip`;
      document.body.appendChild(a); a.click();
      document.body.removeChild(a); URL.revokeObjectURL(url);
      this.closeModal('progressModal');
      this._toast('Dataset exported!', 'success');
    } catch(e) { this.closeModal('progressModal'); this._toast('Export failed', 'error'); }
  },

  /* ── SPLIT ── */
  openSplit() {
    // populate info
    const info = document.getElementById('splitInfo');
    const counts = {train:0, valid:0, test:0, none:0};
    state.media.forEach(m => { counts[m.split||'none']++; });
    info.innerHTML = `
      <span class="pg-k">Total images</span><span class="pg-v">${state.media.length}</span>
      <span class="pg-k">Train</span><span class="pg-v">${counts.train}</span>
      <span class="pg-k">Valid</span><span class="pg-v">${counts.valid}</span>
      <span class="pg-k">Test</span><span class="pg-v">${counts.test}</span>
      <span class="pg-k">Unsplit</span><span class="pg-v">${counts.none}</span>`;
    this.openModal('splitModal');
  },

  async startSplit() {
    const train = parseFloat(document.getElementById('trainNum').value) || 0.7;
    const val   = parseFloat(document.getElementById('valNum').value)   || 0.15;
    const test  = parseFloat(document.getElementById('testNum').value)  || 0.15;
    const sum   = train + val + test;

    if (Math.abs(sum - 1.0) > 0.01) {
      document.getElementById('ratioErr').style.display = '';
      return;
    }
    document.getElementById('ratioErr').style.display = 'none';
    this.closeModal('splitModal');
    this.openModal('progressModal');
    document.getElementById('progTitle').textContent = 'Splitting Dataset…';

    try {
      const r = await fetch('/api/split', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({
          project: state.project,
          train, val, test,
          shuffle: document.getElementById('shuffleCk').checked,
        })
      });
      const d = await r.json();
      this.closeModal('progressModal');
      if (d.success) {
        document.getElementById('resultGrid').innerHTML = `
          <span class="pg-k">Train</span><span class="pg-v">${d.train||0} images</span>
          <span class="pg-k">Valid</span><span class="pg-v">${d.val||0} images</span>
          <span class="pg-k">Test</span><span class="pg-v">${d.test||0} images</span>`;
        document.getElementById('resultTitle').textContent = 'Split Complete';
        this.openModal('resultModal');
        await this._loadMedia();
      } else { this._toast(d.error || 'Split failed', 'error'); }
    } catch(e) { this.closeModal('progressModal'); this._toast('Split failed','error'); }
  },

  /* ── NAVIGATION ── */
  nextImage() {
    if (state.currentIdx < state.media.length - 1) {
      this.loadImage(state.currentIdx + 1);
    } else if (!state.activeJobId && state.listPage < state.listTotalPages) {
      // Only cross pages when NOT locked to a specific job
      this._loadMedia(state.listPage + 1);
    }
    // If activeJobId is set: stop at the last image — do not bleed into next job
  },
  prevImage() {
    if (state.currentIdx > 0) {
      this.loadImage(state.currentIdx - 1);
    } else if (!state.activeJobId && state.listPage > 1) {
      // Only cross pages when NOT locked to a specific job
      this._goToPrevPageLastImage();
    }
    // If activeJobId is set: stop at the first image — do not bleed into prev job
  },
  async _goToPrevPageLastImage() {
    await this._loadMedia(state.listPage - 1);
    if (state.media.length > 0) {
      this.loadImage(state.media.length - 1, true);
    }
  },

  /* ── MODALS ── */
  openModal(id) { document.getElementById(id).style.display = 'flex'; },
  closeModal(id) { document.getElementById(id).style.display = 'none'; },

  /* ── TOAST ── */
  _toast(msg, type = 'info') {
    const stack = document.getElementById('toastStack');
    const t = document.createElement('div');
    t.className = `toast ${type}`;
    const icons = {success:'check-circle', error:'exclamation-circle', warn:'exclamation-triangle', info:'info-circle'};
    t.innerHTML = `<i class="fas fa-${icons[type]||'info-circle'}"></i>
      <span class="toast-msg">${msg}</span>
      <button class="toast-x"><i class="fas fa-times"></i></button>`;
    t.querySelector('.toast-x').addEventListener('click', () => t.remove());
    stack.appendChild(t);
    setTimeout(() => { t.style.opacity='0'; t.style.transition='opacity .3s'; setTimeout(()=>t.remove(),300); }, 4000);
  },

  /* ── KEYBOARD ── */
  _bindKeys() {
    document.addEventListener('keydown', e => {
      if (e.key === 'Shift') {
        const tag = document.activeElement.tagName;
        const inInput = (tag==='INPUT'||tag==='TEXTAREA'||tag==='SELECT');
        if (!inInput && state._mouseCanvas && state.imgEl) {
          const img = this._toImg(state._mouseCanvas.cx, state._mouseCanvas.cy);
          this._updateCursor(state._mouseCanvas.cx, state._mouseCanvas.cy, img, true);
        }
      }

      // Ignore when typing in inputs
      const tag = document.activeElement.tagName;
      const inInput = (tag==='INPUT'||tag==='TEXTAREA'||tag==='SELECT') && e.key !== 'Escape';

      // Always: Escape
      if (e.key === 'Escape') {
        if (document.getElementById('clsPopup').style.display !== 'none') { this.closePopup(); return; }
        // close topmost modal
        const modals = ['shortcutsModal','newProjModal','resultModal','splitModal','progressModal','importModal','uploadModal'];
        for (const m of modals) {
          if (document.getElementById(m).style.display !== 'none') { this.closeModal(m); return; }
        }
        state.selectedId = null; state.pendingBox = null; state.drawing = false;
        this._render(); this._updateAnnoList(); this._updateProps();
        return;
      }

      // Popup is open: arrow keys navigate, Enter confirms, Delete removes
      const popupOpen = document.getElementById('clsPopup').style.display !== 'none';
      if (popupOpen) {
        if (e.key === 'ArrowDown')  { e.preventDefault(); this._cpMove(+1); return; }
        if (e.key === 'ArrowUp')    { e.preventDefault(); this._cpMove(-1); return; }
        if (e.key === 'Enter')      { e.preventDefault(); this._confirmPopup(); return; }
        // Delete/Backspace should ONLY remove the annotation when focus is NOT
        // in a text input (cpSearch or cpNewClsName). If the user is typing,
        // let the key reach the input normally.
        if (e.key === 'Delete' || e.key === 'Backspace') {
          const focused = document.activeElement;
          const inTextField = (
            focused?.id === 'cpSearch' ||
            focused?.id === 'cpNewClsName' ||
            focused?.tagName === 'INPUT' ||
            focused?.tagName === 'TEXTAREA'
          );
          if (!inTextField) {
            e.preventDefault();
            this._deleteFromPopup();
          }
          return; // either way, don't let it fall through to canvas shortcuts
        }
        return;  // block all other shortcuts while popup open
      }

      if (inInput) return;

      // Ctrl combos
      if (e.ctrlKey || e.metaKey) {
        if (e.key === 'z') { e.preventDefault(); this.undo(); }
        if (e.key === 'y') { e.preventDefault(); this.redo(); }
        if (e.key === 's') { e.preventDefault(); this._saveCurrentAnnotations(); }
        if (e.key === 'c') { e.preventDefault(); this.copySelected(); }
        if (e.key === 'v') { e.preventDefault(); this.pasteBox(); }
        if (e.key === 'a') { e.preventDefault(); this._selectAllBoxes(); }
        return;
      }

      switch(e.key) {
        case 'b': case 'B': this.setMode('bbox'); break;
        case 'v': case 'V': this.setMode('edit'); break;
        case 'p': case 'P': this.setMode('polygon'); break;
        case 'r': case 'R': this.toggleRepeatMode(); break;
        case 'n': case 'N': this.toggleNullMark(); break;
        case ' ': e.preventDefault(); this.setMode('pan'); break;
        case 'f': case 'F': this._fitImage(); break;
        case 'l': case 'L': this.toggleZoomLock(); break;
        case 'g': case 'G': this.toggleGrid(); break;
        case 't': case 'T': this.toggleShowLabels(); break;
        case '+': case '=': this.zoomIn(); break;
        case '-': case '_': this.zoomOut(); break;
        case '0': this._fitImage(); break;
        case 'ArrowRight': case 'd': case 'D':
          if (e.shiftKey) { e.preventDefault(); if (state.listPage < state.listTotalPages) this._loadMedia(state.listPage + 1); }
          else this.nextImage();
          break;
        case 'ArrowLeft':  case 'a': case 'A':
          if (e.shiftKey) { e.preventDefault(); if (state.listPage > 1) this._loadMedia(state.listPage - 1); }
          else this.prevImage();
          break;
        case 'Delete': case 'Backspace': this.deleteSelected(); break;
        case 'c': case 'C':
          if (state.selectedId) {
            const box = state.bboxes.find(b=>b.id===state.selectedId);
            if (box) this._showClassPopupForEdit(box, null);
          }
          break;
        case 's': case 'S': this._saveCurrentAnnotations(); break;
        // Enter can also finish polygon
        case 'Enter':
          if (state.mode === 'polygon' && state.polygonPoints.length >= 3) {
            e.preventDefault();
            this._finishPolygon(null);
          }
          break;
        default:
          // 1-9: select class
          if (e.key >= '1' && e.key <= '9') {
            const idx = parseInt(e.key) - 1;
            if (idx < state.classes.length) this.selectClass(state.classes[idx].id);
          }
      }
    });

    document.addEventListener('keyup', e => {
      if (e.key === 'Shift') {
        const tag = document.activeElement.tagName;
        const inInput = (tag==='INPUT'||tag==='TEXTAREA'||tag==='SELECT');
        if (!inInput && state._mouseCanvas && state.imgEl) {
          const img = this._toImg(state._mouseCanvas.cx, state._mouseCanvas.cy);
          this._updateCursor(state._mouseCanvas.cx, state._mouseCanvas.cy, img, false);
        }
      }
    });
  },

  /* ── SELECT ALL ── */
  _selectAllBoxes() {
    if (!state.bboxes.length) return;
    // Cycle: select first unselected or deselect all
    if (!state.selectedId) {
      state.selectedId = state.bboxes[0].id;
    } else {
      state.selectedId = null;
    }
    this._render(); this._updateAnnoList(); this._updateProps();
  },


  /* ═══════════════════════════════════════════════════════════════
     SPA ROUTING
  ═══════════════════════════════════════════════════════════════ */
  _bindRightNav() {
    document.querySelectorAll('.rn-item[data-page]').forEach(btn => {
      btn.addEventListener('click', () => this.showPage(btn.dataset.page));
    });
  },

  showPage(page) {
    state.currentPage = page;
    const url = new URL(location.href);
    url.hash = page;
    history.replaceState(null, '', url.toString());
    document.querySelectorAll('.rn-item').forEach(b => b.classList.toggle('active', b.dataset.page === page));
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    const target = document.getElementById(`page-${page}`);
    if (target) target.classList.add('active');
    if (page === 'dataset')  this._loadDatasetPage();
    if (page === 'versions') this._loadVersionsPage();
    if (page === 'classes')  this._loadClassesPage();
    if (page === 'upload')   { this._initUploadPage(); }
    if (page === 'projects') this._loadProjectsPage();
  },

  _updateNavBadges() {
    const el = document.getElementById('rnAnnotateBadge');
    if (el) el.textContent = state.annotatedPaths.size;
    // Dataset badge: show total images across all completed datasets
    const dsEl = document.getElementById('rnDatasetBadge');
    if (dsEl) {
      const total = state.listTotalDatasetImages ?? 0;
      dsEl.textContent = total > 999 ? Math.round(total/1000) + 'k' : total;
    }
    const clsEl = document.getElementById('rnClassesBadge');
    if (clsEl) clsEl.textContent = state.classes.length;
    this._syncProjectDropdowns(state.project);
    const centerLabel = document.getElementById('upCenterProjectLabel');
    if (centerLabel) centerLabel.textContent = state.project;
    this._updateProjectsBadge();
    // Refresh dataset image count in background
    this._refreshDatasetImageCount();
  },

  async _refreshDatasetImageCount() {
    // Debounce: don't hammer the server
    clearTimeout(this._dsCountTimer);
    this._dsCountTimer = setTimeout(async () => {
      try {
        const r = await fetch(`/api/datasets/images?project=${encodeURIComponent(state.project)}&per_page=1&page=1`);
        if (!r.ok) return;
        const d = await r.json();
        state.listTotalDatasetImages = d.pagination?.total ?? 0;
        const dsEl = document.getElementById('rnDatasetBadge');
        if (dsEl) {
          const t = state.listTotalDatasetImages;
          dsEl.textContent = t > 999 ? Math.round(t/1000) + 'k' : t;
        }
      } catch(e) { /* silent */ }
    }, 1200);
  },

  async _updateProjectsBadge() {
    try {
      const r = await fetch('/api/workspace/folders');
      const folders = await r.json();
      const badge = document.getElementById('rnProjectsBadge');
      if (badge) badge.textContent = folders.length;
    } catch(e) {}
  },

  _updateHeaderBreadcrumb() {
    const el = document.getElementById('hdrBreadcrumb');
    if (el) el.textContent = state.project;
    const projEl = document.getElementById('hdrProjectName');
    if (projEl) projEl.textContent = state.project;
  },

  _updateHeaderImage(filename, idx, total) {
    const fnEl = document.getElementById('hdrFileName');
    if (fnEl) fnEl.textContent = filename || '—';
    const bcEl = document.getElementById('hdrBreadcrumbFile');
    if (bcEl) bcEl.textContent = filename || '';

    // Show global index (across all pages), not page-local index
    const globalIdx   = (idx >= 0 && total > 0)
      ? (state.listPage - 1) * state.listPerPage + idx + 1
      : 0;
    const globalTotal = state.listTotal || total;
    const label = globalTotal ? `${globalIdx} / ${globalTotal}` : '0 / 0';

    // Header counter (text)
    const ctrEl = document.getElementById('hdrCounter');
    if (ctrEl) ctrEl.textContent = label;
    const counterEl = document.getElementById('imageCounter');
    if (counterEl) counterEl.textContent = label;

    // Bottom-center nav bar — split current / total
    const navBar   = document.getElementById('imgNavBar');
    const navCur   = document.getElementById('imgNavCurrent');
    const navTot   = document.getElementById('imgNavTotal');
    const navPrev  = document.getElementById('imgNavPrev');
    const navNext  = document.getElementById('imgNavNext');

    if (navBar) {
      const hasImage = idx >= 0 && globalTotal > 0;
      navBar.style.display = hasImage ? '' : 'none';
      if (navCur) navCur.textContent = hasImage ? globalIdx : '—';
      if (navTot) navTot.textContent = hasImage ? globalTotal : '—';
      if (navPrev) navPrev.disabled = (globalIdx <= 1);
      if (navNext) navNext.disabled = (globalIdx >= globalTotal);
    }
  },

  /* ═══ RIGHT PANEL TABS ═══════════════════════════════════════ */
  _bindRightPanelTabs() {
    document.querySelectorAll('.rp-tab[data-rpt]').forEach(tab => {
      tab.addEventListener('click', () => {
        const key = tab.dataset.rpt;
        document.querySelectorAll('.rp-tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.rp-panel').forEach(p => p.classList.remove('active'));
        tab.classList.add('active');
        const panel = document.getElementById(`rpt-${key}`);
        if (panel) panel.classList.add('active');
        if (key === 'raw')      this._updateRawData();
        if (key === 'comments') this._renderComments();
      });
    });
    document.getElementById('copyRawBtn')?.addEventListener('click', () => {
      const text = state.bboxes.map(b => {
        const xc = ((b.x + b.w/2) / state.imgW).toFixed(6);
        const yc = ((b.y + b.h/2) / state.imgH).toFixed(6);
        const w  = (b.w / state.imgW).toFixed(6);
        const h  = (b.h / state.imgH).toFixed(6);
        return `${b.cls} ${xc} ${yc} ${w} ${h}`;
      }).join('\n');
      navigator.clipboard?.writeText(text).then(() => this._toast('Copied to clipboard', 'success'));
    });
    document.getElementById('commentSendBtn')?.addEventListener('click', () => this._addComment());
    document.getElementById('commentInput')?.addEventListener('keydown', e => { if (e.key === 'Enter') this._addComment(); });
    document.getElementById('clearNotesBtn')?.addEventListener('click', () => {
      const item = state.media[state.currentIdx];
      if (!item) return;
      delete state.imageComments[item.path];
      this._renderComments();
    });
  },

  _updateRawData() {
    const view = document.getElementById('rawDataView');
    if (!view) return;
    if (!state.bboxes.length) { view.innerHTML = '<div class="raw-data-empty">No annotations yet</div>'; return; }
    view.innerHTML = state.bboxes.map(b => {
      const cls  = state.classes.find(c => c.id === b.cls);
      const xc   = ((b.x + b.w/2) / state.imgW).toFixed(6);
      const yc   = ((b.y + b.h/2) / state.imgH).toFixed(6);
      const w    = (b.w / state.imgW).toFixed(6);
      const h    = (b.h / state.imgH).toFixed(6);
      const [r,g,bv] = cls?.color || [180,180,180];
      return `<div class="raw-line"><span class="raw-cls" style="color:rgb(${r},${g},${bv})">${b.cls}</span><span class="raw-coords">${xc} ${yc} ${w} ${h}</span></div>`;
    }).join('');
  },

  _addComment() {
    const inp = document.getElementById('commentInput');
    if (!inp) return;
    const text = inp.value.trim();
    if (!text || state.currentIdx < 0) return;
    const item = state.media[state.currentIdx];
    if (!item) return;
    if (!state.imageComments[item.path]) state.imageComments[item.path] = [];
    state.imageComments[item.path].push({ text, time: new Date().toLocaleTimeString() });
    inp.value = '';
    this._renderComments();
  },

  _renderComments() {
    const list = document.getElementById('commentsList');
    if (!list) return;
    const item     = state.media[state.currentIdx];
    const comments = (item && state.imageComments[item.path]) || [];
    list.innerHTML = !comments.length
      ? '<div style="text-align:center;padding:20px;color:var(--tx3);font-size:12px;">No notes for this image</div>'
      : comments.map(c => `<div class="comment-item"><div class="ci-text">${c.text}</div><div class="ci-time">${c.time}</div></div>`).join('');
    list.scrollTop = list.scrollHeight;
  },

  _updateUnusedClasses() {
    const section = document.getElementById('unusedClsSection');
    const chips   = document.getElementById('unusedClsChips');
    if (!section || !chips) return;
    const usedIds = new Set(state.bboxes.map(b => b.cls));
    const unused  = state.classes.filter(c => !usedIds.has(c.id));
    if (!unused.length) { section.style.display = 'none'; return; }
    section.style.display = '';
    chips.innerHTML = unused.map(cls => {
      const [r,g,b] = cls.color;
      return `<button class="unused-chip" style="border-color:rgb(${r},${g},${b});color:rgb(${r},${g},${b})" onclick="app.selectClass(${cls.id})">${cls.name}</button>`;
    }).join('');
  },

  /* ═══ DATASET PAGE ═══════════════════════════════════════════ */
  _loadDatasetPage() {
    state.dsPage = 1;
    state.dsSelectedPaths = new Set();
    state.dsSelectMode = false;
    this._fetchDatasetImages();
    this._dsPopulateClassFilter();
    if (!this._datasetBound) {
      this._datasetBound = true;

      // Search
      document.getElementById('dsSearch')?.addEventListener('input', e => {
        state.dsSearch = e.target.value; state.dsPage = 1; this._fetchDatasetImages();
      });

      // Split pills
      document.querySelectorAll('#dsSplitPills .ds-pill').forEach(btn => {
        btn.addEventListener('click', () => {
          document.querySelectorAll('#dsSplitPills .ds-pill').forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
          state.dsFilter = btn.dataset.dsf; state.dsPage = 1; this._fetchDatasetImages();
        });
      });

      // Status pills
      document.querySelectorAll('#dsStatusPills .ds-pill').forEach(btn => {
        btn.addEventListener('click', () => {
          document.querySelectorAll('#dsStatusPills .ds-pill').forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
          state.dsAnnoFilter = btn.dataset.dsa; state.dsPage = 1; this._fetchDatasetImages();
        });
      });

      // Class filter
      document.getElementById('dsClassFilter')?.addEventListener('change', e => {
        state.dsClassFilter = e.target.value; state.dsPage = 1; this._fetchDatasetImages();
      });

      // Select mode toggle
      document.getElementById('dsSelToggle')?.addEventListener('click', () => {
        state.dsSelectMode = !state.dsSelectMode;
        state.dsSelectedPaths = new Set();
        document.getElementById('dsSelToggle').classList.toggle('active', state.dsSelectMode);
        document.getElementById('dsGrid').classList.toggle('ds-select-mode', state.dsSelectMode);
        this._dsUpdateSelToolbar();
        // Re-render to show/hide checkboxes
        if (this._dsCurrentItems) this._renderDatasetGrid(this._dsCurrentItems, this._dsLastPg || {});
      });

      // Select-all via Ctrl+A when page is active
      document.addEventListener('keydown', e => {
        if (state.currentPage !== 'dataset') return;
        if ((e.ctrlKey || e.metaKey) && e.key === 'a' && state.dsSelectMode) {
          e.preventDefault();
          (this._dsCurrentItems || []).forEach(i => state.dsSelectedPaths.add(i.path));
          this._renderDatasetGrid(this._dsCurrentItems, this._dsLastPg || {});
          this._dsUpdateSelToolbar();
        }
      });

      // Clear selection
      document.getElementById('dsSelClearBtn')?.addEventListener('click', () => {
        state.dsSelectedPaths = new Set();
        this._renderDatasetGrid(this._dsCurrentItems, this._dsLastPg || {});
        this._dsUpdateSelToolbar();
      });

      // Delete selected
      document.getElementById('dsSelDeleteBtn')?.addEventListener('click', () => this._dsDeleteSelected());

      // Re-annotate selected
      document.getElementById('dsSelAnnotateBtn')?.addEventListener('click', () => this._dsReAnnotateSelected());

      document.getElementById('dsExportBtn')?.addEventListener('click', () => this.startExport());
      document.getElementById('dsSplitBtn')?.addEventListener('click', () => this.openSplit());

      // Per-page selector
      document.getElementById('dsPerPageSelect')?.addEventListener('change', e => {
        state.dsPerPage = parseInt(e.target.value) || 50;
        state.dsPage = 1;
        this._fetchDatasetImages();
      });
    }
  },

  // Populate class filter dropdown from project classes + null option
  _dsPopulateClassFilter() {
    const sel = document.getElementById('dsClassFilter');
    if (!sel) return;
    const current = sel.value;
    sel.innerHTML = '<option value="">All classes</option><option value="__null__">— Null (no class) —</option>';
    (state.classes || []).forEach(cls => {
      const opt = document.createElement('option');
      opt.value = cls.id;
      opt.textContent = `${cls.name}`;
      if (String(cls.id) === current) opt.selected = true;
      sel.appendChild(opt);
    });
    if (current && current !== '__null__') sel.value = current;
  },

  _dsUpdateSelToolbar() {
    const n    = state.dsSelectedPaths?.size || 0;
    const bar  = document.getElementById('dsSelToolbar');
    const cnt  = document.getElementById('dsSelCount');
    if (bar) bar.style.display = n > 0 ? '' : 'none';
    if (cnt) cnt.textContent   = `${n} selected`;
  },

  async _dsDeleteSelected() {
    const paths = [...(state.dsSelectedPaths || [])];
    if (!paths.length) return;
    if (!confirm(`Delete ${paths.length} image${paths.length > 1 ? 's' : ''} permanently? This cannot be undone.`)) return;
    try {
      const r = await fetch('/api/datasets/images/delete', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project: state.project, paths }),
      });
      const d = await r.json();
      if (d.success) {
        this._toast(`Deleted ${d.deleted} image${d.deleted !== 1 ? 's' : ''}`, 'success');
        state.dsSelectedPaths = new Set();
        this._dsUpdateSelToolbar();
        this._fetchDatasetImages();
        this._refreshDatasetImageCount?.();
      } else { this._toast('Delete failed', 'error'); }
    } catch(e) { this._toast('Network error', 'error'); }
  },

  async _dsReAnnotateSelected() {
    const paths = [...(state.dsSelectedPaths || [])];
    if (!paths.length) return;
    // Use the first selected image's dataset_id to move back to active work
    const item = (this._dsCurrentItems || []).find(i => state.dsSelectedPaths.has(i.path));
    if (!item) return;
    if (!confirm(`Move ${paths.length} image${paths.length > 1 ? 's' : ''} back to Active Work for re-annotation?\nTheir dataset entry will be updated.`)) return;
    this._toast('Opening first image in annotator…', 'info');
    // Load the full dataset for review and jump to first selected image
    await this._loadDatasetForReview({ dataset_id: item.dataset_id });
    const idx = state.media.findIndex(m => m.path === item.path);
    if (idx >= 0) this.loadImage(idx, true);
  },

  async _fetchDatasetImages() {
    const grid  = document.getElementById('dsGrid');
    const empty = document.getElementById('dsEmpty');
    const pag   = document.getElementById('dsPagination');
    if (!grid) return;

    // Show loading shimmer
    grid.innerHTML = Array(8).fill(
      `<div class="ds-card ds-card-skeleton"><div class="ds-thumb-skeleton"></div><div class="ds-info-skeleton"></div></div>`
    ).join('');
    if (empty) empty.style.display = 'none';
    if (pag)   pag.style.display = 'none';

    const annoMap = { all: 'all', annotated: 'yes', empty: 'no', null: 'null' };
    const params = new URLSearchParams({
      project:   state.project,
      page:      state.dsPage,
      per_page:  state.dsPerPage,
      split:     state.dsFilter     || 'all',
      annotated: annoMap[state.dsAnnoFilter] || 'all',
      q:         state.dsSearch     || '',
    });
    if (state.dsClassFilter) params.set('class_id', state.dsClassFilter);

    try {
      const r = await fetch(`/api/datasets/images?${params}`);
      if (!r.ok) throw new Error('Failed');
      const d = await r.json();
      this._renderDatasetGrid(d.items || [], d.pagination || {});
    } catch(e) {
      grid.innerHTML = `<div class="ds-empty" id="dsEmpty" style="grid-column:1/-1">
        <i class="fas fa-exclamation-circle"></i><p>Failed to load dataset images</p></div>`;
    }
  },

  _renderDatasetGrid(items, pg) {
    const grid  = document.getElementById('dsGrid');
    const empty = document.getElementById('dsEmpty');
    const pag   = document.getElementById('dsPagination');
    if (!grid) return;

    // Cache for lightbox navigation and selection
    this._dsCurrentItems = items;
    this._dsLastPg = pg;

    // Apply select-mode class to grid
    if (state.dsSelectMode) grid.classList.add('ds-select-mode');
    else grid.classList.remove('ds-select-mode');

    const total = pg.total || items.length;
    const pages = pg.total_pages || 1;
    const cur   = pg.page || state.dsPage;

    // Update counters
    const elT = document.getElementById('dsStatTotal');
    const elA = document.getElementById('dsStatAnnotated');
    if (elT) elT.textContent = total;
    if (elA) elA.textContent = items.filter(m => m.annotated).length +
      (pg.total ? ` / ${total}` : '');

    if (!items.length) {
      grid.innerHTML = '';
      if (empty) empty.style.display = '';
      if (pag)   pag.style.display = 'none';
      return;
    }
    if (empty) empty.style.display = 'none';
    if (pag)   pag.style.display = '';

    // Render cards — each card uses a canvas to overlay bboxes on the thumbnail
    grid.innerHTML = items.map(item => {
      const thumb = `/api/thumbnail?path=${encodeURIComponent(item.path)}&project=${encodeURIComponent(state.project)}`;
      const safe  = item.path.replace(/\\/g,'\\\\').replace(/'/g,"\\'");
      const sp    = item.split || 'none';
      const dsLabel = item.dataset_id ? item.dataset_id.replace(/^job_/, '').replace(/_/g,' ') : '';
      const isSel = state.dsSelectedPaths?.has(item.path);
      const isNull = item.is_null;
      return `<div class="ds-card${isSel ? ' ds-selected' : ''}"
               onclick="app._dsCardClick('${safe}', event)" title="${item.name}">
        <div class="ds-thumb-wrap">
          <div class="ds-card-checkbox" onclick="event.stopPropagation();app._dsToggleSelect('${safe}')">
            ${isSel ? '<i class="fas fa-check"></i>' : ''}
          </div>
          <img class="ds-thumb" src="${thumb}" loading="lazy"
               data-path="${item.path.replace(/"/g,'&quot;')}"
               onload="app._dsDrawBboxes(this)"
               onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">
          <div class="ds-thumb-ph" style="display:none"><i class="fas fa-image"></i></div>
          <canvas class="ds-bbox-canvas" aria-hidden="true"></canvas>
          <span class="ds-split-badge ${sp}">${sp === 'none' ? 'unsplit' : sp}</span>
          ${isNull
            ? '<span class="ds-anno-badge null"><i class="fas fa-ban"></i></span>'
            : item.annotated
              ? '<span class="ds-anno-badge"><i class="fas fa-check"></i></span>'
              : ''}
        </div>
        <div class="ds-card-info">
          <div class="ds-card-name">${item.name}</div>
          <div class="ds-card-meta-row">
            <span class="ds-ds-label" title="${item.dataset_id}">${dsLabel}</span>
          </div>
        </div>
      </div>`;
    }).join('');

    // Pagination bar
    this._renderDsPagination(cur, pages, total);
  },

  // Draw bounding boxes on the dataset card thumbnail once it loads
  async _dsDrawBboxes(img) {
    const path = img.dataset.path;
    if (!path) return;
    try {
      const r = await fetch(`/api/annotations?path=${encodeURIComponent(path)}&project=${encodeURIComponent(state.project)}`);
      if (!r.ok) return;
      const d = await r.json();
      if (!d.bboxes || !d.bboxes.length) return;

      const canvas = img.nextElementSibling?.nextElementSibling; // canvas is after ph div
      if (!canvas || canvas.tagName !== 'CANVAS') return;
      const iw = img.naturalWidth  || img.offsetWidth  || 160;
      const ih = img.naturalHeight || img.offsetHeight || 120;
      const dw = img.offsetWidth   || 160;
      const dh = img.offsetHeight  || 120;
      canvas.width  = dw;
      canvas.height = dh;
      const ctx = canvas.getContext('2d');

      const scaleX = dw / iw;
      const scaleY = dh / ih;

      d.bboxes.forEach((b, i) => {
        // Pick a colour from the class palette
        const palette = [
          '#00e5b0','#ff6b6b','#ffd93d','#6bcb77','#4d96ff',
          '#ff6bce','#c77dff','#ffb347','#00d4d4','#ff9f1c',
        ];
        const col = palette[(b.class_id || 0) % palette.length];
        ctx.strokeStyle = col;
        ctx.lineWidth   = Math.max(1, dw * 0.012);
        ctx.shadowColor = col;
        ctx.shadowBlur  = 3;

        if (b.type === 'polygon' && b.points) {
          ctx.beginPath();
          b.points.forEach((p, pi) => {
            const px = p.x * dw, py = p.y * dh;
            pi === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py);
          });
          ctx.closePath();
          ctx.stroke();
          ctx.fillStyle = col + '22';
          ctx.fill();
        } else {
          const x = (b.x_center - b.width  / 2) * dw;
          const y = (b.y_center - b.height / 2) * dh;
          const w = b.width  * dw;
          const h = b.height * dh;
          ctx.strokeRect(x, y, w, h);
          ctx.fillStyle = col + '18';
          ctx.fillRect(x, y, w, h);
        }
        ctx.shadowBlur = 0;
      });
    } catch(e) { /* no bbox overlay on error */ }
  },

  _renderDsPagination(cur, pages, total) {
    const pag = document.getElementById('dsPagination');
    if (!pag) return;
    // Always show pagination bar (has per-page selector even on single page)
    pag.style.display = '';

    // Sync per-page select to current state
    const ppSel = document.getElementById('dsPerPageSelect');
    if (ppSel) ppSel.value = state.dsPerPage;

    const pi = pag.querySelector('.ds-page-info');
    if (pi) {
      if (total === 0) {
        pi.textContent = '0 images';
      } else {
        const start = (cur - 1) * state.dsPerPage + 1;
        const end   = Math.min(cur * state.dsPerPage, total);
        pi.textContent = `${start}–${end} of ${total}`;
      }
    }

    const btns = pag.querySelector('.ds-page-btns');
    if (!btns) return;
    btns.innerHTML = '';
    if (pages <= 1) return; // no page buttons needed if only one page

    const mk = (label, page, disabled = false, active = false) => {
      const b = document.createElement('button');
      b.className = 'ds-pg-btn' + (active ? ' active' : '');
      b.innerHTML = label; b.disabled = disabled;
      b.addEventListener('click', () => { state.dsPage = page; this._fetchDatasetImages(); });
      btns.appendChild(b);
    };

    mk('<i class="fas fa-chevron-left"></i>', cur - 1, cur === 1);
    const maxP = 5;
    let ps = Math.max(1, cur - Math.floor(maxP / 2));
    let pe = Math.min(pages, ps + maxP - 1);
    if (pe - ps < maxP - 1) ps = Math.max(1, pe - maxP + 1);
    if (ps > 1) { mk('1', 1); if (ps > 2) { const e = document.createElement('span'); e.className='ds-pg-ell'; e.textContent='…'; btns.appendChild(e); } }
    for (let p = ps; p <= pe; p++) mk(p, p, false, p === cur);
    if (pe < pages) { if (pe < pages - 1) { const e = document.createElement('span'); e.className='ds-pg-ell'; e.textContent='…'; btns.appendChild(e); } mk(pages, pages); }
    mk('<i class="fas fa-chevron-right"></i>', cur + 1, cur === pages);
  },

  _dsOpenImage(path) {
    const items = this._dsCurrentItems || [];
    const idx   = items.findIndex(m => m.path === path);
    this._dsShowViewer(path, idx, items);
  },

  // Card click — toggle select in select mode, open viewer otherwise
  _dsCardClick(path, event) {
    if (state.dsSelectMode) {
      this._dsToggleSelect(path);
    } else {
      this._dsOpenImage(path);
    }
  },

  _dsToggleSelect(path) {
    if (!state.dsSelectedPaths) state.dsSelectedPaths = new Set();
    if (state.dsSelectedPaths.has(path)) state.dsSelectedPaths.delete(path);
    else state.dsSelectedPaths.add(path);
    // Update just that card's visual state
    const safe = path.replace(/\\/g,'\\\\').replace(/'/g,"\\'");
    const card = document.querySelector(`.ds-card[onclick*="${CSS.escape(path.slice(-20))}"]`) ||
                 [...document.querySelectorAll('.ds-card')].find(c => c.title === path.split('/').pop() ||
                   c.querySelector('.ds-card-name')?.textContent === path.split('/').pop());
    if (card) {
      const isSel = state.dsSelectedPaths.has(path);
      card.classList.toggle('ds-selected', isSel);
      const cb = card.querySelector('.ds-card-checkbox');
      if (cb) cb.innerHTML = isSel ? '<i class="fas fa-check"></i>' : '';
    }
    this._dsUpdateSelToolbar();
  },

  async _dsShowViewer(path, idx, items) {
    document.getElementById('dsLightbox')?.remove();

    const total   = items.length;
    const item    = items[idx] || { path, name: path.split('/').pop(), split: '', annotated: false };
    const hasPrev = idx > 0;
    const hasNext = idx < total - 1;

    const lb = document.createElement('div');
    lb.id = 'dsLightbox';
    lb.className = 'ds-lightbox';
    lb._items = items;
    lb._idx   = idx;
    lb.innerHTML = `
      <div class="ds-lb-backdrop"></div>
      <div class="ds-lb-panel">
        <!-- Header -->
        <div class="ds-lb-head">
          <div class="ds-lb-head-left">
            <span class="ds-lb-name">${item.name}</span>
            <span class="ds-lb-split-chip ${item.split || 'none'}">${item.split || 'unsplit'}</span>
          </div>
          <div class="ds-lb-head-right">
            <span class="ds-lb-counter">${idx + 1} / ${total}</span>
            <button class="ds-lb-btn annotate-btn" id="dsLbAnnotateBtn" title="Open in annotator">
              <i class="fas fa-tag"></i> Annotate
            </button>
            <button class="ds-lb-close" title="Close (Esc)"><i class="fas fa-times"></i></button>
          </div>
        </div>

        <!-- Image area with prev/next -->
        <div class="ds-lb-body">
          <button class="ds-lb-nav prev" id="dsLbPrev" title="Previous image (←)" ${!hasPrev ? 'disabled' : ''}>
            <i class="fas fa-chevron-left"></i>
          </button>
          <div class="ds-lb-img-wrap">
            <img class="ds-lb-img" id="dsLbImg"
                 src="/api/image?path=${encodeURIComponent(path)}&project=${encodeURIComponent(state.project)}"
                 onload="app._dsViewerLoaded(this)">
            <canvas class="ds-lb-canvas" id="dsLbCanvas"></canvas>
            <div class="ds-lb-spinner" id="dsLbSpinner"><i class="fas fa-circle-notch fa-spin"></i></div>
          </div>
          <button class="ds-lb-nav next" id="dsLbNext" title="Next image (→)" ${!hasNext ? 'disabled' : ''}>
            <i class="fas fa-chevron-right"></i>
          </button>
        </div>

        <!-- Info footer -->
        <div class="ds-lb-foot">
          <span class="ds-lb-path">${item.path}</span>
          <span class="ds-lb-anno-state ${item.annotated ? 'annotated' : 'raw'}">
            <i class="fas fa-${item.annotated ? 'check-circle' : 'circle'}"></i>
            ${item.annotated ? 'Annotated' : 'Unannotated'}
          </span>
        </div>
      </div>`;

    document.body.appendChild(lb);
    lb._bboxes = [];

    // Close handler
    const close = () => {
      lb.classList.remove('ds-lightbox-visible');
      setTimeout(() => lb.remove(), 200);
      document.removeEventListener('keydown', kbHandler);
    };
    lb.querySelector('.ds-lb-close').addEventListener('click', close);
    lb.querySelector('.ds-lb-backdrop').addEventListener('click', e => {
      if (e.target === lb.querySelector('.ds-lb-backdrop')) close();
    });

    // Navigate
    const goTo = (newIdx) => {
      if (newIdx < 0 || newIdx >= lb._items.length) return;
      const newPath = lb._items[newIdx].path;
      lb.remove();
      document.removeEventListener('keydown', kbHandler);
      this._dsShowViewer(newPath, newIdx, lb._items);
    };

    lb.querySelector('#dsLbPrev')?.addEventListener('click', () => goTo(lb._idx - 1));
    lb.querySelector('#dsLbNext')?.addEventListener('click', () => goTo(lb._idx + 1));

    // "Annotate" button — load this dataset image into the annotator for bbox editing
    lb.querySelector('#dsLbAnnotateBtn')?.addEventListener('click', async () => {
      close();
      // Load dataset images into the annotator via review mode,
      // then jump to the clicked image — user can edit bboxes directly
      await this._loadDatasetForReview({ dataset_id: item.dataset_id });
      // After review loads, find this specific image and open it
      const targetIdx = state.media.findIndex(m => m.path === path);
      if (targetIdx >= 0) {
        this.loadImage(targetIdx, true);
      }
      this._toast(`Editing ${item.name} — changes save back to the dataset`, 'info');
    });

    // Keyboard nav
    const kbHandler = e => {
      if (e.key === 'Escape')     { close(); }
      if (e.key === 'ArrowRight') { goTo(lb._idx + 1); }
      if (e.key === 'ArrowLeft')  { goTo(lb._idx - 1); }
    };
    document.addEventListener('keydown', kbHandler);

    requestAnimationFrame(() => lb.classList.add('ds-lightbox-visible'));

    // Fetch bboxes
    try {
      const r = await fetch(`/api/annotations?path=${encodeURIComponent(path)}&project=${encodeURIComponent(state.project)}`);
      if (r.ok) {
        const d = await r.json();
        lb._bboxes = d.bboxes || [];
        // Redraw if image already loaded
        const img = document.getElementById('dsLbImg');
        if (img?.complete && img.naturalWidth) this._dsViewerLoaded(img);
      }
    } catch(e) { lb._bboxes = []; }
  },

  _dsViewerLoaded(img) {
    const lb = document.getElementById('dsLightbox');
    if (!lb) return;
    const spinner = document.getElementById('dsLbSpinner');
    if (spinner) spinner.style.display = 'none';

    const canvas = document.getElementById('dsLbCanvas');
    if (!canvas) return;

    // Size canvas to match rendered image exactly
    const rect = img.getBoundingClientRect();
    const dw   = Math.round(rect.width)  || img.naturalWidth;
    const dh   = Math.round(rect.height) || img.naturalHeight;
    canvas.width  = dw;
    canvas.height = dh;
    canvas.style.width  = dw + 'px';
    canvas.style.height = dh + 'px';

    const ctx    = canvas.getContext('2d');
    const bboxes = lb._bboxes || [];
    if (!bboxes.length) return;

    const palette = [
      '#00e5b0','#ff6b6b','#ffd93d','#6bcb77','#4d96ff',
      '#ff6bce','#c77dff','#ffb347','#00d4d4','#ff9f1c',
    ];
    const fontSize = Math.max(12, dw * 0.016);

    bboxes.forEach(b => {
      const col = palette[(b.class_id || 0) % palette.length];
      ctx.strokeStyle = col;
      ctx.lineWidth   = Math.max(2, dw * 0.0025);
      ctx.shadowColor = col;
      ctx.shadowBlur  = 6;

      if (b.type === 'polygon' && b.points) {
        ctx.beginPath();
        b.points.forEach((p, i) => {
          i === 0 ? ctx.moveTo(p.x * dw, p.y * dh) : ctx.lineTo(p.x * dw, p.y * dh);
        });
        ctx.closePath();
        ctx.stroke();
        ctx.fillStyle = col + '28'; ctx.fill();
      } else {
        const x = (b.x_center - b.width  / 2) * dw;
        const y = (b.y_center - b.height / 2) * dh;
        const w = b.width  * dw;
        const h = b.height * dh;
        ctx.strokeRect(x, y, w, h);
        ctx.fillStyle = col + '18'; ctx.fillRect(x, y, w, h);
        // Class label pill — show name if available, fallback to index
        ctx.shadowBlur = 0;
        const cls = state.classes?.find(c => c.id === (b.class_id ?? -1));
        const label = cls ? cls.name : (b.class_id != null ? `#${b.class_id}` : '?');
        ctx.font = `700 ${fontSize}px Sora, sans-serif`;
        const tw = ctx.measureText(label).width;
        const lx = x, ly = y > fontSize + 4 ? y - fontSize - 4 : y + 2;
        ctx.fillStyle = col; ctx.fillRect(lx, ly, tw + 8, fontSize + 4);
        ctx.fillStyle = '#000'; ctx.fillText(label, lx + 4, ly + fontSize);
      }
      ctx.shadowBlur = 0;
    });
  },

  /* ═══ VERSIONS PAGE ══════════════════════════════════════════ */
  async _loadVersionsPage() {
    try {
      const r = await fetch(`/api/versions?project=${encodeURIComponent(state.project)}`);
      state.versions = await r.json();
    } catch(e) { state.versions = []; }
    this._renderVersionsList();
    if (!this._versionsBound) {
      this._versionsBound = true;
      document.getElementById('createVersionBtn')?.addEventListener('click', () => this._vwOpen());
      document.getElementById('vsStartCreateBtn')?.addEventListener('click', () => this._vwOpen());
    }
  },

  _renderVersionsList() {
    const scroll = document.getElementById('vsListScroll');
    const empty  = document.getElementById('vsEmptyList');
    if (!scroll) return;
    scroll.innerHTML = '';
    if (empty) scroll.appendChild(empty);
    if (!state.versions.length) { if (empty) empty.style.display = ''; return; }
    if (empty) empty.style.display = 'none';

    const sorted = [...state.versions].reverse();
    sorted.forEach((ver, idx) => {
      const isCurrent = idx === 0; // most recent = current
      const pp  = ver.preprocessing || {};
      const sc  = ver.splits || {};
      const total = ver.total_images || 0;

      // Preprocessing summary line
      let ppLine = '';
      if (pp.resize_mode && pp.resize_mode !== 'none') {
        ppLine = `${pp.resize_w||'?'}×${pp.resize_h||'?'} – ${pp.resize_mode.charAt(0).toUpperCase()+pp.resize_mode.slice(1)}`;
      } else if (pp.auto_orient || pp.normalize) {
        ppLine = [pp.auto_orient?'Auto-orient':'', pp.normalize?'Normalize':''].filter(Boolean).join(' · ');
      }

      // Version number — extract from name or use index
      const vNum = ver.name.match(/^v?(\d+)/i)?.[1] || (sorted.length - idx);

      const div = document.createElement('div');
      div.className = 'vs-item' + (state.selectedVersionId === ver.id ? ' active' : '');
      div.innerHTML = `
        <div class="vs-item-header">
          <div class="vs-item-vnum">v${vNum}</div>
          ${isCurrent ? '<span class="vs-item-current">current</span>' : ''}
          <div class="vs-item-actions">
            <button class="vs-item-act" title="Download" onclick="event.stopPropagation();app._downloadVersion('${ver.id}')">
              <i class="fas fa-download"></i>
            </button>
            <button class="vs-item-act danger" title="Delete" onclick="event.stopPropagation();app._deleteVersion('${ver.id}')">
              <i class="fas fa-trash-alt"></i>
            </button>
          </div>
        </div>
        <div class="vs-item-name">${this._escHtml(ver.name)}</div>
        <div class="vs-item-ts"><i class="fas fa-clock"></i> ${ver.created_at}</div>
        <div class="vs-item-stats">
          <span class="vs-item-stat"><i class="fas fa-images"></i> ${total.toLocaleString()} images</span>
          <span class="vs-item-stat"><i class="fas fa-tags"></i> ${ver.num_classes||0} classes</span>
        </div>
        <div class="vs-item-split-bar">
          <div class="vs-isb-train" style="width:${sc.train&&total?Math.round(sc.train/total*100):0}%" title="Train"></div>
          <div class="vs-isb-val"   style="width:${sc.valid&&total?Math.round(sc.valid/total*100):0}%" title="Val"></div>
          <div class="vs-isb-test"  style="flex:1" title="Test"></div>
        </div>
        <div class="vs-item-split-nums">
          <span class="train">${sc.train||0} train</span>
          <span class="valid">${sc.valid||0} val</span>
          <span class="test">${sc.test||0} test</span>
        </div>
        ${ppLine ? `<div class="vs-item-pp"><i class="fas fa-sliders-h"></i> ${ppLine}</div>` : ''}
      `;
      div.addEventListener('click', () => {
        state.selectedVersionId = ver.id;
        document.querySelectorAll('.vs-item').forEach(v => v.classList.remove('active'));
        div.classList.add('active');
        this._renderVersionDetail(ver);
      });
      scroll.insertBefore(div, empty);
    });
  },

  _renderVersionDetail(ver) {
    const pane = document.getElementById('vsDetailPane');
    if (!pane) return;
    const sc   = ver.splits || {};
    const pp   = ver.preprocessing || {};
    const augs = ver.augmentations || [];
    const total = ver.total_images || 0;
    const trainN = sc.train || 0, valN = sc.valid || 0, testN = sc.test || 0;
    const trainPct = total ? Math.round(trainN/total*100) : 0;
    const valPct   = total ? Math.round(valN/total*100)   : 0;
    const testPct  = 100 - trainPct - valPct;
    const ppChips = [
      pp.resize_mode && pp.resize_mode !== 'none' ? `${pp.resize_mode} ${pp.resize_w}×${pp.resize_h}` : null,
      pp.auto_orient ? 'Auto-orient' : null,
      pp.normalize   ? 'Normalize'   : null,
    ].filter(Boolean);
    const folderPath = ver.folder_path || '';

    pane.innerHTML = `
      <div class="vs-detail-card">
        <div class="vs-detail-tag"><i class="fas fa-archive"></i> Version</div>
        <div class="vs-detail-name">${this._escHtml(ver.name)}</div>
        <div class="vs-detail-date"><i class="fas fa-clock" style="margin-right:5px"></i>${ver.created_at}</div>
        ${ver.note ? `<div class="vs-detail-note">${this._escHtml(ver.note)}</div>` : ''}
        <div class="vs-detail-grid">
          <div class="vs-dg-item"><div class="vs-dg-val">${total}</div><div class="vs-dg-lbl">Images</div></div>
          <div class="vs-dg-item"><div class="vs-dg-val">${ver.annotated_images||0}</div><div class="vs-dg-lbl">Annotated</div></div>
          <div class="vs-dg-item"><div class="vs-dg-val">${ver.num_classes||0}</div><div class="vs-dg-lbl">Classes</div></div>
          <div class="vs-dg-item"><div class="vs-dg-val">${augs.length}</div><div class="vs-dg-lbl">Augments</div></div>
        </div>
        <div class="vs-split-bar-detail">
          <div class="train" style="width:${trainPct}%"></div>
          <div class="valid" style="width:${valPct}%"></div>
          <div class="test"  style="width:${testPct}%"></div>
        </div>
        <div class="vs-split-legend">
          <span><i class="fas fa-circle" style="color:var(--accent)"></i> Train ${trainN}</span>
          <span><i class="fas fa-circle" style="color:#60a5fa"></i> Val ${valN}</span>
          <span><i class="fas fa-circle" style="color:#c084fc"></i> Test ${testN}</span>
        </div>
        ${ppChips.length ? `<div class="vs-pp-summary">${ppChips.map(c=>`<span class="vs-pp-chip">${c}</span>`).join('')}</div>` : ''}

        <!-- Folder location on disk -->
        <div class="vs-folder-box">
          <div class="vs-folder-head">
            <i class="fas fa-folder-open"></i>
            <span>Saved to disk</span>
            <span class="vs-folder-size" id="vsFolderSize_${ver.id}">loading…</span>
          </div>
          <div class="vs-folder-path" title="${folderPath}">${folderPath || '—'}</div>
          <div class="vs-folder-tree">
            <div class="vs-ftree-line">
              <i class="fas fa-folder" style="color:#60a5fa"></i>
              <span>images/</span>
              <span class="vs-ftree-split train">train/</span>
              <span class="vs-ftree-split valid">val/</span>
              <span class="vs-ftree-split test">test/</span>
            </div>
            <div class="vs-ftree-line">
              <i class="fas fa-folder" style="color:#f59e0b"></i>
              <span>labels/</span>
              <span class="vs-ftree-split train">train/</span>
              <span class="vs-ftree-split valid">valid/</span>
              <span class="vs-ftree-split test">test/</span>
            </div>
            <div class="vs-ftree-line"><i class="fas fa-file-code" style="color:var(--accent)"></i> data.yaml</div>
            <div class="vs-ftree-line"><i class="fas fa-file-alt" style="color:var(--tx3)"></i> README.md</div>
          </div>
        </div>

        <div class="vs-detail-actions">
          <button class="primary-btn" onclick="app._downloadVersion('${ver.id}')">
            <i class="fas fa-download"></i> Download ZIP
          </button>
          <button class="ghost-btn" onclick="app._deleteVersion('${ver.id}')">
            <i class="fas fa-trash-alt"></i> Delete
          </button>
        </div>
      </div>`;

    // Fetch live folder size in background
    if (folderPath) {
      fetch('/api/versions/' + encodeURIComponent(ver.id) + '/info?project=' + encodeURIComponent(state.project))
        .then(r => r.json()).then(d => {
          const el = document.getElementById('vsFolderSize_' + ver.id);
          if (el) el.textContent = d.exists
            ? (d.size_mb + ' MB · ' + d.file_count + ' files')
            : 'Folder missing';
        }).catch(() => {
          const el = document.getElementById('vsFolderSize_' + ver.id);
          if (el) el.textContent = '';
        });
    } else {
      const el = document.getElementById('vsFolderSize_' + ver.id);
      if (el) el.textContent = '';
    }
  },

  // ── Version Wizard ────────────────────────────────────────────
  async _vwOpen() {
    state._vwStep = 1;
    state._vwAugs = [];
    state._vwRatioLocked = false;

    // Auto-name
    const nameEl = document.getElementById('vwName');
    if (nameEl) nameEl.value = `v${(state.versions.length + 1)}.0`;
    const noteEl = document.getElementById('vwNote');
    if (noteEl) noteEl.value = '';

    // Show overlay immediately, then load stats
    const ov = document.getElementById('vwOverlay');
    if (ov) ov.style.display = '';
    if (!this._vwBound) {
      this._vwBound = true;
      this._vwBindEvents();
    }
    this._vwUpdateSliders();
    this._vwRenderAugs();
    this._vwGoToStep(1);

    // Populate stats from Completed Datasets (not Active Work)
    try {
      const [rAnn, rAll] = await Promise.all([
        fetch(`/api/datasets/images?project=${encodeURIComponent(state.project)}&per_page=1&page=1&annotated=yes`),
        fetch(`/api/datasets/images?project=${encodeURIComponent(state.project)}&per_page=1&page=1`),
      ]);
      const dAnn = await rAnn.json();
      const dAll = await rAll.json();
      const annTotal = dAnn.pagination?.total || 0;
      const total    = dAll.pagination?.total || 0;
      const cls      = (state.classes || []).length;
      const unann    = Math.max(0, total - annTotal);
      const setV = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
      setV('vwStatImages', total);
      setV('vwStatAnnotated', annTotal);
      setV('vwStatClasses', cls);
      setV('vwStatUnannotated', unann);
      const notice = document.getElementById('vwUnannoNotice');
      if (notice) notice.style.display = unann > 0 ? '' : 'none';
      this._vwUpdateSliders(); // re-run now we have the real count
    } catch(e) {
      // Fallback to local state
      const total = state.listTotal || state.media.length;
      const ann   = state.annotatedPaths?.size || 0;
      const cls   = (state.classes || []).length;
      const unann = Math.max(0, total - ann);
      const ids   = ['vwStatImages','vwStatAnnotated','vwStatClasses','vwStatUnannotated'];
      const vals  = [total, ann, cls, unann];
      ids.forEach((id, i) => { const el = document.getElementById(id); if (el) el.textContent = vals[i]; });
    }
  },

  _vwClose() {
    const ov = document.getElementById('vwOverlay');
    if (ov) {
      const dr = document.getElementById('vwDrawer');
      if (dr) { dr.style.animation = 'vwSlideOut .2s forwards'; }
      setTimeout(() => {
        if (ov) ov.style.display = 'none';
        if (dr) dr.style.animation = '';
      }, 200);
    }
  },

  _vwBindEvents() {
    document.getElementById('vwClose')?.addEventListener('click', () => this._vwClose());
    document.getElementById('vwBackdrop')?.addEventListener('click', () => this._vwClose());
    document.getElementById('vwBtnBack')?.addEventListener('click', () => this._vwGoToStep(state._vwStep - 1));
    document.getElementById('vwBtnNext')?.addEventListener('click', () => {
      if (state._vwStep === 2 && !this._vwValidateSplit()) return;
      this._vwGoToStep(state._vwStep + 1);
    });
    document.getElementById('vwBtnCreate')?.addEventListener('click', () => this._vwCreate());
    document.getElementById('vwBtnClear')?.addEventListener('click', () => this._vwOpen()); // reset

    // Split sliders
    ['vwTrainSlider','vwValSlider','vwTestSlider'].forEach(id => {
      document.getElementById(id)?.addEventListener('input', () => this._vwUpdateSliders());
    });
    // Split presets
    document.querySelectorAll('.vw-preset').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.vw-preset').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const t = parseInt(btn.dataset.train), v = parseInt(btn.dataset.val), te = parseInt(btn.dataset.test);
        const ts = document.getElementById('vwTrainSlider'); if(ts) ts.value = t;
        const vs = document.getElementById('vwValSlider');   if(vs) vs.value = v;
        const ss = document.getElementById('vwTestSlider');  if(ss) ss.value = te;
        this._vwUpdateSliders();
      });
    });
    // Resize mode
    document.querySelectorAll('.vw-rm-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.vw-rm-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const dimsRow = document.getElementById('vwDims');
        if (dimsRow) dimsRow.style.display = btn.dataset.mode === 'none' ? 'none' : '';
        this._vwUpdateSizeEst();
      });
    });
    // Size presets
    document.querySelectorAll('.vw-size-preset').forEach(btn => {
      btn.addEventListener('click', () => {
        const w = document.getElementById('vwResizeW'), h = document.getElementById('vwResizeH');
        if (w) w.value = btn.dataset.w; if (h) h.value = btn.dataset.h;
        this._vwUpdateSizeEst();
      });
    });
    // Ratio lock
    document.getElementById('vwRatioLock')?.addEventListener('click', () => {
      state._vwRatioLocked = !state._vwRatioLocked;
      document.getElementById('vwRatioLock')?.classList.toggle('locked', state._vwRatioLocked);
      document.getElementById('vwRatioIcon').className = state._vwRatioLocked ? 'fas fa-lock' : 'fas fa-lock-open';
    });
    document.getElementById('vwResizeW')?.addEventListener('input', () => {
      if (state._vwRatioLocked) { document.getElementById('vwResizeH').value = document.getElementById('vwResizeW').value; }
      this._vwUpdateSizeEst();
    });
    document.getElementById('vwResizeH')?.addEventListener('input', () => { this._vwUpdateSizeEst(); });
    // Aug add/picker
    document.getElementById('vwAugAddBtn')?.addEventListener('click', () => {
      const p = document.getElementById('vwAugPicker');
      if (p) p.style.display = p.style.display === 'none' ? '' : 'none';
    });
    document.querySelectorAll('.vw-aug-opt').forEach(btn => {
      btn.addEventListener('click', () => {
        state._vwAugs.push(btn.dataset.aug);
        document.getElementById('vwAugPicker').style.display = 'none';
        this._vwRenderAugs();
      });
    });
    // Steps clickable
    document.querySelectorAll('.vw-step').forEach(s => {
      s.addEventListener('click', () => {
        const target = parseInt(s.dataset.step);
        if (target < state._vwStep) this._vwGoToStep(target);
      });
    });
  },

  _vwGoToStep(n) {
    const total = 5;
    n = Math.max(1, Math.min(total, n));
    state._vwStep = n;

    // Show/hide panels
    for (let i = 1; i <= total; i++) {
      const p = document.getElementById(`vwStep${i}`);
      if (p) p.classList.toggle('active', i === n);
    }
    // Update step indicators
    document.querySelectorAll('.vw-step').forEach(s => {
      const si = parseInt(s.dataset.step);
      s.classList.toggle('active', si === n);
      s.classList.toggle('done',   si < n);
    });
    document.querySelectorAll('.vw-step-line').forEach((l,i) => {
      l.classList.toggle('done', i < n - 1);
    });
    // Footer buttons
    const back   = document.getElementById('vwBtnBack');
    const next   = document.getElementById('vwBtnNext');
    const create = document.getElementById('vwBtnCreate');
    if (back)   back.style.display   = n > 1 ? '' : 'none';
    if (next)   next.style.display   = n < total ? '' : 'none';
    if (create) create.style.display = n === total ? '' : 'none';

    if (n === total) this._vwBuildSummary();
  },

  _vwUpdateSliders() {
    const t = parseInt(document.getElementById('vwTrainSlider')?.value || 70);
    const v = parseInt(document.getElementById('vwValSlider')?.value   || 20);
    const te= parseInt(document.getElementById('vwTestSlider')?.value  || 10);
    // Use annotated count from Completed Datasets (stored in stat card)
    const annEl = document.getElementById('vwStatAnnotated');
    const total = parseInt(annEl?.textContent || '0') || 0;
    const set = (id, val, cnt) => {
      const el = document.getElementById(id); if(el) el.textContent = val+'%';
      const ce = document.getElementById(cnt); if(ce) ce.textContent = Math.round(total * val / 100) + ' imgs';
    };
    set('vwTrainPct','vwTrainCount',  t, 'vwTrainCount');
    document.getElementById('vwTrainPct').textContent   = t+'%';
    document.getElementById('vwTrainCount').textContent = Math.round(total*t/100)+' imgs';
    document.getElementById('vwValPct').textContent     = v+'%';
    document.getElementById('vwValCount').textContent   = Math.round(total*v/100)+' imgs';
    document.getElementById('vwTestPct').textContent    = te+'%';
    document.getElementById('vwTestCount').textContent  = Math.round(total*te/100)+' imgs';
    // Bar
    document.getElementById('vwSbTrain').style.width = t+'%';
    document.getElementById('vwSbVal').style.width   = v+'%';
    document.getElementById('vwSbTest').style.width  = te+'%';
    document.getElementById('vwSbTrainPct').textContent = t+'%';
    document.getElementById('vwSbValPct').textContent   = v+'%';
    document.getElementById('vwSbTestPct').textContent  = te+'%';
    this._vwValidateSplit(false);
  },

  _vwValidateSplit(showToast = true) {
    const t = parseInt(document.getElementById('vwTrainSlider')?.value || 70);
    const v = parseInt(document.getElementById('vwValSlider')?.value   || 20);
    const te= parseInt(document.getElementById('vwTestSlider')?.value  || 10);
    const ok = (t + v + te === 100);
    const err = document.getElementById('vwSplitErr');
    if (err) err.style.display = ok ? 'none' : '';
    if (!ok && showToast) this._toast('Ratios must sum to 100%', 'warn');
    return ok;
  },

  _vwUpdateSizeEst() {
    const w = parseInt(document.getElementById('vwResizeW')?.value || 1280);
    const h = parseInt(document.getElementById('vwResizeH')?.value || 720);
    const total = state.listTotal || state.media.length;
    const bytesPerImg = w * h * 3 * 0.1; // rough JPEG estimate
    const mb = (bytesPerImg * total / 1024 / 1024).toFixed(0);
    const el = document.getElementById('vwSizeEst');
    if (el) el.textContent = `Est. ~${mb} MB for ${total} images`;
  },

  _vwRenderAugs() {
    const list = document.getElementById('vwAugList');
    if (!list) return;
    const icons = {
      flip_h:'fas fa-arrows-alt-h', flip_v:'fas fa-arrows-alt-v',
      rotate90:'fas fa-redo', rotate_range:'fas fa-sync-alt',
      brightness:'fas fa-sun', contrast:'fas fa-adjust',
      blur:'fas fa-eye-slash', grayscale:'fas fa-circle-half-stroke',
      crop:'fas fa-crop-alt', noise:'fas fa-wave-square',
      cutout:'fas fa-square', mosaic:'fas fa-th',
    };
    const labels = {
      flip_h:'Flip Horizontal', flip_v:'Flip Vertical',
      rotate90:'Rotate 90°', rotate_range:'Rotate ±15°',
      brightness:'Brightness Jitter', contrast:'Contrast Jitter',
      blur:'Gaussian Blur', grayscale:'Grayscale',
      crop:'Random Crop', noise:'Add Noise',
      cutout:'Cutout Patch', mosaic:'Mosaic 4×',
    };
    if (!state._vwAugs.length) {
      list.innerHTML = '<div style="font-size:12px;color:var(--tx3);padding:10px 0">No augmentations added. Click "Add Augmentation" to begin.</div>';
      return;
    }
    list.innerHTML = state._vwAugs.map((aug, i) => `
      <div class="vw-aug-item">
        <div class="vw-aug-item-icon"><i class="${icons[aug]||'fas fa-magic'}"></i></div>
        <span class="vw-aug-item-name">${labels[aug]||aug}</span>
        <button class="vw-aug-item-del" onclick="state._vwAugs.splice(${i},1);app._vwRenderAugs()" title="Remove"><i class="fas fa-times"></i></button>
      </div>`).join('');
  },

  _vwBuildSummary() {
    const sum = document.getElementById('vwSummary');
    if (!sum) return;
    const name  = document.getElementById('vwName')?.value || '—';
    const note  = document.getElementById('vwNote')?.value || '';
    const t = parseInt(document.getElementById('vwTrainSlider')?.value || 70);
    const v = parseInt(document.getElementById('vwValSlider')?.value   || 20);
    const te= parseInt(document.getElementById('vwTestSlider')?.value  || 10);
    // Use annotated Completed Datasets count for summary
    const annEl2 = document.getElementById('vwStatAnnotated');
    const total  = parseInt(annEl2?.textContent || '0') || 0;
    const activeMode = document.querySelector('.vw-rm-btn.active')?.dataset?.mode || 'stretch';
    const w = document.getElementById('vwResizeW')?.value || 1280;
    const h = document.getElementById('vwResizeH')?.value || 720;
    const ao = document.getElementById('vwAutoOrient')?.checked;
    const no = document.getElementById('vwNormalize')?.checked;
    const augs = state._vwAugs || [];

    const row = (k, v2) => `<div class="vw-sum-row"><span class="vw-sum-key">${k}</span><span class="vw-sum-val">${v2}</span></div>`;
    sum.innerHTML = `
      <div class="vw-sum-section">
        <div class="vw-sum-title"><i class="fas fa-tag"></i> Version Info</div>
        ${row('Name', name)}
        ${note ? row('Notes', note) : ''}
        ${row('Source', 'Completed Datasets only')}
        ${row('Images in version', total)}
        ${row('Classes', (state.classes||[]).length)}
      </div>
      <div class="vw-sum-section">
        <div class="vw-sum-title"><i class="fas fa-sitemap"></i> Split</div>
        ${row('Train', `${t}% · ${Math.round(total*t/100)} images`)}
        ${row('Validation', `${v}% · ${Math.round(total*v/100)} images`)}
        ${row('Test', `${te}% · ${Math.round(total*te/100)} images`)}
      </div>
      <div class="vw-sum-section">
        <div class="vw-sum-title"><i class="fas fa-sliders-h"></i> Preprocessing</div>
        ${row('Resize mode', activeMode === 'none' ? 'No resize' : `${activeMode} → ${w}×${h}`)}
        ${row('Auto-orient', ao ? 'Yes' : 'No')}
        ${row('Normalize', no ? 'Yes' : 'No')}
      </div>
      ${augs.length ? `<div class="vw-sum-section"><div class="vw-sum-title"><i class="fas fa-magic"></i> Augmentations (${augs.length})</div>${augs.map(a=>row('',a)).join('')}</div>` : ''}
    `;
  },

  async _vwCreate() {
    if (!this._vwValidateSplit()) return;
    const btn = document.getElementById('vwBtnCreate');
    if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i> Creating…'; }

    const name  = document.getElementById('vwName')?.value.trim() || `v${(state.versions.length+1)}.0`;
    const note  = document.getElementById('vwNote')?.value.trim() || '';
    const t     = parseInt(document.getElementById('vwTrainSlider')?.value || 70) / 100;
    const v     = parseInt(document.getElementById('vwValSlider')?.value   || 20) / 100;
    const te    = parseInt(document.getElementById('vwTestSlider')?.value  || 10) / 100;
    const shuffle = document.getElementById('vwShuffle')?.checked ?? true;
    const mode  = document.querySelector('.vw-rm-btn.active')?.dataset?.mode || 'stretch';
    const w     = parseInt(document.getElementById('vwResizeW')?.value || 1280);
    const h     = parseInt(document.getElementById('vwResizeH')?.value || 720);
    const ao    = document.getElementById('vwAutoOrient')?.checked ?? true;
    const norm  = document.getElementById('vwNormalize')?.checked  ?? false;

    const payload = {
      project: state.project, name, note,
      split_ratio:    { train: t, val: v, test: te, shuffle },
      preprocessing:  { resize_mode: mode, resize_w: w, resize_h: h, auto_orient: ao, normalize: norm },
      augmentations:  state._vwAugs || [],
    };

    try {
      const r = await fetch('/api/versions', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify(payload),
      });
      const d = await r.json();
      if (d.success) {
        this._vwClose();
        this._toast(`Version "${name}" created — ${d.version?.total_images||0} images`, 'success');
        await this._loadVersionsPage();
        // Auto-select new version
        const newVer = state.versions.find(v2 => v2.id === d.version?.id);
        if (newVer) {
          state.selectedVersionId = newVer.id;
          this._renderVersionsList();
          this._renderVersionDetail(newVer);
        }
      } else {
        this._toast(d.error || 'Failed to create version', 'error');
      }
    } catch(e) {
      this._toast('Network error creating version', 'error');
    } finally {
      if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-archive"></i> Create Version'; }
    }
  },

  async _deleteVersion(id) {
    if (!confirm('Delete this version permanently?')) return;
    try {
      await fetch('/api/versions', { method:'DELETE', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ project: state.project, id }) });
      if (state.selectedVersionId === id) {
        state.selectedVersionId = null;
        const p = document.getElementById('vsDetailPane');
        if (p) p.innerHTML = '';
      }
      await this._loadVersionsPage();
      this._toast('Version deleted', 'success');
    } catch(e) { this._toast('Delete failed', 'error'); }
  },

  async _downloadVersion(id) {
    if (!id) { this._toast('No version selected', 'warn'); return; }
    this._toast('Preparing download…', 'info');
    const url = `/api/versions/${encodeURIComponent(id)}/download?project=${encodeURIComponent(state.project)}`;
    const a = document.createElement('a');
    a.href = url;
    a.download = '';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  },

  /* ═══ CLASSES PAGE ═══════════════════════════════════════════ */
  async _loadClassesPage() {
    try {
      const r = await fetch(`/api/stats?project=${encodeURIComponent(state.project)}`);
      const d = await r.json();
      state.clsPageStats = {};
      (d.class_counts || []).forEach(cc => { state.clsPageStats[cc.id] = {count:cc.count, images:cc.images}; });
    } catch(e) { state.clsPageStats = {}; }
    this._renderClassesTable();
    if (!this._classesBound) {
      this._classesBound = true;
      document.getElementById('clsPageColor')?.addEventListener('input', e => {
        const sw = document.getElementById('clsPageColorSwatch'); if (sw) sw.style.background = e.target.value;
      });
      document.getElementById('clsPageAddBtn')?.addEventListener('click', () => this._clsPageAdd());
      document.getElementById('clsPageName')?.addEventListener('keydown', e => { if (e.key === 'Enter') this._clsPageAdd(); });
      document.getElementById('clsPageExportBtn')?.addEventListener('click', () => {
        const text = state.classes.map(c => c.name).join('\n');
        const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(new Blob([text], {type:'text/plain'})), download: 'classes.txt' });
        a.click(); this._toast('Exported classes.txt', 'success');
      });
      document.getElementById('clsPageSyncBtn')?.addEventListener('click', async () => {
        try { await fetch('/api/classes/sync', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({project: state.project}) }); this._toast('Synced data.yaml', 'success'); }
        catch(e) { this._toast('Sync failed', 'warn'); }
      });
    }
  },

  /* ═══════════════════════════════════════════════════════════════
     PROJECTS PAGE
  ═══════════════════════════════════════════════════════════════ */

  async _loadProjectsPage() {
    // Bind UI events once (idempotent guard on each element via dataset flag)
    this._bindProjectsPage();
    try {
      const r = await fetch('/api/workspace/folders');
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const folders = await r.json();
      this._renderProjectsPage(folders);
    } catch(e) {
      console.warn('loadProjectsPage failed', e);
      this._renderProjectsPage([]);
    }
  },

  _bindProjectsPage() {
    // Use a flag on the overlay element to ensure we only attach listeners once
    const overlay = document.getElementById('projModalOverlay');
    if (!overlay || overlay.dataset.bound === '1') return;
    overlay.dataset.bound = '1';

    const openModal = () => {
      overlay.style.display = 'flex';
      const inp = document.getElementById('projModalNameInput');
      if (inp) inp.value = '';
      const errEl = document.getElementById('projModalError');
      if (errEl) errEl.textContent = '';
      const prev = document.getElementById('projCoverPreview');
      if (prev) prev.innerHTML = `<i class="fas fa-image"></i><span>Click to set cover image (optional)</span>`;
      this._projModalCoverBlob = null;
      setTimeout(() => document.getElementById('projModalNameInput')?.focus(), 60);
    };
    const closeModal = () => {
      overlay.style.display = 'none';
      this._projModalCoverBlob = null;
      const btn = document.getElementById('projModalConfirm');
      if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-check"></i> Create Project'; }
    };

    document.getElementById('projCreateBtn')?.addEventListener('click', openModal);
    document.getElementById('projEmptyCreateBtn')?.addEventListener('click', openModal);
    document.getElementById('projModalClose')?.addEventListener('click', closeModal);
    document.getElementById('projModalCancel')?.addEventListener('click', closeModal);
    overlay.addEventListener('click', e => { if (e.target === overlay) closeModal(); });

    // Cover image picker in modal
    const coverPicker = document.getElementById('projCoverPicker');
    const coverFile   = document.getElementById('projCoverFile');
    coverPicker?.addEventListener('click', () => coverFile?.click());
    coverFile?.addEventListener('change', e => {
      const file = e.target.files[0];
      if (!file) return;
      this._projModalCoverBlob = file;
      const reader = new FileReader();
      reader.onload = ev => {
        const prev = document.getElementById('projCoverPreview');
        if (!prev) return;
        prev.innerHTML = `
          <img src="${ev.target.result}" alt="">
          <div class="proj-cover-change-hint"><i class="fas fa-camera"></i> Change cover</div>`;
      };
      reader.readAsDataURL(file);
      coverFile.value = '';
    });

    // Create project
    const doCreate = async () => {
      const nameInp = document.getElementById('projModalNameInput');
      const errEl   = document.getElementById('projModalError');
      const btn     = document.getElementById('projModalConfirm');
      const name    = nameInp?.value.trim();
      if (!name) { if (errEl) errEl.textContent = 'Project name is required.'; return; }
      if (!/^[a-zA-Z0-9_\-. ]+$/.test(name)) {
        if (errEl) errEl.textContent = 'Use only letters, numbers, spaces, hyphens, underscores.';
        return;
      }
      if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i> Creating…'; }
      if (errEl) errEl.textContent = '';
      try {
        const r = await fetch('/api/projects', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({name})
        });
        const d = await r.json();
        if (!r.ok || d.error) {
          if (errEl) errEl.textContent = d.error || 'Failed to create project.';
          if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-check"></i> Create Project'; }
          return;
        }
        // Upload cover if one was selected
        if (this._projModalCoverBlob) {
          try {
            const fd = new FormData();
            fd.append('file', this._projModalCoverBlob);
            const cr = await fetch(`/api/projects/${encodeURIComponent(name)}/cover`, { method:'POST', body: fd });
            if (!cr.ok) console.warn('Cover upload failed:', cr.status);
          } catch(coverErr) { console.warn('Cover upload error:', coverErr); }
        }
        closeModal();
        await this._switchProject(name);      // sets state.project = name, persists server-side
        await this._loadProjectsPage();       // re-render with new project visible + active
        this._updateNavBadges();
        this._toast(`Project "${name}" created`, 'success');
      } catch(err) {
        if (errEl) errEl.textContent = 'Network error — please try again.';
        if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-check"></i> Create Project'; }
      }
    };

    document.getElementById('projModalConfirm')?.addEventListener('click', doCreate);
    document.getElementById('projModalNameInput')?.addEventListener('keydown', e => {
      if (e.key === 'Enter') doCreate();
      if (e.key === 'Escape') closeModal();
    });

    // Live search filter (use event delegation on the grid body)
    document.getElementById('projSearchInput')?.addEventListener('input', () => {
      const q = document.getElementById('projSearchInput').value.toLowerCase().trim();
      document.querySelectorAll('.proj-card').forEach(card => {
        const n = (card.dataset.projName || '').toLowerCase();
        card.style.display = (!q || n.includes(q)) ? '' : 'none';
      });
    });
  },

  _renderProjectsPage(folders) {
    const grid    = document.getElementById('projGrid');
    const empty   = document.getElementById('projEmpty');
    const countEl = document.getElementById('projPageCount');
    const badge   = document.getElementById('rnProjectsBadge');
    if (!grid) return;

    if (badge)   badge.textContent   = folders.length;
    if (countEl) countEl.textContent = folders.length;

    grid.innerHTML = '';

    if (!folders.length) {
      if (empty) empty.style.display = 'flex';
      return;
    }
    if (empty) empty.style.display = 'none';

    // Cache-bust token generated once per render cycle
    const cb = Date.now();

    folders.forEach(f => {
      const isActive = (f.name === state.project);
      const pct      = f.total > 0 ? Math.round(f.annotated / f.total * 100) : 0;
      // Use no-cache cover URL; always fresh because of the render-time cb token
      const coverSrc = f.has_cover
        ? `/api/projects/${encodeURIComponent(f.name)}/cover?cb=${cb}`
        : null;

      const card = document.createElement('div');
      card.className = 'proj-card' + (isActive ? ' active-proj' : '');
      card.dataset.projName = f.name;

      const thumbInner = coverSrc
        ? `<img src="${coverSrc}" alt="${this._escHtml(f.name)}">`
        : `<div class="proj-card-thumb-placeholder"><i class="fas fa-folder-open"></i><span class="proj-thumb-hint">Open project → Annotate → Set as Cover</span></div>`;

      card.innerHTML = `
        <div class="proj-card-thumb">
          ${thumbInner}
          ${isActive ? '<div class="proj-card-active-badge"><i class="fas fa-check-circle"></i> Active</div>' : ''}
        </div>
        <div class="proj-card-body">
          <div class="proj-card-name" title="${this._escHtml(f.name)}">${this._escHtml(f.name)}</div>
          <div class="proj-card-meta">
            <div class="proj-card-meta-row">
              <i class="fas fa-images"></i>
              <span class="val">${f.total}</span>&nbsp;images&nbsp;·&nbsp;<span class="val">${f.annotated}</span>&nbsp;annotated
            </div>
            <div class="proj-card-meta-row">
              <i class="fas fa-clock"></i>
              ${this._escHtml(f.last_modified || '—')}
            </div>
          </div>
          <div class="proj-card-progress">
            <div class="proj-card-progress-fill" style="width:${pct}%"></div>
          </div>
        </div>
        <div class="proj-card-footer">
          <button class="proj-card-open-btn">
            <i class="fas fa-${isActive ? 'pencil-alt' : 'folder-open'}"></i>
            ${isActive ? 'Annotate' : 'Open'}
          </button>
          <button class="proj-card-del-btn" title="Delete project">
            <i class="fas fa-trash-alt"></i>
          </button>
        </div>`;

      // ── Click card body → open project ──────────────────────────────
      card.querySelector('.proj-card-body').addEventListener('click', () => {
        this._projOpenProject(f.name);
      });
      card.querySelector('.proj-card-open-btn').addEventListener('click', e => {
        e.stopPropagation();
        this._projOpenProject(f.name);
      });

      // ── Delete ───────────────────────────────────────────────────────
      card.querySelector('.proj-card-del-btn').addEventListener('click', async e => {
        e.stopPropagation();
        if (!confirm(`Delete project "${f.name}" and ALL its data?\nThis cannot be undone.`)) return;
        try {
          const dr = await fetch('/api/projects', {
            method: 'DELETE',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name: f.name})
          });
          if (!dr.ok) throw new Error(`HTTP ${dr.status}`);
          if (state.project === f.name) {
            const remaining = folders.filter(x => x.name !== f.name);
            if (remaining.length) await this._switchProject(remaining[0].name);
            else { window.location.reload(); return; }
          }
          await this._loadProjectsPage();
          this._updateNavBadges();
          this._toast(`Project "${f.name}" deleted`, 'success');
        } catch(e2) { this._toast('Failed to delete project', 'error'); }
      });

      grid.appendChild(card);
    });   // end folders.forEach
  },    // end _renderProjectsPage

  async _projOpenProject(name) {
    await this._switchProject(name);
    // Navigate to annotate immediately — don't block on grid refresh
    this.showPage('annotate');
    // Refresh projects grid in background so active badge is correct on return
    this._loadProjectsPage().catch(() => {});
  },

  _renderClassesTable() {
    const body = document.getElementById('clsPageTableBody');
    if (!body) return;
    if (!state.classes.length) {
      body.innerHTML = '<div class="cls-table-empty"><i class="fas fa-tags"></i><p style="margin-top:6px;color:var(--tx2)">No classes yet — add one above.</p></div>';
      return;
    }
    body.innerHTML = state.classes.map(cls => {
      const [r,g,b] = cls.color;
      const hex = '#' + [r,g,b].map(v => v.toString(16).padStart(2,'0')).join('');
      const st  = state.clsPageStats[cls.id] || {count:0, images:0};
      return `<div class="cls-table-row">
        <div class="color-picker-wrap"><div class="ct-swatch" style="background:rgb(${r},${g},${b})"></div><input type="color" value="${hex}" onchange="app._clsPageChangeColor(${cls.id},this.value)"></div>
        <div class="ct-name"><input type="text" value="${cls.name}" onblur="app._clsPageRename(${cls.id},this.value)" onkeydown="if(event.key==='Enter')this.blur()"></div>
        <div class="ct-id">${cls.id}</div>
        <div class="ct-count">${st.count}</div>
        <div class="ct-count" style="color:var(--tx2)">${st.images}</div>
        <div class="ct-actions"><button class="ct-btn danger" onclick="app.deleteClass(${cls.id})"><i class="fas fa-trash-alt"></i></button></div>
      </div>`;
    }).join('');
  },

  async _clsPageAdd() {
    const ni = document.getElementById('clsPageName'), ci = document.getElementById('clsPageColor');
    const name = ni?.value.trim();
    if (!name) return;
    const hex = ci?.value || '#FF3B3B';
    const r = parseInt(hex.slice(1,3),16), g = parseInt(hex.slice(3,5),16), b = parseInt(hex.slice(5,7),16);
    const newId = state.classes.length ? Math.max(...state.classes.map(c=>c.id)) + 1 : 0;
    try {
      const res = await fetch('/api/classes', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({project:state.project, name, color:[r,g,b], id:newId}) });
      const d   = await res.json();
      if (d.success) { state.classes.push({id:newId, name, color:[r,g,b]}); if(ni) ni.value=''; this._populateClassList(); this._renderClassesTable(); this._updateNavBadges(); this._toast(`Class "${name}" added`, 'success'); }
    } catch(e) { this._toast('Failed to add class', 'error'); }
  },

  async _clsPageRename(id, newName) {
    newName = newName.trim();
    const cls = state.classes.find(c => c.id === id);
    if (!cls || !newName || cls.name === newName) return;
    try { await fetch('/api/classes/rename', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({project:state.project, id, name:newName}) }); cls.name = newName; this._populateClassList(); this._renderClassesTable(); this._toast(`Renamed to "${newName}"`, 'success'); }
    catch(e) { this._toast('Rename failed', 'error'); }
  },

  async _clsPageChangeColor(id, hex) {
    const r = parseInt(hex.slice(1,3),16), g = parseInt(hex.slice(3,5),16), b = parseInt(hex.slice(5,7),16);
    const cls = state.classes.find(c => c.id === id);
    if (!cls) return;
    cls.color = [r,g,b];
    try { await fetch('/api/classes/color', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({project:state.project, id, color:[r,g,b]}) }); } catch(e) {}
    this._populateClassList(); this._renderClassesTable(); this._render();
  },

  /* ═══ ADD CLASS FROM POPUP ══════════════════════════════════ */
  async _cpAddNewClass() {
    const inp = document.getElementById('cpNewClsName');
    const name = inp?.value.trim();
    if (!name) { this._toast('Enter a class name', 'warn'); return; }
    if (state.classes.find(c => c.name.toLowerCase() === name.toLowerCase())) {
      this._toast('Class already exists', 'warn'); return;
    }
    const newId = state.classes.length ? Math.max(...state.classes.map(c => c.id)) + 1 : 0;
    const color = CLASS_PALETTE[newId % CLASS_PALETTE.length];
    try {
      const res = await fetch('/api/classes', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({project: state.project, name, color, id: newId})
      });
      const d = await res.json();
      if (d.success) {
        state.classes.push({id: newId, name, color});
        state.selectedCls = newId;
        this._populateClassList();
        this._renderClassesTable && this._renderClassesTable();
        this._updateNavBadges();
        this._populatePopupList(document.getElementById('cpSearch')?.value || '');
        const form = document.getElementById('cpAddClsForm');
        if (form) form.style.display = 'none';
        if (inp) inp.value = '';
        this._toast(`"${name}" added & selected`, 'success');
      }
    } catch(e) { this._toast('Failed to add class', 'error'); }
  },

  /* ═══ UPLOAD PAGE ════════════════════════════════════════════ */
  _initUploadPage() {
    // Update center label
    const centerLabel = document.getElementById('upCenterProjectLabel');
    if (centerLabel) centerLabel.textContent = state.project;

    // Load all panels
    this._loadProjectsPanel();
    this._loadUploadBatches();
    this._loadCompletedDatasets();

    // Bind refresh buttons safely (clone to avoid duplicate listeners)
    ['upActiveRefreshBtn', 'upDsRefreshBtn'].forEach(id => {
      const btn = document.getElementById(id);
      if (!btn) return;
      const clone = btn.cloneNode(true);
      btn.parentNode.replaceChild(clone, btn);
    });
    document.getElementById('upActiveRefreshBtn')?.addEventListener('click', () => {
      this._manualRefresh();
    });
    document.getElementById('upDsRefreshBtn')?.addEventListener('click', () => {
      this._loadCompletedDatasets();
    });

    // Bind project panel buttons (only once)
    if (!this._uploadPageBound) {
      this._uploadPageBound = true;
      this._bindProjectPanel();
    }

    // Start auto-refresh
    this._startAutoRefresh();
  },

  // ── Project panel ──────────────────────────────────────────────────────────
  _bindProjectPanel() {
    const newBtn     = document.getElementById('upNewProjectBtn');
    const form       = document.getElementById('upNewProjForm');
    const nameInp    = document.getElementById('upNewProjName');
    const confirmBtn = document.getElementById('upNewProjConfirm');
    const cancelBtn  = document.getElementById('upNewProjCancel');
    let projFormOpen = false;

    newBtn?.addEventListener('click', () => {
      projFormOpen = !projFormOpen;
      form.style.display = projFormOpen ? '' : 'none';
      if (projFormOpen) setTimeout(() => nameInp?.focus(), 50);
    });

    const doCreate = async () => {
      const name = nameInp?.value.trim();
      if (!name) { this._toast('Enter a project name', 'warn'); return; }
      try {
        const r = await fetch('/api/projects', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({name})
        });
        const d = await r.json();
        if (d.success) {
          if (nameInp) nameInp.value = '';
          projFormOpen = false;
          form.style.display = 'none';
          await this._switchProject(name);
          this._toast(`Project "${name}" created`, 'success');
        }
      } catch(e) { this._toast('Failed to create project', 'error'); }
    };

    confirmBtn?.addEventListener('click', doCreate);
    nameInp?.addEventListener('keydown', e => {
      if (e.key === 'Enter') doCreate();
      if (e.key === 'Escape') { form.style.display = 'none'; projFormOpen = false; }
    });
    cancelBtn?.addEventListener('click', () => { form.style.display = 'none'; projFormOpen = false; });
  },

  async _loadProjectsPanel() {
    try {
      const r = await fetch('/api/workspace/folders');
      const folders = await r.json();
      this._renderProjectsPanel(folders);
    } catch(e) { console.warn('loadProjectsPanel failed', e); }
  },

  _renderProjectsPanel(folders) {
    const list  = document.getElementById('upProjList');
    const badge = document.getElementById('upProjectCount');
    if (!list) return;
    if (badge) badge.textContent = folders.length;
    list.innerHTML = '';
    if (!folders.length) {
      list.innerHTML = '<div class="up-proj-empty-hint"><i class="fas fa-folder-open"></i> No projects yet</div>';
      return;
    }
    folders.forEach(f => {
      const isActive = f.name === state.project;
      const pct = f.total > 0 ? Math.round(f.annotated / f.total * 100) : 0;
      const el = document.createElement('div');
      el.className = 'up-proj-item' + (isActive ? ' active' : '');
      el.innerHTML = `
        <i class="fas fa-folder${isActive ? '-open' : ''}"></i>
        <span class="up-proj-item-name" title="${this._escHtml(f.name)}">${this._escHtml(f.name)}</span>
        <div class="up-proj-item-meta">
          <span class="up-proj-item-counts">${f.annotated}/${f.total}</span>
          <div class="up-proj-item-progress">
            <div class="up-proj-item-progress-fill" style="width:${pct}%"></div>
          </div>
        </div>
        <button class="up-proj-del-btn" title="Delete project"><i class="fas fa-trash-alt"></i></button>`;
      el.addEventListener('click', e => {
        if (e.target.closest('.up-proj-del-btn')) return;
        this._switchProject(f.name);
      });
      el.querySelector('.up-proj-del-btn').addEventListener('click', async e => {
        e.stopPropagation();
        const nm = f.name;
        if (!confirm(`Delete project "${nm}" and ALL its data? This cannot be undone.`)) return;
        try {
          await fetch('/api/projects', {
            method: 'DELETE', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name: nm})
          });
          if (state.project === nm) {
            const remaining = folders.filter(x => x.name !== nm);
            if (remaining.length) await this._switchProject(remaining[0].name);
            else window.location.reload();
          } else {
            await this._loadProjectsPanel();
          }
          this._toast(`Project "${nm}" deleted`, 'success');
        } catch(e2) { this._toast('Failed to delete project', 'error'); }
      });
      list.appendChild(el);
    });
  },

  // ── Unified project switch ─────────────────────────────────────────────────
  async _switchProject(name) {
    const isSame = (name === state.project);

    // Update state immediately so UI feels responsive
    state.project       = name;
    state.currentIdx    = -1;
    state.bboxes        = [];
    state.media         = [];
    state.filteredMedia = [];
    state.listPage      = 1;    // always start from page 1 on project switch
    state.listTotalDatasetImages = 0;
    state.activeJobId   = null; // clear any job lock on project switch
    state.activeJobId   = null; // clear any job lock on project switch
    state.activeJobName = '';

    if (!isSame) {
      state.classes = [];
      this._populateClassList();
    }

    // Sync dropdowns + labels instantly (no network needed)
    this._syncProjectDropdowns(name);
    const cl = document.getElementById('upCenterProjectLabel');
    if (cl) cl.textContent = name;

    // Persist active project (fire-and-forget, non-blocking)
    fetch('/api/app-state', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ last_active_project: name })
    }).catch(() => {});

    // ── Critical path: load media for the annotate page ─────────────────────
    await this._loadMedia();
    this._updateHeaderBreadcrumb();
    this._updateNavBadges();

    if (!isSame) {
      this._toast(`Switched to "${name}"`, 'info');
    }

    // ── Deferred: refresh side-panels in background (don't block navigation) ─
    // Only refresh panels that are currently visible to the user
    Promise.all([
      this._loadProjectsPanel(),
      state.currentPage === 'upload' ? this._loadUploadBatches() : Promise.resolve(),
      state.currentPage === 'upload' ? this._loadCompletedDatasets() : Promise.resolve(),
    ]).catch(() => {});
  },

  // Keeps header select + right-nav select in sync with current project
  _syncProjectDropdowns(name) {
    ['projectSelect', 'rnProjectSelect'].forEach(id => {
      const sel = document.getElementById(id);
      if (!sel) return;
      if (!Array.from(sel.options).find(o => o.value === name)) {
        const opt = document.createElement('option');
        opt.value = name; opt.textContent = name;
        sel.appendChild(opt);
      }
      sel.value = name;
    });
    const inp = document.getElementById('upPageProjectName');
    if (inp) inp.value = name;
    // Update rnProjectName if it still exists (legacy)
    const rnName = document.getElementById('rnProjectName');
    if (rnName) rnName.textContent = name;
  },

  // Right-nav project panel wiring
  _initRightNavProjectPanel() {
    const sel      = document.getElementById('rnProjectSelect');
    const newBtn   = document.getElementById('rnNewProjectBtn');
    const delBtn   = document.getElementById('rnDeleteProjectBtn');
    const form     = document.getElementById('rnProjCreateForm');
    const nameInp  = document.getElementById('rnNewProjName');
    const confirm_ = document.getElementById('rnProjConfirmBtn');
    const cancel_  = document.getElementById('rnProjCancelBtn');

    sel?.addEventListener('change', async e => {
      await this._switchProject(e.target.value);
    });

    let formOpen = false;
    newBtn?.addEventListener('click', () => {
      formOpen = !formOpen;
      form.style.display = formOpen ? '' : 'none';
      if (formOpen) setTimeout(() => nameInp?.focus(), 50);
    });

    const doCreate = async () => {
      const name = nameInp?.value.trim();
      if (!name) { this._toast('Enter a project name', 'warn'); return; }
      try {
        const r = await fetch('/api/projects', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({name})
        });
        const d = await r.json();
        if (d.success) {
          if (nameInp) nameInp.value = '';
          formOpen = false;
          if (form) form.style.display = 'none';
          await this._switchProject(name);
          this._toast(`Project "${name}" created`, 'success');
        }
      } catch(e) { this._toast('Failed to create project', 'error'); }
    };

    confirm_?.addEventListener('click', doCreate);
    nameInp?.addEventListener('keydown', e => {
      if (e.key === 'Enter') doCreate();
      if (e.key === 'Escape') { form.style.display = 'none'; formOpen = false; }
    });
    cancel_?.addEventListener('click', () => { form.style.display = 'none'; formOpen = false; });

    delBtn?.addEventListener('click', () => this._deleteProject());
  },

  // ── Auto-refresh ───────────────────────────────────────────────────────────
  _startAutoRefresh() {
    this._stopAutoRefresh();
    const dot = document.getElementById('upAutoRefreshDot');
    if (dot) dot.classList.add('active');
    this._arLastBatchCount = state._uploadBatches?.length ?? -1;
    this._arLastBatchTotal = (state._uploadBatches || []).reduce((s, b) => s + (b.total || 0), 0);
    this._arInterval = setInterval(() => this._autoRefreshTick(), 4000);
  },

  _stopAutoRefresh() {
    if (this._arInterval) { clearInterval(this._arInterval); this._arInterval = null; }
    const dot = document.getElementById('upAutoRefreshDot');
    if (dot) dot.classList.remove('active');
  },

  async _autoRefreshTick() {
    if (state.currentPage !== 'upload') { this._stopAutoRefresh(); return; }
    try {
      const r = await fetch(`/api/uploads?project=${encodeURIComponent(state.project)}`);
      if (!r.ok) return;
      const batches = await r.json();
      const currCount = batches.length;
      const currTotal = batches.reduce((s, b) => s + (b.total || 0), 0);
      const changed   = currCount !== this._arLastBatchCount || currTotal !== this._arLastBatchTotal;
      this._arLastBatchCount = currCount;
      this._arLastBatchTotal = currTotal;
      if (changed) {
        this._renderUploadBatches(batches);
        this._loadCompletedDatasets();
        await this._loadMedia();
        this._updateNavBadges();
      }
    } catch(e) { /* silent */ }
  },

  async _manualRefresh() {
    const btn = document.getElementById('upActiveRefreshBtn');
    if (btn) { const i = btn.querySelector('i'); if (i) i.style.animation = 'fa-spin 0.5s linear'; }
    await this._loadUploadBatches();
    await this._loadMedia();
    this._updateNavBadges();
    setTimeout(() => {
      const btn2 = document.getElementById('upActiveRefreshBtn');
      const i2 = btn2?.querySelector('i'); if (i2) i2.style.animation = '';
    }, 500);
  },

  // ════════════════════════════════════════════════════════════════════
  //  UPLOAD BATCH SYSTEM  (projects/<n>/job_N/images + labels)
  // ════════════════════════════════════════════════════════════════════

  async _loadUploadBatches() {
    try {
      const r = await fetch(`/api/uploads?project=${encodeURIComponent(state.project)}`);
      if (!r.ok) return;
      this._renderUploadBatches(await r.json());
    } catch(e) { console.warn('loadUploadBatches failed', e); }
  },

  _renderUploadBatches(batches) {
    state._uploadBatches = batches;   // cache for modal info lookup
    const list  = document.getElementById('uhpList');
    const empty = document.getElementById('uhpEmpty');
    const badge = document.getElementById('upActiveCount');
    if (!list) return;
    Array.from(list.querySelectorAll('.uhp-batch-card')).forEach(c => c.remove());

    // Filter out batches that are fully complete:
    // all images annotated AND already added to a dataset AND no raw images left
    const activeBatches = (batches || []).filter(b => {
      const total    = b.total     || 0;
      const pending  = b.pending !== undefined ? b.pending : (b.unannotated || 0);
      const inDs     = !!b.in_dataset;
      // Hide only when: added to dataset AND nothing left to annotate
      if (inDs && total > 0 && pending === 0 && (b.null_count || 0) === 0) return false;
      return true;
    });

    if (badge) badge.textContent = activeBatches.length;
    if (!activeBatches.length) {
      if (empty) empty.style.display = '';
      this._updateJobStats('', 0, 0, 0);
      return;
    }
    if (empty) empty.style.display = 'none';
    [...activeBatches].sort((a,b) => b.upload_id - a.upload_id)
                      .forEach(b => list.appendChild(this._buildBatchCard(b)));

    // Show stats for the most-recently-uploaded active batch
    const latest = [...activeBatches].sort((a,b) => b.upload_id - a.upload_id)[0];
    if (latest) {
      this._updateJobStats(
        latest.job_name    || '',
        latest.total       || 0,
        latest.annotated   || 0,
        latest.unannotated || 0
      );
    }
  },

  _buildBatchCard(batch) {
    const srcIcon = {images:'fas fa-images', folder:'fas fa-folder-open', zip:'fas fa-file-archive', video:'fas fa-film'};
    const icon    = srcIcon[batch.source] || 'fas fa-images';
    const preAnn  = batch.annotated  || 0;
    const nullCnt = batch.null_count || 0;
    const pending = batch.pending !== undefined ? batch.pending : (batch.unannotated || 0);
    const total   = batch.total || 0;
    const pct     = total > 0 ? Math.round((preAnn + nullCnt) / total * 100) : 0;
    const inDs    = !!batch.in_dataset;
    const cls     = batch.cls_names || [];

    // Parse readable date/time — try datetime_str first (2024-03-21_14-23-45), then uploaded_at, then label
    let dayStr = '', timeStr = '';
    const rawDt = batch.datetime_str || batch.uploaded_at || '';
    const dtParts = rawDt.match(/(\d{4})-(\d{2})-(\d{2})[_T](\d{2})[-:](\d{2})[-:](\d{2})/);
    if (dtParts) {
      const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
      const h = parseInt(dtParts[4]), mn = dtParts[5];
      const ampm = h < 12 ? 'AM' : 'PM';
      dayStr  = `${months[parseInt(dtParts[2])-1]} ${parseInt(dtParts[3])}, ${dtParts[1]}`;
      timeStr = `${h%12||12}:${mn} ${ampm}`;
    } else {
      // fallback: parse "Uploaded on MM/DD/YY at H:MM AM/PM"
      const lm = (batch.label||'').match(/(\d{2})\/(\d{2})\/(\d{2}) at (\d+):(\d{2}) (AM|PM)/);
      if (lm) { dayStr = `${lm[1]}/${lm[2]}/${lm[3]}`; timeStr = `${lm[4]}:${lm[5]} ${lm[6]}`; }
      else { dayStr = batch.label || `Batch #${batch.upload_id}`; timeStr = ''; }
    }

    const srcLabel = (batch.source || 'images').toUpperCase();
    const srcColor = {FOLDER:'#f59e0b', ZIP:'#818cf8', VIDEO:'#a855f7', IMAGES:'#22c5e1'}[srcLabel] || '#22c5e1';
    const splits   = batch.source_splits || {};

    const card = document.createElement('div');
    card.className = 'uhp-batch-card';
    card.dataset.uploadId = batch.upload_id;

    card.innerHTML = `
      <div class="uhp-card-head">
        <div class="uhp-card-icon ${batch.source||'images'}"><i class="${icon}"></i></div>
        <div class="uhp-card-meta">
          <div class="uhp-card-daystr">${this._escHtml(dayStr)}</div>
          <div class="uhp-card-timestr">${this._escHtml(timeStr)}</div>
          <div class="uhp-card-badges">
            <span class="uhp-src-badge" style="background:${srcColor}22;color:${srcColor};border-color:${srcColor}44">${srcLabel}</span>
            ${inDs ? '<span class="uhp-ds-badge"><i class="fas fa-check-circle"></i> In Dataset</span>' : ''}
          </div>
        </div>
        <div class="uhp-card-actions-col">
          <button class="uhp-card-del" title="Delete batch"><i class="fas fa-trash-alt"></i></button>
          <div class="uhp-card-click-hint"><i class="fas fa-mouse-pointer"></i></div>
        </div>
      </div>

      <div class="uhp-folder-breakdown">
        ${total > 0 ? `
        <div class="uhp-anno-progress">
          <div class="uhp-anno-bar-wrap">
            <div class="uhp-anno-bar-annotated" style="width:${total>0?Math.round(preAnn/total*100):0}%"></div>
            <div class="uhp-anno-bar-null"      style="width:${total>0?Math.round(nullCnt/total*100):0}%"></div>
            <div class="uhp-anno-bar-raw"></div>
          </div>
          <div class="uhp-anno-legend">
            ${preAnn > 0  ? `<div class="uhp-anno-leg-item"><div class="uhp-anno-leg-dot annotated"></div> Annotated <span class="uhp-anno-leg-num">${preAnn}</span></div>` : ''}
            ${pending > 0 ? `<div class="uhp-anno-leg-item"><div class="uhp-anno-leg-dot raw"></div> Raw <span class="uhp-anno-leg-num">${pending}</span></div>` : ''}
            ${nullCnt > 0 ? `<div class="uhp-anno-leg-item"><div class="uhp-anno-leg-dot null"></div> Null <span class="uhp-anno-leg-num">${nullCnt}</span></div>` : ''}
            <div class="uhp-anno-leg-item" style="margin-left:auto;color:var(--tx3)">${total} total &nbsp;·&nbsp; ${pct}% done</div>
          </div>
        </div>` : `<div class="uhp-folder-empty"><i class="fas fa-inbox"></i> No images yet</div>`}
      </div>

      ${splits && Object.keys(splits).length > 0 ? `
      <div class="uhp-source-splits">
        <span class="uhp-splits-label">Source:</span>
        ${splits.train !== undefined ? `<span class="uhp-split-tag train"><i class="fas fa-dumbbell"></i> train ${splits.train}</span>` : ''}
        ${splits.valid !== undefined ? `<span class="uhp-split-tag valid"><i class="fas fa-check"></i> val ${splits.valid}</span>` : ''}
        ${splits.test  !== undefined ? `<span class="uhp-split-tag test"><i class="fas fa-flask"></i> test ${splits.test}</span>` : ''}
      </div>` : ''}

      <div class="uhp-card-footer">
        ${preAnn > 0 ? `<button class="uhp-btn review"><i class="fas fa-eye"></i> Review</button>` : ''}
        ${pending > 0 ? `<button class="uhp-btn annotate"><i class="fas fa-tags"></i>${preAnn > 0 ? ' Label Raw' : ' Annotate'}</button>` : ''}
        <div class="uhp-footer-spacer"></div>
        <button class="uhp-btn add-ds ${inDs?'readd':''}">
          ${inDs
            ? '<i class="fas fa-plus-circle"></i> Re-add'
            : '<i class="fas fa-database"></i> Add to Dataset'}
        </button>
      </div>`;

    // Whole card click → open annotator with this batch's images only
    card.addEventListener('click', e => {
      if (e.target.closest('.uhp-btn') || e.target.closest('.uhp-card-del')) return;
      this._loadBatchIntoAnnotator(batch.upload_id);
    });
    card.querySelector('.uhp-btn.review')   ?.addEventListener('click', e => { e.stopPropagation(); this._loadBatchIntoAnnotator(batch.upload_id); });
    card.querySelector('.uhp-btn.annotate') ?.addEventListener('click', e => { e.stopPropagation(); this._loadBatchIntoAnnotator(batch.upload_id, 'raw'); });
    card.querySelector('.uhp-btn.add-ds').addEventListener('click', e => {
      e.stopPropagation();
      this._selectBatchForDataset(batch.upload_id, card);
    });
    card.querySelector('.uhp-card-del').addEventListener('click', async e => {
      e.stopPropagation();
      if (!confirm(`Delete batch #${batch.upload_id} and all its images? This cannot be undone.`)) return;
      await fetch(`/api/uploads/${batch.upload_id}?project=${encodeURIComponent(state.project)}`, {method:'DELETE'});
      card.remove(); this._toast('Batch deleted', 'success'); await this._loadMedia();
    });
    return card;
  },

  async _loadBatchIntoAnnotator(uploadId, folderFilter = null) {
    try {
      const r = await fetch(`/api/uploads/${uploadId}/media?project=${encodeURIComponent(state.project)}`);
      const d = await r.json();
      if (!d.media || !d.media.length) { this._toast('No images in this batch','warn'); return; }
      let media = d.media;
      if (folderFilter) {
        media = d.media.filter(m => m.folder === folderFilter);
        if (!media.length) { this._toast(`No images in ${folderFilter}/`,'warn'); return; }
      }

      // ── Lock the annotator to this job ──────────────────────────────────────
      // This prevents nextImage/prevImage from crossing into other jobs.
      state.activeJobId    = uploadId;
      state.activeJobTotal = media.length;
      // Build a human-readable name from the batch
      const batch = state._uploadBatches?.find(b => b.upload_id === uploadId);
      state.activeJobName  = batch?.datetime_str || batch?.label || `Job #${uploadId}`;

      state.media          = media;
      state.annotatedPaths = new Set(d.annotated  || []);
      state.nullPaths      = new Set(d.null_paths || []);

      // Reset pagination state to reflect this job (1 page, no cross-job navigation)
      state.listPage       = 1;
      state.listTotal      = media.length;
      state.listTotalPages = 1;   // ONE page = ONE job, no overflow

      if (d.classes && d.classes.length) { state.classes = d.classes; this._populateClassList(); }
      this._applyFilter();
      this._updateTotals();
      this._updateNavBadges();
      this._updateJobStatusBar();  // show per-job annotated/pending counts in sidebar
      this.showPage('annotate');
      if (state.filteredMedia.length > 0) this.loadImage(0, true);
      const pre  = (d.annotated||[]).length;
      const lbl  = folderFilter ? ` (${folderFilter}/)` : '';
      this._toast(`Job ${uploadId}${lbl}: ${media.length} images · ${pre} annotated`, 'success');
    } catch(e) { this._toast('Failed to load batch','error'); console.error(e); }
  },

  async _selectBatchForDataset(uploadId, card) {
    document.querySelectorAll('.uhp-batch-card.selected').forEach(c => c.classList.remove('selected'));
    if (card) card.classList.add('selected');
    state._uhpSelectedBatchId = uploadId;

    // ── Fill modal with live batch counts ──────────────────────────────────
    // Always fetch fresh from the server so counts are correct whether we're
    // on the upload page (batches cached) or the annotate page (may be stale).
    const lbl = document.getElementById('uspBatchLabel');
    const ann  = document.getElementById('uspAnnotatedCount');
    const raw  = document.getElementById('uspRawCount');
    const nul  = document.getElementById('uspNullCount');

    // Show modal immediately with loading state
    if (lbl) lbl.textContent = `Job #${uploadId} — loading…`;
    if (ann) ann.textContent = '…';
    if (raw) raw.textContent = '…';
    if (nul) nul.textContent = '—';

    const modal = document.getElementById('uspModal');
    if (modal) modal.style.display = 'flex';

    // Re-init sliders to defaults whenever the modal opens
    const tEl = document.getElementById('batchTrainSlider');
    const vEl = document.getElementById('batchValSlider');
    const sEl = document.getElementById('batchTestSlider');
    if (tEl) tEl.value = 70;
    if (vEl) vEl.value = 15;
    if (sEl) sEl.value = 15;
    // Trigger UI sync
    const tPct = document.getElementById('batchTrainPct');
    const vPct = document.getElementById('batchValPct');
    const sPct = document.getElementById('batchTestPct');
    if (tPct) tPct.textContent = '70%';
    if (vPct) vPct.textContent = '15%';
    if (sPct) sPct.textContent = '15%';
    const pb = document.getElementById('uspPreviewTrain');
    const pv = document.getElementById('uspPreviewVal');
    const pt = document.getElementById('uspPreviewTest');
    if (pb) pb.style.width = '70%';
    if (pv) pv.style.width = '15%';
    if (pt) pt.style.width = '15%';
    const errEl = document.getElementById('uspRatioErr');
    if (errEl) errEl.style.display = 'none';
    const cfBtn = document.getElementById('uspConfirmBtn');
    if (cfBtn) cfBtn.disabled = false;

    try {
      // Fetch this specific batch's counts from the server
      const r = await fetch(`/api/uploads?project=${encodeURIComponent(state.project)}`);
      if (r.ok) {
        const batches = await r.json();
        state._uploadBatches = batches; // keep cache fresh
        const batch = batches.find(b => b.upload_id === uploadId);
        if (batch) {
          const dt = batch.datetime_str || batch.label || `Job #${uploadId}`;
          if (lbl) lbl.textContent = `${dt}`;
          if (ann) ann.textContent = batch.annotated   || 0;
          if (raw) raw.textContent = batch.pending      || batch.unannotated || 0;
          if (nul) nul.textContent = batch.null_count   || 0;
        } else {
          // Batch not in list — still allow adding (might be freshly uploaded)
          if (lbl) lbl.textContent = `Job #${uploadId}`;
          if (ann) ann.textContent = state.annotatedPaths.size;
          if (raw) raw.textContent = (state.media.length - state.annotatedPaths.size);
          if (nul) nul.textContent = 0;
        }
      }
    } catch(e) {
      // Network error — fill from local state as fallback
      if (lbl) lbl.textContent = `Job #${uploadId}`;
      if (ann) ann.textContent = state.annotatedPaths.size;
      if (raw) raw.textContent = (state.media.length - state.annotatedPaths.size);
      if (nul) nul.textContent = 0;
    }
  },

  _selectBatchForDatasetById(uploadId) {
    const card = document.querySelector(`.uhp-batch-card[data-upload-id="${uploadId}"]`);
    if (card) {
      this._selectBatchForDataset(uploadId, card);
    } else {
      // switch to upload page and scroll Active Work
      this.showPage('upload');
      state._uhpSelectedBatchId = uploadId;
      const modal = document.getElementById('uspModal');
      if (modal) modal.style.display = 'flex';
    }
  },

  // ── Completed Datasets panel ────────────────────────────────────────────

  async _loadCompletedDatasets() {
    const list  = document.getElementById('upDsList');
    const empty = document.getElementById('upDsEmpty');
    const badge = document.getElementById('upDsCount');
    if (!list) return;
    try {
      // Scan Completed_Datasets/ via a backend endpoint
      const r = await fetch(`/api/datasets?project=${encodeURIComponent(state.project)}`);
      if (!r.ok) throw new Error('no endpoint');
      const datasets = await r.json();
      // Update badge
      if (badge) badge.textContent = datasets.length;
      // Clear old cards
      Array.from(list.querySelectorAll('.upds-card')).forEach(c => c.remove());
      if (!datasets.length) {
        if (empty) empty.style.display = '';
        return;
      }
      if (empty) empty.style.display = 'none';
      const sorted = [...datasets].sort((a,b) => (b.dataset_id||'').localeCompare(a.dataset_id||''));
      sorted.forEach(ds => list.appendChild(this._buildDatasetCard(ds)));
    } catch(e) {
      // Fallback: try to read from project folder listing
      if (badge) badge.textContent = '—';
    }
  },

  _buildDatasetCard(ds) {
    const sc     = ds.split_counts || ds.original_statistics?.splits || {};
    const trainN = sc.train || 0;
    const validN = sc.valid || 0;
    const testN  = sc.test  || 0;
    const total  = ds.total_images || (trainN + validN + testN);
    const id     = ds.dataset_id || ds.datetime_str || '—';

    // Parse readable date/time from job_YYYY-MM-DD_HH-MM-SS
    let dayStr = id, timeStr = '';
    const parts = id.match(/^job_(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})-(\d{2})/);
    if (parts) {
      const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
      const h = parseInt(parts[4]), mn = parts[5];
      const ampm = h < 12 ? 'AM' : 'PM';
      dayStr  = `${months[parseInt(parts[2])-1]} ${parseInt(parts[3])}, ${parts[1]}`;
      timeStr = `${h%12||12}:${mn} ${ampm}`;
    }

    // Split percentages for bar
    const trainPct = total > 0 ? Math.round(trainN / total * 100) : 0;
    const validPct = total > 0 ? Math.round(validN / total * 100) : 0;
    const testPct  = total > 0 ? 100 - trainPct - validPct : 0;

    const card = document.createElement('div');
    card.className = 'upds-card';
    card.innerHTML = `
      <div class="upds-card-header">
        <div class="upds-card-icon-wrap"><i class="fas fa-database"></i></div>
        <div class="upds-card-info">
          <div class="upds-date-main">${this._escHtml(dayStr)}</div>
          <div class="upds-date-time">${this._escHtml(timeStr)}</div>
        </div>
        <div class="upds-total-chip">
          <span class="upds-total-num">${total}</span>
          <span class="upds-total-lbl">imgs</span>
        </div>
        <button class="upds-card-del" title="Delete dataset"><i class="fas fa-trash-alt"></i></button>
      </div>

      <!-- Compact split info: one row + one bar -->
      <div class="upds-split-compact">
        <div class="upds-split-row">
          <span class="upds-split-tag train"><i class="fas fa-dumbbell"></i> ${trainN} <em>train</em></span>
          <span class="upds-split-tag valid"><i class="fas fa-check-circle"></i> ${validN} <em>val</em></span>
          <span class="upds-split-tag test"><i class="fas fa-flask"></i> ${testN} <em>test</em></span>
        </div>
        <div class="upds-split-bar-wrap">
          <div class="upds-split-bar-train" style="width:${trainPct}%" title="Train ${trainPct}%"></div>
          <div class="upds-split-bar-valid" style="width:${validPct}%" title="Val ${validPct}%"></div>
          <div class="upds-split-bar-test"  style="width:${testPct}%"  title="Test ${testPct}%"></div>
        </div>
        <div class="upds-split-pct-row">
          <span class="train">${trainPct}%</span>
          <span class="valid">${validPct}%</span>
          <span class="test">${testPct}%</span>
        </div>
      </div>

      <div class="upds-card-footer">
        <button class="upds-btn export"><i class="fas fa-file-export"></i> Export</button>
        <button class="upds-btn view"><i class="fas fa-eye"></i> Review</button>
        <button class="upds-btn move-active" title="Move images back to Active Work for re-annotation">
          <i class="fas fa-undo-alt"></i> Move to Active Work
        </button>
        <button class="upds-del-btn" title="Delete"><i class="fas fa-trash-alt"></i></button>
      </div>`;

    card.querySelector('.upds-btn.export').addEventListener('click', e => {
      e.stopPropagation();
      this._toast('Export — use the Export tab to configure format', 'info');
    });
    card.querySelector('.upds-btn.view').addEventListener('click', e => {
      e.stopPropagation();
      this._loadDatasetForReview(ds);
    });
    card.querySelector('.upds-btn.move-active').addEventListener('click', async e => {
      e.stopPropagation();
      if (!confirm(`Move all images from this dataset back to Active Work for re-annotation?\n\nThe dataset will be removed.`)) return;
      try {
        const r = await fetch(
          `/api/datasets/${encodeURIComponent(id)}/move_to_active?project=${encodeURIComponent(state.project)}`,
          { method: 'POST' }
        );
        const d = await r.json();
        if (d.success) {
          this._toast(`Moved ${d.moved} images to Active Work (Job #${d.upload_id})`, 'success');
          card.remove();
          await this._loadUploadBatches();
          await this._loadCompletedDatasets();
          await this._loadMedia();
        } else {
          this._toast(d.error || 'Move failed', 'error');
        }
      } catch(e2) { this._toast('Network error', 'error'); }
    });

    const _delDs = async e => {
      e.stopPropagation();
      if (!confirm(`Delete dataset ${id}? This cannot be undone.`)) return;
      try {
        await fetch(`/api/datasets/${encodeURIComponent(id)}?project=${encodeURIComponent(state.project)}`, {method:'DELETE'});
      } catch(er) {}
      card.remove();
      this._toast('Dataset deleted', 'success');
      await this._loadCompletedDatasets();
    };
    card.querySelector('.upds-card-del')?.addEventListener('click', _delDs);
    card.querySelector('.upds-del-btn')?.addEventListener('click', _delDs);
    return card;
  },

  async _loadDatasetForReview(ds) {
    const id = ds.dataset_id || ds.datetime_str;
    const btn = event?.target?.closest('.upds-btn.view');
    if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i> Loading…'; }

    try {
      const r = await fetch(
        `/api/datasets/${encodeURIComponent(id)}/media?project=${encodeURIComponent(state.project)}`
      );
      if (!r.ok) throw new Error('Failed to load dataset media');
      const d = await r.json();

      if (!d.media || !d.media.length) {
        this._toast('No images found in this dataset', 'warn');
        return;
      }

      // Load dataset images into the annotator — read-only review mode
      // (activeJobId = null means no write-lock, but images load with annotations)
      state.activeJobId    = null;
      state.media          = d.media;
      state.annotatedPaths = new Set(d.annotated || []);
      state.nullPaths      = new Set(d.null_paths || []);
      state.listPage       = 1;
      state.listTotal      = d.media.length;
      state.listTotalPages = 1;

      if (d.classes && d.classes.length) {
        state.classes = d.classes;
        this._populateClassList();
      }

      this._applyFilter();
      this._updateTotals();
      this._updateNavBadges();
      this.showPage('annotate');
      if (state.filteredMedia.length > 0) this.loadImage(0, true);

      this._toast(
        `Reviewing dataset: ${d.media.length} images · ${(d.annotated||[]).length} annotated — read-only view`,
        'info'
      );
    } catch(e) {
      this._toast('Failed to load dataset for review', 'error');
      console.error(e);
    } finally {
      if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-eye"></i> Review'; }
    }
  },

  async _addBatchToDataset(uploadId) {
    const g = id => parseInt(document.getElementById(id)?.value || 0);
    const train = g('batchTrainSlider') / 100;
    const val   = g('batchValSlider')   / 100;
    const test  = g('batchTestSlider')  / 100;
    if (Math.abs(train+val+test-1) > 0.02) { this._toast('Ratios must sum to 100%','error'); return; }
    try {
      const r = await fetch(`/api/uploads/${uploadId}/add_to_dataset`, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({project: state.project, train, val, test}),
      });
      const d = await r.json();
      if (d.success) {
        const sc    = d.split_counts || {};
        const moved = d.moved_annotated || 0;
        const kept  = d.remaining_raw   || 0;
        this._toast(
          `Dataset created: ${moved} images → train:${sc.train||0} valid:${sc.valid||0} test:${sc.test||0}` +
          (kept > 0 ? ` · ${kept} raw images remain in Active Work` : ''),
          'success'
        );
        document.querySelectorAll('.uhp-batch-card.selected').forEach(c => c.classList.remove('selected'));
        state._uhpSelectedBatchId = null;
        await this._loadUploadBatches();
        await this._loadCompletedDatasets();
        await this._loadProjectsPanel();
        await this._loadMedia();
      } else { this._toast(`Failed: ${d.error}`,'error'); }
    } catch(e) { this._toast('Failed','error'); }
  },

  _esc(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  },


  async _loadWorkspaceTree() {
    const body = document.getElementById('upTreeBody');
    if (!body) return;
    body.innerHTML = '<div class="up-tree-loading"><div class="spinner" style="width:20px;height:20px;border-width:2px;margin:auto"></div></div>';
    try {
      const r = await fetch('/api/workspace/folders');
      const folders = await r.json();
      this._renderUploadTree(folders);
    } catch(e) {
      body.innerHTML = '<div class="up-tree-empty"><i class="fas fa-exclamation-circle"></i><p>Failed to load.</p></div>';
    }
  },

  _renderUploadTree(folders) {
    const body = document.getElementById('upTreeBody');
    if (!body) return;
    if (!folders.length) {
      body.innerHTML = '<div class="up-tree-empty"><i class="fas fa-inbox"></i><p>No projects yet.<br>Create one on the right.</p></div>';
      return;
    }
    body.innerHTML = '';
    folders.forEach(folder => {
      const isActive = folder.name === state.project;
      const pct = folder.progress || 0;
      const el = document.createElement('div');
      el.className = 'up-tree-item' + (isActive ? ' active' : '');
      el.innerHTML =
        '<div class="uti-header">' +
          '<span class="uti-icon"><i class="fas fa-folder'+(isActive?'-open':'')+'"></i></span>' +
          '<span class="uti-name" title="'+folder.name+'">'+folder.name+'</span>' +
          '<span class="uti-total">'+folder.total+'</span>' +
        '</div>' +
        '<div class="uti-subfolders">' +
          '<span class="uti-sub unanno"><i class="fas fa-circle-notch"></i> Unannotated <b>'+folder.unannotated+'</b></span>' +
          '<span class="uti-sub anno"><i class="fas fa-check-circle"></i> Annotated <b>'+folder.annotated+'</b></span>' +
          (folder.split > 0 ? '<span class="uti-sub split"><i class="fas fa-sitemap"></i> Split <b>'+folder.split+'</b></span>' : '') +
        '</div>' +
        '<div class="uti-progress-bar"><div class="uti-progress-fill" style="width:'+pct+'%"></div></div>' +
        '<div class="uti-pct">'+pct+'% annotated</div>';
      el.addEventListener('click', async () => {
        state.project = folder.name;
        document.querySelectorAll('.up-tree-item').forEach(x => { x.classList.remove('active'); x.querySelector('.uti-icon i').className='fas fa-folder'; });
        el.classList.add('active');
        el.querySelector('.uti-icon i').className = 'fas fa-folder-open';
        const inp = document.getElementById('upPageProjectName');
        if (inp) inp.value = folder.name;
        const sel = document.getElementById('projectSelect');
        if (sel) sel.value = folder.name;
        await this._loadMedia();
        this._updateNavBadges();
        this.showPage('annotate');
      });
      body.appendChild(el);
    });
  },

  /* ── Version Modal Helpers ── */
  _bindUploadPage() {
    document.getElementById('uocImages')?.addEventListener('click', () => document.getElementById('upPageImagesInput').click());
    document.getElementById('uocFolder')?.addEventListener('click', () => document.getElementById('upPageFolderInput').click());
    document.getElementById('uocVideo')?.addEventListener('click',  () => document.getElementById('upPageVideoInput').click());
    document.getElementById('uocImport')?.addEventListener('click', () => document.getElementById('upPageImportInput').click());
    document.getElementById('upPageImagesInput')?.addEventListener('change', async e => {
      this._upPageSetProject();
      this._upShowFilePreview(e.target.files);
      await this._handleFilesDrop(e.target.files);
      this._upHideFilePreview();
      e.target.value = '';
    });
    document.getElementById('upPageFolderInput')?.addEventListener('change', async e => {
      this._upPageSetProject();
      this._upShowFilePreview(e.target.files);
      await this._handleFilesDrop(e.target.files);
      this._upHideFilePreview();
      e.target.value = '';
    });
    document.getElementById('upPageVideoInput')?.addEventListener('change',  e => { this._upPageSetProject(); const vids=Array.from(e.target.files); if(vids.length) this._openVideoModal(vids); e.target.value=''; });
    document.getElementById('upPageImportInput')?.addEventListener('change', async e => {
      this._upPageSetProject();
      const file = e.target.files[0];
      e.target.value = '';
      if (!file) return;
      await this._handleZipUploadFromPage(file);
    });
    const drop = document.getElementById('upPageDrop');
    drop?.addEventListener('dragover',  e => { e.preventDefault(); drop.classList.add('drag-over'); });
    drop?.addEventListener('dragenter', e => { e.preventDefault(); drop.classList.add('drag-over'); });
    drop?.addEventListener('dragleave', e => {
      // Only remove if leaving the drop zone entirely (not a child element)
      if (!drop.contains(e.relatedTarget)) drop.classList.remove('drag-over');
    });
    drop?.addEventListener('drop', async e => {
      e.preventDefault(); drop.classList.remove('drag-over');
      this._upPageSetProject();
      this._upShowFilePreview(e.dataTransfer.files);
      await this._handleFilesDrop(e.dataTransfer.files);
      this._upHideFilePreview();
    });
    drop?.addEventListener('click', () => document.getElementById('upPageImagesInput').click());

    // ── Split modal sliders ───────────────────────────────────────────────────
    // ── Split sliders: auto-sync so train+val+test always = 100% ────────────
    const _syncSplitSliders = (changedId) => {
      const tEl = document.getElementById('batchTrainSlider');
      const vEl = document.getElementById('batchValSlider');
      const sEl = document.getElementById('batchTestSlider');
      if (!tEl || !vEl || !sEl) return;

      let t = parseInt(tEl.value);
      let v = parseInt(vEl.value);
      let s = parseInt(sEl.value);

      // Clamp all to [0,100]
      t = Math.min(100, Math.max(0, t));
      v = Math.min(100, Math.max(0, v));
      s = Math.min(100, Math.max(0, s));

      // Redistribute: the changed slider takes its value,
      // remaining two share leftover proportionally
      const step = 5;
      if (changedId === 'batchTrainSlider') {
        const left = 100 - t;
        const total = v + s || 1;
        v = Math.round(left * v / total / step) * step;
        s = 100 - t - v;
      } else if (changedId === 'batchValSlider') {
        const left = 100 - v;
        const total = t + s || 1;
        t = Math.round(left * t / total / step) * step;
        s = 100 - t - v;
      } else {
        const left = 100 - s;
        const total = t + v || 1;
        t = Math.round(left * t / total / step) * step;
        v = 100 - t - s;
      }

      // Clamp edges
      t = Math.min(100, Math.max(0, t));
      v = Math.min(100, Math.max(0, v));
      s = Math.max(0, 100 - t - v);

      tEl.value = t; vEl.value = v; sEl.value = s;
      _updateSplitUI(t, v, s);
    };

    const _updateSplitUI = (t, v, s) => {
      const tPct = document.getElementById('batchTrainPct');
      const vPct = document.getElementById('batchValPct');
      const sPct = document.getElementById('batchTestPct');
      if (tPct) tPct.textContent = t + '%';
      if (vPct) vPct.textContent = v + '%';
      if (sPct) sPct.textContent = s + '%';

      const pb = document.getElementById('uspPreviewTrain');
      const pv = document.getElementById('uspPreviewVal');
      const pt = document.getElementById('uspPreviewTest');
      if (pb) pb.style.width = t + '%';
      if (pv) pv.style.width = v + '%';
      if (pt) pt.style.width = s + '%';

      const sum = t + v + s;
      const ok  = Math.abs(sum - 100) <= 1;
      const err = document.getElementById('uspRatioErr');
      if (err) err.style.display = ok ? 'none' : '';
      const btn = document.getElementById('uspConfirmBtn');
      if (btn) btn.disabled = !ok;
    };

    const updateSplitModal = () => {
      const t = parseInt(document.getElementById('batchTrainSlider')?.value || 70);
      const v = parseInt(document.getElementById('batchValSlider')?.value   || 15);
      const s = parseInt(document.getElementById('batchTestSlider')?.value  || 15);
      _updateSplitUI(t, v, s);
    };

    ['batchTrainSlider','batchValSlider','batchTestSlider'].forEach(id => {
      document.getElementById(id)?.addEventListener('input', () => _syncSplitSliders(id));
    });
    updateSplitModal();

    const closeSplitModal = () => {
      document.getElementById('uspModal').style.display = 'none';
      document.querySelectorAll('.uhp-batch-card.selected').forEach(c => c.classList.remove('selected'));
      state._uhpSelectedBatchId = null;
    };
    document.getElementById('uspConfirmBtn')?.addEventListener('click', () => {
      if (!this._checkBatchRatios()) return;
      const id = state._uhpSelectedBatchId;
      if (id != null) {
        closeSplitModal();
        this._addBatchToDataset(id);
      }
    });
    document.getElementById('uspCancelBtn')?.addEventListener('click', closeSplitModal);
    document.getElementById('uspCloseBtn') ?.addEventListener('click', closeSplitModal);
    document.getElementById('uspModal')    ?.addEventListener('click', e => {
      if (e.target === document.getElementById('uspModal')) closeSplitModal();
    });

    document.getElementById('upPageCreateBtn')?.addEventListener('click', async () => {
      const name = document.getElementById('upPageProjectName')?.value.trim();
      if (!name) { this._toast('Enter a project name first', 'warning'); return; }
      try {
        await fetch('/api/projects', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({name}) });
        state.project = name;
        const sel = document.getElementById('projectSelect');
        if (sel && !Array.from(sel.options).find(o=>o.value===name)) { const opt=document.createElement('option'); opt.value=name; opt.textContent=name; sel.appendChild(opt); }
        if (sel) sel.value = name;
        await this._loadMedia();
        this._updateNavBadges();
        await this._loadWorkspaceTree();
        this._loadUploadBatches();
        this._loadCompletedDatasets();
        // clear input
        const inp = document.getElementById('upPageProjectName');
        if (inp) inp.value = '';
        this._toast('Project "'+name+'" created — uploads will go here', 'success');
      } catch(e) { this._toast('Failed to create project','error'); }
    });
  },

  _upPageSetProject() {
    const name = document.getElementById('upPageProjectName')?.value.trim();
    if (name && name !== state.project) { state.project = name; const el = document.getElementById('rnProjectName'); if(el) el.textContent = name; }
  },

  // Show file count preview chip inside the drop zone
  _upShowFilePreview(files) {
    const chip = document.getElementById('upFilePreview');
    const txt  = document.getElementById('upFilePreviewText');
    if (!chip || !chip) return;
    const arr = Array.from(files || []);
    const imgs = arr.filter(f => /\.(jpe?g|png|bmp|tiff?|webp)$/i.test(f.name)).length;
    const vids = arr.filter(f => /\.(mp4|avi|mov|mkv|webm)$/i.test(f.name)).length;
    const zips = arr.filter(f => /\.zip$/i.test(f.name)).length;
    const total = imgs || vids || zips || arr.length;
    const label = imgs  ? `${imgs} image${imgs  !== 1 ? 's' : ''} ready to upload`
                : vids  ? `${vids} video${vids  !== 1 ? 's' : ''} selected`
                : zips  ? `${zips} ZIP archive${zips !== 1 ? 's' : ''} selected`
                : `${total} file${total !== 1 ? 's' : ''} selected`;
    if (txt) txt.textContent = label;
    chip.style.display = '';
  },

  _upHideFilePreview() {
    const chip = document.getElementById('upFilePreview');
    if (chip) chip.style.display = 'none';
  },

  // Set the upload page progress bar state:
  // pct  = 0–100  | text = status string | sub = sub-line | done = true → success style
  _upSetPageProgress(pct, text, sub, done = false) {
    const bar  = document.getElementById('upPageProgress');
    const fill = document.getElementById('upPageProgFill');
    const pctEl = document.getElementById('upPageProgPct');
    const textEl = document.getElementById('upPageProgText');
    const subEl  = document.getElementById('upPageProgSub');
    const iconEl = bar?.querySelector('.up-prog-label i');
    if (!bar) return;
    if (done === null) { bar.style.display = 'none'; bar.classList.remove('success'); return; }
    bar.style.display = '';
    bar.classList.toggle('success', !!done);
    if (fill) fill.style.width = pct + '%';
    if (pctEl) pctEl.textContent = pct + '%';
    if (textEl) textEl.textContent = text || (done ? 'Upload complete' : 'Uploading…');
    if (subEl) subEl.textContent = sub || '';
    if (iconEl) {
      iconEl.className = done
        ? 'fas fa-check-circle'
        : 'fas fa-circle-notch';
    }
    if (done) {
      // Auto-hide after 2.5 s
      clearTimeout(this._upProgHideTimer);
      this._upProgHideTimer = setTimeout(() => {
        if (bar) { bar.style.display = 'none'; bar.classList.remove('success'); }
      }, 2500);
    }
  },

  _escHtml(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  },

  async _parseYamlClasses(yamlFile) {
    try {
      const text = await yamlFile.text();
      const classes = [];
      let inNames = false;
      for (const line of text.split('\n')) {
        const t = line.trim();
        if (t.startsWith('names:')) {
          const rest = t.split(':')[1]?.trim().replace(/^\[|\]$/g,'');
          if (rest) {
            classes.push(...rest.split(',').map(x=>x.trim().replace(/['"]/g,'')).filter(Boolean));
            break;
          }
          inNames = true;
        } else if (inNames) {
          if (t.startsWith('-')) classes.push(t.slice(1).trim().replace(/['"]/g,''));
          else if (t && !t.startsWith(' ')) break;
        }
      }
      return classes;
    } catch(e) { return []; }
  },

  // ══════════════════════════════════════════════════════════════════
  //  YOLO UPLOAD DETECTION MODAL  (full featured)
  // ══════════════════════════════════════════════════════════════════

  _showUploadDetectionModal({ type, images, labels, classes, splitFolders, hasYaml, warnings, splits, filename }) {
    return new Promise(resolve => {
      document.getElementById('uploadDetectionModal')?.remove();

      const isYoloDs  = Object.keys(splits || splitFolders || {}).length > 0;
      const splitInfo = splits || {};

      // Build split rows with match stats
      const splitColors = { train: '#00d4a0', valid: '#818cf8', test: '#f59e0b' };
      const splitRows = Object.entries(splitInfo).map(([sp, sd]) => {
        const matchPct = sd.images > 0 ? Math.round((sd.matched||sd.images) / sd.images * 100) : 0;
        const col = splitColors[sp] || '#888';
        return `
          <div class="udr-split-block" style="border-left-color:${col}">
            <div class="udr-split-block-head">
              <div class="udr-split-name" style="color:${col}"><i class="fas fa-folder-open"></i> ${sp}/</div>
              <div class="udr-split-imgcount">${sd.images} img</div>
              <div class="udr-split-matchbadge" style="${matchPct===100?'background:rgba(34,197,94,.12);color:#22c55e':'background:rgba(245,158,11,.1);color:#f59e0b'}">
                ${matchPct === 100 ? '<i class="fas fa-check"></i> All matched' : `${sd.matched||sd.images}/${sd.images} matched`}
              </div>
            </div>
            <div class="udr-split-bar-track"><div class="udr-split-bar-fill" style="width:${matchPct}%;background:${col}"></div></div>
          </div>`;
      }).join('');

      // Fallback split rows from raw count
      const fallbackSplitRows = Object.keys(splitInfo).length === 0 && splitFolders
        ? Object.entries(splitFolders).map(([sp, n]) => {
            const col = splitColors[sp] || '#888';
            return `<div class="udr-split-block" style="border-left-color:${col}">
              <div class="udr-split-block-head">
                <div class="udr-split-name" style="color:${col}"><i class="fas fa-folder-open"></i> ${sp}/</div>
                <div class="udr-split-imgcount">${n} images</div>
              </div>
            </div>`;
          }).join('')
        : '';

      const clsPills = (classes||[]).slice(0,12).map((c,i) => {
        const pal = ['#00d4a0','#818cf8','#f59e0b','#22c5e1','#f87171','#a78bfa','#34d399','#fb923c'];
        return `<span class="udr-cls-chip" style="background:${pal[i%pal.length]}1a;color:${pal[i%pal.length]};border-color:${pal[i%pal.length]}44">${this._escHtml(c)}</span>`;
      }).join('') + ((classes||[]).length > 12 ? `<span class="udr-cls-chip udr-more">+${classes.length-12} more</span>` : '');

      const warnHtml = (warnings||[]).slice(0,4).map(w =>
        `<div class="udr-warn-row"><i class="fas fa-exclamation-triangle"></i>${this._escHtml(w)}</div>`
      ).join('');

      const overlay = document.createElement('div');
      overlay.id = 'uploadDetectionModal';
      overlay.className = 'udr-overlay';
      overlay.innerHTML = `
        <div class="udr-modal">

          <!-- Header -->
          <div class="udr-modal-head">
            <div class="udr-head-icon"><i class="fas fa-search"></i></div>
            <div class="udr-head-text">
              <div class="udr-head-title">Dataset Analysis</div>
              <div class="udr-head-sub">${filename ? this._escHtml(filename) : 'YOLO Dataset'}</div>
            </div>
            <button class="udr-close-btn" id="udrCloseBtn"><i class="fas fa-times"></i></button>
          </div>

          <!-- Detection type badge -->
          <div class="udr-type-banner ${isYoloDs ? 'yolo' : 'mixed'}">
            <i class="fas ${isYoloDs ? 'fa-layer-group' : 'fa-images'}"></i>
            <span>${isYoloDs ? 'YOLO Dataset Detected' : this._escHtml(type)}</span>
          </div>

          <!-- Stats grid -->
          <div class="udr-stats-grid">
            <div class="udr-stat-cell">
              <div class="udr-stat-num">${images}</div>
              <div class="udr-stat-lbl">Images</div>
            </div>
            <div class="udr-stat-cell">
              <div class="udr-stat-num">${labels}</div>
              <div class="udr-stat-lbl">Labels</div>
            </div>
            <div class="udr-stat-cell">
              <div class="udr-stat-num">${(classes||[]).length || '—'}</div>
              <div class="udr-stat-lbl">Classes</div>
            </div>
            <div class="udr-stat-cell ${hasYaml ? 'has-yaml' : ''}">
              <div class="udr-stat-num"><i class="fas ${hasYaml ? 'fa-check-circle' : 'fa-times-circle'}"></i></div>
              <div class="udr-stat-lbl">data.yaml</div>
            </div>
          </div>

          <!-- Dataset structure -->
          ${isYoloDs || fallbackSplitRows ? `
          <div class="udr-section">
            <div class="udr-section-hd"><i class="fas fa-sitemap"></i> Dataset Structure</div>
            <div class="udr-splits-list">${splitRows || fallbackSplitRows}</div>
          </div>` : ''}

          <!-- Classes -->
          ${clsPills ? `
          <div class="udr-section">
            <div class="udr-section-hd"><i class="fas fa-tags"></i> Classes from data.yaml</div>
            <div class="udr-cls-chips">${clsPills}</div>
          </div>` : ''}

          <!-- Warnings -->
          ${warnHtml ? `
          <div class="udr-section">
            <div class="udr-section-hd warn"><i class="fas fa-exclamation-triangle"></i> Warnings</div>
            <div class="udr-warns">${warnHtml}</div>
          </div>` : ''}

          <!-- Upload options -->
          <div class="udr-section">
            <div class="udr-section-hd"><i class="fas fa-route"></i> Import Routing</div>
            <div class="udr-route-grid">
              <div class="udr-route-row">
                <div class="udr-route-from"><i class="fas fa-tags" style="color:#22c55e"></i> With labels</div>
                <div class="udr-route-arrow"><i class="fas fa-long-arrow-alt-right"></i></div>
                <div class="udr-route-to"><code>job_N/images/ + labels/</code></div>
              </div>
              <div class="udr-route-row">
                <div class="udr-route-from"><i class="fas fa-image" style="color:#3b82f6"></i> No labels</div>
                <div class="udr-route-arrow"><i class="fas fa-long-arrow-alt-right"></i></div>
                <div class="udr-route-to"><code>job_N/images/</code></div>
              </div>
              <div class="udr-route-row">
                <div class="udr-route-from"><i class="fas fa-file-code" style="color:var(--accent)"></i> Classes</div>
                <div class="udr-route-arrow"><i class="fas fa-long-arrow-alt-right"></i></div>
                <div class="udr-route-to"><code>job_N/data.yaml</code></div>
              </div>
            </div>
          </div>

          <!-- Footer -->
          <div class="udr-footer">
            <button class="udr-cancel-btn" id="udrCancelBtn"><i class="fas fa-times"></i> Cancel</button>
            <button class="udr-confirm-btn" id="udrConfirmBtn">
              <i class="fas fa-cloud-upload-alt"></i> Import ${images} Images
            </button>
          </div>

        </div>`;

      document.body.appendChild(overlay);

      const close = val => { overlay.remove(); resolve(val); };
      document.getElementById('udrConfirmBtn').addEventListener('click', () => close(true));
      document.getElementById('udrCancelBtn') .addEventListener('click', () => close(false));
      document.getElementById('udrCloseBtn')  .addEventListener('click', () => close(false));
      overlay.addEventListener('click', e => { if (e.target === overlay) close(false); });
    });
  },

  // ── Post-upload result summary card ─────────────────────────────────────
  _showUploadResultCard(result, uploadId, type = 'folder') {
    const el = document.getElementById('upYoloResult');
    if (!el) return;
    el.style.display = '';

    const preAnn = result.annotated || 0;
    const raw    = result.unannotated || result.total_images - preAnn || 0;
    const cls    = result.cls_names || [];
    const splits = result.splits || {};
    const total  = result.total_images || preAnn + raw;

    const hasSplits   = Object.keys(splits).length > 0;
    const splitColors = { train:'#00d4a0', valid:'#818cf8', test:'#f59e0b' };

    const splitRowsHtml = hasSplits
      ? Object.entries(splits).map(([sp, sd]) => {
          const col = splitColors[sp] || '#888';
          const pct = sd.images > 0 ? Math.round((sd.matched||sd.images) / sd.images * 100) : 100;
          return `
            <div class="uyr-split-row" style="border-left:3px solid ${col}">
              <span class="uyr-split-name" style="color:${col}">${sp}/</span>
              <span class="uyr-split-imgs">${sd.images} images</span>
              <span class="uyr-split-match" style="color:${pct===100?'#22c55e':'#f59e0b'}">${sd.matched||sd.images} matched</span>
              <div class="uyr-split-bar"><div style="width:${pct}%;background:${col}"></div></div>
            </div>`;
        }).join('')
      : '';

    const clsPills = cls.slice(0,10).map((c,i) => {
      const pal = ['#00d4a0','#818cf8','#f59e0b','#22c5e1','#f87171','#a78bfa'];
      return `<span class="uyr-cls-chip" style="background:${pal[i%pal.length]}1a;color:${pal[i%pal.length]};border-color:${pal[i%pal.length]}33">${this._escHtml(c)}</span>`;
    }).join('') + (cls.length > 10 ? `<span class="uyr-cls-chip">+${cls.length-10}</span>` : '');

    el.className = 'uyr-card';
    el.innerHTML = `
      <div class="uyr-card-head">
        <div class="uyr-card-icon"><i class="fas fa-check-circle"></i></div>
        <div class="uyr-card-title">
          <div class="uyr-card-headline">Import Complete</div>
          <div class="uyr-card-sub">Batch #${uploadId} created in Active Work</div>
        </div>
        <button class="uyr-dismiss" onclick="document.getElementById('upYoloResult').style.display='none'">
          <i class="fas fa-times"></i>
        </button>
      </div>

      <div class="uyr-totals">
        <div class="uyr-total-cell total"><div class="uyr-total-num">${total}</div><div class="uyr-total-lbl">Total</div></div>
        <div class="uyr-total-cell preann"><div class="uyr-total-num">${preAnn}</div><div class="uyr-total-lbl">Pre-annotated</div></div>
        <div class="uyr-total-cell raw"><div class="uyr-total-num">${raw}</div><div class="uyr-total-lbl">Raw</div></div>
        <div class="uyr-total-cell classes"><div class="uyr-total-num">${cls.length}</div><div class="uyr-total-lbl">Classes</div></div>
      </div>

      ${hasSplits ? `<div class="uyr-splits-section"><div class="uyr-sub-hd">Dataset Splits</div>${splitRowsHtml}</div>` : ''}

      ${cls.length ? `<div class="uyr-cls-section"><div class="uyr-sub-hd">Classes Imported</div><div class="uyr-cls-chips">${clsPills}</div></div>` : ''}

      <div class="uyr-actions">
        ${preAnn > 0 ? `<button class="uyr-action-btn review" onclick="app._loadBatchIntoAnnotator(${uploadId})"><i class="fas fa-eye"></i> Review Pre-annotated</button>` : ''}
        ${raw > 0    ? `<button class="uyr-action-btn label"  onclick="app._loadBatchIntoAnnotator(${uploadId},'raw')"><i class="fas fa-tags"></i> Annotate Raw Images</button>` : ''}
        <button class="uyr-action-btn add-ds" onclick="app._selectBatchForDatasetById(${uploadId})"><i class="fas fa-database"></i> Add to Dataset</button>
      </div>`;
  },

  async _handleZipUploadFromPage(file) {
    // Step 1: deep-scan the ZIP to show YOLO detection modal
    const progBar  = document.getElementById('upPageProgress');
    const progFill = document.getElementById('upPageProgFill');
    const progText = document.getElementById('upPageProgText');

    if (progBar) { progBar.style.display = ''; }
    if (progText) progText.textContent = 'Analysing dataset…';

    let preview = null;
    try {
      const fd = new FormData();
      fd.append('file', file);
      fd.append('project', state.project);
      const r = await fetch(`/api/import/preview?project=${encodeURIComponent(state.project)}`, {method:'POST', body:fd});
      preview  = await r.json();
    } catch(e) { preview = null; }

    if (progBar) progBar.style.display = 'none';

    if (!preview?.success) {
      this._toast(preview?.error || 'Could not read ZIP file', 'error');
      return;
    }

    // Step 2: show detection modal with deep analysis
    const confirmed = await this._showUploadDetectionModal({
      type:     preview.is_yolo_dataset ? 'YOLO Dataset' : 'ZIP Archive',
      images:   preview.total_images,
      labels:   preview.total_labels,
      classes:  preview.cls_names || [],
      splits:   preview.splits || {},
      splitFolders: {},
      hasYaml:  preview.has_yaml,
      warnings: preview.warnings || [],
      filename: file.name,
    });

    if (!confirmed) return;

    // Step 3: upload the ZIP through existing import route
    if (progBar)  { progBar.style.display = ''; }
    if (progFill) progFill.style.width = '0%';
    if (progText) progText.textContent  = 'Importing dataset…';

    const fd2 = new FormData();
    fd2.append('file',          file);
    fd2.append('project',       state.project);
    fd2.append('merge_mode',    'rename');
    fd2.append('import_images', 'true');
    fd2.append('import_labels', 'true');

    try {
      const r2 = await fetch('/api/import', {method:'POST', body:fd2});
      if (progFill) progFill.style.width = '100%';
      const d = await r2.json();

      if (progBar) progBar.style.display = 'none';

      if (d.success) {
        // Build combined result including preview's split data
        const result = {
          ...d,
          total_images: preview.total_images,
          annotated:    d.annotated || d.labels_imported || 0,
          unannotated:  d.unannotated || (preview.total_images - (d.labels_imported || 0)),
          cls_names:    d.cls_names || preview.cls_names || [],
          splits:       preview.splits || {},
          is_yolo_dataset: preview.is_yolo_dataset,
        };
        this._upSetPageProgress(100, 'Import complete!', `${d.images_imported} images imported`, true);
        this._showUploadResultCard(result, d.upload_id, 'zip');
        this._toast(`ZIP import complete: ${d.images_imported} images`, 'success');
        await this._loadMedia();
        await this._loadUploadBatches();
        await this._loadCompletedDatasets();
      } else {
        this._toast(d.error || 'Import failed', 'error');
      }
    } catch(e) {
      if (progBar) progBar.style.display = 'none';
      this._toast('Import failed', 'error');
    }
  },

  _checkBatchRatios() {
    const t = parseInt(document.getElementById('batchTrainSlider')?.value || 70);
    const v = parseInt(document.getElementById('batchValSlider')?.value   || 15);
    const s = parseInt(document.getElementById('batchTestSlider')?.value  || 15);
    const ok  = Math.abs(t + v + s - 100) <= 1;
    const err = document.getElementById('uspRatioErr');
    if (err) err.style.display = ok ? 'none' : '';
    const btn = document.getElementById('uspConfirmBtn');
    if (btn) btn.disabled = !ok;
    return ok;
  },

  /* ── UI BINDINGS ── */
  _bindUI() {
    // Mode buttons
    document.getElementById('bboxModeBtn').addEventListener('click', () => this.setMode('bbox'));
    document.getElementById('editModeBtn').addEventListener('click', () => this.setMode('edit'));
    document.getElementById('panModeBtn' ).addEventListener('click', () => this.setMode('pan'));

    // Mode buttons
    document.getElementById('bboxModeBtn').addEventListener('click', () => this.setMode('bbox'));
    document.getElementById('editModeBtn').addEventListener('click', () => this.setMode('edit'));
    document.getElementById('panModeBtn' ).addEventListener('click', () => this.setMode('pan'));

    // Undo/redo
    document.getElementById('undoBtn').addEventListener('click', () => this.undo());
    document.getElementById('redoBtn').addEventListener('click', () => this.redo());

    // Zoom
    document.getElementById('zoomInBtn' ).addEventListener('click', () => this.zoomIn());
    document.getElementById('zoomOutBtn').addEventListener('click', () => this.zoomOut());
    document.getElementById('fitBtn'    ).addEventListener('click', () => this._fitImage());
    document.getElementById('zoomLockBtn').addEventListener('click', () => this.toggleZoomLock());

    // Bottom-center image navigator buttons
    document.getElementById('imgNavPrev')?.addEventListener('click', () => this.prevImage());
    document.getElementById('imgNavNext')?.addEventListener('click', () => this.nextImage());
    document.getElementById('zoomDisplay').addEventListener('dblclick', () => this._fitImage());

    // Toolbar actions
    document.getElementById('importBtn').addEventListener('click', () => this.openImport());
    document.getElementById('exportBtn').addEventListener('click', () => this.startExport());
    document.getElementById('splitBtn' ).addEventListener('click', () => this.openSplit());
    document.getElementById('helpBtn'  ).addEventListener('click', () => this.openModal('shortcutsModal'));
    document.getElementById('settingsBtn').addEventListener('click', () => this.openSettings());

    // Null mark button
    document.getElementById('nullMarkBtn')?.addEventListener('click', () => this.toggleNullMark());

    // New toolbar buttons
    document.getElementById('statsBtn')?.addEventListener('click', () => this.openStats());
    document.getElementById('toggleGridBtn')?.addEventListener('click', () => this.toggleGrid());
    document.getElementById('toggleLabelsBtn')?.addEventListener('click', () => this.toggleShowLabels());

    // Set current image as project cover
    document.getElementById('setCoverBtn')?.addEventListener('click', () => this._setCurrentImageAsCover());

    // Mode buttons (floating toolbar)
    document.getElementById('bboxModeBtn')?.addEventListener('click', () => this.setMode('bbox'));
    document.getElementById('editModeBtn')?.addEventListener('click', () => this.setMode('edit'));
    document.getElementById('panModeBtn' )?.addEventListener('click', () => this.setMode('pan'));
    document.getElementById('polyModeBtn')?.addEventListener('click', () => this.setMode('polygon'));
    document.getElementById('repeatModeBtn')?.addEventListener('click', () => this.toggleRepeatMode());

    // Popup: Add New Class inline
    document.getElementById('cpAddClsToggle')?.addEventListener('click', () => {
      const form = document.getElementById('cpAddClsForm');
      if (form) {
        const visible = form.style.display !== 'none';
        form.style.display = visible ? 'none' : '';
        if (!visible) document.getElementById('cpNewClsName')?.focus();
      }
    });
    document.getElementById('cpAddClsBtn')?.addEventListener('click', () => this._cpAddNewClass());
    document.getElementById('cpNewClsName')?.addEventListener('keydown', e => {
      // Stop ALL keys from bubbling to the document-level handler so that
      // Backspace deletes text (not the annotation) and other shortcuts stay inactive.
      e.stopPropagation();
      if (e.key === 'Enter')  { this._cpAddNewClass(); }
      if (e.key === 'Escape') {
        // Close the add-class form but keep the popup open
        const form = document.getElementById('cpAddClsForm');
        if (form) form.style.display = 'none';
        document.getElementById('cpSearch')?.focus();
      }
    });

    // Settings modal apply button
    document.getElementById('applySettingsBtn')?.addEventListener('click', () => this.applySettings());
    document.getElementById('brightnessSlider')?.addEventListener('input', () => this.applyImageAdjustments());
    document.getElementById('contrastSlider')?.addEventListener('input', () => this.applyImageAdjustments());
    document.getElementById('settingLabelOpacity')?.addEventListener('input', e => {
      document.getElementById('settingLabelOpacityVal').textContent = Math.round(e.target.value*100)+'%';
    });
    document.getElementById('settingLineWidth')?.addEventListener('input', e => {
      document.getElementById('settingLineWidthVal').textContent = e.target.value+'px';
    });
    document.getElementById('settingGridSize')?.addEventListener('input', e => {
      document.getElementById('settingGridSizeVal').textContent = e.target.value+'px';
    });
    document.getElementById('resetAdjBtn')?.addEventListener('click', () => this.resetImageAdjustments());

    // Auto-save toggle
    document.getElementById('autoSaveToggle').addEventListener('change', e => {
      state.autoSave = e.target.checked;
      this._toast(`Auto-save ${state.autoSave ? 'enabled' : 'disabled'}`, 'info');
    });

    // Empty state buttons
    document.getElementById('emptyImportBtn').addEventListener('click', () => this.openImport());
    document.getElementById('emptyUploadBtn').addEventListener('click', () => this.openModal('uploadModal'));

    // Upload zone
    const uz = document.getElementById('uploadZone');
    uz.addEventListener('dragover', e => { e.preventDefault(); uz.classList.add('drag-over'); });
    uz.addEventListener('dragleave', () => uz.classList.remove('drag-over'));
    uz.addEventListener('drop', e => { e.preventDefault(); uz.classList.remove('drag-over'); this._handleFilesDrop(e.dataTransfer.files); });
    uz.addEventListener('click', () => document.getElementById('fileInput').click());
    document.getElementById('browseBtn').addEventListener('click', e => { e.stopPropagation(); document.getElementById('fileInput').click(); });
    document.getElementById('fileInput').addEventListener('change', e => {
      this._handleFilesDrop(e.target.files);
      e.target.value = ''; // reset so same file can be picked again
    });

    // Video modal
    const videoDrop = document.getElementById('videoDrop');
    videoDrop.addEventListener('dragover',  e => { e.preventDefault(); videoDrop.classList.add('drag'); });
    videoDrop.addEventListener('dragleave', () => videoDrop.classList.remove('drag'));
    videoDrop.addEventListener('drop', e => {
      e.preventDefault(); videoDrop.classList.remove('drag');
      const vids = Array.from(e.dataTransfer.files).filter(f => /\.(mp4|avi|mov|mkv|webm)$/i.test(f.name));
      if (vids.length) {
        state._pendingVideos = [...(state._pendingVideos||[]), ...vids];
        this._renderVideoList();
      }
    });
    document.getElementById('videoFileInput').addEventListener('change', e => {
      const vids = Array.from(e.target.files);
      state._pendingVideos = [...(state._pendingVideos||[]), ...vids];
      this._renderVideoList();
      e.target.value = '';
    });
    document.getElementById('startExtractBtn').addEventListener('click', () => this.startExtractFrames());

    // FPS / size change → update estimate
    document.getElementById('fpsSelect').addEventListener('change', () => this._updateFrameEstimate());
    document.getElementById('sizeSelect').addEventListener('change', () => {
      const val = document.getElementById('sizeSelect').value;
      document.getElementById('customSizeRow').style.display = val === 'custom' ? '' : 'none';
    });

    // Import modal
    const impDrop = document.getElementById('importDrop');
    impDrop.addEventListener('dragover', e => { e.preventDefault(); impDrop.classList.add('drag'); });
    impDrop.addEventListener('dragleave', () => impDrop.classList.remove('drag'));
    impDrop.addEventListener('drop', e => {
      e.preventDefault(); impDrop.classList.remove('drag');
      const f = e.dataTransfer.files[0];
      if (f) { document.getElementById('importFileInput').files; this.previewImport(f); }
    });
    document.getElementById('importFileInput').addEventListener('change', e => {
      if (e.target.files[0]) this.previewImport(e.target.files[0]);
    });
    document.getElementById('startImportBtn').addEventListener('click', () => this.startImport());

    // Split modal
    document.getElementById('startSplitBtn').addEventListener('click', () => this.startSplit());
    this._bindSplitSliders();

    // Props panel
    document.getElementById('applyPropsBtn').addEventListener('click', () => this.applyProps());
    document.getElementById('delSelBtn'    ).addEventListener('click', () => this.deleteSelected());

    // Class input – Enter to add
    document.getElementById('addClassBtn').addEventListener('click', () => this.addClassFromInput());
    document.getElementById('newClassName').addEventListener('keydown', e => {
      if (e.key === 'Enter') this.addClassFromInput();
    });

    // Popup
    document.getElementById('cpConfirm')?.addEventListener('click', () => this._confirmPopup());
    document.getElementById('cpCancel' )?.addEventListener('click', () => this.closePopup());
    document.getElementById('cpDelete' )?.addEventListener('click', () => this._deleteFromPopup());
    document.getElementById('cpSearch' ).addEventListener('input', e => {
      this._cpKbdIdx = 0;
      this._populatePopupList(e.target.value);
    });
    document.getElementById('cpSearch').addEventListener('keydown', e => {
      if (e.key === 'ArrowDown') { e.preventDefault(); this._cpMove(+1); }
      if (e.key === 'ArrowUp')   { e.preventDefault(); this._cpMove(-1); }
      if (e.key === 'Enter')     { e.preventDefault(); this._confirmPopup(); }
    });

    // Search
    document.getElementById('imageSearch').addEventListener('input', e => {
      state.searchText = e.target.value;
      document.getElementById('clearSearch').style.display = e.target.value ? '' : 'none';
      // Reset to page 1 so results start from beginning
      state.listPage = 1;
      this._applyFilter();
    });
    document.getElementById('clearSearch').addEventListener('click', () => {
      document.getElementById('imageSearch').value = '';
      state.searchText = '';
      document.getElementById('clearSearch').style.display = 'none';
      state.listPage = 1;
      this._applyFilter();
    });

    // Pagination prev/next buttons
    const pageBar = document.getElementById('listPageBar');
    if (pageBar) {
      pageBar.querySelector('.lp-prev')?.addEventListener('click', () => {
        if (state.listPage > 1) this._loadMedia(state.listPage - 1);
      });
      pageBar.querySelector('.lp-next')?.addEventListener('click', () => {
        if (state.listPage < state.listTotalPages) this._loadMedia(state.listPage + 1);
      });
    }
    // Per-page size selector
    document.getElementById('lpPerPage')?.addEventListener('change', e => {
      state.listPerPage = parseInt(e.target.value, 10);
      state.listPage    = 1;
      // If a batch/job is currently locked in, reload that batch so the job
      // context is preserved (avoids _loadMedia clearing activeJobId and
      // replacing the batch images with all-project images).
      if (state.activeJobId != null) {
        this._loadBatchIntoAnnotator(state.activeJobId);
      } else {
        this._loadMedia(1);
      }
    });

    // Job lock bar: "All jobs" button clears the job lock and loads all images
    document.getElementById('jlbClearBtn')?.addEventListener('click', () => {
      this._loadMedia(1);
    });

    // Filter tabs — two independent groups: Status (all/annotated/empty) and Split (all/train/valid/test)
    document.querySelectorAll('.ftab').forEach(btn => {
      btn.addEventListener('click', () => {
        const f = btn.dataset.filter;
        const isSplitBtn = btn.hasAttribute('data-split-filter') ||
                           (f !== 'annotated' && f !== 'empty' && f !== 'all') ||
                           btn.closest('.filter-pills')?.querySelector('[data-split-filter]') === btn;

        // Determine which group this button belongs to by checking its siblings
        const group = btn.closest('.filter-pills');
        if (group) {
          // Clear only siblings in the same pill group
          group.querySelectorAll('.ftab').forEach(b => b.classList.remove('active'));
        } else {
          // Legacy: clear all (fallback)
          document.querySelectorAll('.ftab').forEach(b => b.classList.remove('active'));
        }
        btn.classList.add('active');

        if (f === 'annotated' || f === 'empty') {
          state.filterAnno = f;
        } else if (f === 'all') {
          // Which group? Check if there's a data-split-filter sibling
          const hasSplit = group?.querySelector('[data-split-filter]');
          if (hasSplit) { state.filterSplit = 'all'; }
          else          { state.filterAnno  = 'all'; }
        } else {
          // train / valid / test
          state.filterSplit = f;
        }
        state.listPage = 1;
        this._applyFilter();
        this._updatePagination();
      });
    });

    // Project — header dropdown
    document.getElementById('projectSelect').addEventListener('change', async e => {
      await this._switchProject(e.target.value);
    });
    document.getElementById('newProjectBtn').addEventListener('click', () => this.openModal('newProjModal'));
    document.getElementById('createProjBtn').addEventListener('click', () => this._createProject());
    document.getElementById('deleteProjectBtn').addEventListener('click', () => this._deleteProject());
    document.getElementById('newProjName').addEventListener('keydown', e => {
      if (e.key === 'Enter') this._createProject();
    });

    // Project — right-nav panel
    this._initRightNavProjectPanel();

    // Header nav buttons
    document.getElementById('prevImgBtn')?.addEventListener('click', () => {
      if (state.currentIdx > 0) this.loadImage(state.currentIdx - 1);
    });
    document.getElementById('nextImgBtn')?.addEventListener('click', () => {
      if (state.currentIdx < state.media.length - 1) this.loadImage(state.currentIdx + 1);
    });

    // Complete button — mark image as reviewed
    document.getElementById('completeBtn')?.addEventListener('click', () => {
      if (state.currentIdx < 0) return;
      const item = state.media[state.currentIdx];
      if (!item) return;
      state.annotatedPaths.add(item.path);
      this._updateImageStatusBadge(item);
      this._updateNavBadges();
      this._updateAddToDatasetBtn();
      this._toast('Image marked as complete', 'success');
      // Auto-advance
      if (state.currentIdx < state.media.length - 1) {
        setTimeout(() => this.loadImage(state.currentIdx + 1), 300);
      }
    });

    // Add to dataset button
    document.getElementById('addToDatasetBtn')?.addEventListener('click', () => {
      // If we're in a locked job, use the proper batch dataset modal
      if (state.activeJobId != null) {
        this._selectBatchForDataset(state.activeJobId, null);
      } else {
        this.openSplit();  // all-project split flow
      }
    });
    // Header "Dataset" button — same logic
    document.getElementById('addToDatasetHdrBtn')?.addEventListener('click', () => {
      if (state.activeJobId != null) {
        this._selectBatchForDataset(state.activeJobId, null);
      } else {
        this.openSplit();
      }
    });

    // ── ATD Floating panel (new inline Add to Dataset panel) ─────────────────
    this._bindAtdPanel();
  },

  // ── Inline "Add to Dataset" floating panel ──────────────────────────────
  _bindAtdPanel() {
    const pill       = document.getElementById('atdPill');
    const panel      = document.getElementById('atdPanel');
    const closeBtn   = document.getElementById('atdPanelClose');
    const cancelBtn  = document.getElementById('atdCancelBtn');
    const confirmBtn = document.getElementById('atdConfirmBtn');
    const caret      = document.getElementById('atdPillCaret');
    if (!pill || !panel) return;

    // ── Open / close helpers ───────────────────────────────────────────────
    const openPanel = () => {
      panel.style.display = '';
      requestAnimationFrame(() => panel.classList.add('atd-panel-visible'));
      if (caret) caret.style.transform = 'rotate(180deg)';
      this._atdRefreshStats();
      this._atdSyncSliders();
    };
    const closePanel = () => {
      panel.classList.remove('atd-panel-visible');
      setTimeout(() => { panel.style.display = 'none'; }, 220);
      if (caret) caret.style.transform = '';
    };

    pill.addEventListener('click', () => {
      const isOpen = panel.classList.contains('atd-panel-visible');
      isOpen ? closePanel() : openPanel();
    });
    closeBtn?.addEventListener('click', closePanel);
    cancelBtn?.addEventListener('click', closePanel);

    // ── Slider sync ────────────────────────────────────────────────────────
    const sliders = [
      { slider: 'atdTrainSlider', pct: 'atdTrainPct', preview: 'atdPreviewTrain' },
      { slider: 'atdValSlider',   pct: 'atdValPct',   preview: 'atdPreviewVal'   },
      { slider: 'atdTestSlider',  pct: 'atdTestPct',  preview: 'atdPreviewTest'  },
    ];
    const syncSliders = () => {
      const t = parseInt(document.getElementById('atdTrainSlider')?.value || 70);
      const v = parseInt(document.getElementById('atdValSlider')?.value   || 15);
      const s = parseInt(document.getElementById('atdTestSlider')?.value  || 15);
      document.getElementById('atdTrainPct').textContent = t + '%';
      document.getElementById('atdValPct').textContent   = v + '%';
      document.getElementById('atdTestPct').textContent  = s + '%';
      document.getElementById('atdPreviewTrain').style.width = t + '%';
      document.getElementById('atdPreviewVal').style.width   = v + '%';
      document.getElementById('atdPreviewTest').style.width  = s + '%';
      const ok = Math.abs(t + v + s - 100) <= 1;
      const errEl = document.getElementById('atdRatioErr');
      if (errEl) errEl.style.display = ok ? 'none' : '';
      if (confirmBtn) confirmBtn.disabled = !ok;
      return ok;
    };
    sliders.forEach(({ slider }) => {
      document.getElementById(slider)?.addEventListener('input', syncSliders);
    });
    this._atdSyncSliders = syncSliders;

    // ── Refresh stats from current job ─────────────────────────────────────
    this._atdRefreshStats = async () => {
      const annotated = state.annotatedPaths.size;
      const total     = state.listTotal || state.media.length;
      const raw       = total - annotated;
      const pct       = total > 0 ? Math.round(annotated / total * 100) : 0;

      const setEl = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
      setEl('atdStatAnnotated', annotated);
      setEl('atdStatRaw',       raw);
      setEl('atdStatTotal',     total);
      const fill = document.getElementById('atdProgressFill');
      if (fill) fill.style.width = pct + '%';

      // If we have a locked job, also fetch fresh server counts
      if (state.activeJobId != null) {
        try {
          const r = await fetch(`/api/uploads?project=${encodeURIComponent(state.project)}`);
          if (r.ok) {
            const batches = await r.json();
            const b = batches.find(x => x.upload_id === state.activeJobId);
            if (b) {
              const a2 = b.annotated || 0;
              const t2 = b.total     || total;
              setEl('atdStatAnnotated', a2);
              setEl('atdStatRaw',       t2 - a2);
              setEl('atdStatTotal',     t2);
              const p2 = t2 > 0 ? Math.round(a2 / t2 * 100) : 0;
              if (fill) fill.style.width = p2 + '%';
            }
          }
        } catch(e) { /* use local counts */ }
      }
    };

    // ── Confirm → create dataset ───────────────────────────────────────────
    confirmBtn?.addEventListener('click', async () => {
      const t = parseInt(document.getElementById('atdTrainSlider')?.value || 70);
      const v = parseInt(document.getElementById('atdValSlider')?.value   || 15);
      const s = parseInt(document.getElementById('atdTestSlider')?.value  || 15);
      if (Math.abs(t + v + s - 100) > 1) {
        document.getElementById('atdRatioErr').style.display = '';
        return;
      }

      // ── CRITICAL: flush any pending debounced save BEFORE reading from disk ──
      // _triggerSave has a 600 ms delay. If the user annotated and immediately
      // clicked "Create Dataset", the last annotation is still only in memory.
      // Force-save NOW so the backend sees it on disk.
      clearTimeout(state.saveTimer);
      if (state.currentIdx >= 0 && state.imgW > 0 && state.imgH > 0) {
        await this._saveCurrentAnnotations();
      }

      // ── Resolve which upload batch to add ─────────────────────────────────
      let uploadId = state.activeJobId;

      if (uploadId == null) {
        // Not locked to a specific job. Use the current image's job name to find
        // the correct batch — much more reliable than "most recent by id".
        const currentItem = state.media[state.currentIdx];
        const jobName = currentItem?.job;

        if (jobName) {
          // Fetch fresh batch list to find the right upload_id
          try {
            const rb = await fetch(`/api/uploads?project=${encodeURIComponent(state.project)}`);
            if (rb.ok) {
              const batches = await rb.json();
              state._uploadBatches = batches;
              const match = batches.find(b => b.job_name === jobName);
              if (match) uploadId = match.upload_id;
            }
          } catch(e) { /* fall through */ }
        }

        // Last resort: most recent batch
        if (uploadId == null && state._uploadBatches?.length > 0) {
          uploadId = [...state._uploadBatches].sort((a, b) => b.upload_id - a.upload_id)[0].upload_id;
        }
      }

      if (uploadId == null) {
        this._toast('No active job found — open a batch from the Upload page first', 'warn');
        return;
      }

      confirmBtn.disabled = true;
      confirmBtn.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i> Creating…';

      try {
        const r = await fetch(`/api/uploads/${uploadId}/add_to_dataset`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            project: state.project,
            train: t / 100,
            val:   v / 100,
            test:  s / 100,
          }),
        });
        const d = await r.json();
        if (d.success) {
          const sc    = d.split_counts || {};
          const moved = d.moved_annotated || 0;
          const kept  = d.remaining_raw   || 0;
          this._toast(
            `Dataset created: ${moved} image${moved !== 1 ? 's' : ''} → ` +
            `train:${sc.train||0} · val:${sc.valid||0} · test:${sc.test||0}` +
            (kept > 0 ? ` · ${kept} raw remain in Active Work` : ''),
            'success'
          );
          closePanel();
          state.activeJobId = null;
          await this._loadMedia();
          await this._loadUploadBatches?.();
          await this._loadCompletedDatasets?.();
          await this._loadProjectsPanel?.();
          this._updateAddToDatasetBtn();
        } else {
          this._toast(d.error || 'Failed to create dataset', 'error');
        }
      } catch(e) {
        this._toast('Network error — dataset not created', 'error');
      } finally {
        confirmBtn.disabled = false;
        confirmBtn.innerHTML = '<i class="fas fa-check"></i> Create Dataset';
      }
    });

    // Expose so _updateAddToDatasetBtn can close the panel on hide
    this._atdClosePanel = closePanel;
  },

  _bindSplitSliders() {
    const pairs = [
      ['trainSlider','trainNum','trainPct'],
      ['valSlider',  'valNum',  'valPct'],
      ['testSlider', 'testNum', 'testPct'],
    ];
    const sync = () => {
      const tv = parseFloat(document.getElementById('trainNum').value)||0;
      const vv = parseFloat(document.getElementById('valNum').value)||0;
      const tt = parseFloat(document.getElementById('testNum').value)||0;
      document.getElementById('trainPct').textContent = Math.round(tv*100)+'%';
      document.getElementById('valPct').textContent   = Math.round(vv*100)+'%';
      document.getElementById('testPct').textContent  = Math.round(tt*100)+'%';
      document.getElementById('trainSlider').value = Math.round(tv*100);
      document.getElementById('valSlider').value   = Math.round(vv*100);
      document.getElementById('testSlider').value  = Math.round(tt*100);
      const ok = Math.abs(tv+vv+tt-1.0) <= 0.01;
      document.getElementById('ratioErr').style.display = ok ? 'none' : '';
    };
    pairs.forEach(([sid, nid]) => {
      document.getElementById(sid).addEventListener('input', e => {
        document.getElementById(nid).value = (parseInt(e.target.value)/100).toFixed(2);
        sync();
      });
      document.getElementById(nid).addEventListener('input', sync);
    });
  },

  /* ── SIDEBAR RESIZERS ── */
  _bindSidebars() {
    // ── Drag-to-resize ────────────────────────────────────────────────────────
    const makeResizer = (handleId, sidebarId, prop, min, max, flip = false) => {
      const handle  = document.getElementById(handleId);
      const sidebar = document.getElementById(sidebarId);
      if (!handle || !sidebar) return;
      let dragging = false, startX = 0, startW = 0;
      handle.addEventListener('mousedown', e => {
        if (sidebar.classList.contains('collapsed')) return;
        dragging = true; startX = e.clientX;
        startW = sidebar.offsetWidth; e.preventDefault();
      });
      document.addEventListener('mousemove', e => {
        if (!dragging) return;
        const dx = flip ? (startX - e.clientX) : (e.clientX - startX);
        const nw = Math.max(min, Math.min(max, startW + dx));
        document.documentElement.style.setProperty(prop, nw + 'px');
      });
      document.addEventListener('mouseup', () => { dragging = false; });
    };
    makeResizer('resizeLeft',  'sidebarLeft',  '--left-w',  160, 420);
    makeResizer('resizeRight', 'sidebarRight', '--right-w', 200, 500, true);

    // ── Left sidebar collapse ────────────────────────────────────────────────
    const leftSb      = document.getElementById('sidebarLeft');
    const leftToggle  = document.getElementById('leftSbToggle');
    const leftExpand  = document.getElementById('leftSbExpand');
    const leftHead    = document.getElementById('leftSbHead');

    const LKEY = 'annomaster_left_collapsed';
    const RKEY = 'annomaster_right_collapsed';
    const CKEY_CLS  = 'annomaster_cls_collapsed';
    const CKEY_ANNO = 'annomaster_anno_collapsed';

    const setLeftCollapsed = (collapsed) => {
      if (!leftSb) return;
      leftSb.classList.toggle('collapsed', collapsed);
      try { localStorage.setItem(LKEY, collapsed ? '1' : '0'); } catch(e) {}
      // Keep strip count in sync
      const strip = document.getElementById('totalCountStrip');
      const badge = document.getElementById('totalCount');
      if (strip && badge) strip.textContent = badge.textContent;
    };

    if (leftToggle) leftToggle.addEventListener('click', e => {
      e.stopPropagation();
      setLeftCollapsed(!leftSb.classList.contains('collapsed'));
    });
    if (leftExpand) leftExpand.addEventListener('click', () => setLeftCollapsed(false));

    // Restore left state
    try { if (localStorage.getItem(LKEY) === '1') setLeftCollapsed(true); } catch(e) {}

    // ── Right sidebar collapse ───────────────────────────────────────────────
    const rightSb      = document.getElementById('sidebarRight');
    const rightToggle  = document.getElementById('rightSbToggle');
    const restoreTab   = document.getElementById('rsbRestoreTab');
    const workspace    = document.querySelector('.workspace');

    const setRightCollapsed = (collapsed) => {
      if (!rightSb) return;
      rightSb.classList.toggle('collapsed', collapsed);
      workspace?.classList.toggle('right-sb-collapsed', collapsed);

      // Show/hide restore tab with a tiny delay so slide finishes first
      if (restoreTab) {
        if (collapsed) {
          restoreTab.style.display = 'flex';
          requestAnimationFrame(() => restoreTab.classList.add('visible'));
        } else {
          restoreTab.classList.remove('visible');
          // Hide after transition completes
          setTimeout(() => {
            if (!rightSb.classList.contains('collapsed')) {
              restoreTab.style.display = 'none';
            }
          }, 280);
        }
      }

      // Manage panel visibility
      const panels = rightSb.querySelectorAll('.rp-panel');
      panels.forEach(p => { p.style.display = collapsed ? 'none' : ''; });
      if (!collapsed) {
        const active = rightSb.querySelector('.rp-tab.active');
        if (active) {
          const id = 'rpt-' + active.dataset.rpt;
          const panel = document.getElementById(id);
          if (panel) panel.style.display = 'flex';
        }
      }

      // Flip the tab-bar collapse icon
      const icon = rightToggle?.querySelector('i');
      if (icon) {
        icon.className = collapsed ? 'fas fa-chevron-left' : 'fas fa-chevron-right';
      }

      try { localStorage.setItem(RKEY, collapsed ? '1' : '0'); } catch(e) {}
    };

    if (rightToggle) rightToggle.addEventListener('click', e => {
      e.stopPropagation();
      setRightCollapsed(!rightSb.classList.contains('collapsed'));
    });
    if (restoreTab) restoreTab.addEventListener('click', () => setRightCollapsed(false));

    // Restore right state
    try { if (localStorage.getItem(RKEY) === '1') setRightCollapsed(true); } catch(e) {}

    // ── Section collapse: Classes + Annotations ──────────────────────────────
    const bindSectionCollapse = (headId, bodyId, storageKey, startCollapsed = false) => {
      const head = document.getElementById(headId);
      const body = document.getElementById(bodyId);
      if (!head || !body) return;
      // Support both old .section-collapse-btn and new .ml-chevron icon
      const btn     = head.querySelector('.section-collapse-btn');
      const chevron = head.querySelector('.ml-chevron');

      const setCollapsed = (collapsed, animate = true) => {
        if (!animate) {
          body.style.transition = 'none';
          if (chevron) chevron.style.transition = 'none';
        }
        body.classList.toggle('collapsed', collapsed);
        // Remove startup class so transitions work
        body.classList.remove('ml-sub-body-collapsed');
        if (btn)     btn.classList.toggle('rotated', collapsed);
        if (chevron) chevron.classList.toggle('collapsed', collapsed);
        if (!animate) {
          requestAnimationFrame(() => {
            body.style.transition = '';
            if (chevron) chevron.style.transition = '';
          });
        }
        try { localStorage.setItem(storageKey, collapsed ? '1' : '0'); } catch(e) {}
      };

      head.addEventListener('click', () => setCollapsed(!body.classList.contains('collapsed') && !body.classList.contains('ml-sub-body-collapsed')));

      // Restore state (no animation on load)
      try {
        const saved = localStorage.getItem(storageKey);
        if (saved === '1' || (saved === null && startCollapsed)) {
          setCollapsed(true, false);
        } else if (saved === null && !startCollapsed) {
          // first load — ensure not collapsed
          body.classList.remove('ml-sub-body-collapsed');
        }
      } catch(e) {
        if (startCollapsed) setCollapsed(true, false);
      }
    };

    // Right sidebar: Classes and Annotations sections
    bindSectionCollapse('clsPanelHead',  'clsBody',  CKEY_CLS);
    bindSectionCollapse('annoPanelHead', 'annoBody', CKEY_ANNO);

    // Left sidebar: Media Library sub-sections
    const MKEY_OVERVIEW = 'annomaster_ml_overview';
    const MKEY_FILTER   = 'annomaster_ml_filter';
    const MKEY_UPLOAD   = 'annomaster_ml_upload';
    const MKEY_IMAGES   = 'annomaster_ml_images';
    bindSectionCollapse('mlOverviewHead', 'mlOverviewBody', MKEY_OVERVIEW, false);
    bindSectionCollapse('mlFilterHead',   'mlFilterBody',   MKEY_FILTER,   false);
    bindSectionCollapse('mlUploadHead',   'mlUploadBody',   MKEY_UPLOAD,   true);  // starts collapsed
    bindSectionCollapse('mlImagesHead',   'mlImagesBody',   MKEY_IMAGES,   false);

    // Keep strip badge in sync whenever totalCount changes
    const totalBadge = document.getElementById('totalCount');
    if (totalBadge) {
      new MutationObserver(() => {
        const strip = document.getElementById('totalCountStrip');
        if (strip) strip.textContent = totalBadge.textContent;
      }).observe(totalBadge, { childList: true, characterData: true, subtree: true });
    }
  },

  /* ── FILE UPLOAD ── */
  async _handleFilesDrop(files) {
    const arr      = Array.from(files);
    const images   = arr.filter(f => /\.(jpe?g|png|bmp|tiff?|webp)$/i.test(f.name));
    const videos   = arr.filter(f => /\.(mp4|avi|mov|mkv|webm)$/i.test(f.name));
    const labels   = arr.filter(f => f.name.endsWith('.txt') && f.name !== 'classes.txt');
    const yamlFile = arr.find(f => f.name === 'data.yaml' || f.name === 'data.yml');
    const classTxt = arr.find(f => f.name === 'classes.txt');
    const isYolo   = labels.length > 0 || !!yamlFile || !!classTxt;

    if (videos.length && !images.length && !isYolo) { this._openVideoModal(videos); return; }
    if (!images.length) { this._toast('No supported image files found','warn'); return; }

    const prog = document.getElementById('uploadProg');
    const fill = document.getElementById('uprogFill');
    const text = document.getElementById('uprogText');
    if (prog) prog.style.display = '';
    if (text) text.textContent = 'Creating upload batch…';

    // Show fullscreen overlay
    const _ov = document.getElementById('uploadOverlay');
    const _ovText = document.getElementById('uploadOverlayText');
    const _ovPct  = document.getElementById('uploadOverlayPct');
    const _ovSub  = document.getElementById('uploadOverlaySub');
    const _ovBar  = document.getElementById('uploadOverlayBar');
    const _showOv = (txt, pct, sub) => {
      if (_ov)     { _ov.style.display = 'flex'; }
      if (_ovText) _ovText.textContent = txt || 'Uploading…';
      if (_ovPct)  _ovPct.textContent  = (pct||0) + '%';
      if (_ovSub)  _ovSub.textContent  = sub || '';
      if (_ovBar)  _ovBar.style.width  = (pct||0) + '%';
    };
    const _hideOv = () => { if (_ov) _ov.style.display = 'none'; };
    // NOTE: overlay is shown AFTER user confirms any detection modal, not here

    // ── YOLO / labeled folder upload ─────────────────────────────────────────
    if (isYolo) {
      // Show detection analysis modal before uploading
      if (prog) prog.style.display = 'none';
      const clsFromYaml = yamlFile ? await this._parseYamlClasses(yamlFile) : [];
      // Analyze structure
      const hasLabels = labels.length > 0;
      const splitFolders = {};
      images.forEach(f => {
        const parts = (f.webkitRelativePath || f.name).split('/');
        for (const p of parts) {
          if (['train','valid','test','validation'].includes(p)) {
            const sp = p === 'validation' ? 'valid' : p;
            splitFolders[sp] = (splitFolders[sp]||0) + 1;
          }
        }
      });
      const isYoloDataset = Object.keys(splitFolders).length > 0;
      const confirmed = await this._showUploadDetectionModal({
        type:         isYoloDataset ? 'YOLO Dataset' : (hasLabels ? 'Mixed (Images + Labels)' : 'Images + Classes'),
        images:       images.length,
        labels:       labels.length,
        classes:      clsFromYaml,
        splitFolders,
        hasYaml:      !!yamlFile,
        splits:       Object.keys(splitFolders).length > 0
          ? Object.fromEntries(Object.entries(splitFolders).map(([sp,n]) => [sp, {images:n, matched:n}]))
          : {},
        warnings:     [],
        filename:     (images[0]?.webkitRelativePath||'').split('/')[0] || '',
      });
      if (!confirmed) { _hideOv(); return; }
      if (prog) prog.style.display = '';
      if (text) text.textContent = 'Creating upload batch…';
      _showOv('Uploading…', 0, '');

      // ── CRITICAL: For YOLO datasets, images and labels MUST be sent together
      // in the same request so the backend can match img→label pairs.
      // We group by split (train/valid/test/unsplit) and send each split as one batch.
      // data.yaml + classes.txt are included in EVERY request so classes are always parsed.

      const extraFiles = [...(yamlFile?[yamlFile]:[]), ...(classTxt?[classTxt]:[])];

      // Group files by split folder
      const splitGroups = {};  // 'train'|'valid'|'test'|'_flat' → {images:[], labels:[]}
      const allImgAndLbl = [...images, ...labels];
      for (const f of allImgAndLbl) {
        const relPath = f.webkitRelativePath || f.name;
        const parts   = relPath.split('/');
        let   split   = '_flat';
        for (const p of parts) {
          const lp = p.toLowerCase();
          if (['train','valid','val','test','validation'].includes(lp)) {
            split = (lp === 'val' || lp === 'validation') ? 'valid' : lp;
            break;
          }
        }
        if (!splitGroups[split]) splitGroups[split] = { images: [], labels: [] };
        if (/\.(jpe?g|png|bmp|tiff?|webp)$/i.test(f.name)) {
          splitGroups[split].images.push(f);
        } else {
          splitGroups[split].labels.push(f);
        }
      }

      // Create the batch first
      let uploadId = null;
      try {
        const br = await fetch('/api/upload/create_batch', {
          method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({project: state.project, source:'folder'}),
        });
        const bd = await br.json();
        if (bd.success) uploadId = bd.batch.upload_id;
      } catch(e) {}

      // ── Chunked upload: 40 images+labels per request (handles 700+ image datasets) ──
      let lastResult  = null;
      let totalDone   = 0;
      const totalImgs = images.length;
      const CHUNK     = 40;

      // Build flat {imgFile, label|null} pairs
      const allPairs = [];
      for (const grp of Object.values(splitGroups)) {
        const lblMap = {};
        grp.labels.forEach(f => { lblMap[f.name.replace(/\.txt$/i, '')] = f; });
        grp.images.forEach(imgFile => {
          const stem = imgFile.name.replace(/\.[^.]+$/, '');
          allPairs.push({ imgFile, label: lblMap[stem] || null });
        });
      }

      for (let ci = 0; ci < allPairs.length; ci += CHUNK) {
        const chunk   = allPairs.slice(ci, ci + CHUNK);
        const chunkNo  = Math.min(ci + CHUNK, allPairs.length);
        const pctDone  = Math.round(chunkNo / totalImgs * 100);
        const fd       = new FormData();
        fd.append('project', state.project);
        if (uploadId != null) fd.append('upload_id', uploadId);
        extraFiles.forEach(f => fd.append('files', f, f.webkitRelativePath || f.name));
        chunk.forEach(({ imgFile, label }) => {
          fd.append('files', imgFile, imgFile.webkitRelativePath || imgFile.name);
          if (label) fd.append('files', label, label.webkitRelativePath || label.name);
        });

        if (text) text.textContent = `Uploading images…`;
        if (fill) fill.style.width = pctDone + '%';
        const pctEl = document.getElementById('upPageProgPct');
        const subEl = document.getElementById('upPageProgSub');
        if (pctEl) pctEl.textContent = pctDone + '%';
        if (subEl) subEl.textContent = `${chunkNo} of ${totalImgs} images`;
        _showOv('Uploading images…', pctDone, `${chunkNo} of ${totalImgs} images`);

        try {
          const r = await fetch('/api/upload/folder', { method: 'POST', body: fd });
          const d = await r.json();
          if (d.success) {
            lastResult = d;
            if (uploadId == null && d.upload_id) uploadId = d.upload_id;
            if (d.classes?.length) { state.classes = d.classes; this._populateClassList(); }
          }
        } catch(e) { console.error('[Upload] chunk error:', e); }
        totalDone = chunkNo;
      }

      if (prog) prog.style.display = 'none';
      _hideOv();

      if (lastResult) {
        const preAnn = lastResult.annotated  || 0;
        const raw    = lastResult.unannotated || 0;
        this._upSetPageProgress(100, 'Import complete!', `${preAnn + raw} images (${preAnn} annotated · ${raw} raw)`, true);
        this._toast(`Import complete: ${preAnn + raw} images (${preAnn} pre-annotated · ${raw} raw)`, 'success');
        this._showUploadResultCard(lastResult, uploadId, 'folder');
      } else {
        this._upSetPageProgress(100, 'Upload complete!', `${images.length} images uploaded`, true);
        this._toast(`${images.length} images uploaded`, 'success');
      }
      await this._loadMedia();
      await this._loadUploadBatches();
      return;
    }

    // ── Plain image upload → job_N/images/ ───────────────────────────────────
    let uploadId = null;
    try {
      const br = await fetch('/api/upload/create_batch', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({project: state.project, source:'images'}),
      });
      const bd = await br.json();
      if (bd.success) uploadId = bd.batch.upload_id;
    } catch(e) {}

    this._upSetPageProgress(0, 'Uploading images…', `0 of ${images.length} images`);
    _showOv('Uploading images…', 0, `0 of ${images.length} images`);
    let done = 0;
    for (const img of images) {
      const fd = new FormData();
      fd.append('file', img);
      fd.append('project', state.project);
      if (uploadId != null) fd.append('upload_id', uploadId);
      try { await fetch('/api/upload', {method:'POST', body:fd}); } catch(e) {}
      done++;
      const pct2 = Math.round(done/images.length*100);
      if (fill) fill.style.width = pct2+'%';
      if (text) text.textContent = `Uploading images…`;
      this._upSetPageProgress(pct2, 'Uploading images…', `${done} of ${images.length} images`);
      _showOv('Uploading images…', pct2, `${done} of ${images.length} images`);
    }
    if (prog) prog.style.display = 'none';
    _hideOv();
    this._upSetPageProgress(100, 'Upload complete!', `${done} image${done>1?'s':''} uploaded`, true);
    this._toast(`${done} image${done>1?'s':''} uploaded → raw/`, 'success');
    await this._loadMedia();
    await this._loadUploadBatches();
  },


  _openVideoModal(videoFiles) {
    state._pendingVideos = videoFiles || [];
    this.openModal('uploadModal');
    this._renderVideoList();
    // Reset progress
    document.getElementById('extractProgress').style.display = 'none';
    document.getElementById('frameEstimate').style.display   = 'none';
    document.getElementById('startExtractBtn').disabled      = state._pendingVideos.length === 0;
  },

  _renderVideoList() {
    const list = document.getElementById('videoList');
    const btn  = document.getElementById('startExtractBtn');

    if (!state._pendingVideos || !state._pendingVideos.length) {
      list.style.display = 'none';
      btn.disabled = true;
      return;
    }
    list.style.display = '';
    list.innerHTML = '';
    state._pendingVideos.forEach((f, i) => {
      const size = f.size > 1e6 ? (f.size/1e6).toFixed(1)+' MB' : (f.size/1e3).toFixed(0)+' KB';
      const row = document.createElement('div');
      row.className = 'video-file-item';
      row.innerHTML = `
        <i class="fas fa-film"></i>
        <span class="vfi-name" title="${f.name}">${f.name}</span>
        <span class="vfi-size">${size}</span>
        <button class="vfi-remove" data-idx="${i}" title="Remove"><i class="fas fa-times"></i></button>`;
      row.querySelector('.vfi-remove').addEventListener('click', () => {
        state._pendingVideos.splice(i, 1);
        this._renderVideoList();
      });
      list.appendChild(row);
    });
    btn.disabled = false;
    this._updateFrameEstimate();
  },

  _updateFrameEstimate() {
    if (!state._pendingVideos?.length) return;
    const fps   = parseInt(document.getElementById('fpsSelect').value) || 5;
    const count = state._pendingVideos.length;
    const est   = document.getElementById('frameEstimate');
    const txt   = document.getElementById('frameEstimateText');
    est.style.display = '';
    txt.textContent   = `${count} video${count>1?'s':''} selected · will extract ~${fps} frame${fps>1?'s':''}/sec per video`;
  },

  async startExtractFrames() {
    const videos = state._pendingVideos;
    if (!videos || !videos.length) { this._toast('No videos selected', 'warn'); return; }

    const fps    = parseInt(document.getElementById('fpsSelect').value) || 5;
    const size   = document.getElementById('sizeSelect').value;
    const fmt    = document.getElementById('frameFormatSelect').value;
    const split  = document.getElementById('frameSplitSelect').value;
    const customW = parseInt(document.getElementById('customW').value) || 0;
    const customH = parseInt(document.getElementById('customH').value) || 0;

    // Show progress, disable button
    document.getElementById('extractProgress').style.display = '';
    document.getElementById('startExtractBtn').disabled      = true;
    document.querySelector('#uploadModal .ghost-btn').disabled = true;

    let totalFrames = 0;

    for (let i = 0; i < videos.length; i++) {
      const video = videos[i];
      document.getElementById('extractProgressFile').textContent = `File ${i+1}/${videos.length}: ${video.name}`;

      const fd = new FormData();
      fd.append('file',     video);
      fd.append('project',  state.project);
      fd.append('fps',      fps);
      fd.append('size',     size);
      fd.append('format',   fmt);
      fd.append('split',    split);
      if (size === 'custom') {
        fd.append('custom_w', customW);
        fd.append('custom_h', customH);
      }

      try {
        const r = await fetch('/api/extract_frames', {method:'POST', body:fd});
        const d = await r.json();
        if (d.success) {
          totalFrames += d.frames_extracted || 0;
          document.getElementById('extractProgFill').style.width = ((i+1)/videos.length*100) + '%';
          document.getElementById('extractProgressDetail').textContent =
            `${totalFrames} frames extracted so far…`;
          document.getElementById('extractProgressText').textContent =
            `Extracting video ${i+1} of ${videos.length}…`;
        } else {
          this._toast(`Failed on ${video.name}: ${d.error}`, 'error');
        }
      } catch(e) {
        this._toast(`Error on ${video.name}: ${e.message}`, 'error');
      }
    }

    // Done
    document.getElementById('extractProgressText').textContent = `Done! ${totalFrames} frames extracted.`;
    document.getElementById('extractProgFill').style.width = '100%';
    document.querySelector('#uploadModal .ghost-btn').disabled = false;

    state._pendingVideos = [];
    this._toast(`Extracted ${totalFrames} frames from ${videos.length} video${videos.length>1?'s':''}`, 'success');
    await this._loadMedia();
    await this._loadUploadBatches();

    // Close modal after 1.5 sec
    setTimeout(() => this.closeModal('uploadModal'), 1500);
  },

  /* ── PROJECT ── */
  async _createProject() {
    const name = document.getElementById('newProjName').value.trim();
    if (!name) return;
    try {
      const r = await fetch('/api/projects', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({name})
      });
      const d = await r.json();
      if (d.success) {
        this.closeModal('newProjModal');
        document.getElementById('newProjName').value = '';
        await this._switchProject(name);
        this._toast(`Project "${name}" created`, 'success');
      }
    } catch(e) { this._toast('Failed to create project', 'error'); }
  },

  async _deleteProject() {
    if (!confirm(`Delete project "${state.project}" and all its data? This cannot be undone.`)) return;
    try {
      await fetch('/api/projects', {
        method:'DELETE', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({name: state.project})
      });
      window.location.reload();
    } catch(e) { this._toast('Failed to delete project', 'error'); }
  },

};

/* ── BOOT ── */
document.addEventListener('DOMContentLoaded', () => app.init());
window.app = app;