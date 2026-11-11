import { useCallback, useEffect, useRef, useState } from 'react';
import { hitTest, isRejected, isSuggested, type Box } from './boxes';
import { applyResize } from './reducer';
import type { Action, CanvasState, Handle } from './reducer';

const HANDLE_R = 6;
const HANDLES: Handle[] = ['nw', 'ne', 'sw', 'se', 'n', 's', 'e', 'w'];
const MIN_SCALE = 0.05, MAX_SCALE = 24;
const clamp = (v: number, a: number, b: number) => Math.max(a, Math.min(b, v));

type Geom = { x: number; y: number; w: number; h: number };
type DragInfo =
  | { kind: 'draw'; ox: number; oy: number }
  | { kind: 'move'; id: string; offX: number; offY: number; box0: Box }
  | { kind: 'resize'; id: string; handle: Handle; box0: Box };
type Live = { kind: 'draw'; box: Geom } | { kind: 'move' | 'resize'; id: string; box: Geom };

interface Props {
  state: CanvasState;
  dispatch: (a: Action) => void;
  image: HTMLImageElement | null;
  classColors: string[];
  classNames?: string[];
  showLabels?: boolean;
  showGrid?: boolean;
  panMode?: boolean;
  onView?: (v: { scale: number; ox: number; oy: number }) => void;
}

/** Black or white text, whichever reads better on the given class colour. */
function contrastText(color: string): string {
  let c = (color || '').replace('#', '');
  if (c.length === 3) c = c.split('').map((x) => x + x).join('');
  const r = parseInt(c.slice(0, 2), 16), g = parseInt(c.slice(2, 4), 16), b = parseInt(c.slice(4, 6), 16);
  if (Number.isNaN(r) || Number.isNaN(g) || Number.isNaN(b)) return '#fff';
  return (0.299 * r + 0.587 * g + 0.114 * b) / 255 > 0.6 ? '#0b0b12' : '#ffffff';
}

/** Reads a live CSS token off <html> so canvas colours follow the theme. CACHED
 *  (getComputedStyle is expensive); cleared on theme change. */
let _tokenCache: Record<string, string> = {};
let _tokenObserver: MutationObserver | null = null;
function token(name: string, fallback: string): string {
  if (typeof getComputedStyle === 'undefined') return fallback;
  const hit = _tokenCache[name];
  if (hit !== undefined) return hit;
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
  _tokenCache[name] = v;
  if (!_tokenObserver && typeof MutationObserver !== 'undefined') {
    _tokenObserver = new MutationObserver(() => { _tokenCache = {}; });
    _tokenObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['class', 'style', 'data-theme'] });
  }
  return v;
}
const isTyping = (e: Event) => ['INPUT', 'SELECT', 'TEXTAREA'].includes((e.target as Element)?.tagName);

/**
 * Annotation canvas. Zoom (wheel/±/F/0) + pan (Pan tool / Space / middle-drag).
 *
 * SMOOTH DRAWING (ported from the original's imperative `_render()`): while you
 * drag to draw/move/resize, we DON'T dispatch to React on every move — that
 * re-rendered the whole tree per event and made drawing janky. Instead the drag
 * preview is painted directly to the canvas (`drawScene` reads a `live` ref), and
 * we commit to the reducer only on mouse-UP (one POINTER_MOVE + POINTER_UP). The
 * reducer stays the single source of truth for committed boxes.
 */
