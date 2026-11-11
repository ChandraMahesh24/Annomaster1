/**
 * AI ANNOTATE — prompted labelling (text prompting + box prompting).
 *
 * WHAT THIS IS, AND WHAT IT IS NOT
 * ════════════════════════════════
 * Smart Detect runs a fixed detector: the weights decide what the classes
 * are. This asks the opposite question — "find the thing I am naming" —
 * where the name is either a word ("forklift") or one example box drawn on
 * the frame. Two prompt types, one pipeline.
 *
 * It creates NO new annotation lifecycle. Every prediction is committed
 * through `Boxes.reconcile()`, exactly like a Smart Detect result, so it
 * lands as a SUGGESTION: dashed outline, counted as pending, written to
 * `.suggestions.json` rather than the `.txt`, and excluded from every
 * export until a human accepts it. Confirmed boxes are never touched, and
 * a previously rejected box is never re-suggested.
 *
 * WHY THE SLIDER FILTERS INSTEAD OF RE-RUNNING
 * ════════════════════════════════════════════
 * The server runs once at a low confidence FLOOR and returns everything
 * above it; `_raw` keeps that list. Dragging the slider re-filters `_raw`
 * locally, so the prediction count responds instantly — "higher confidence
 * means fewer predictions" — where a re-run would cost seconds per tick on
 * CPU.
 *
 * That makes raising the threshold a REMOVAL, which is the one genuinely
 * new rule here, and `_sync()` states it: a box may be withdrawn only if
 * it is still `suggested` AND this panel put it there in this session
 * (`_prun`, never serialised — after a reload the panel stops claiming
 * it). Anything the user has accepted stays: accepting is a human
 * decision and a slider must not undo one. Rejected stays rejected.
 */
