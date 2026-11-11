import { memo, useState } from 'react';
import type { Klass } from '../api/hooks';
import { confirmed, isSuggested, suggested } from './boxes';
import type { Action, CanvasState } from './reducer';

/**
 * Right sidebar — ports `.sidebar.right-sidebar`: a Labels tab (class list +
 * per-image annotation list) and a Properties tab (selected box class + X/Y/W/H
 * + accept/reject for suggestions). Class + annotation lists mirror the
 * original's `.rp-panel` structure.
 *
 * MEMOISED: while DRAWING a box, only `state.draft` changes — `boxes`/`selectedId`
 * keep the same reference — so this panel skips re-rendering on every pointer
 * move. That's what keeps drawing smooth (the panel iterating boxes 60×/sec was
 * a big chunk of the per-frame cost). It still updates on move/resize/select,
 * where `boxes` genuinely changes.
 */
function RightPanelImpl({ state, dispatch, classes, dims, onAddClass }: {
  state: CanvasState;
  dispatch: (a: Action) => void;
  classes: Klass[];
  dims: { w: number; h: number };
  onAddClass: (name: string) => void;
}) {
  const [tab, setTab] = useState<'labels' | 'props'>('labels');
  const [newCls, setNewCls] = useState('');
  const sel = state.boxes.find((b) => b.id === state.selectedId) || null;
  const clsName = (i: number) => classes.find((c) => c.id === i)?.name ?? `class ${i}`;
  const clsColor = (i: number) => classes.find((c) => c.id === i)?.color ?? '#00e5b0';
  const visible = state.boxes.filter((b) => b.state !== 'rejected');

  return (
    <aside className="sidebar right-sidebar" id="sidebarRight">
      <div className="rp-tabs">
        <button className={`rp-tab${tab === 'labels' ? ' active' : ''}`} onClick={() => setTab('labels')}>Labels</button>
        <button className={`rp-tab${tab === 'props' ? ' active' : ''}`} onClick={() => setTab('props')}>Properties</button>
      </div>

      {tab === 'labels' && (
        <div className="rp-panel active" id="rpt-labels">
          <div className="panel-section" id="clsSectionWrap">
            <div className="panel-head">
              <span className="ph-title"><i className="fas fa-tags" /> Classes</span>
              <div className="ph-head-right"><span className="ph-badge">{classes.length}</span></div>
            </div>
            <div className="panel-body">
              <div className="add-cls-row">
                <input type="text" placeholder="New class name…" value={newCls}
                       onChange={(e) => setNewCls(e.target.value)}
                       onKeyDown={(e) => { if (e.key === 'Enter' && newCls.trim()) { onAddClass(newCls.trim()); setNewCls(''); } }} />
                <button className="add-cls-btn" title="Add (Enter)" onClick={() => { if (newCls.trim()) { onAddClass(newCls.trim()); setNewCls(''); } }}><i className="fas fa-plus" /></button>
              </div>
              <div className="cls-list" id="clsList">
                {classes.map((c) => (
                  <div key={c.id} className={`cls-row${state.currentCls === c.id ? ' sel' : ''}`} onClick={() => dispatch({ t: 'SET_CLASS', cls: c.id })}>
                    <span className="cls-swatch" style={{ background: c.color }} />
                    <span className="cls-name">{c.name}</span>
                    <span className="cls-id-badge">{c.id}</span>
                  </div>
                ))}
                {!classes.length && <div className="cls-empty"><i className="fas fa-layer-group" /> No classes yet</div>}
              </div>
            </div>
          </div>

          <div className="panel-divider" />
          <div className="panel-section panel-grow">
            <div className="panel-head">
              <span className="ph-title"><i className="fas fa-draw-polygon" /> Annotations</span>
              <div className="ph-head-right">
                <span className="ph-badge">{confirmed(state.boxes).length}</span>
                {suggested(state.boxes).length > 0 && <span className="ph-badge" style={{ background: 'var(--warning-bg)', color: 'var(--warning)' }}>{suggested(state.boxes).length}?</span>}
              </div>
            </div>
            <div className="panel-body panel-body-grow">
              <div className="anno-list" id="annoList">
                {visible.length ? visible.map((b) => (
                  <div key={b.id} className={`anno-row${state.selectedId === b.id ? ' sel' : ''}${isSuggested(b) ? ' suggested' : ''}`} onClick={() => dispatch({ t: 'SELECT', id: b.id })}>
                    <span className="anno-swatch" style={{ background: clsColor(b.cls) }} />
                    <span className="anno-label">{clsName(b.cls)}</span>
                    {isSuggested(b) && b.conf != null && <span className="anno-conf">{Math.round(b.conf * 100)}%</span>}
                    {isSuggested(b) ? (
                      <span className="anno-actions">
                        <button title="Accept" onClick={(e) => { e.stopPropagation(); dispatch({ t: 'ACCEPT', id: b.id }); }}><i className="fas fa-check" /></button>
                        <button title="Reject" onClick={(e) => { e.stopPropagation(); dispatch({ t: 'REJECT', id: b.id }); }}><i className="fas fa-times" /></button>
                      </span>
                    ) : (
                      <button className="anno-del" title="Delete" onClick={(e) => { e.stopPropagation(); dispatch({ t: 'SELECT', id: b.id }); dispatch({ t: 'DELETE_SELECTED' }); }}><i className="fas fa-trash-alt" /></button>
                    )}
                  </div>
                )) : <div className="props-placeholder">No annotations yet — draw a box.</div>}
              </div>
            </div>
          </div>
        </div>
      )}

      {tab === 'props' && (
        <div className="rp-panel active" id="rpt-props">
          <div className="panel-section">
            <div className="panel-head"><span className="ph-title"><i className="fas fa-cube" /> Box Properties</span></div>
            {sel ? (
              <div className="props-form" id="propsForm">
                <div className="pf-group full">
                  <label>Class</label>
                  <select value={sel.cls} onChange={(e) => dispatch({ t: 'SET_BOX', id: sel.id, patch: { cls: Number(e.target.value) } })}>
                    {classes.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                  </select>
                </div>
                <div className="pf-row">
                  <PfNum label="X" v={sel.x} on={(x) => dispatch({ t: 'SET_BOX', id: sel.id, patch: { x } })} max={dims.w} />
                  <PfNum label="Y" v={sel.y} on={(y) => dispatch({ t: 'SET_BOX', id: sel.id, patch: { y } })} max={dims.h} />
                </div>
                <div className="pf-row">
                  <PfNum label="W" v={sel.w} on={(w) => dispatch({ t: 'SET_BOX', id: sel.id, patch: { w } })} max={dims.w} />
                  <PfNum label="H" v={sel.h} on={(h) => dispatch({ t: 'SET_BOX', id: sel.id, patch: { h } })} max={dims.h} />
                </div>
                {isSuggested(sel) && (
                  <div className="pf-row">
                    <button className="btn btn-primary btn-full" onClick={() => dispatch({ t: 'ACCEPT', id: sel.id })}>Accept</button>
                    <button className="btn btn-ghost btn-full" onClick={() => dispatch({ t: 'REJECT', id: sel.id })}>Reject</button>
                  </div>
                )}
                <button className="btn btn-ghost btn-full" onClick={() => dispatch({ t: 'DELETE_SELECTED' })}><i className="fas fa-trash-alt" /> Delete box</button>
              </div>
            ) : (
              <div className="props-placeholder" id="propsEmpty">Select a box to edit its properties.</div>
            )}
          </div>
        </div>
      )}
    </aside>
  );
}

function PfNum({ label, v, on, max }: { label: string; v: number; on: (n: number) => void; max: number }) {
  return (
    <div className="pf-group">
      <label>{label}</label>
      <input type="number" min={0} max={Math.round(max)} value={Math.round(v)} onChange={(e) => on(Math.max(0, Number(e.target.value)))} />
    </div>
  );
}

// Skip re-render while only the draft changes (boxes/selectedId unchanged).
export const RightPanel = memo(RightPanelImpl, (a, b) =>
  a.state.boxes === b.state.boxes &&
  a.state.selectedId === b.state.selectedId &&
  a.classes === b.classes &&
  a.dims === b.dims &&
  a.dispatch === b.dispatch &&
  a.onAddClass === b.onAddClass,
);