export function Canvas({ state, dispatch, image, classColors, classNames = [], showLabels = true, showGrid = false, panMode = false, onView }: Props) {
  const ref = useRef<HTMLCanvasElement>(null);
  const view = useRef({ scale: 1, ox: 0, oy: 0 });
  const pan = useRef<{ sx: number; sy: number; ox: number; oy: number } | null>(null);
  const spaceHeld = useRef(false);
  const dragInfo = useRef<DragInfo | null>(null);
  const live = useRef<Live | null>(null);
  const [tick, setTick] = useState(0);
  const [zoomPct, setZoomPct] = useState(100);
  const [panReady, setPanReady] = useState(false);
  const redraw = useCallback(() => setTick((t) => (t + 1) & 0xffff), []);

  const toImg = (cx: number, cy: number) => ({
    x: (cx - view.current.ox) / view.current.scale,
    y: (cy - view.current.oy) / view.current.scale,
  });
  const toCv = (x: number, y: number) => ({
    x: x * view.current.scale + view.current.ox,
    y: y * view.current.scale + view.current.oy,
  });

  const fit = useCallback(() => {
    const cv = ref.current;
    if (!cv || !image) return;
    const r = cv.getBoundingClientRect();
    const s = Math.min(r.width / image.width, r.height / image.height) || 1;
    view.current = { scale: s, ox: (r.width - image.width * s) / 2, oy: (r.height - image.height * s) / 2 };
    setZoomPct(Math.round(s * 100));
    redraw();
  }, [image, redraw]);

  const zoomAt = useCallback((cx: number, cy: number, factor: number) => {
    const v = view.current;
    const ns = clamp(v.scale * factor, MIN_SCALE, MAX_SCALE);
    const k = ns / v.scale;
    view.current = { scale: ns, ox: cx - (cx - v.ox) * k, oy: cy - (cy - v.oy) * k };
    setZoomPct(Math.round(ns * 100));
    redraw();
  }, [redraw]);

  const zoomCenter = useCallback((factor: number) => {
    const cv = ref.current; if (!cv) return;
    const r = cv.getBoundingClientRect();
    zoomAt(r.width / 2, r.height / 2, factor);
  }, [zoomAt]);

  const reset100 = useCallback(() => {
    const cv = ref.current; if (!cv || !image) return;
    const r = cv.getBoundingClientRect();
    view.current = { scale: 1, ox: (r.width - image.width) / 2, oy: (r.height - image.height) / 2 };
    setZoomPct(100); redraw();
  }, [image, redraw]);

  useEffect(() => { onView?.({ ...view.current }); }, [tick, onView]);
  useEffect(() => { fit(); }, [image, fit]);
  useEffect(() => {
    const cv = ref.current; if (!cv || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(() => redraw());
    ro.observe(cv);
    return () => ro.disconnect();
  }, [redraw]);

  useEffect(() => {
    const cv = ref.current; if (!cv) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const r = cv.getBoundingClientRect();
      zoomAt(e.clientX - r.left, e.clientY - r.top, e.deltaY < 0 ? 1.12 : 1 / 1.12);
    };
    cv.addEventListener('wheel', onWheel, { passive: false });
    return () => cv.removeEventListener('wheel', onWheel);
  }, [zoomAt]);

  useEffect(() => {
    const kd = (e: KeyboardEvent) => {
      if (isTyping(e)) return;
      if (e.code === 'Space') { spaceHeld.current = true; setPanReady(true); }
      else if (e.key === '+' || e.key === '=') { e.preventDefault(); zoomCenter(1.2); }
      else if (e.key === '-' || e.key === '_') { e.preventDefault(); zoomCenter(1 / 1.2); }
      else if (e.key === 'f' || e.key === 'F') { fit(); }
      else if (e.key === '0') { reset100(); }
    };
    const ku = (e: KeyboardEvent) => { if (e.code === 'Space') { spaceHeld.current = false; setPanReady(false); } };
    const blur = () => { spaceHeld.current = false; setPanReady(false); };
    window.addEventListener('keydown', kd);
    window.addEventListener('keyup', ku);
    window.addEventListener('blur', blur);
    return () => {
      window.removeEventListener('keydown', kd);
      window.removeEventListener('keyup', ku);
      window.removeEventListener('blur', blur);
    };
  }, [zoomCenter, fit, reset100]);

  // ── Draw everything. Used by the render effect AND called imperatively during a
  //    drag (with a `live` override for the box being drawn/moved/resized). ──
  const drawScene = () => {
    const cv = ref.current;
    if (!cv) return;
    const ctx = cv.getContext('2d');
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    const cssW = cv.clientWidth, cssH = cv.clientHeight;
    const needW = Math.round(cssW * dpr), needH = Math.round(cssH * dpr);
    if (cv.width !== needW || cv.height !== needH) { cv.width = needW; cv.height = needH; }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    ctx.clearRect(0, 0, cssW, cssH);
    ctx.fillStyle = token('--panel', '#111119');
    ctx.fillRect(0, 0, cssW, cssH);
    if (image) {
      ctx.drawImage(image, view.current.ox, view.current.oy,
        image.width * view.current.scale, image.height * view.current.scale);
    }

    if (showGrid && image) {
      const step = 40 * view.current.scale;
      ctx.strokeStyle = token('--ink-a06', 'rgba(255,255,255,.06)');
      ctx.lineWidth = 1;
      ctx.beginPath();
      for (let gx = view.current.ox; gx < cssW; gx += step) { ctx.moveTo(gx, 0); ctx.lineTo(gx, cssH); }
      for (let gy = view.current.oy; gy < cssH; gy += step) { ctx.moveTo(0, gy); ctx.lineTo(cssW, gy); }
      ctx.stroke();
    }

    const accent = token('--accent', '#00e5b0');
    const lv = live.current;
    for (const b of state.boxes) {
      if (isRejected(b)) continue;
      // While moving/resizing this box, draw its LIVE geometry (not the committed one).
      const g: Geom = (lv && lv.kind !== 'draw' && lv.id === b.id) ? lv.box : b;
      const selected = b.id === state.selectedId || (lv && lv.kind !== 'draw' && lv.id === b.id);
      const color = classColors[b.cls] || accent;
      const p = toCv(g.x, g.y);
      const w = g.w * view.current.scale, h = g.h * view.current.scale;
      ctx.lineWidth = selected ? 2.5 : 1.6;
      ctx.strokeStyle = color;
      ctx.setLineDash(isSuggested(b) ? [6, 4] : []);
      ctx.globalAlpha = isSuggested(b) ? 0.85 : 1;
      ctx.strokeRect(p.x, p.y, w, h);
      ctx.globalAlpha = 1;
      ctx.setLineDash([]);

      // Class-name label above the box (with confidence for suggestions). Hidden
      // by the View → Labels toggle. Sits above the box, or inside its top edge
      // when there's no room above.
      if (showLabels) {
        const name = classNames[b.cls] ?? `class ${b.cls}`;
        const label = (isSuggested(b) && b.conf != null) ? `${name}  ${Math.round(b.conf * 100)}%` : name;
        ctx.font = '700 11px Inter, system-ui, sans-serif';
        const padX = 5, lh = 15;
        const tw = ctx.measureText(label).width + padX * 2;
        const ly = p.y - lh >= 0 ? p.y - lh : p.y;      // flip inside if no room above
        ctx.globalAlpha = isSuggested(b) ? 0.9 : 1;
        ctx.fillStyle = color;
        ctx.fillRect(p.x, ly, tw, lh);
        ctx.globalAlpha = 1;
        ctx.fillStyle = contrastText(color);
        ctx.textBaseline = 'middle';
        ctx.fillText(label, p.x + padX, ly + lh / 2 + 0.5);
        ctx.textBaseline = 'alphabetic';
      }
      if (selected) {
        for (const hnd of HANDLES) {
          const hp = handlePos(p.x, p.y, w, h, hnd);
          ctx.fillStyle = '#fff'; ctx.strokeStyle = color; ctx.lineWidth = 2;
          ctx.beginPath(); ctx.arc(hp.x, hp.y, HANDLE_R, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
        }
      }
    }

    // The in-progress rectangle (live draw preview, or the reducer's draft).
    const draft: Geom | null = (lv && lv.kind === 'draw') ? lv.box : state.draft;
    if (draft && (draft.w > 0 || draft.h > 0)) {
      const p = toCv(draft.x, draft.y);
      ctx.strokeStyle = accent; ctx.lineWidth = 1.6; ctx.setLineDash([4, 3]);
      ctx.strokeRect(p.x, p.y, draft.w * view.current.scale, draft.h * view.current.scale);
      ctx.setLineDash([]);
    }
  };

  // Repaint on committed-state / image / zoom changes.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { drawScene(); }, [state, image, classColors, showLabels, showGrid, tick]);

  // ── Pointer ──
  function hitHandle(cx: number, cy: number): Handle | null {
    if (!state.selectedId) return null;
    const b = state.boxes.find((x) => x.id === state.selectedId);
    if (!b) return null;
    const p = toCv(b.x, b.y);
    const w = b.w * view.current.scale, h = b.h * view.current.scale;
    for (const hnd of HANDLES) {
      const hp = handlePos(p.x, p.y, w, h, hnd);
      if (Math.hypot(cx - hp.x, cy - hp.y) <= HANDLE_R + 3) return hnd;
    }
    return null;
  }
  function pos(e: React.PointerEvent) {
    const r = ref.current!.getBoundingClientRect();
    return { cx: e.clientX - r.left, cy: e.clientY - r.top };
  }

  function onDown(e: React.PointerEvent) {
    const { cx, cy } = pos(e);
    if (panMode || spaceHeld.current || e.button === 1) {          // pan
      e.preventDefault();
      (e.target as Element).setPointerCapture?.(e.pointerId);
      pan.current = { sx: cx, sy: cy, ox: view.current.ox, oy: view.current.oy };
      return;
    }
    (e.target as Element).setPointerCapture?.(e.pointerId);
    const handle = hitHandle(cx, cy);
    const { x, y } = toImg(cx, cy);
    const selBox = state.boxes.find((b) => b.id === state.selectedId);

    // Decide the operation — mirrors the reducer's POINTER_DOWN exactly.
    if (handle && selBox) {
      dragInfo.current = { kind: 'resize', id: selBox.id, handle, box0: selBox };
      live.current = { kind: 'resize', id: selBox.id, box: { ...selBox } };
    } else if (state.mode === 'draw') {
      dragInfo.current = { kind: 'draw', ox: x, oy: y };            // draw mode ALWAYS draws
      live.current = { kind: 'draw', box: { x, y, w: 0, h: 0 } };
    } else {
      const hit = hitTest(state.boxes, x, y);
      if (hit) {
        dragInfo.current = { kind: 'move', id: hit.id, offX: x - hit.x, offY: y - hit.y, box0: hit };
        live.current = { kind: 'move', id: hit.id, box: { ...hit } };
      } else {
        dragInfo.current = null; live.current = null;
      }
    }
    dispatch({ t: 'POINTER_DOWN', x, y, handle });                 // reducer sets phase/selection/draft
  }

  function onMove(e: React.PointerEvent) {
    const { cx, cy } = pos(e);
    if (pan.current) {
      view.current.ox = pan.current.ox + (cx - pan.current.sx);
      view.current.oy = pan.current.oy + (cy - pan.current.sy);
      redraw();
      return;
    }
    const di = dragInfo.current;
    if (!di) return;
    const { x, y } = toImg(cx, cy);
    if (di.kind === 'draw') {
      live.current = { kind: 'draw', box: { x: Math.min(di.ox, x), y: Math.min(di.oy, y), w: Math.abs(x - di.ox), h: Math.abs(y - di.oy) } };
    } else if (di.kind === 'move') {
      live.current = { kind: 'move', id: di.id, box: { x: x - di.offX, y: y - di.offY, w: di.box0.w, h: di.box0.h } };
    } else {
      const r = applyResize(di.box0, di.handle, x, y);
      live.current = { kind: 'resize', id: di.id, box: { x: r.x, y: r.y, w: r.w, h: r.h } };
    }
    drawScene();                                                   // imperative — no dispatch, no re-render
  }

  function onUp(e: React.PointerEvent) {
    if (pan.current) { pan.current = null; redraw(); return; }
    const di = dragInfo.current;
    dragInfo.current = null;
    live.current = null;
    const { cx, cy } = pos(e); const { x, y } = toImg(cx, cy);
    if (di) dispatch({ t: 'POINTER_MOVE', x, y });                 // reducer computes final geometry
    dispatch({ t: 'POINTER_UP', x, y });                          // reducer commits (idempotent otherwise)
  }

  const cursor = pan.current ? 'grabbing' : (panMode || panReady) ? 'grab' : state.mode === 'draw' ? 'crosshair' : 'default';

  return (
    <>
      <canvas
        ref={ref}
        className="anno-canvas"
        style={{ width: '100%', height: '100%', display: 'block', cursor, touchAction: 'none' }}
        onPointerDown={onDown}
        onPointerMove={onMove}
        onPointerUp={onUp}
      />

      {/* Zoom pill — ports the original's .zoom-controls */}
      <div className="zoom-controls">
        <button className="zc-btn" title="Zoom out (−)" onClick={() => zoomCenter(1 / 1.2)}><i className="fas fa-minus" /></button>
        <span className="zc-display" title="Reset to 100% (0)" onDoubleClick={reset100}>{zoomPct}%</span>
        <button className="zc-btn" title="Zoom in (+)" onClick={() => zoomCenter(1.2)}><i className="fas fa-plus" /></button>
        <div className="zc-sep" />
        <button className="zc-btn" title="Fit to screen (F)" onClick={fit}><i className="fas fa-expand" /></button>
        <button className="zc-btn" title="Actual size 1:1 (0)" onClick={reset100}><i className="fas fa-compress" /></button>
      </div>
    </>
  );
}

function handlePos(x: number, y: number, w: number, h: number, hnd: Handle) {
  const mx = x + w / 2, my = y + h / 2, r = x + w, b = y + h;
  switch (hnd) {
    case 'nw': return { x, y }; case 'ne': return { x: r, y };
    case 'sw': return { x, y: b }; case 'se': return { x: r, y: b };
    case 'n': return { x: mx, y }; case 's': return { x: mx, y: b };
    case 'w': return { x, y: my }; case 'e': return { x: r, y: my };
  }
}