const PromptAnnotate = (() => {
  const TEXT = 'text';
  const BOX = 'box';

  let _open = false;
  let _mode = TEXT;
  let _engine = null;
  let _engines = [];
  let _phrases = [];
  let _conf = 0.4;          // DISPLAY threshold, not the server's floor
  let _floor = 0.05;
  let _raw = [];            // last run's predictions, unfiltered
  let _runId = null;        // tags boxes this panel may still withdraw
  let _busy = false;
  let _settingsLoaded = false;
  let _saveTimer = null;
  let _prevMode = null;     // canvas mode to restore when leaving box-draw

  const POS_KEY = 'am_pabar_pos';
  const COL_KEY = 'am_pabar_collapsed';

  const $ = id => document.getElementById(id);

  // ── Small helpers ───────────────────────────────────────────────────────

  function _spec(id) {
    return _engines.find(e => e.id === (id || _engine)) || null;
  }

  function _supports(mode, id) {
    const s = _spec(id);
    return !s || (s.modes || []).includes(mode);
  }

  function _setError(msg) {
    const el = $('paError');
    if (!el) return;
    el.hidden = !msg;
    el.textContent = msg || '';
  }

  function _setMeta(msg) {
    const el = $('paMeta');
    if (el) el.textContent = msg || '—';
  }

  /* Persisted per project, like Smart Detect's settings: a project's
     prompt ("crate, pallet") is a property of what is being labelled, not
     of the browser it was typed in. Debounced — the slider fires on every
     tick. */
  function _persist(patch) {
    if (!patch) return;
    clearTimeout(_saveTimer);
    _saveTimer = setTimeout(async () => {
      try {
        await fetch(_p('/ai/prompt/settings'), {
          method: 'PUT', headers: _authH(), body: JSON.stringify(patch),
        });
      } catch (e) { /* best effort */ }
    }, 400);
  }

  // ── Engine list ─────────────────────────────────────────────────────────

  async function _loadEngines() {
    const sel = $('paEngineSelect');
    try {
      const r = await fetch('/api/ai/prompt/engines', { headers: _authH() });
      const d = await r.json();
      _engines = d.engines || [];
      _floor = typeof d.conf_floor === 'number' ? d.conf_floor : 0.05;
      if (!_engine || !_spec(_engine)) _engine = d.default || (_engines[0] || {}).id;
    } catch (e) {
      _setError('Could not read the prompt engine list from the server.');
      return;
    }
    if (!sel) return;
    sel.innerHTML = '';
    _engines.forEach(e => {
      const o = document.createElement('option');
      o.value = e.id;
      // An engine that needs a file the server does not have is shown but
      // marked, rather than hidden — "why is SAM3 missing?" is a worse
      // question than "SAM3 (needs weights)".
      o.textContent = e.installed ? e.label
        : (e.download_mb ? `${e.label} (${e.download_mb} MB download)`
                         : `${e.label} (needs weights)`);
      sel.appendChild(o);
    });
    sel.value = _engine;
    _syncEngineUI();
  }

  /* Reflect the selected engine: which tabs it can serve, and what a first
     run will cost. The download warning matters — a text prompt on a cold
     YOLOE pulls a ~600 MB encoder, and a silent 10-minute spinner is
     indistinguishable from a hang. */
  function _syncEngineUI() {
    const s = _spec();
    if (!s) return;

    [[TEXT, 'paTabText'], [BOX, 'paTabBox']].forEach(([m, id]) => {
      const btn = $(id);
      if (!btn) return;
      const ok = (s.modes || []).includes(m);
      btn.disabled = !ok;
      btn.title = ok ? '' : `${s.label} does not support ${m} prompting.`;
    });

    // Switched to an engine that cannot do the open tab → move the user.
    if (!_supports(_mode)) _setPromptMode(_supports(TEXT) ? TEXT : BOX);

    const bits = [s.blurb];
    if (!s.installed) {
      bits.push(s.error ? s.error
        : `First run downloads ${s.weights} (${s.download_mb} MB).`);
    }
    const enc = s.text_encoder;
    if (_mode === TEXT && enc && enc.installed === false) {
      bits.push(`Text prompting also downloads ${enc.name} (~${enc.mb} MB) once.`);
    }
    // Without this, a minutes-long CPU run is indistinguishable from a hang.
    if (s.speed === 'slow') bits.push('Slow without a GPU — minutes per image.');
    _setMeta(bits.filter(Boolean).join(' · '));
    _setError('');
  }

  // ── Phrase chips ────────────────────────────────────────────────────────

  function _renderChips() {
    const wrap = $('paChips');
    if (!wrap) return;
    wrap.innerHTML = '';
    _phrases.forEach((p, i) => {
      const chip = document.createElement('span');
      chip.className = 'pa-chip';
      chip.innerHTML = `<span></span><button type="button" title="Remove">
                        <i class="fas fa-times"></i></button>`;
      chip.querySelector('span').textContent = p;
      chip.querySelector('button').addEventListener('click', () => {
        _phrases.splice(i, 1);
        _renderChips();
        _persist({ phrases: _phrases });
      });
      wrap.appendChild(chip);
    });
  }

  function _addPhrase(raw) {
    // Commas split, so "person, helmet" in one go does what it looks like.
    const parts = String(raw || '').split(',').map(s => s.trim()).filter(Boolean);
    let added = false;
    for (const p of parts) {
      if (_phrases.some(x => x.toLowerCase() === p.toLowerCase())) continue;
      _phrases.push(p);
      added = true;
    }
    if (added) { _renderChips(); _persist({ phrases: _phrases }); }
  }

  // ── Box-prompt exemplars ────────────────────────────────────────────────

  function _syncExemplarUI() {
    const n = (state.promptBoxes || []).length;
    const c = $('paExemplarCount');
    if (c) c.textContent = `${n} example${n === 1 ? '' : 's'}`;
    const t = $('paDrawToggle');
    if (t) t.classList.toggle('is-active', state.mode === 'prompt');
    const l = $('paDrawToggleLabel');
    if (l) l.textContent = state.mode === 'prompt' ? 'Drawing — click to stop'
                                                   : 'Draw example box';
  }

  function _toggleDraw() {
    if (state.mode === 'prompt') {
      app.setMode(_prevMode || 'bbox');
    } else {
      _prevMode = state.mode;
      app.setMode('prompt');
    }
    _syncExemplarUI();
  }

  // ── Committing predictions ──────────────────────────────────────────────

  /* Map one server prediction onto a canvas box, creating the class if the
     project does not have it yet. Prompted labels are new by definition —
     the user just typed a word, or named an example — so class creation is
     the normal path here, not an edge case. */
  function _toBox(p) {
    let cls = state.classes.find(
      c => c.name.toLowerCase() === String(p.class_name).toLowerCase());
    if (!cls) {
      const palette = [[251, 191, 36], [34, 197, 225], [99, 102, 241],
                       [74, 222, 128], [236, 72, 153]];
      const id = state.classes.length
        ? Math.max(...state.classes.map(c => c.id)) + 1 : 0;
      cls = { id, name: p.class_name, color: palette[id % palette.length] };
      state.classes.push(cls);
      if (typeof app._populateClassList === 'function') app._populateClassList();
    }
    const ix = (p.x_center - p.width / 2) * state.imgW;
    const iy = (p.y_center - p.height / 2) * state.imgH;
    return {
      id: Math.random().toString(36).slice(2),
      cls: cls.id, type: 'bbox',
      x: Math.max(0, ix), y: Math.max(0, iy),
      w: Math.min(p.width * state.imgW, state.imgW - ix),
      h: Math.min(p.height * state.imgH, state.imgH - iy),
      conf: p.conf,
      _prun: _runId,       // this run owns the box, so the slider may drop it
    };
  }

  /* Make the canvas agree with (last run ∩ current threshold).
     Two directions:
       ADD    — everything above threshold, through Boxes.reconcile(), so
                confirmed work is never touched and rejected boxes are
                never re-suggested.
       REMOVE — only boxes still `suggested` that this run added and that
                have now fallen below the threshold. An accepted box is a
                human decision; the slider does not get to reverse it. */
  function _sync(announce) {
    if (!state.imgW || !state.imgH) return;

    const keep = _raw.filter(p => p.conf >= _conf);
    const detections = keep.map(_toBox);

    const { boxes, summary } = Boxes.reconcile(state.bboxes, detections);
    state.bboxes = boxes;

    /* `_prun` marks a box this panel put on the canvas in THIS session. It
       is deliberately not serialised, so after a reload the panel no
       longer claims those boxes and the slider cannot withdraw them —
       by then they are just suggestions like any other. */
    const dropped = state.bboxes.filter(b =>
      b._prun && Boxes.isSuggested(b) &&
      typeof b.conf === 'number' && b.conf < _conf);
    if (dropped.length) {
      const gone = new Set(dropped.map(b => b.id));
      state.bboxes = state.bboxes.filter(b => !gone.has(b.id));
      if (state.selectedId && gone.has(state.selectedId)) state.selectedId = null;
    }

    app._render();
    app._updateAnnoList();
    app._updateClassCounts();
    app._statusObjects();
    app._updateReviewBanner();
    app._triggerSave();

    if (announce) {
      const bits = [];
      if (summary.added) bits.push(`${summary.added} new`);
      if (summary.refreshed) bits.push(`${summary.refreshed} refreshed`);
      if (summary.skippedConfirmed) bits.push(`${summary.skippedConfirmed} already confirmed`);
      if (summary.skippedRejected) bits.push(`${summary.skippedRejected} previously rejected`);
      const msg = bits.length ? bits.join(' · ') : 'No changes';
      app._toast(summary.added ? `${summary.added} suggestion(s) to review` : msg,
                 summary.added ? 'info' : 'info');
      _setMeta(`${keep.length} of ${_raw.length} predictions shown · ${msg}`);
    } else if (_raw.length) {
      _setMeta(`${keep.length} of ${_raw.length} predictions shown`);
    }
  }

  // ── Run ─────────────────────────────────────────────────────────────────

  async function run() {
    if (_busy) return;
    const item = state.currentIdx >= 0 ? state.media[state.currentIdx] : null;
    if (!item) { _setError('Open an image first.'); return; }

    const body = { path: item.path, engine: _engine, mode: _mode, conf: _floor };
    if (_mode === TEXT) {
      // Whatever is half-typed in the field is clearly intended too.
      const typed = ($('paPhraseInput') || {}).value;
      if (typed && typed.trim()) { _addPhrase(typed); $('paPhraseInput').value = ''; }
      if (!_phrases.length) {
        _setError('Type what to look for, e.g. "person, helmet".');
        return;
      }
      body.phrases = _phrases;
    } else {
      const ex = state.promptBoxes || [];
      if (!ex.length) {
        _setError('Draw at least one example box first.');
        return;
      }
      body.boxes = ex.map(b => ({
        x1: b.x, y1: b.y, x2: b.x + b.w, y2: b.y + b.h, label: b.label,
      }));
    }

    _busy = true;
    _setError('');
    const btn = $('paRunBtn');
    const lbl = $('paRunLabel');
    if (btn) btn.disabled = true;
    const spec = _spec();
    const cold = spec && !spec.installed;
    if (lbl) lbl.textContent = cold ? 'Downloading model…' : 'Running…';
    _setMeta(cold ? 'First run — fetching weights, this happens once.'
           : (spec && spec.speed === 'slow')
             ? `Prompting ${spec.label} — this can take a few minutes on CPU…`
             : 'Prompting the model…');

    try {
      const r = await fetch(_p('/ai/prompt'), {
        method: 'POST', headers: _authH(), body: JSON.stringify(body),
      });
      const d = await r.json();
      if (!r.ok) {
        _setError(d.error || 'The prompt failed.');
        _setMeta('—');
        return;
      }
      _raw = (d.predictions || []).slice().sort((a, b) => b.conf - a.conf);
      _runId = 'pr' + Date.now().toString(36);
      app._pushHistory();
      _sync(true);
      if (!_raw.length) {
        _setMeta(`Nothing matched (${d.elapsed_ms} ms). Try different wording, ` +
                 'a different example box, or a lower confidence.');
      } else {
        _setMeta(`${_raw.filter(p => p.conf >= _conf).length} of ${_raw.length} ` +
                 `predictions shown · ${d.engine} · ${d.elapsed_ms} ms`);
      }
      // A finished run means the weights are now on the server, so the
      // "first run downloads N MB" warning must stop appearing. Marked on
      // the cached entry rather than by re-listing, because re-listing
      // rewrites the meta line and would wipe the result just reported.
      if (spec) spec.installed = true;
    } catch (e) {
      _setError('Could not reach the server: ' + e.message);
    } finally {
      _busy = false;
      if (btn) btn.disabled = false;
      if (lbl) lbl.textContent = 'Run prompt';
    }
  }

  // ── Mode + lifecycle ────────────────────────────────────────────────────

  function _setPromptMode(m) {
    _mode = (m === BOX) ? BOX : TEXT;
    ['paTabText', 'paTabBox'].forEach(id => {
      const btn = $(id);
      if (!btn) return;
      const on = btn.dataset.mode === _mode;
      btn.classList.toggle('is-active', on);
      btn.setAttribute('aria-selected', String(on));
    });
    const pt = $('paPaneText'), pb = $('paPaneBox');
    if (pt) pt.hidden = _mode !== TEXT;
    if (pb) pb.hidden = _mode !== BOX;
    // Leaving box mode should not leave the canvas armed for drawing.
    if (_mode !== BOX && state.mode === 'prompt') app.setMode(_prevMode || 'bbox');
    _syncExemplarUI();
    _persist({ mode: _mode });
  }

  /* A new frame invalidates everything: the predictions belonged to the
     previous image and the exemplars were drawn on it. Clearing here is
     what keeps the panel honest across navigation — the alternative,
     carrying them over, silently prompts one image with another's boxes. */
  function _onImageChanged() {
    _raw = [];
    _runId = null;
    app.clearPromptBoxes();
    _syncExemplarUI();
    // One owner for the pending count: it drives both AI panels' buttons.
    app._updateReviewBanner();
    if (_open) _setMeta(_spec() ? _spec().blurb : '—');
  }

  async function _loadSettings() {
    try {
      const r = await fetch(_p('/ai/prompt/settings'), { headers: _authH() });
      if (!r.ok) return;
      const d = await r.json();
      if (d.engine) _engine = d.engine;
      if (typeof d.conf === 'number') _conf = d.conf;
      if (d.mode) _mode = d.mode === BOX ? BOX : TEXT;
      if (Array.isArray(d.phrases)) _phrases = d.phrases.slice();
      _settingsLoaded = true;

      const cs = $('paConfSlider'), cv = $('paConfVal');
      if (cs) cs.value = Math.round(_conf * 100);
      if (cv) cv.textContent = `${Math.round(_conf * 100)}%`;
      _renderChips();
    } catch (e) { /* defaults stay in effect */ }
  }

  async function open() {
    _open = true;
    const bar = $('paBar');
    if (bar) bar.style.display = '';
    if (!_settingsLoaded) await _loadSettings();
    await _loadEngines();
    _setPromptMode(_mode);
    app._updateReviewBanner();
  }

  function close() {
    _open = false;
    const bar = $('paBar');
    if (bar) bar.style.display = 'none';
    if (state.mode === 'prompt') app.setMode(_prevMode || 'bbox');
    app.clearPromptBoxes();
    _raw = [];
    _runId = null;
    _syncExemplarUI();
  }

  // ── Drag + collapse ─────────────────────────────────────────────────────
  /* Same treatment as the Smart Detect bar, and for the same reason: every
     pixel of a floating panel is annotation area the user cannot see. The
     saved position is a viewport FRACTION, so a bar parked at the right
     edge of a wide monitor is not off-screen on a laptop. */
  function _clampIntoView(left, top, el) {
    const wrap = el.offsetParent || document.body;
    return {
      left: Math.min(Math.max(0, left), Math.max(0, wrap.clientWidth - el.offsetWidth)),
      top:  Math.min(Math.max(0, top),  Math.max(0, wrap.clientHeight - el.offsetHeight)),
    };
  }

  function _initDrag() {
    const bar = $('paBar'), handle = $('paBarHandle');
    if (!bar || !handle) return;
    let sx = 0, sy = 0, ox = 0, oy = 0, dragging = false;

    handle.addEventListener('mousedown', e => {
      if (e.target.closest('button, select, input, label')) return;
      if (window.innerWidth <= 639) return;
      e.preventDefault();
      const r = bar.getBoundingClientRect();
      const wr = (bar.offsetParent || document.body).getBoundingClientRect();
      ox = r.left - wr.left; oy = r.top - wr.top;
      sx = e.clientX; sy = e.clientY;
      dragging = true;
      bar.classList.add('is-moved', 'is-dragging');
      bar.style.left = ox + 'px';
      bar.style.top = oy + 'px';
    });

    window.addEventListener('mousemove', e => {
      if (!dragging) return;
      const pos = _clampIntoView(ox + (e.clientX - sx), oy + (e.clientY - sy), bar);
      bar.style.left = pos.left + 'px';
      bar.style.top = pos.top + 'px';
    });

    window.addEventListener('mouseup', () => {
      if (!dragging) return;
      dragging = false;
      bar.classList.remove('is-dragging');
      const wrap = bar.offsetParent || document.body;
      try {
        localStorage.setItem(POS_KEY, JSON.stringify({
          fx: parseFloat(bar.style.left) / Math.max(1, wrap.clientWidth),
          fy: parseFloat(bar.style.top) / Math.max(1, wrap.clientHeight),
        }));
      } catch (e) { /* private mode */ }
    });

    window.addEventListener('resize', () => {
      if (!bar.classList.contains('is-moved')) return;
      const pos = _clampIntoView(parseFloat(bar.style.left) || 0,
                                 parseFloat(bar.style.top) || 0, bar);
      bar.style.left = pos.left + 'px';
      bar.style.top = pos.top + 'px';
    });

    const btn = $('paBarCollapse');
    const setCollapsed = on => {
      bar.classList.toggle('is-collapsed', on);
      if (btn) {
        btn.setAttribute('aria-expanded', String(!on));
        btn.title = on ? 'Expand' : 'Collapse';
      }
      try { localStorage.setItem(COL_KEY, on ? '1' : '0'); } catch (e) {}
    };
    btn?.addEventListener('click', () =>
      setCollapsed(!bar.classList.contains('is-collapsed')));
    try {
      if (localStorage.getItem(COL_KEY) === '1') setCollapsed(true);
    } catch (e) {}

    if (window.innerWidth > 639) {
      let raw = null;
      try { raw = JSON.parse(localStorage.getItem(POS_KEY) || 'null'); } catch (e) {}
      if (raw && typeof raw.fx === 'number') {
        const wrap = bar.offsetParent || document.body;
        const pos = _clampIntoView(raw.fx * wrap.clientWidth,
                                   raw.fy * wrap.clientHeight, bar);
        bar.classList.add('is-moved');
        bar.style.left = pos.left + 'px';
        bar.style.top = pos.top + 'px';
      }
    }
  }

  // ── Init ────────────────────────────────────────────────────────────────

  function init() {
    if (!$('paBar')) return;      // not the annotate page

    $('promptAnnotateBtn')?.addEventListener('click', () => {
      if (_open) close(); else open();
    });
    $('paBarClose')?.addEventListener('click', close);
    _initDrag();

    $('paTabText')?.addEventListener('click', () => _setPromptMode(TEXT));
    $('paTabBox')?.addEventListener('click', () => _setPromptMode(BOX));

    $('paPhraseAdd')?.addEventListener('click', () => {
      const inp = $('paPhraseInput');
      if (!inp) return;
      _addPhrase(inp.value);
      inp.value = '';
      inp.focus();
    });
    $('paPhraseInput')?.addEventListener('keydown', e => {
      if (e.key === 'Enter') {
        e.preventDefault();
        _addPhrase(e.target.value);
        e.target.value = '';
      } else if (e.key === 'Backspace' && !e.target.value && _phrases.length) {
        _phrases.pop();
        _renderChips();
        _persist({ phrases: _phrases });
      }
    });

    $('paDrawToggle')?.addEventListener('click', _toggleDraw);
    $('paExemplarClear')?.addEventListener('click', () => {
      app.clearPromptBoxes();
      _syncExemplarUI();
    });

    // The slider only ever re-filters the cached run — no network call, so
    // it can respond on every tick.
    $('paConfSlider')?.addEventListener('input', e => {
      _conf = parseInt(e.target.value, 10) / 100;
      const v = $('paConfVal');
      if (v) v.textContent = `${Math.round(_conf * 100)}%`;
      _sync(false);
      _persist({ conf: _conf });
    });

    $('paRunBtn')?.addEventListener('click', run);
    $('paApproveBtn')?.addEventListener('click', () => {
      app.acceptAllSuggestions();   // itself refreshes the count
    });

    $('paEngineSelect')?.addEventListener('change', e => {
      _engine = e.target.value;
      _persist({ engine: _engine });
      _syncEngineUI();
    });

    // Canvas ↔ panel: the exemplar count lives on the canvas, the label
    // showing it lives here.
    app._onPromptBoxesChanged = _syncExemplarUI;
    app.onImageLoaded(_onImageChanged);
    // Pressing V or B leaves prompt mode without touching this panel, so
    // the "Drawing — click to stop" label would otherwise lie.
    app._onModeChanged = () => _syncExemplarUI();
  }

  return { init, open, close, run, isOpen: () => _open };
})();

document.addEventListener('DOMContentLoaded', () => PromptAnnotate.init());
