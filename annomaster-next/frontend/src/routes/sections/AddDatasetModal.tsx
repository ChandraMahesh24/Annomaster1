import { useState } from 'react';
import { useAddBatchToDataset, type Batch } from '../../api/hooks';

/**
 * "Add to Completed Dataset" — ports the original's `.usp-*` split modal. Shows
 * how many images will move (annotated + null) vs stay (raw), lets you set
 * train/val/test ratios with live sliders, and on confirm sends only the
 * annotated images to the dataset (Roboflow-style). Files never move server-side.
 */
export function AddDatasetModal({ wid, project, batch, onClose, onDone }: {
  wid: number; project: string; batch: Batch;
  onClose: () => void; onDone: (msg: string) => void;
}) {
  const add = useAddBatchToDataset(wid, project);
  const [train, setTrain] = useState(70);
  const [val, setVal] = useState(15);
  const [test, setTest] = useState(15);
  const sum = train + val + test;
  const bad = Math.abs(sum - 100) > 0.5;

  async function confirm() {
    if (bad) return;
    const r = await add.mutateAsync({
      upload_id: batch.upload_id, train: train / 100, val: val / 100, test: test / 100,
    });
    const sc = r.split_counts;
    onDone(`Dataset updated: ${r.moved_annotated} image${r.moved_annotated !== 1 ? 's' : ''} → ` +
      `train:${sc.train} · val:${sc.val} · test:${sc.test}` +
      (r.remaining_raw > 0 ? ` · ${r.remaining_raw} raw remain in Active Work` : ''));
    onClose();
  }

  const annotated = batch.annotated;
  const raw = batch.pending;
  const nul = batch.null_count;

  return (
    <div className="usp-overlay" style={{ display: 'flex' }} onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="usp-modal">
        <div className="usp-head">
          <div className="usp-head-icon"><i className="fas fa-database" /></div>
          <div className="usp-head-text">
            <div className="usp-head-title">Add to Completed Dataset</div>
            <div className="usp-head-sub">Set split ratios for annotated images</div>
          </div>
          <button className="usp-close" onClick={onClose}><i className="fas fa-times" /></button>
        </div>

        <div className="usp-info-strip">
          <div className="usp-info-cell annotated">
            <div className="usp-info-num">{annotated}</div>
            <div className="usp-info-lbl">Annotated → Dataset</div>
          </div>
          <div className="usp-info-cell raw">
            <div className="usp-info-num">{raw}</div>
            <div className="usp-info-lbl">Raw → Stay in Batch</div>
          </div>
          <div className="usp-info-cell null">
            <div className="usp-info-num">{nul}</div>
            <div className="usp-info-lbl">Null refs → Dataset</div>
          </div>
        </div>

        <div className="usp-split-section">
          <div className="usp-split-label-row">
            <span>Split Ratios</span>
            {bad && <span className="usp-ratio-err" style={{ display: 'inline' }}><i className="fas fa-exclamation-circle" /> Must sum to 100%</span>}
          </div>
          <div className="usp-preview-bar">
            <div className="usp-preview-train" style={{ width: `${train}%` }}>Train</div>
            <div className="usp-preview-val" style={{ width: `${val}%` }}>Val</div>
            <div className="usp-preview-test" style={{ width: `${test}%` }}>Test</div>
          </div>
          <div className="usp-sliders">
            <SliderRow icon="fa-dumbbell" cls="train" label="Train" value={train} onChange={setTrain} />
            <SliderRow icon="fa-check-circle" cls="val" label="Val" value={val} onChange={setVal} />
            <SliderRow icon="fa-flask" cls="test" label="Test" value={test} onChange={setTest} />
          </div>
        </div>

        <div className="usp-note">
          <i className="fas fa-info-circle" />
          Annotated images will be <strong>added to the dataset</strong> (their split is set). Raw images stay in Active Work.
        </div>

        <div className="usp-footer">
          <button className="usp-cancel-btn" onClick={onClose}><i className="fas fa-times" /> Cancel</button>
          <button className="usp-confirm-btn" disabled={bad || annotated + nul === 0 || add.isPending} onClick={confirm}>
            {add.isPending ? <><i className="fas fa-circle-notch fa-spin" /> Creating…</> : <><i className="fas fa-check" /> Create Dataset</>}
          </button>
        </div>
      </div>
    </div>
  );
}

function SliderRow({ icon, cls, label, value, onChange }: {
  icon: string; cls: string; label: string; value: number; onChange: (n: number) => void;
}) {
  return (
    <div className="usp-slider-row">
      <div className={`usp-slider-lbl ${cls}`}><i className={`fas ${icon}`} /> {label}</div>
      <input type="range" min={0} max={100} step={5} value={value} className={`usp-range ${cls}`}
             onChange={(e) => onChange(+e.target.value)} />
      <div className="usp-slider-pct">{value}%</div>
    </div>
  );
}
