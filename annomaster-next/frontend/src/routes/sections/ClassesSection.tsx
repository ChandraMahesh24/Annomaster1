import { useState } from 'react';
import { useClasses, useSetClasses, type Klass } from '../../api/hooks';

const PALETTE = ['#ff3b3b', '#ff8e1e', '#ffd31e', '#4ade80', '#22c5e1', '#6366f1', '#a855f7', '#ec4899'];

/** #classes — ports #page-classes: .cls-page-header + .cls-add-form + .cls-table. */
export function ClassesSection({ wid, project }: { wid: number; project: string }) {
  const { data: classes = [] } = useClasses(wid, project);
  const save = useSetClasses(wid, project);
  const [name, setName] = useState('');
  const [color, setColor] = useState(PALETTE[0]);

  const add = () => {
    if (!name.trim()) return;
    save.mutate([...classes, { id: classes.length, name: name.trim(), color }] as Klass[]);
    setName(''); setColor(PALETTE[(classes.length + 1) % PALETTE.length]);
  };
  const del = (id: number) => save.mutate(classes.filter((c) => c.id !== id).map((c, i) => ({ ...c, id: i })));

  return (
    <div className="page" id="page-classes">
      <div className="cls-page-header">
        <h2><i className="fas fa-tags" /> Class Manager</h2>
      </div>
      <div className="cls-page-body">
        <div className="cls-add-form">
          <div className="fg" style={{ flex: 1 }}>
            <input className="input" placeholder="Class name" value={name}
                   onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && add()} />
          </div>
          <div className="fg" style={{ minWidth: 80 }}>
            <div className="color-picker-wrap" style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
              {PALETTE.map((c) => (
                <span key={c} className="ct-swatch" onClick={() => setColor(c)}
                      style={{ background: c, width: 22, height: 22, borderRadius: 5, cursor: 'pointer', outline: color === c ? '2px solid var(--tx)' : 'none' }} />
              ))}
            </div>
          </div>
          <button className="primary-btn" onClick={add} style={{ marginBottom: 0 }}><i className="fas fa-plus" /> Add</button>
        </div>

        <div className="cls-table-wrap">
          <div className="cls-table-head">
            <span>Color</span><span>Name</span><span>ID</span><span>Boxes</span><span>Images</span>
            <span style={{ textAlign: 'right' }}>Actions</span>
          </div>
          {classes.map((c) => (
            <div className="cls-row" key={c.id}>
              <span><span className="ct-swatch" style={{ background: c.color, width: 20, height: 20, borderRadius: 5, display: 'inline-block' }} /></span>
              <span>{c.name}</span>
              <span className="mono">{c.id}</span>
              <span className="mono">—</span>
              <span className="mono">—</span>
              <span style={{ textAlign: 'right' }}>
                <button className="ghost-btn sm" onClick={() => del(c.id)}><i className="fas fa-trash-alt" /></button>
              </span>
            </div>
          ))}
          {!classes.length && <div className="uhp-empty"><p className="uhp-empty-title">No classes yet</p></div>}
        </div>
      </div>
    </div>
  );
}
