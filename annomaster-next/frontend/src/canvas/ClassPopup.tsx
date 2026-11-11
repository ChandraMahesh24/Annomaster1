import { useEffect, useMemo, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import type { Klass } from '../api/hooks';

/**
 * Class-assignment popup — ports `.cls-popup` from annotate.html. Opens when a
 * box is freshly drawn, to assign its class. Matches the original's keyboard UX:
 *  • the current class is pre-highlighted
 *  • ↑/↓ move the highlight, Enter confirms the HIGHLIGHTED class (not just the
 *    first one), so pressing Enter saves the class you actually chose
 *  • type a name + Enter creates a new class
 *  • click a class to pick it · Esc cancels (removes the box)
 */
export function ClassPopup({ classes, currentCls, onPick, onAddClass, onConfirm, onCancel, onDelete, style }: {
  classes: Klass[];
  currentCls?: number;
  onPick: (cls: number) => void;
  onAddClass: (name: string) => Promise<number>;
  onConfirm: () => void;
  onCancel: () => void;
  onDelete: () => void;
  style?: CSSProperties;
}) {
  const [q, setQ] = useState('');
  const [hi, setHi] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  useEffect(() => { inputRef.current?.focus(); }, []);

  const filtered = useMemo(
    () => classes.filter((c) => c.name.toLowerCase().includes(q.toLowerCase())),
    [classes, q],
  );
  const canCreate = q.trim().length > 0 && !classes.some((c) => c.name.toLowerCase() === q.trim().toLowerCase());
  const rows = filtered.length + (canCreate ? 1 : 0);   // last index = "create" row when canCreate

  // Pre-highlight the box's current class; re-anchor to top when the query changes.
  useEffect(() => {
    const i = filtered.findIndex((c) => c.id === currentCls);
    setHi(i >= 0 ? i : 0);
  }, [currentCls]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setHi(0); }, [q]);

  function pick(cls: number) { onPick(cls); onConfirm(); }

  async function confirmHighlighted() {
    if (canCreate && hi === filtered.length) {           // "create" row
      const id = await onAddClass(q.trim()); pick(id); return;
    }
    if (filtered[hi]) { pick(filtered[hi].id); return; }
    if (canCreate && q.trim()) { const id = await onAddClass(q.trim()); pick(id); return; }
    onConfirm();                                          // nothing to pick → just close
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Escape') { onCancel(); return; }
    if (e.key === 'Enter') { e.preventDefault(); void confirmHighlighted(); return; }
    if (e.key === 'ArrowDown') { e.preventDefault(); setHi((h) => Math.min(h + 1, Math.max(0, rows - 1))); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setHi((h) => Math.max(0, h - 1)); }
  }

  // keep the highlighted row in view
  useEffect(() => {
    listRef.current?.querySelector<HTMLElement>('.cp-item.selected')?.scrollIntoView({ block: 'nearest' });
  }, [hi]);

  return (
    <div className="cls-popup" id="clsPopup" style={style} onKeyDown={onKeyDown}>
      <div className="cp-header">
        <span className="cp-header-title"><i className="fas fa-tags" /> Assign Class</span>
        <button className="cp-header-close" title="Cancel (Esc)" onClick={onCancel}><i className="fas fa-times" /></button>
      </div>
      <div className="cp-search">
        <i className="fas fa-search" />
        <input ref={inputRef} type="text" placeholder="Search or type new class…" value={q} onChange={(e) => setQ(e.target.value)} autoComplete="off" />
      </div>
      <div className="cp-list" id="cpList" ref={listRef}>
        {filtered.map((c, i) => (
          <button key={c.id} className={`cp-item${i === hi ? ' selected' : ''}`}
                  onMouseEnter={() => setHi(i)} onClick={() => pick(c.id)}>
            <span className="cp-swatch" style={{ background: c.color }} />
            <span className="cp-name">{c.name}</span>
            <span className="cp-id mono">{c.id}</span>
          </button>
        ))}
        {canCreate && (
          <button className={`cp-item${hi === filtered.length ? ' selected' : ''}`}
                  onMouseEnter={() => setHi(filtered.length)} onClick={() => void confirmHighlighted()}>
            <i className="fas fa-plus-circle" /> <span className="cp-name">Create “{q.trim()}”</span>
          </button>
        )}
        {!rows && <div className="cp-empty" style={{ padding: '10px 12px', color: 'var(--tx3)', fontSize: 12 }}>No classes — type a name to create one.</div>}
      </div>
      <div className="cp-foot">
        <button className="cp-del-btn" title="Delete box (Esc)" onClick={onDelete}><i className="fas fa-trash-alt" /></button>
        <button className="cp-cancel-btn" title="Cancel (Esc)" onClick={onCancel}><i className="fas fa-times" /> Cancel</button>
        <button className="cp-confirm-btn" title="Confirm (Enter)" onClick={() => void confirmHighlighted()}><i className="fas fa-check" /> Confirm</button>
      </div>
    </div>
  );
}
