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
  let _examples = [];       // the project's saved box-prompt examples
  let _exPositive = true;   // next drawn example: "this is" (true) / "not this"
  let _auto = true;         // box tab: predict each image as it opens
  let _autoPending = false; // an image opened while a run was in flight
  let _savedMode = null;    // tab saved in project settings (applied by open())
  let _modeTouched = false; // the user picked a tab — saved settings must not override it

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
    if (s.device) {
      bits.push(s.device === 'cpu' ? 'Runs on CPU'
                                   : `Runs on GPU (${s.device_name || s.device})`);
    }
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

  // ── Box prompting: the project's example library (Roboflow-style) ───────
  /* Examples are saved per project on the server (core/box_examples.py) and
     used on EVERY image: draw "this is a 1_staff" on frame 12 and frame 40
     gets 1_staff suggestions. They are prompts, never annotations — they
     live in prompt_examples.json, not in any label file. On screen, the
     examples drawn on the current image are shown via state.promptBoxes
     (accent = "this is", danger = "not this"). */

  const _norm = p => String(p || '').replace(/\\/g, '/').replace(/^\/+/, '');
  const _cur = () => (state.currentIdx >= 0 ? state.media[state.currentIdx] : null);
  const _cls = id => state.classes.find(c => c.id === id) || null;

  function _selectedClass() {
    const id = state.selectedCls;
    return (id === null || id === undefined) ? null : _cls(id);
  }

  function _syncExemplarUI() {
    const t = $('paDrawToggle');
    if (t) t.classList.toggle('is-active', state.mode === 'prompt');
    const l = $('paDrawToggleLabel');
    if (l) l.textContent = state.mode === 'prompt' ? 'Drawing — click to stop'
                                                   : 'Draw example box';
    const sc = _selectedClass();
    const lab = $('paExClass');
    if (lab) {
      lab.textContent = sc ? `${_exPositive ? '' : 'not '}${sc.name}` : 'Pick a class';
      lab.classList.toggle('is-missing', !sc);
    }
    [['paExPos', true], ['paExNeg', false]].forEach(([id, v]) => {
      const b = $(id);
      if (!b) return;
      b.classList.toggle('is-active', _exPositive === v);
      b.setAttribute('aria-pressed', String(_exPositive === v));
    });
  }

  function _toggleDraw() {
    if (state.mode === 'prompt') {
      app.setMode(_prevMode || 'bbox');
    } else {
      if (!_selectedClass()) {
        _setError('Pick the class to teach in the class list first.');
        return;
      }
      _prevMode = state.mode;
      app.setMode('prompt');
    }
    _syncExemplarUI();
  }

  function _renderExamples() {
    const wrap = $('paExList');
    if (!wrap) return;
    const by = new Map();
    for (const e of _examples) {
      const s = by.get(e.class_id) || { pos: 0, neg: 0 };
      if (e.positive === false) s.neg++; else s.pos++;
      by.set(e.class_id, s);
    }
    wrap.innerHTML = '';
    if (!by.size) {
      const p = document.createElement('div');
      p.className = 'pa-ex-empty';
      p.textContent = 'No examples yet — pick a class and draw a box around one.';
      wrap.appendChild(p);
      return;
    }
    for (const [cid, s] of by) {
      const c = _cls(cid);
      const row = document.createElement('div');
      row.className = 'pa-ex-item';
      row.innerHTML = `<span class="pa-ex-dot"></span><span class="pa-ex-name"></span>
        <span class="pa-ex-n"></span>
        <button type="button" title="Remove all examples of this class"><i class="fas fa-times"></i></button>`;
      const col = c && Array.isArray(c.color) ? `rgb(${c.color.join(',')})` : 'currentColor';
      row.querySelector('.pa-ex-dot').style.background = col;
      row.querySelector('.pa-ex-name').textContent = c ? c.name : `class ${cid} (deleted)`;
      row.querySelector('.pa-ex-n').innerHTML =
        `${s.pos} example${s.pos === 1 ? '' : 's'}` + (s.neg ? ` · <span class="neg">${s.neg} not</span>` : '');
      row.querySelector('button').addEventListener('click', () =>
        _removeExamples({ class_id: cid }, `Remove every example of ${c ? c.name : 'this class'}?`));
      wrap.appendChild(row);
    }
  }

  /* Paint the current image's saved examples. Overwrites state.promptBoxes:
     on this panel every on-screen exemplar is a saved one. */
  function _showImageExamples() {
    const item = _cur();
    if (!_open || _mode !== BOX || !item || !state.imgW) {
      if (state.promptBoxes.length) app.clearPromptBoxes();
      return;
    }
    const here = _norm(item.path);
    state.promptBoxes = _examples.filter(e => e.image === here).map(e => {
      const c = _cls(e.class_id);
      const name = c ? c.name : `class ${e.class_id}`;
      return {
        x: e.box[0] * state.imgW, y: e.box[1] * state.imgH,
        w: (e.box[2] - e.box[0]) * state.imgW, h: (e.box[3] - e.box[1]) * state.imgH,
        positive: e.positive !== false, exId: e.id, label: name,
        tag: (e.positive === false ? 'not ' : 'example: ') + name,
      };
    });
    app._render();
    _syncExemplarUI();
  }

  async function _loadExamples() {
    try {
      const r = await fetch(_p('/ai/examples'), { headers: _authH() });
      const d = await r.json().catch(() => ({}));
      if (r.ok) _examples = d.examples || [];
    } catch (e) { /* keep what we had */ }
    _renderExamples();
    _showImageExamples();
  }

  async function _postExamples(path, boxes, okMsg) {
    try {
      const r = await fetch(_p('/ai/examples'), {
        method: 'POST', headers: _authH(),
        body: JSON.stringify({ image: path, boxes }),
      });
      const d = await r.json().catch(() => ({ error: `HTTP ${r.status}` }));
      if (!r.ok) throw new Error(d.error || `HTTP ${r.status}`);
      _examples = d.examples || _examples;
      _setError('');
      if (okMsg && d.added) app._toast(okMsg(d.added.length), 'success');
      return d.added || [];
    } catch (e) {
      _setError('Could not save the example: ' + e.message);
      return null;
    } finally {
      _renderExamples();
      _showImageExamples();
    }
  }

  async function _removeExamples(selector, question) {
    if (question && !confirm(question)) return;
    try {
      const r = await fetch(_p('/ai/examples'), {
        method: 'DELETE', headers: _authH(), body: JSON.stringify(selector),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.error || `HTTP ${r.status}`);
      _examples = d.examples || [];
      if (d.removed) app._toast(`${d.removed} example(s) removed`, 'info');
    } catch (e) {
      _setError('Could not remove examples: ' + e.message);
    }
    _renderExamples();
    _showImageExamples();
  }

  /* Canvas → panel: a box was just drawn in 'prompt' mode. Save every
     not-yet-saved one as an example of the selected class, then (if auto
     is on) re-predict this image right away so the user sees what the new
     example taught — the Roboflow feedback loop. */
  async function _onPromptBoxesChanged() {
    const fresh = (state.promptBoxes || []).filter(b => !b.exId);
    if (!fresh.length) { _syncExemplarUI(); return; }
    const item = _cur();
    const sc = _selectedClass();
    if (!item || !sc || !state.imgW) {
      state.promptBoxes = state.promptBoxes.filter(b => b.exId);
      app._render();
      _setError('Pick the class to teach in the class list, then draw the example.');
      return;
    }
    const W = state.imgW, H = state.imgH;
    const boxes = fresh.map(b => ({
      x1: b.x / W, y1: b.y / H, x2: (b.x + b.w) / W, y2: (b.y + b.h) / H,
      class_id: sc.id, positive: _exPositive,
    }));
    const added = await _postExamples(item.path, boxes,
      n => `${n} ${_exPositive ? '' : '"not" '}example${n === 1 ? '' : 's'} of ${sc.name} saved`);
    if (added && added.length && _auto) run();
  }

  /* "Use my boxes": the user's confirmed boxes on this image become examples
     in one click — the fastest way to teach from work already done. */
  async function _useMyBoxes() {
    const item = _cur();
    if (!item || !state.imgW) { _setError('Open an image first.'); return; }
    const mine = (state.bboxes || []).filter(b =>
      b.type === 'bbox' && Boxes.isConfirmed(b) && _cls(b.cls) && b.w > 0 && b.h > 0);
    if (!mine.length) { _setError('This image has no confirmed boxes to learn from.'); return; }
    const W = state.imgW, H = state.imgH;
    const added = await _postExamples(item.path, mine.map(b => ({
      x1: b.x / W, y1: b.y / H, x2: (b.x + b.w) / W, y2: (b.y + b.h) / H,
      class_id: b.cls, positive: true,
    })), n => n ? `${n} of your boxes saved as examples` : 'Those boxes are already examples');
    if (added && added.length === 0) app._toast('Those boxes are already examples', 'info');
  }

  /* Auto-predict the image that just opened from the library. Idempotent —
     results go through Boxes.reconcile, so confirmed work is never touched
     and rejected boxes are never re-suggested. A run already in flight
     finishes for ITS image (see _applyToOtherImage); this image is then
     predicted when it ends. */
  function _maybeAutoRun() {
    if (!_open || _mode !== BOX || !_auto) return;
    if (!_examples.some(e => e.positive !== false)) return;
    if (_busy) { _autoPending = true; return; }
    run();
  }

  // ── Committing predictions ──────────────────────────────────────────────

  /* Map one server prediction onto a canvas box, creating the class if the
     project does not have it yet. Prompted labels are new by definition —
     the user just typed a word, or named an example — so class creation is
     the normal path here, not an edge case. */
  function _findClass(name) {
    const n = String(name).trim().toLowerCase();
    return state.classes.find(c => c.name.toLowerCase() === n) || null;
  }

  /* Create every class a run needs ON THE SERVER, before any box uses it.
     A class pushed only into `state.classes` is lost on reload while the
     saved boxes keep its id — they come back pointing at a class the
     project does not have. Done once per run, not per slider tick. */
  async function _ensureClasses(names) {
    const missing = [...new Set(names.map(n => String(n).trim()))]
      .filter(n => n && !_findClass(n));
    const failed = [];
    for (const name of missing) {
      const id = state.classes.length
        ? Math.max(...state.classes.map(c => c.id)) + 1 : 0;
      const color = (typeof CLASS_PALETTE !== 'undefined' && CLASS_PALETTE.length)
        ? CLASS_PALETTE[id % CLASS_PALETTE.length] : [251, 191, 36];
      try {
        const r = await fetch(_p('/classes'), {
          method: 'POST', headers: _authH(),
          body: JSON.stringify({ name, color, id }),
        });
        const d = await r.json().catch(() => ({}));
        if (!r.ok || !d.success) throw new Error(d.error || `HTTP ${r.status}`);
        if (!_findClass(name)) {
          state.classes.push({ id: d.new_id ?? id, name, color });
        }
      } catch (e) {
        failed.push(name);
      }
    }
    if (missing.length && typeof app._populateClassList === 'function') {
      app._populateClassList();
    }
    if (failed.length) {
      app._toast(`Could not add class ${failed.map(n => `"${n}"`).join(', ')} ` +
                 'to the project — its suggestions were skipped.', 'error');
    }
    return new Set(failed.map(n => n.toLowerCase()));
  }

  /* One server prediction → one canvas box in a W×H pixel space. W/H are
     the open image's size, or VIRTUAL for an image that is not on screen
     (see _applyToOtherImage). `owned` tags it `_prun` so the slider may
     withdraw it later — only meaningful for the image on screen. */
  function _toBox(p, W = state.imgW, H = state.imgH, owned = true) {
    // _ensureClasses() ran before any box is built, and predictions whose
    // class could not be created were dropped — so this resolves.
    const cls = _findClass(p.class_name);
    if (!cls) return null;
    const ix = (p.x_center - p.width / 2) * W;
    const iy = (p.y_center - p.height / 2) * H;
    const box = {
      id: Math.random().toString(36).slice(2),
      cls: cls.id, type: 'bbox',
      x: Math.max(0, ix), y: Math.max(0, iy),
      w: Math.min(p.width * W, W - ix),
      h: Math.min(p.height * H, H - iy),
      conf: p.conf,
    };
    if (owned) box._prun = _runId;   // this run owns the box, so the slider may drop it
    return box;
  }

  /* A run finished for an image the user has since navigated away from.

     Users keep working during a ~20-40 s CPU run — the audit log showed
     exactly that: start a prompt, move on through the next frames. The
     results must neither be painted on the wrong image nor thrown away, so
     they are committed to the image they were run FOR, on the server:

       GET its saved boxes → Boxes.reconcile (same rules as on-canvas: a
       confirmed box is never touched, a rejected one never re-suggested) →
       POST them back.

     Without the image's pixel size, boxes live on a VIRTUAL square canvas.
     That is exact for this purpose: IoU is invariant under independent x/y
     scaling. _convertBboxes rounds to whole pixels, so the canvas is 1e9
     wide: the round-trip error (1e-9) is far below the 6 decimals the
     label file stores, so the image's CONFIRMED boxes — which this save
     rewrites — come back byte-identical rather than drifting by 1e-6. The
     new boxes land as SUGGESTIONS in the sidecar, waiting for review. */
  const VIRTUAL = 1e9;

  async function _applyToOtherImage(path, preds) {
    const name = String(path).split(/[\\/]/).pop();
    const keep = preds.filter(p => p.conf >= _conf);
    if (!keep.length) {
      const msg = `Prompt finished for ${name}: nothing above ${Math.round(_conf * 100)}%.`;
      app._toast(msg, 'info');
      return msg;
    }
    try {
      const r = await fetch(_p('/annotations?path=' + encodeURIComponent(path)),
                            { headers: _authH() });
      const d = await r.json().catch(() => null);
      if (!r.ok || !d) throw new Error(`could not read its annotations (HTTP ${r.status})`);
      if (d.is_null) {
        // Saving suggestions would rewrite the label file and silently undo
        // the user's "nothing to annotate here" decision.
        const msg = `Prompt finished for ${name}, but it is marked Null — ` +
                    'results not added. Unmark it and run again.';
        app._toast(msg, 'info');
        return msg;
      }
      const existing = app._convertBboxes(
        [...(d.bboxes || []), ...(d.suggestions || [])], VIRTUAL, VIRTUAL);
      const detections = keep.map(p => _toBox(p, VIRTUAL, VIRTUAL, false)).filter(Boolean);
      const { boxes, summary } = Boxes.reconcile(existing, detections);
      if (!summary.added && !summary.refreshed) {
        const msg = `Prompt finished for ${name}: no new suggestions.`;
        app._toast(msg, 'info');
        return msg;
      }
      const s = await fetch(_p('/annotations'), {
        method: 'POST', headers: _authH(),
        body: JSON.stringify({ path, bboxes: Boxes.serialize(boxes, VIRTUAL, VIRTUAL) }),
      });
      if (!s.ok) {
        const e = await s.json().catch(() => ({}));
        throw new Error(e.error || e.message || `save failed (HTTP ${s.status})`);
      }
      const msg = `${summary.added + summary.refreshed} suggestion(s) saved to ${name} — ` +
                  'open it to review.';
      app._toast(msg, 'success');
      // The user may have navigated BACK to it while this was in flight; the
      // canvas then shows the pre-save state, and its next auto-save would
      // overwrite the sidecar. Reload it from disk instead.
      const cur = state.currentIdx >= 0 ? state.media[state.currentIdx] : null;
      if (cur && cur.path === path) app.loadImage(state.currentIdx, true);
      return msg;
    } catch (e) {
      const msg = `Prompt results for ${name} could not be saved: ${e.message}`;
      app._toast(msg, 'error');
      return msg;
    }
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
    // Arrow wrapper: map() would pass (item, index, array) into W/H.
    const detections = keep.map(p => _toBox(p)).filter(Boolean);

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
      // Box tab = the project's example library, whichever images the
      // examples were drawn on. The server reads the library itself.
      if (!_examples.some(e => e.positive !== false)) {
        _setError('Pick a class and draw a box around one example of it first.');
        return;
      }
      body.mode = 'examples';
    }

    _busy = true;
    _setError('');
    const btn = $('paRunBtn');
    const lbl = $('paRunLabel');
    if (btn) btn.disabled = true;
    const spec = _spec();
    const cold = spec && !spec.installed;
    const verb = cold ? 'Downloading model' : 'Running';
    // A ticking counter: on CPU a run takes ~50 s, and a static "Running…"
    // that long is indistinguishable from a hang.
    const t0 = Date.now();
    const tick = () => {
      if (lbl) lbl.textContent = `${verb}… ${Math.round((Date.now() - t0) / 1000)} s`;
    };
    tick();
    const timer = setInterval(tick, 1000);
    _setMeta(cold ? 'First run — fetching weights, this happens once.'
           : (spec && spec.speed === 'slow')
             ? `Prompting ${spec.label} on CPU — usually under a minute…`
             : 'Prompting the model…');

    // The run is for THIS image. Navigating away during it must not paint
    // its boxes onto whatever image is open when the answer arrives.
    const runPath = item.path;

    try {
      const r = await fetch(_p('/ai/prompt'), {
        method: 'POST', headers: _authH(), body: JSON.stringify(body),
      });
      // A proxy error page or a crashed worker returns HTML, not JSON.
      const d = await r.json().catch(() => ({
        error: `Server returned an unexpected response (HTTP ${r.status}).`,
      }));
      if (!r.ok || d.error) {
        _setError(d.error || `The prompt failed (HTTP ${r.status}).`);
        _setMeta('—');
        return;
      }
      // Closing the panel during a run is the user cancelling it.
      if (!_open) return;
      let preds = (d.predictions || []).slice().sort((a, b) => b.conf - a.conf);
      const failed = await _ensureClasses(preds.map(p => p.class_name));
      if (failed.size) preds = preds.filter(p => !failed.has(String(p.class_name).toLowerCase()));
      // The run belongs to the image it started on. If the user moved on
      // while it ran (normal — a CPU run takes tens of seconds), commit the
      // results to THAT image on the server instead of the one on screen.
      // Checked after _ensureClasses, which also awaited the network.
      const now = state.currentIdx >= 0 ? state.media[state.currentIdx] : null;
      if (!now || now.path !== runPath) {
        _setMeta(await _applyToOtherImage(runPath, preds));
        return;
      }
      _raw = preds;
      _runId = 'pr' + Date.now().toString(36);
      app._pushHistory();
      _sync(true);
      if (!_raw.length) {
        _setMeta(`Nothing matched (${d.elapsed_ms} ms). Try different wording, ` +
                 'a different example box, or a lower confidence.');
      } else {
        _setMeta(`${_raw.filter(p => p.conf >= _conf).length} of ${_raw.length} ` +
                 `predictions shown · ${d.engine} · ` +
                 `${d.device && d.device !== 'cpu' ? 'GPU' : 'CPU'} · ${d.elapsed_ms} ms`);
      }
      // A finished run means the weights are now on the server, so the
      // "first run downloads N MB" warning must stop appearing. Marked on
      // the cached entry rather than by re-listing, because re-listing
      // rewrites the meta line and would wipe the result just reported.
      if (spec) spec.installed = true;
    } catch (e) {
      _setError('Could not reach the server: ' + e.message);
    } finally {
      clearInterval(timer);
      _busy = false;
      if (btn) btn.disabled = false;
      if (lbl) lbl.textContent = 'Run prompt';
      // The user opened another image while this ran: predict that one now.
      if (_autoPending) {
        _autoPending = false;
        const now = _cur();
        if (now && now.path !== runPath) setTimeout(_maybeAutoRun, 0);
      }
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
    _showImageExamples();          // examples are only drawn while the box tab is open
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
    // Saved examples belong to their image: show this image's, hide the last's.
    _showImageExamples();
    _syncExemplarUI();
    // One owner for the pending count: it drives both AI panels' buttons.
    app._updateReviewBanner();
    if (_open) _setMeta(_spec() ? _spec().blurb : '—');
    _maybeAutoRun();
  }

  async function _loadSettings() {
    try {
      const r = await fetch(_p('/ai/prompt/settings'), { headers: _authH() });
      if (!r.ok) return;
      const d = await r.json();
      if (d.engine) _engine = d.engine;
      if (typeof d.conf === 'number') _conf = d.conf;
      // Remembered, not applied: open() applies it only if the user hasn't
      // already clicked a tab while this request was in flight. Applying it
      // here once overwrote a fresh "Box prompt" click with the saved "text"
      // — the Box tab showed while the panel ran text prompts.
      if (d.mode) _savedMode = d.mode === BOX ? BOX : TEXT;
      if (Array.isArray(d.phrases)) _phrases = d.phrases.slice();
      if (typeof d.auto === 'boolean') _auto = d.auto;
      _settingsLoaded = true;

      const ar = $('paAutoRun');
      if (ar) ar.checked = _auto;
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
    const firstLoad = !_settingsLoaded;
    if (firstLoad) await _loadSettings();
    await _loadEngines();
    if (firstLoad && !_modeTouched && _savedMode) _mode = _savedMode;
    _setPromptMode(_mode);
    await _loadExamples();
    app._updateReviewBanner();
    _maybeAutoRun();
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

    $('paTabText')?.addEventListener('click', () => { _modeTouched = true; _setPromptMode(TEXT); });
    $('paTabBox')?.addEventListener('click', () => { _modeTouched = true; _setPromptMode(BOX); _maybeAutoRun(); });

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
      const item = _cur();
      if (!item) return;
      if (!_examples.some(e => e.image === _norm(item.path))) {
        app._toast('No examples on this image', 'info');
        return;
      }
      _removeExamples({ image: item.path }, 'Remove the examples drawn on this image?');
    });
    $('paUseMine')?.addEventListener('click', _useMyBoxes);
    $('paExPos')?.addEventListener('click', () => { _exPositive = true; _syncExemplarUI(); });
    $('paExNeg')?.addEventListener('click', () => { _exPositive = false; _syncExemplarUI(); });
    $('paAutoRun')?.addEventListener('change', e => {
      _auto = !!e.target.checked;
      _persist({ auto: _auto });
      if (_auto) _maybeAutoRun();
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
    app._onPromptBoxesChanged = _onPromptBoxesChanged;
    app._onClassSelected = () => _syncExemplarUI();
    app.onImageLoaded(_onImageChanged);
    // Pressing V or B leaves prompt mode without touching this panel, so
    // the "Drawing — click to stop" label would otherwise lie.
    app._onModeChanged = () => _syncExemplarUI();
  }

  return { init, open, close, run, isOpen: () => _open };
})();

document.addEventListener('DOMContentLoaded', () => PromptAnnotate.init());
