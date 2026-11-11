import { useState } from 'react';
import { useMembers, useAssignBatch, useUnassignBatch, type Batch } from '../../api/hooks';

/**
 * Assign / Reassign a batch to an annotator — ports the original's `.bam-*`
 * modal. Lists workspace members, lets you pick one, optional note, and (when
 * reassigning) shows the current assignee's progress + a Remove button.
 */
export function AssignModal({ wid, project, batch, onClose }: {
  wid: number; project: string; batch: Batch; onClose: () => void;
}) {
  const { data: members = [], isLoading } = useMembers(wid);
  const assign = useAssignBatch(wid, project);
  const unassign = useUnassignBatch(wid, project);
  const current = batch.assignment;
  const isReassign = !!current;
  const [selected, setSelected] = useState<number | null>(null);
  const [note, setNote] = useState('');

  async function confirm() {
    if (selected == null) return;
    await assign.mutateAsync({ upload_id: batch.upload_id, assigned_to: selected, note });
    onClose();
  }
  async function remove() {
    await unassign.mutateAsync(batch.upload_id);
    onClose();
  }

  return (
    <div className="bam-overlay bam-visible" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="bam-modal" role="dialog" aria-modal="true">
        <div className="bam-head">
          <div className="bam-head-icon"><i className="fas fa-user-tag" /></div>
          <div className="bam-head-info">
            <div className="bam-head-title">{isReassign ? 'Reassign Batch' : 'Assign Batch'}</div>
            <div className="bam-head-sub">Batch #{batch.upload_id} · select an annotator below</div>
          </div>
          <button className="bam-close" aria-label="Close" onClick={onClose}><i className="fas fa-times" /></button>
        </div>

        <div className="bam-body">
          <div className="bam-section-lbl">Choose annotator</div>
          <div className="bam-members">
            {isLoading ? (
              <div className="bam-spinner"><i className="fas fa-circle-notch fa-spin" /> Loading workspace members…</div>
            ) : !members.length ? (
              <div className="bam-empty"><i className="fas fa-users-slash" /><br />No members in this workspace.<br />Invite someone first.</div>
            ) : members.map((m) => {
              const isCurrent = current?.assigned_to === m.user_id;
              return (
                <div key={m.user_id}
                     className={`bam-member-card${isCurrent ? ' bam-current-assign' : ''}${selected === m.user_id ? ' bam-selected' : ''}`}
                     onClick={() => setSelected(m.user_id)}>
                  <div className="bam-member-avatar">{(m.username || '?')[0].toUpperCase()}</div>
                  <div className="bam-member-info">
                    <div className="bam-member-name">{m.username}</div>
                    <div className="bam-member-role">{m.role}</div>
                  </div>
                  {isCurrent && <span className="bam-curr-tag"><i className="fas fa-star" /> Current</span>}
                </div>
              );
            })}
          </div>

          {isReassign && current && (
            <div className="bam-current-block">
              <div className="bam-current-label">Current assignment</div>
              <div className="bam-current-row">
                <div className="bam-current-avatar">{(current.assignee || '?')[0].toUpperCase()}</div>
                <div>
                  <div className="bam-current-name">{current.assignee}</div>
                  <div className={`bam-current-status bam-s-${current.status}`}>{current.status.replace('_', ' ')}</div>
                </div>
                <div className="bam-current-pct">{current.progress_pct}%<br /><small>done</small></div>
              </div>
            </div>
          )}

          <div className="bam-note-wrap">
            <label className="bam-note-lbl">Note <span>(optional)</span></label>
            <textarea className="bam-note-input" rows={2} value={note} onChange={(e) => setNote(e.target.value)}
                      placeholder="Instructions, priority, focus area…" />
          </div>
        </div>

        <div className="bam-footer">
          {isReassign && (
            <button className="bam-unassign-btn" onClick={remove} disabled={unassign.isPending}>
              <i className="fas fa-user-minus" /> Remove
            </button>
          )}
          <div style={{ flex: 1 }} />
          <button className="bam-cancel-btn" onClick={onClose}>Cancel</button>
          <button className="bam-confirm-btn" disabled={selected == null || assign.isPending} onClick={confirm}>
            {assign.isPending
              ? <span className="bam-confirm-spin"><i className="fas fa-circle-notch fa-spin" /></span>
              : <span className="bam-confirm-label"><i className="fas fa-user-check" /> {isReassign ? 'Reassign' : 'Assign'}</span>}
          </button>
        </div>
      </div>
    </div>
  );
}
