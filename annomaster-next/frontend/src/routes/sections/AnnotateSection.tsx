import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { imageUrl } from '../../api/client';
import { useClasses, useSetClasses, type Klass } from '../../api/hooks';

const PALETTE = ['#ff3b3b', '#ff8e1e', '#ffd31e', '#4ade80', '#22c5e1', '#6366f1', '#a855f7', '#ec4899'];
import { useTheme } from '../../theme/ThemeProvider';
import { Canvas } from '../../canvas/Canvas';
import { SmartDetect } from '../../canvas/SmartDetect';
import { ClassPopup } from '../../canvas/ClassPopup';
import { RightPanel } from '../../canvas/RightPanel';
import type { AnnotateApi } from '../../canvas/useAnnotate';

/**
 * #annotate — full port of annotate.html's `.workspace` body: LEFT image-list
 * sidebar + CANVAS (grouped `.draw-toolbar` + canvas + `.cls-popup` on draw) +
 * RIGHT properties/labels sidebar. Class is assigned via the popup (as in the
 * original), not a toolbar dropdown.
 */
export function AnnotateSection({ wid, project, anno, batchLabel, onClearBatch }: {
  wid: number; project: string; anno: AnnotateApi;
  batchLabel?: string | null; onClearBatch?: () => void;
}) {
  useTheme();
  const { data: classes = [] } = useClasses(wid, project);
  const setClasses = useSetClasses(wid, project);
  // Indexed by CLASS ID (not array position) so a deleted class can't shift
  // every box's colour/name. Canvas looks these up by box.cls.
  const classColors = useMemo(() => { const a: string[] = []; classes.forEach((c) => { a[c.id] = c.color || '#00e5b0'; }); return a; }, [classes]);
  const classNames = useMemo(() => { const a: string[] = []; classes.forEach((c) => { a[c.id] = c.name; }); return a; }, [classes]);
  const { state, dispatch, images, idx, img, dims, current } = anno;

  // Smart Detect starts CLOSED — it only opens (and only then auto-detects) when
  // you click the toolbar button. Also reset it to closed when you switch batches.
  const [showDetect, setShowDetect] = useState(false);
  const [showLabels, setShowLabels] = useState(true);
  const [showGrid, setShowGrid] = useState(false);
  const [panMode, setPanMode] = useState(false);
  useEffect(() => { setShowDetect(false); }, [batchLabel]);

  // Canvas transform (reported by Canvas) — used to place the class popup ON the
  // canvas next to the box just drawn, instead of below the canvas.
  const areaRef = useRef<HTMLDivElement>(null);
  const [view, setView] = useState({ scale: 1, ox: 0, oy: 0 });
  const drawnBox = state.justDrawn != null ? state.boxes.find((b) => b.id === state.justDrawn) : null;
  // Always return a valid on-canvas position when a box was just drawn, so the
  // class popup NEVER falls to the bottom of the page (it did when areaRef/view
  // weren't ready). Falls back to a fixed top-left spot if we can't measure.
  const popupStyle: React.CSSProperties | undefined = (() => {
    if (!drawnBox) return undefined;
    const area = areaRef.current;
    if (!area) return { left: 20, top: 60 };
    const aw = area.clientWidth, ah = area.clientHeight;
    const sx = drawnBox.x * view.scale + view.ox;
    const sy = drawnBox.y * view.scale + view.oy;
    const sh = drawnBox.h * view.scale;
    const W = 264, H = 300;
    const left = Math.max(8, Math.min(isFinite(sx) ? sx : 20, aw - W - 8));
    let top = (isFinite(sy) ? sy : 40) + (isFinite(sh) ? sh : 0) + 8;
    if (top + H > ah) top = Math.max(8, sy - H - 8);      // flip above if no room below
    top = Math.max(8, Math.min(top, ah - 70));
    return { left, top };
  })();

  const addClass = useCallback(async (name: string): Promise<number> => {
    const id = classes.length;
    await setClasses.mutateAsync([...classes, { id, name, color: PALETTE[id % PALETTE.length] }] as Klass[]);
    return id;
  }, [classes, setClasses]);

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (['INPUT', 'SELECT', 'TEXTAREA'].includes((e.target as Element)?.tagName)) return;
      if (e.key === 'Escape') dispatch({ t: state.justDrawn ? 'DISCARD_DRAWN' : 'CANCEL' });
      else if (e.key === 'Delete' || e.key === 'Backspace') dispatch({ t: 'DELETE_SELECTED' });
      else if (e.key === 'b' || e.key === 'B') setMode('draw');
      else if (e.key === 'v' || e.key === 'V') setMode('select');
      else if (e.key === 'ArrowLeft' || e.key === 'a' || e.key === 'A') { e.preventDefault(); anno.nav(-1); }
      else if (e.key === 'ArrowRight' || e.key === 'd' || e.key === 'D') { e.preventDefault(); anno.nav(1); }
      else if ((e.key === 's' || e.key === 'S') && (e.ctrlKey || e.metaKey)) { e.preventDefault(); anno.save(); }
    };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [dispatch, anno, state.justDrawn]);

  const draw = state.mode === 'draw' && !panMode, select = state.mode === 'select' && !panMode;
  const setMode = (m: 'draw' | 'select') => { setPanMode(false); dispatch({ t: 'SET_MODE', mode: m }); };

  return (
    <div className="anno-layout">
      {/* ── LEFT: image list ── */}
      <aside className="sidebar left-sidebar">
        <div className="panel-head sb-head-collapsible"><span><i className="fas fa-images" /> Images</span><span className="mono">{anno.total}</span></div>

        {batchLabel && (
          <div className="batch-filter-banner">
            <span className="bfb-text"><i className="fas fa-layer-group" /> Batch: {batchLabel}</span>
            <button className="bfb-clear" title="Show all images" onClick={onClearBatch}><i className="fas fa-times" /> Clear</button>
          </div>
        )}

        {/* Filter tabs — All / Annotated / Unannotated (ported from the old Media Library) */}
        <div className="media-filters">
          {([['all', 'All'], ['annotated', 'Annotated'], ['unannotated', 'Unannotated']] as const).map(([f, label]) => (
            <button key={f} className={`media-filter-tab${anno.filter === f ? ' active' : ''}`} onClick={() => anno.setFilter(f)}>{label}</button>
          ))}
        </div>

        <div className="img-list-wrap">
          <div className="img-list-inner">
            {images.map((im, i) => (
              <button key={im.id} className={`img-list-item${i === idx ? ' active' : ''}`} onClick={() => anno.go(i)} title={im.filename}>
                <img className="img-list-thumb" src={imageUrl(anno.base, im.path)} alt="" loading="lazy" />
                <span className="img-list-name">{im.filename}</span>
                <span className={`img-list-dot ${im.is_annotated ? 'done' : 'pending'}`} />
              </button>
            ))}
            {!images.length && <div className="list-empty">No images — upload some first.</div>}
          </div>
        </div>

        {/* Pager: page-size selector (20/50/100) + prev/next when multi-page */}
        <div className="img-list-pager">
          <label className="ilp-perpage" title="Images per page">
            <span>Show</span>
            <select value={anno.perPage} onChange={(e) => anno.setPerPage(Number(e.target.value))}>
              <option value={20}>20</option>
              <option value={50}>50</option>
              <option value={100}>100</option>
            </select>
          </label>
          {anno.pages > 1 && (
            <div className="ilp-nav">
              <button className="ilp-btn" disabled={anno.page <= 1} onClick={() => anno.setPage(anno.page - 1)} title="Previous page"><i className="fas fa-chevron-left" /></button>
              <span className="ilp-info">{anno.page} / {anno.pages}</span>
              <button className="ilp-btn" disabled={anno.page >= anno.pages} onClick={() => anno.setPage(anno.page + 1)} title="Next page"><i className="fas fa-chevron-right" /></button>
            </div>
          )}
        </div>
      </aside>

      {/* ── CENTER: canvas ── */}
      <div className="canvas-area" id="page-annotate" ref={areaRef}>
        <div className="draw-toolbar" id="floatToolbar">
          <div className="dt-group">
            <div className="dt-group-label">Draw</div>
            <div className="dt-btn-row">
              <button className={`dt-btn${draw ? ' active' : ''}`} data-mode="bbox" title="Bounding Box (B)" onClick={() => setMode('draw')}><i className="fas fa-vector-square" /><span>Box</span></button>
              <button className="dt-btn" data-mode="polygon" title="Polygon (P) — coming soon" disabled><i className="fas fa-draw-polygon" /><span>Poly</span></button>
              <div className="dt-hint-chip"><i className="fas fa-info-circle" /> Drag anywhere · Select (V) to edit</div>
            </div>
          </div>
          <div className="dt-sep" />
          <div className="dt-group">
            <div className="dt-group-label">Edit</div>
            <div className="dt-btn-row">
              <button className={`dt-btn${select ? ' active' : ''}`} data-mode="edit" title="Select / Edit (V)" onClick={() => setMode('select')}><i className="fas fa-mouse-pointer" /><span>Select</span></button>
              <button className={`dt-btn${panMode ? ' active' : ''}`} data-mode="pan" title="Pan (drag) · or hold Space / middle-mouse · wheel to zoom" onClick={() => setPanMode((p) => !p)}><i className="fas fa-hand-paper" /><span>Pan</span></button>
            </div>
          </div>
          <div className="dt-sep" />
          <div className="dt-group">
            <div className="dt-group-label">View</div>
            <div className="dt-btn-row">
              <button className={`dt-btn toggle${showLabels ? ' active' : ''}`} title="Toggle Labels (T)" onClick={() => setShowLabels((s) => !s)}><i className="fas fa-tag" /><span>Labels</span></button>
              <button className={`dt-btn toggle${showGrid ? ' active' : ''}`} title="Toggle Grid (G)" onClick={() => setShowGrid((s) => !s)}><i className="fas fa-border-all" /><span>Grid</span></button>
            </div>
          </div>
          <div className="dt-sep" />
          <div className="dt-group">
            <div className="dt-group-label">Mark</div>
            <div className="dt-btn-row">
              <button className="dt-btn dt-btn-null" title="Mark empty / background" onClick={anno.markNull}><i className="fas fa-ban" /><span>Null</span></button>
            </div>
          </div>
          <div className="dt-sep dt-sep-accent" />
          <div className="dt-group">
            <div className="dt-group-label dt-group-label-ai">AI</div>
            <div className="dt-btn-row">
              <button className={`dt-btn-ai${showDetect ? ' dt-btn-ai-active' : ''}`} id="smartDetectBtn" title="Smart Detect" onClick={() => setShowDetect((s) => !s)}><i className="fas fa-wand-magic-sparkles" /><span>Smart Detect</span></button>
            </div>
          </div>
        </div>

        <Canvas state={state} dispatch={dispatch} image={img} classColors={classColors} classNames={classNames} showLabels={showLabels} showGrid={showGrid} panMode={panMode} onView={setView} />

        {state.justDrawn && (
          <ClassPopup classes={classes} style={popupStyle} currentCls={drawnBox?.cls ?? state.currentCls}
                      onPick={(cls) => dispatch({ t: 'ASSIGN_CLASS', id: state.justDrawn!, cls })}
                      onAddClass={addClass} onConfirm={() => dispatch({ t: 'CLEAR_JUST_DRAWN' })}
                      onCancel={() => dispatch({ t: 'DISCARD_DRAWN' })} onDelete={() => dispatch({ t: 'DISCARD_DRAWN' })} />
        )}
        {showDetect && <SmartDetect wid={wid} project={project} imagePath={current?.path ?? null} dims={dims} state={state} dispatch={dispatch} onClose={() => setShowDetect(false)} />}

        {/* Bottom-center image navigator — ‹  current / total  › (← → or A/D) */}
        {anno.total > 0 && (
          <div className="img-nav-bar" id="imgNavBar">
            <button className="img-nav-btn prev" title="Previous image (← / A)" disabled={anno.globalIndex <= 0} onClick={() => anno.nav(-1)}><i className="fas fa-chevron-left" /></button>
            <div className="img-nav-counter">
              <span className="img-nav-current">{anno.globalIndex + 1}</span>
              <span className="img-nav-sep">/</span>
              <span className="img-nav-total">{anno.total}</span>
            </div>
            <button className="img-nav-btn next" title="Next image (→ / D)" disabled={anno.globalIndex >= anno.total - 1} onClick={() => anno.nav(1)}><i className="fas fa-chevron-right" /></button>
          </div>
        )}
      </div>

      {/* ── RIGHT: properties / labels ── */}
      <RightPanel state={state} dispatch={dispatch} classes={classes} dims={dims} onAddClass={addClass} />
    </div>
  );
}
