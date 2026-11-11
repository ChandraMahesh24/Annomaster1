import { useState } from 'react';
import { useDataset, useAddToDataset } from '../../api/hooks';

/** #dataset — ports #page-dataset: .ds-header + .ds-filter-bar (split pills) + splits. */
export function DatasetSection({ wid, project }: { wid: number; project: string }) {
  const { data } = useDataset(wid, project);
  const add = useAddToDataset(wid, project);
  const base = `/api/workspaces/${wid}/projects/${encodeURIComponent(project)}`;
  const [filter, setFilter] = useState<'all' | 'train' | 'val' | 'test' | 'none'>('all');

  const splits = data?.splits ?? { train: 0, valid: 0, test: 0 } as Record<string, number>;

  return (
    <div className="page" id="page-dataset">
      <div className="ds-header">
        <div className="ds-title"><i className="fas fa-images" /> Dataset</div>
        <div className="ds-controls">
          <button className="primary-btn" onClick={() => add.mutate(undefined)}>
            <i className="fas fa-plus" /> Add annotated (70/20/10)
          </button>
        </div>
      </div>

      <div className="ds-filter-bar">
        <div className="ds-filter-group">
          <span className="ds-filter-label"><i className="fas fa-sitemap" /> Split</span>
          <div className="ds-pills">
            <button className={`ds-pill${filter === 'all' ? ' active' : ''}`} onClick={() => setFilter('all')}>All</button>
            <button className={`ds-pill ds-split-train${filter === 'train' ? ' active' : ''}`} onClick={() => setFilter('train')}><span className="ds-split-dot train" />Train</button>
            <button className={`ds-pill ds-split-valid${filter === 'val' ? ' active' : ''}`} onClick={() => setFilter('val')}><span className="ds-split-dot valid" />Val</button>
            <button className={`ds-pill ds-split-test${filter === 'test' ? ' active' : ''}`} onClick={() => setFilter('test')}><span className="ds-split-dot test" />Test</button>
          </div>
        </div>
        <div className="ds-filter-group" style={{ marginLeft: 'auto' }}>
          <span className="ds-filter-label"><i className="fas fa-file-export" /> Export</span>
          <div className="ds-pills">
            {(['yolo', 'coco', 'voc'] as const).map((f) => (
              <a key={f} className="ds-pill" href={`${base}/export?format=${f}`}>{f.toUpperCase()}</a>
            ))}
          </div>
        </div>
      </div>

      <div style={{ display: 'flex', gap: 16, padding: 24 }}>
        {(['train', 'valid', 'test'] as const).map((s) => (
          <div key={s} className="uhp-batch-card" style={{ textAlign: 'center', minWidth: 120 }}>
            <div style={{ fontSize: 30, fontWeight: 800, color: 'var(--accent)' }}>{splits[s] ?? 0}</div>
            <div className="uhp-batch-meta" style={{ textTransform: 'uppercase' }}>{s}</div>
          </div>
        ))}
        <div className="uhp-batch-card" style={{ textAlign: 'center', minWidth: 120 }}>
          <div style={{ fontSize: 30, fontWeight: 800 }}>{data?.total ?? 0}</div>
          <div className="uhp-batch-meta">TOTAL</div>
        </div>
      </div>
    </div>
  );
}
