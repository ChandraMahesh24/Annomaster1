import { useEffect, useRef, useState } from 'react';
import { logAutosave, predict, useAiSettings, useModelInfo, useModels, useSaveAiSettings, useUploadModel } from '../api/ai';
import type { Detection } from './boxes';
import { suggested } from './boxes';
import type { Action, CanvasState } from './reducer';

interface Props {
  wid: number; project: string;
  imagePath: string | null;
  dims: { w: number; h: number };
  state: CanvasState;
  dispatch: (a: Action) => void;
  onClose?: () => void;
}

/**
 * Smart Detect bar — ports the compact `.sd-bar` from annotate-v2.css: model
 * selector, Confidence + Overlap sliders, Approve N, Auto-approve, re-run.
 * Auto-runs on image change (idempotent via reconcile-against-saved-state).
 */
export function SmartDetect({ wid, project, imagePath, dims, state, dispatch, onClose }: Props) {
  const { data: models = [] } = useModels();
  const { data: settings } = useAiSettings(wid, project);
  const save = useSaveAiSettings(wid, project);
  const uploadModel = useUploadModel();

  // Upload a new .pt model, then auto-select it (everything else stays the same).
  async function onUploadModel(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    e.target.value = '';
    if (!f) return;
    if (!f.name.endsWith('.pt')) { setStatus('Only .pt model files are allowed.'); return; }
    setStatus(`Uploading ${f.name}…`);
    try {
      const r = await uploadModel.mutateAsync(f);
      const name = r.name || f.name;
      setModel(name); save.mutate({ model: name });
      lastRun.current = null;                 // let it re-detect with the new model
      setStatus(`Model “${name}” ready.`);
    } catch (err) { setStatus((err as Error).message); }
  }

  const [model, setModel] = useState<string | null>(null);
  const [conf, setConf] = useState(0.45);
  const [iou, setIou] = useState(0.5);
  const [auto, setAuto] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [status, setStatus] = useState('');
  const lastRun = useRef<string | null>(null);

  // ── Draggable bar ──────────────────────────────────────────────────────────
  // The CSS is ready (.is-moved clears the default anchor; .is-dragging shows a
  // grabbing cursor). Drag by the header; position persists as a FRACTION of the
  // canvas area so it survives resizes and never lands off-screen.
  const barRef = useRef<HTMLDivElement>(null);
  const [moved, setMoved] = useState<{ x: number; y: number } | null>(null);
  const [dragging, setDragging] = useState(false);
  const dragStart = useRef<{ mx: number; my: number; ox: number; oy: number } | null>(null);
  const posRef = useRef<{ x: number; y: number } | null>(null);
  const POS_KEY = 'am_sd_pos';

  function clampPos(x: number, y: number) {
    const bar = barRef.current; if (!bar) return { x, y };
    const parent = bar.offsetParent as HTMLElement | null;
    const pw = parent?.clientWidth ?? window.innerWidth;
    const ph = parent?.clientHeight ?? window.innerHeight;
    return {
      x: Math.max(4, Math.min(x, pw - bar.offsetWidth - 4)),
      y: Math.max(4, Math.min(y, ph - 40)),
    };
  }

  // restore saved position after first layout
  useEffect(() => {
    const bar = barRef.current; if (!bar) return;
    try {
      const raw = localStorage.getItem(POS_KEY); if (!raw) return;
      const f = JSON.parse(raw);
      const parent = bar.offsetParent as HTMLElement | null;
      const pw = parent?.clientWidth ?? window.innerWidth;
      const ph = parent?.clientHeight ?? window.innerHeight;
      setMoved(clampPos(Math.round(f.fx * pw), Math.round(f.fy * ph)));
    } catch { /* ignore */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function onHeadDown(e: React.PointerEvent) {
    if ((e.target as Element).closest('button, select, input, a, label')) return;  // let controls work
    const bar = barRef.current; if (!bar) return;
    e.preventDefault();
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
    dragStart.current = { mx: e.clientX, my: e.clientY, ox: bar.offsetLeft, oy: bar.offsetTop };
    setDragging(true);
  }
  function onHeadMove(e: React.PointerEvent) {
    if (!dragStart.current) return;
    const d = dragStart.current;
    const p = clampPos(d.ox + (e.clientX - d.mx), d.oy + (e.clientY - d.my));
    posRef.current = p;
    setMoved(p);
  }
  function onHeadUp() {
    if (!dragStart.current) return;
    dragStart.current = null;
    setDragging(false);
    const parent = barRef.current?.offsetParent as HTMLElement | null;
    if (posRef.current && parent) {
      try {
        localStorage.setItem(POS_KEY, JSON.stringify({
          fx: posRef.current.x / parent.clientWidth,
          fy: posRef.current.y / parent.clientHeight,
        }));
      } catch { /* ignore */ }
    }
  }

  useEffect(() => {
    if (!settings) return;
    setModel(settings.model); setConf(settings.conf); setIou(settings.iou);
    setAuto(settings.mode === 'autosave');
  }, [settings]);

  const info = useModelInfo(model);

  async function run(path: string) {
    if (!model) { setStatus('No model — add a .pt to models/.'); return; }
    setStatus('Detecting…');
    try {
      const r = await predict(wid, project, path, model, conf);
      const W = dims.w || 1, H = dims.h || 1;
      const dets: Detection[] = r.predictions.map((p) => ({
        cls: p.yolo_cls_id, x: (p.x_center - p.width / 2) * W, y: (p.y_center - p.height / 2) * H,
        w: p.width * W, h: p.height * H, conf: p.conf,
      }));
      dispatch({ t: 'APPLY_DETECTIONS', detections: dets, autoSave: auto, iou });
      if (auto) { logAutosave(wid, project, { path, model, conf, added: dets.length }); setStatus(`Auto-saved ${dets.length}.`); }
      else setStatus(`${dets.length} detection(s) — review.`);
    } catch (e) { setStatus((e as Error).message); }
  }

  useEffect(() => {
    if (imagePath && model && imagePath !== lastRun.current && dims.w) { lastRun.current = imagePath; void run(imagePath); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [imagePath, model, dims.w]);

  const persist = (patch: Parameters<typeof save.mutate>[0]) => save.mutate(patch);
  const pending = suggested(state.boxes).length;
  const classCount = info.data?.class_count ?? info.data?.classes?.length;

  return (
    <div ref={barRef}
         className={`sd-bar${auto ? ' is-auto' : ''}${collapsed ? ' is-collapsed' : ''}${moved ? ' is-moved' : ''}${dragging ? ' is-dragging' : ''}`}
         style={moved ? { left: moved.x, top: moved.y } : undefined}>
      {/* Row 1 — head (drag handle) */}
      <div className="sd-bar-head" onPointerDown={onHeadDown} onPointerMove={onHeadMove} onPointerUp={onHeadUp} title="Drag to move">
        <span className="sd-bar-icon"><i className="fas fa-wand-magic-sparkles" /></span>
        <span className="sd-bar-title">Smart Detect</span>
        <select className="sd-bar-model" value={model ?? ''} onChange={(e) => { setModel(e.target.value); persist({ model: e.target.value }); }}>
          {models.length ? models.map((m) => <option key={m.name} value={m.name}>{m.name}</option>) : <option value="">No models</option>}
        </select>
        <label className="sd-icon-btn sd-upload-mini" title="Upload a new .pt YOLO model">
          <input type="file" accept=".pt" hidden disabled={uploadModel.isPending} onChange={onUploadModel} />
          <i className={`fas ${uploadModel.isPending ? 'fa-circle-notch fa-spin' : 'fa-upload'}`} />
        </label>
        <span className="sd-badge">{auto ? 'Auto-approving' : 'AI Labeling'}</span>
        <button className="sd-icon-btn" title={collapsed ? 'Expand' : 'Collapse'} onClick={() => setCollapsed((c) => !c)}>
          <i className={`fas fa-chevron-${collapsed ? 'down' : 'up'}`} />
        </button>
        {onClose && <button className="sd-icon-btn" title="Close" onClick={onClose}><i className="fas fa-times" /></button>}
      </div>

      {/* Row 2 — sliders + approve */}
      <div className="sd-bar-body">
        <div className="sd-ctrl">
          <div className="sd-ctrl-top">
            <span className="sd-ctrl-label">Confidence</span>
            <button className="sd-help" title="Detections below this score are discarded."><i className="fas fa-circle-question" /></button>
            <span className="sd-ctrl-val">{Math.round(conf * 100)}%</span>
          </div>
          <input className="sd-range" type="range" min={5} max={95} step={5} value={Math.round(conf * 100)}
                 onChange={(e) => setConf(Number(e.target.value) / 100)} onMouseUp={() => persist({ conf })} />
        </div>
        <div className="sd-ctrl">
          <div className="sd-ctrl-top">
            <span className="sd-ctrl-label">Overlap</span>
            <button className="sd-help" title="How much a detection must overlap an existing box to count as the same object."><i className="fas fa-circle-question" /></button>
            <span className="sd-ctrl-val">{Math.round(iou * 100)}%</span>
          </div>
          <input className="sd-range" type="range" min={5} max={95} step={5} value={Math.round(iou * 100)}
                 onChange={(e) => setIou(Number(e.target.value) / 100)} onMouseUp={() => persist({ iou })} />
        </div>
        <button className="sd-approve" disabled={!pending} onClick={() => dispatch({ t: 'ACCEPT_ALL' })}>
          <i className="fas fa-check" /> {pending ? `Approve ${pending}` : 'No predictions'}
        </button>
      </div>

      {/* Row 3 — foot */}
      <div className="sd-bar-foot">
        <span className="sd-bar-meta">
          {info.data?.valid ? `${classCount} class${classCount !== 1 ? 'es' : ''}` : (info.isError ? 'model error' : '')}
        </span>
        <label className="sd-check">
          <input type="checkbox" checked={auto} onChange={(e) => { setAuto(e.target.checked); persist({ mode: e.target.checked ? 'autosave' : 'review' }); }} />
          Auto-approve
        </label>
        <button className="sd-icon-btn sd-run-now" title="Re-run on this image" onClick={() => imagePath && run(imagePath)}><i className="fas fa-paper-plane" /></button>
        {status && <span className="sd-upload-status">{status}</span>}
      </div>
    </div>
  );
}
