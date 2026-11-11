import { useRef, useState } from 'react';
import { Modal } from '../../components/Modal';

export interface FrameSettings { fps: number; size: string; fmt: string; split: string; }

/**
 * Video → Frame Extraction dialog — ports annotate.html's #uploadModal. The
 * original never extracts blind: it always asks FPS / size / format / split
 * first. This modal collects the same four settings and hands them + the chosen
 * videos back to UploadSection, which posts them to /extract_frames.
 */
export function VideoModal({ onClose, onExtract, busy }: {
  onClose: () => void;
  onExtract: (files: File[], s: FrameSettings) => void;
  busy: boolean;
}) {
  const [files, setFiles] = useState<File[]>([]);
  const [fps, setFps] = useState('5');
  const [size, setSize] = useState('original');
  const [fmt, setFmt] = useState('jpg');
  const [split, setSplit] = useState('none');
  const inRef = useRef<HTMLInputElement>(null);

  function addFiles(list: FileList | null) {
    if (!list?.length) return;
    setFiles((prev) => [...prev, ...Array.from(list)]);
  }
  const removeAt = (i: number) => setFiles((p) => p.filter((_, j) => j !== i));

  return (
    <Modal title="Video → Frame Extraction" onClose={onClose} footer={
      <>
        <button className="ghost-btn" onClick={onClose} disabled={busy}>Cancel</button>
        <button className="primary-btn" disabled={!files.length || busy}
                onClick={() => onExtract(files, { fps: +fps, size, fmt, split })}>
          {busy ? <><i className="fas fa-circle-notch fa-spin" /> Extracting…</>
                : <><i className="fas fa-magic" /> Extract Frames</>}
        </button>
      </>
    }>
      {/* Step 1 — select videos */}
      <div className="step-label"><span className="step-num">1</span> Select Video Files</div>
      <input ref={inRef} type="file" accept=".mp4,.avi,.mov,.mkv,.webm" multiple
             style={{ display: 'none' }} onChange={(e) => { addFiles(e.target.files); e.target.value = ''; }} />
      <div className="import-drop" style={{ marginBottom: 10 }}
           onDragOver={(e) => e.preventDefault()}
           onDrop={(e) => { e.preventDefault(); addFiles(e.dataTransfer.files); }}>
        <i className="fas fa-film" />
        <p>Drop video files here or <button className="link-btn" type="button" onClick={() => inRef.current?.click()}>browse</button></p>
        <p style={{ fontSize: 11, color: 'var(--tx3)', marginTop: 4 }}>Supports: mp4, avi, mov, mkv, webm</p>
      </div>

      {files.length > 0 && (
        <div className="video-file-list">
          {files.map((f, i) => (
            <div key={i} className="video-file-row">
              <i className="fas fa-file-video" />
              <span className="vfr-name">{f.name}</span>
              <span className="vfr-size">{(f.size / 1048576).toFixed(1)} MB</span>
              <button className="vfr-x" type="button" title="Remove" onClick={() => removeAt(i)} disabled={busy}><i className="fas fa-times" /></button>
            </div>
          ))}
        </div>
      )}

      {/* Step 2 — settings */}
      <div className="step-label" style={{ marginTop: 14 }}><span className="step-num">2</span> Extraction Settings</div>
      <div className="extract-settings">
        <div className="fg">
          <label>Frame Rate (FPS to extract)</label>
          <select value={fps} onChange={(e) => setFps(e.target.value)}>
            <option value="1">1 fps — sparse keyframes</option>
            <option value="2">2 fps</option>
            <option value="5">5 fps — recommended</option>
            <option value="10">10 fps — dense</option>
            <option value="15">15 fps</option>
            <option value="24">24 fps — every frame (24p video)</option>
            <option value="30">30 fps — every frame (30p video)</option>
          </select>
        </div>
        <div className="fg">
          <label>Output Size</label>
          <select value={size} onChange={(e) => setSize(e.target.value)}>
            <option value="original">Original resolution</option>
            <option value="1080p">1080p (1920×1080)</option>
            <option value="720p">720p (1280×720)</option>
            <option value="480p">480p (854×480)</option>
          </select>
        </div>
        <div className="fg">
          <label>Output Format</label>
          <select value={fmt} onChange={(e) => setFmt(e.target.value)}>
            <option value="jpg">JPG (smaller size)</option>
            <option value="png">PNG (lossless)</option>
          </select>
        </div>
        <div className="fg">
          <label>Output Split</label>
          <select value={split} onChange={(e) => setSplit(e.target.value)}>
            <option value="none">No split — add to root</option>
            <option value="train">Train</option>
            <option value="valid">Valid</option>
            <option value="test">Test</option>
          </select>
        </div>
      </div>
    </Modal>
  );
}
