import type { Batch } from '../../api/hooks';

const SRC_META: Record<string, { icon: string; color: string; label: string }> = {
  folder: { icon: 'fa-folder-open', color: '#f59e0b', label: 'FOLDER' },
  zip: { icon: 'fa-file-archive', color: '#818cf8', label: 'ZIP' },
  video: { icon: 'fa-film', color: '#a855f7', label: 'VIDEO' },
  images: { icon: 'fa-images', color: '#22c5e1', label: 'IMAGES' },
  upload: { icon: 'fa-images', color: '#22c5e1', label: 'IMAGES' },
};
const STATUS_META: Record<string, { color: string; icon: string; label: string }> = {
  pending: { color: '#f59e0b', icon: 'fa-clock', label: 'Pending' },
  in_progress: { color: '#22c5e1', icon: 'fa-pen', label: 'In Progress' },
  submitted: { color: '#a855f7', icon: 'fa-paper-plane', label: 'Submitted' },
  approved: { color: '#22c55e', icon: 'fa-check-circle', label: 'Approved' },
  rejected: { color: '#ef4444', icon: 'fa-times-circle', label: 'Rejected' },
};
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function parseDateTime(s: string | null): { day: string; time: string } {
  const m = (s || '').match(/(\d{4})-(\d{2})-(\d{2})[_T](\d{2})[-:](\d{2})/);
  if (!m) return { day: s || 'Batch', time: '' };
  const h = parseInt(m[4]);
  return {
    day: `${MONTHS[parseInt(m[2]) - 1]} ${parseInt(m[3])}`,
    time: `${h % 12 || 12}:${m[5]} ${h < 12 ? 'AM' : 'PM'}`,
  };
}

/**
 * Compact Active-Work batch card. Deliberately DENSER than the original (which
 * stacked 5 tall bands): one header line (icon · date · source · delete), a thin
 * progress bar, a single stat line (counts + %), one thin assignee line, and a
 * compact action row. Styled by upload.css under #page-upload.
 */
export function BatchCard({ batch, onOpen, onAssign, onAddDataset, onDelete }: {
  batch: Batch;
  onOpen: (mode: 'review' | 'raw') => void;
  onAssign: () => void;
  onAddDataset: () => void;
  onDelete: () => void;
}) {
  const { annotated, null_count: nul, pending, total } = batch;
  const pct = total > 0 ? Math.round((annotated + nul) / total * 100) : 0;
  const src = SRC_META[batch.source] || SRC_META.images;
  const { day, time } = parseDateTime(batch.datetime_str);
  const asgn = batch.assignment;
  const sm = asgn ? (STATUS_META[asgn.status] || { color: '#6b7280', icon: 'fa-circle', label: asgn.status }) : null;
  const stop = (fn: () => void) => (e: React.MouseEvent) => { e.stopPropagation(); fn(); };

  return (
    <div className="uhp-batch-card" data-upload-id={batch.upload_id} onClick={() => onOpen('review')}>
      {/* Header — one line */}
      <div className="uhp-card-head">
        <div className={`uhp-card-icon ${batch.source}`}><i className={`fas ${src.icon}`} /></div>
        <div className="uhp-card-meta">
          <div className="uhp-card-daystr">{day} <span className="uhp-card-timestr">{time}</span></div>
        </div>
        <div className="uhp-head-right">
          <span className="uhp-src-badge" style={{ background: `${src.color}22`, color: src.color, borderColor: `${src.color}44` }}>{src.label}</span>
          {batch.in_dataset && <span className="uhp-ds-badge" title="In dataset"><i className="fas fa-check-circle" /></span>}
          <button className="uhp-card-del" title="Delete batch" onClick={stop(onDelete)}><i className="fas fa-trash-alt" /></button>
        </div>
      </div>

      {/* Progress bar + single stat line */}
      {total > 0 ? (
        <div className="uhp-folder-breakdown">
          <div className="uhp-anno-bar-wrap">
            <div className="uhp-anno-bar-annotated" style={{ width: `${Math.round(annotated / total * 100)}%` }} />
            <div className="uhp-anno-bar-null" style={{ width: `${Math.round(nul / total * 100)}%` }} />
            <div className="uhp-anno-bar-raw" />
          </div>
          <div className="uhp-stat-line">
            <span className="uhp-stat-total">{total} img</span>
            {annotated > 0 && <span className="uhp-stat done">{annotated} done</span>}
            {pending > 0 && <span className="uhp-stat raw">{pending} raw</span>}
            {nul > 0 && <span className="uhp-stat null">{nul} null</span>}
            <span className="uhp-stat-pct">{pct}%</span>
          </div>
        </div>
      ) : (
        <div className="uhp-folder-empty"><i className="fas fa-inbox" /> No images yet</div>
      )}

      {/* Assignee — one thin line */}
      <div className="uhp-assign-row">
        {asgn && sm ? (
          <span className="uhp-assignee" style={{ color: sm.color }}>
            <i className={`fas ${sm.icon}`} /> {asgn.assignee}
            <span className="uhp-assignee-pct">{asgn.progress_pct}%</span>
          </span>
        ) : (
          <span className="uhp-assignee unassigned">
            <i className="fas fa-user-slash" /> Unassigned
            {batch.uploader_name && <span className="uhp-uploader">· by {batch.uploader_name}</span>}
          </span>
        )}
      </div>

      {/* Actions — three equal buttons on one row (open · assign · dataset), so
          labels always fit without clipping. The open button jumps to raw work
          when there's any, else reviews. */}
      <div className="uhp-card-footer">
        <button className="uhp-btn annotate" onClick={stop(() => onOpen(pending > 0 ? 'raw' : 'review'))}
                title={pending > 0 ? 'Annotate raw images' : 'Review annotations'}>
          <i className={`fas ${pending > 0 ? 'fa-pen-nib' : 'fa-eye'}`} /> {pending > 0 ? 'Annotate' : 'Review'}
        </button>
        <button className={`uhp-btn assign ${asgn ? 'reassign' : ''}`} onClick={stop(onAssign)} title={asgn ? 'Reassign' : 'Assign'}>
          <i className="fas fa-user-tag" /> {asgn ? 'Reassign' : 'Assign'}
        </button>
        <button className={`uhp-btn add-ds ${batch.in_dataset ? 'readd' : ''} ${batch.partial_dataset ? 'partial' : ''}`} onClick={stop(onAddDataset)}
                title={batch.partial_dataset ? 'Add remaining' : batch.in_dataset ? 'Re-add' : 'Add to dataset'}>
          <i className="fas fa-database" /> {batch.partial_dataset ? 'Add Rest' : batch.in_dataset ? 'Re-add' : 'Dataset'}
        </button>
      </div>
    </div>
  );
}
