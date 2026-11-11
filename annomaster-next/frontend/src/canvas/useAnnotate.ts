import { useCallback, useEffect, useReducer, useRef, useState } from 'react';
import { api, imageUrl } from '../api/client';
import { deserialize, serialize } from './boxes';
import { initialState, reducer } from './reducer';

export interface Img { id: number; filename: string; path: string; is_annotated: boolean; is_null?: boolean; }

/**
 * Owns all annotate-page state (image list, current index, the box reducer,
 * save). Lifted out of the section so the SHELL HEADER can show the same image
 * nav + save the original annotate.html header has.
 *
 * PAGINATION + BATCH FILTER (ported from the original's paginated media list):
 *  - `batchId` restricts the list to one upload batch, so clicking a batch card
 *    opens the annotator on ONLY that batch.
 *  - the list is paged (`perPage`); `nav` walks images and rolls onto the next/
 *    previous page at the edges, so prev/next feels continuous across pages.
 */
export function useAnnotate(wid: number, project: string, batchId: number | null = null) {
  const base = `/workspaces/${wid}/projects/${encodeURIComponent(project)}`;
  const [images, setImages] = useState<Img[]>([]);
  const [idx, setIdx] = useState(0);
  const [img, setImg] = useState<HTMLImageElement | null>(null);
  const [dims, setDims] = useState({ w: 0, h: 0 });
  const [state, dispatch] = useReducer(reducer, initialState);
  const [saved, setSaved] = useState<'idle' | 'saving' | 'saved'>('idle');
  const [autoSave, setAutoSave] = useState(true);

  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState(50);
  const [filter, setFilter] = useState<'all' | 'annotated' | 'unannotated' | 'null'>('all');
  const [total, setTotal] = useState(0);
  const [pages, setPages] = useState(1);
  // When we roll onto the previous page via nav(-1), land on its LAST image.
  const pendingIdx = useRef<'last' | number | null>(null);

  // Reset to the first page whenever the batch filter, media filter or page size changes.
  useEffect(() => { setPage(1); pendingIdx.current = 0; }, [batchId, filter, perPage]);

  const reload = useCallback(() => {
    const q = new URLSearchParams({ page: String(page), per_page: String(perPage) });
    if (batchId != null) q.set('batch_id', String(batchId));
    if (filter !== 'all') q.set('filter', filter);
    api<{ images: Img[]; total: number; pages: number }>(`${base}/images?${q}`)
      .then((r) => {
        setImages(r.images);
        setTotal(r.total);
        setPages(Math.max(1, r.pages));
        const want = pendingIdx.current;
        pendingIdx.current = null;
        setIdx(want === 'last' ? Math.max(0, r.images.length - 1) : (typeof want === 'number' ? want : 0));
      })
      .catch(() => { setImages([]); setTotal(0); setPages(1); setIdx(0); });
  }, [base, page, perPage, batchId, filter]);
  useEffect(() => { reload(); }, [reload]);

  const current = images[idx];

  // ── Auto-save plumbing ──────────────────────────────────────────────────────
  // Live mirrors of the things a deferred/flush save needs to read.
  const boxesRef = useRef(state.boxes);
  useEffect(() => { boxesRef.current = state.boxes; }, [state.boxes]);
  const autoSaveRef = useRef(autoSave);
  useEffect(() => { autoSaveRef.current = autoSave; }, [autoSave]);
  // The image currently on screen (path + natural dims), set on image load. Used
  // to save the OUTGOING image before we load the next one.
  const displayed = useRef<{ path: string; w: number; h: number } | null>(null);

  // Dedupe identical consecutive saves so the debounced save and the flush-on-nav
  // don't both POST the same annotations (that double-write raced os.replace on
  // Windows). Signature = path + serialized boxes; skip if unchanged.
  const lastSaved = useRef<string>('');
  const persist = useCallback((path: string, boxes: typeof state.boxes, w: number, h: number) => {
    if (!path || !w) return Promise.resolve();
    const payload = serialize(boxes, w, h);
    const sig = `${path}|${JSON.stringify(payload)}`;
    if (sig === lastSaved.current) return Promise.resolve();
    lastSaved.current = sig;
    return api(`${base}/annotations`, { body: { path, bboxes: payload } })
      .catch(() => { lastSaved.current = ''; });   // allow retry on failure
  }, [base]);

  // Load the current image; FIRST flush the previous image's annotations so
  // navigating away never loses work (this is what "Auto" means).
  useEffect(() => {
    const out = displayed.current;
    if (out && autoSaveRef.current) persist(out.path, boxesRef.current, out.w, out.h);
    displayed.current = null;
    if (!current) { setImg(null); return; }
    const el = new Image();
    el.onload = () => {
      setImg(el); setDims({ w: el.width, h: el.height });
      displayed.current = { path: current.path, w: el.width, h: el.height };
    };
    el.onerror = () => { setImg(null); setDims({ w: 1, h: 1 }); };
    el.src = imageUrl(base, current.path);
    api<{ bboxes: any[]; suggestions: any[] }>(`${base}/annotations?path=${encodeURIComponent(current.path)}`)
      .then((r) => { const W = el.width || 1, H = el.height || 1; dispatch({ t: 'SET_BOXES', boxes: [...r.bboxes, ...r.suggestions].map((b) => deserialize(b, W, H)) }); })
      .catch(() => dispatch({ t: 'SET_BOXES', boxes: [] }));
    // Keyed on the image PATH, not the `current` OBJECT. Auto-save updates
    // is_annotated via setImages, which makes a new `current` object with the
    // SAME path — if we depended on the object this effect would re-run, re-fetch
    // annotations and SET_BOXES, wiping a just-drawn box. Path is stable per image.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current?.path, base, persist]);

  // Debounced auto-save while you stay on an image (covers the LAST image, where
  // there's no navigation to flush on). Idempotent, so re-saving loaded boxes is
  // harmless. Also keeps the sidebar "annotated" dot in sync.
  useEffect(() => {
    if (!autoSave || !current || !dims.w) return;
    // Don't persist while the class popup is open (a box was just drawn but its
    // class isn't confirmed yet) — matches the original's "pending box" behaviour,
    // so a box never saves as the default class 0 before you pick.
    if (state.justDrawn) return;
    const id = setTimeout(() => {
      persist(current.path, state.boxes, dims.w, dims.h);
      setImages((list) => list.map((im, i) => i === idx ? { ...im, is_annotated: state.boxes.some((b) => b.state === 'confirmed') } : im));
    }, 1000);
    return () => clearTimeout(id);
  }, [state.boxes, state.justDrawn, autoSave, current, dims, idx, persist]);

  // Flush on unmount (leaving the annotate page) too.
  useEffect(() => () => {
    const out = displayed.current;
    if (out && autoSaveRef.current) persist(out.path, boxesRef.current, out.w, out.h);
  }, [persist]);

  const save = useCallback(async () => {
    if (!current || !dims.w) return;
    setSaved('saving');
    try {
      const payload = serialize(state.boxes, dims.w, dims.h);
      await api(`${base}/annotations`, { body: { path: current.path, bboxes: payload } });
      lastSaved.current = `${current.path}|${JSON.stringify(payload)}`;   // keep dedupe in sync
      setSaved('saved'); setTimeout(() => setSaved('idle'), 1500);
      setImages((list) => list.map((im, i) => i === idx ? { ...im, is_annotated: state.boxes.some((b) => b.state === 'confirmed') } : im));
    } catch { setSaved('idle'); }
  }, [current, base, state.boxes, dims, idx]);

  const markNull = useCallback(async () => {
    if (!current) return;
    await api(`${base}/null`, { body: { path: current.path } }).catch(() => {});
    dispatch({ t: 'SET_BOXES', boxes: [] });
  }, [current, base]);

  const go = useCallback((i: number) => setIdx(Math.max(0, Math.min(images.length - 1, i))), [images.length]);

  // Walk images; at a page edge, roll onto the adjacent page (landing on its
  // first/last image) so prev/next is continuous across the whole batch.
  const nav = useCallback((d: number) => {
    setIdx((c) => {
      const next = c + d;
      if (next >= 0 && next < images.length) return next;
      if (d > 0 && page < pages) { pendingIdx.current = 0; setPage((p) => p + 1); return c; }
      if (d < 0 && page > 1) { pendingIdx.current = 'last'; setPage((p) => p - 1); return c; }
      return c;
    });
  }, [images.length, page, pages]);

  const globalIndex = total ? (page - 1) * perPage + idx : 0;

  return {
    base, images, idx, current, img, dims, state, dispatch, saved, autoSave, setAutoSave,
    save, markNull, go, nav, reload,
    page, pages, perPage, total, globalIndex, setPage, setPerPage,
    filter, setFilter,
  };
}

export type AnnotateApi = ReturnType<typeof useAnnotate>;
