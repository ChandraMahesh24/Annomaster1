import { useState } from 'react';
import { useVersions, useCreateVersion } from '../../api/hooks';
import { Modal } from '../../components/Modal';

/** #versions — ports #page-versions: header + version cards + a create drawer.
 *  (The original's 4-step Source/Split/Preprocess/Augment wizard is condensed
 *  to a single create dialog for now; refined in U7.) */
export function VersionsSection({ wid, project }: { wid: number; project: string }) {
  const { data: versions = [] } = useVersions(wid, project);
  const create = useCreateVersion(wid, project);
  const [show, setShow] = useState(false);
  const [name, setName] = useState('');
  const [note, setNote] = useState('');
  const base = `/api/workspaces/${wid}/projects/${encodeURIComponent(project)}`;

  return (
    <div className="page" id="page-versions">
      <div className="cls-page-header">
        <h2><i className="fas fa-history" /> Dataset Versions</h2>
        <button className="primary-btn" onClick={() => setShow(true)}><i className="fas fa-plus" /> New Version</button>
      </div>

      <div className="cls-page-body">
        {versions.length ? versions.map((v) => (
          <div key={v.name} className="version-card">
            <div className="version-header">
              <div>
                <div className="version-name">{v.name}</div>
                {v.note && <div className="version-note">{v.note}</div>}
                <div className="version-meta">
                  <span>{v.num_images} images</span>
                  <span>train {v.splits?.train ?? 0} · valid {v.splits?.valid ?? 0} · test {v.splits?.test ?? 0}</span>
                </div>
              </div>
              <div className="version-actions">
                <a className="ghost-btn sm" href={`${base}/export?format=yolo&version=${encodeURIComponent(v.name)}`}>
                  <i className="fas fa-download" /> Download
                </a>
              </div>
            </div>
          </div>
        )) : (
          <div className="uhp-empty">
            <div className="uhp-empty-icon"><i className="fas fa-history" /></div>
            <p className="uhp-empty-title">No versions yet</p>
            <span className="uhp-empty-sub">Snapshot your annotated data for training</span>
          </div>
        )}
      </div>

      {show && (
        <Modal title="Create Dataset Version" onClose={() => setShow(false)} footer={<>
          <button className="btn btn-secondary" onClick={() => setShow(false)}>Cancel</button>
          <button className="btn btn-primary" disabled={!name.trim() || create.isPending}
            onClick={async () => { await create.mutateAsync({ name: name.trim(), note }); setShow(false); setName(''); setNote(''); }}>
            Create Snapshot
          </button>
        </>}>
          <div className="form-group">
            <label className="form-label">Version name</label>
            <input className="form-input" value={name} onChange={(e) => setName(e.target.value)} placeholder="v1" autoFocus />
          </div>
          <div className="form-group">
            <label className="form-label">Note (optional)</label>
            <input className="form-input" value={note} onChange={(e) => setNote(e.target.value)} placeholder="What changed" />
          </div>
        </Modal>
      )}
    </div>
  );
}
