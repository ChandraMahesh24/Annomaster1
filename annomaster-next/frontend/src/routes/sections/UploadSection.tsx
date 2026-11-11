import { useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api } from '../../api/client';
import { useBatches, useDataset, type Batch } from '../../api/hooks';
import { VideoModal, type FrameSettings } from './VideoModal';
import { BatchCard } from './BatchCard';
import { AssignModal } from './AssignModal';
import { AddDatasetModal } from './AddDatasetModal';

/**
 * #upload — ports pages/upload.html's 3-column `.up-layout`:
 *   Active Work (batches) · Upload Data (big drop + 4 option cards) · Completed
 * Datasets. Styled by the ported upload.css. `onOpenBatch` opens the annotator
 * filtered to that batch (set by the Workspace shell).
 */
export function UploadSection({ wid, project, onOpenBatch }: {
  wid: number; project: string;
  onOpenBatch: (batch: Batch, mode: 'review' | 'raw') => void;
}) {
  const base = `/workspaces/${wid}/projects/${encodeURIComponent(project)}`;
  const qc = useQueryClient();
  const { data: batches = [], refetch } = useBatches(wid, project);
  const { data: dataset } = useDataset(wid, project);
  const [prog, setProg] = useState<{ pct: number; text: string } | null>(null);
  const [result, setResult] = useState('');
  const [assignBatch, setAssignBatch] = useState<Batch | null>(null);
  const [datasetBatch, setDatasetBatch] = useState<Batch | null>(null);

  const [videoOpen, setVideoOpen] = useState(false);
  const imgRef = useRef<HTMLInputElement>(null);
  const folderRef = useRef<HTMLInputElement>(null);
  const zipRef = useRef<HTMLInputElement>(null);

  const loadBatches = () => qc.invalidateQueries({ queryKey: ['batches', wid, project] });

  async function deleteBatch(b: Batch) {
    if (!confirm(`Delete batch #${b.upload_id} and all its images? This cannot be undone.`)) return;
    await api(`${base}/uploads/${b.upload_id}`, { method: 'DELETE' }).catch(() => {});
    loadBatches();
  }

  async function send(ep: string, list: FileList, field: 'file' | 'files', label: string) {
    setResult(''); setProg({ pct: 30, text: `Uploading ${label}…` });
    const form = new FormData();
    if (field === 'file') form.append('file', list[0]);
    else Array.from(list).forEach((f) => form.append('files', f));
    try {
      const r = await api<{ saved: number; duplicates: number; frames_extracted?: number }>(`${base}/${ep}`, { form });
      setProg({ pct: 100, text: 'Done' });
      setResult(r.frames_extracted != null ? `Extracted ${r.frames_extracted} frames.` : `Saved ${r.saved}, ${r.duplicates} duplicate(s).`);
      loadBatches();
    } catch (e) { setResult((e as Error).message); }
    finally { setTimeout(() => setProg(null), 800); }
  }

  // Video → frame extraction. Posts each chosen video with the settings from
  // the modal (fps/size/format/split), exactly like the original's #uploadModal.
  async function extractFrames(files: File[], s: FrameSettings) {
    setResult('');
    let total = 0;
    try {
      for (let i = 0; i < files.length; i++) {
        setProg({ pct: files.length > 1 ? Math.round((i / files.length) * 90) : 30,
                  text: `Extracting ${files[i].name}…` });
        const form = new FormData();
        form.append('file', files[i]);
        form.append('fps', String(s.fps));
        form.append('fmt', s.fmt);
        form.append('size', s.size);
        form.append('split', s.split);
        const r = await api<{ frames_extracted?: number; mode?: string }>(`${base}/extract_frames`, { form });
        if (r.mode === 'celery') { setResult('Extraction queued — frames will appear shortly.'); }
        else total += r.frames_extracted ?? 0;
      }
      setProg({ pct: 100, text: 'Done' });
      if (total) setResult(`Extracted ${total} frame${total === 1 ? '' : 's'}.`);
      setVideoOpen(false);
      loadBatches();
    } catch (e) { setResult((e as Error).message); }
    finally { setTimeout(() => setProg(null), 800); }
  }

  const CARDS = [
    { id: 'images', icon: 'fa-images', title: 'Raw Images', sub: 'JPG / PNG', on: () => imgRef.current?.click() },
    { id: 'folder', icon: 'fa-folder-open', title: 'YOLO Folder', sub: 'images + labels', on: () => folderRef.current?.click() },
    { id: 'video', icon: 'fa-film', title: 'Video Frames', sub: 'extract via ffmpeg', on: () => setVideoOpen(true) },
    { id: 'zip', icon: 'fa-file-archive', title: 'ZIP Dataset', sub: 'import archive', on: () => zipRef.current?.click() },
  ];

  return (
    <div className="page" id="page-upload">
      <div className="up-layout">
        {/* hidden inputs */}
        <input ref={imgRef} type="file" accept="image/*" multiple hidden onChange={(e) => e.target.files?.length && send('upload/folder', e.target.files, 'files', 'images')} />
        {/* YOLO folder: webkitdirectory lets the user pick a whole images+labels
            tree (as in the original). The backend matches labels to images by
            stem, so nested images/ ⁄ labels/ subdirs are fine. */}
        <input ref={folderRef} type="file" multiple hidden
               accept=".jpg,.jpeg,.png,.bmp,.tiff,.webp,.txt,.yaml,.yml"
               {...({ webkitdirectory: '', directory: '' } as Record<string, string>)}
               onChange={(e) => e.target.files?.length && send('upload/folder', e.target.files, 'files', 'folder')} />
        <input ref={zipRef} type="file" accept=".zip" hidden onChange={(e) => e.target.files?.length && send('import', e.target.files, 'file', 'ZIP')} />

        {/* ── LEFT: Active Work ── */}
        <aside className="up-pane up-activework-pane">
          <div className="up-pane-head">
            <div className="up-pane-head-left">
              <h2 className="up-pane-title">Active Work</h2>
              <span className="up-pane-badge">{batches.length}</span>
            </div>
            <div className="up-pane-actions">
              <button className="up-icon-btn" title="Refresh" onClick={() => refetch()}><i className="fas fa-sync-alt" /></button>
            </div>
          </div>
          <div className="uhp-list">
            {batches.length ? batches.map((b) => (
              <BatchCard key={b.upload_id} batch={b}
                         onOpen={(mode) => onOpenBatch(b, mode)}
                         onAssign={() => setAssignBatch(b)}
                         onAddDataset={() => setDatasetBatch(b)}
                         onDelete={() => deleteBatch(b)} />
            )) : (
              <div className="uhp-empty">
                <div className="uhp-empty-icon"><i className="fas fa-inbox" /></div>
                <p className="uhp-empty-title">No batches yet</p>
                <span className="uhp-empty-sub">Upload images or a YOLO dataset to get started</span>
              </div>
            )}
          </div>
        </aside>

        {/* ── CENTER: Upload Data ── */}
        <main className="up-pane up-upload-pane">
          <div className="up-pane-head">
            <div className="up-pane-head-left"><h2 className="up-pane-title">Upload Data</h2></div>
            <div className="up-pane-project-wrap"><i className="fas fa-folder-open" /> {project}</div>
          </div>
          <div className="up-upload-body">
            <div className="upload-big-drop" onClick={() => imgRef.current?.click()}
                 onDragOver={(e) => e.preventDefault()}
                 onDrop={(e) => { e.preventDefault(); if (e.dataTransfer.files?.length) send('upload/folder', e.dataTransfer.files, 'files', 'images'); }}>
              <div className="ubd-icon-ring"><i className="fas fa-cloud-upload-alt" /></div>
              <h3 className="ubd-title">Drop your dataset here</h3>
              <p className="ubd-desc">Images, a YOLO folder, a ZIP, or a video</p>
              <button className="ubd-browse-btn" type="button">Browse Files</button>
            </div>

            <div className="up-cards-grid">
              {CARDS.map((c) => (
                <div key={c.id} className="upload-option-card" onClick={c.on}>
                  <div className={`uoc-icon-wrap ${c.id}`}><i className={`fas ${c.icon}`} /></div>
                  <span className="uoc-title">{c.title}</span>
                  <span className="uoc-sub">{c.sub}</span>
                </div>
              ))}
            </div>

            {prog && (
              <div className="up-prog-wrap">
                <div className="up-prog-top">
                  <div className="up-prog-label"><i className="fas fa-circle-notch fa-spin" /> {prog.text}</div>
                  <div className="up-prog-pct">{prog.pct}%</div>
                </div>
                <div className="up-prog-bar"><div className="up-prog-fill" style={{ width: `${prog.pct}%` }} /></div>
              </div>
            )}
            {result && <div className="up-import-result">{result}</div>}
          </div>
        </main>

        {/* ── RIGHT: Completed Datasets ── */}
        <aside className="up-pane up-datasets-pane">
          <div className="up-pane-head">
            <div className="up-pane-head-left">
              <h2 className="up-pane-title">Completed Datasets</h2>
              <span className="up-pane-badge">{dataset?.total ?? 0}</span>
            </div>
          </div>
          <div className="upds-list">
            {dataset && dataset.total > 0 ? (
              <div className="upds-card">
                <div className="upds-card-header">
                  <div className="upds-card-icon-wrap"><i className="fas fa-database" /></div>
                  <div className="upds-card-info">
                    <div className="upds-date-main">Current Dataset</div>
                    <div className="upds-date-time">confirmed labels only</div>
                  </div>
                  <div className="upds-total-chip">
                    <div className="upds-total-num">{dataset.total}</div>
                    <div className="upds-total-lbl">images</div>
                  </div>
                </div>
                <div className="upds-split-compact">
                  <div className="upds-split-bar-wrap">
                    <div className="upds-split-bar-train" style={{ width: `${(dataset.splits.train || 0) / dataset.total * 100}%` }} />
                    <div className="upds-split-bar-valid" style={{ width: `${(dataset.splits.valid || 0) / dataset.total * 100}%` }} />
                    <div className="upds-split-bar-test" style={{ width: `${(dataset.splits.test || 0) / dataset.total * 100}%` }} />
                  </div>
                  <div className="upds-split-pct-row">
                    <span className="train">Train {dataset.splits.train || 0}</span>
                    <span className="valid">Valid {dataset.splits.valid || 0}</span>
                    <span className="test">Test {dataset.splits.test || 0}</span>
                  </div>
                </div>
              </div>
            ) : (
              <div className="uhp-empty">
                <div className="uhp-empty-icon"><i className="fas fa-database" /></div>
                <p className="uhp-empty-title">No datasets yet</p>
                <span className="uhp-empty-sub">Annotate a batch then add it to a dataset</span>
              </div>
            )}
          </div>
        </aside>
      </div>

      {videoOpen && (
        <VideoModal busy={!!prog} onClose={() => !prog && setVideoOpen(false)} onExtract={extractFrames} />
      )}
      {assignBatch && (
        <AssignModal wid={wid} project={project} batch={assignBatch} onClose={() => setAssignBatch(null)} />
      )}
      {datasetBatch && (
        <AddDatasetModal wid={wid} project={project} batch={datasetBatch}
                         onClose={() => setDatasetBatch(null)} onDone={(msg) => setResult(msg)} />
      )}
    </div>
  );
}
