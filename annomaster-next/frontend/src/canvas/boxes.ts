/**
 * Box lifecycle logic — a faithful TypeScript port of the `Boxes` module in the
 * original static/js/main.js. Same guarantees, now typed and pure so it can be
 * unit-tested in isolation (see boxes.test.ts).
 *
 * THE CORE INVARIANT: a model prediction is a SUGGESTION, never an annotation,
 * until a human accepts it. Every box carries an explicit `state`.
 */
export type BoxStateT = 'suggested' | 'confirmed' | 'rejected';

export interface Box {
  id: string;
  cls: number;
  x: number; y: number; w: number; h: number; // image-pixel coords
  state: BoxStateT;
  conf?: number;                                // only on suggested / former-suggested
  type?: 'bbox' | 'polygon';
  points?: { x: number; y: number }[];
}

export const IOU_THRESHOLD = 0.5;

let _seq = 0;
export function newId(): string {
  return `b${Date.now().toString(36)}${(_seq++).toString(36)}`;
}

export const isSuggested = (b: Box) => b.state === 'suggested';
export const isConfirmed = (b: Box) => !b.state || b.state === 'confirmed';
export const isRejected = (b: Box) => b.state === 'rejected';

export const suggested = (list: Box[]) => list.filter(isSuggested);
export const confirmed = (list: Box[]) => list.filter(isConfirmed);

export function area(b: Box): number {
  return Math.max(0, b.w) * Math.max(0, b.h);
}

export function iou(a: Box, b: Box): number {
  const x1 = Math.max(a.x, b.x);
  const y1 = Math.max(a.y, b.y);
  const x2 = Math.min(a.x + a.w, b.x + b.w);
  const y2 = Math.min(a.y + a.h, b.y + b.h);
  const inter = Math.max(0, x2 - x1) * Math.max(0, y2 - y1);
  if (inter <= 0) return 0;
  const uni = area(a) + area(b) - inter;
  return uni > 0 ? inter / uni : 0;
}

function contains(b: Box, px: number, py: number): boolean {
  return px >= b.x && px <= b.x + b.w && py >= b.y && py <= b.y + b.h;
}

/**
 * SMALLEST-AREA-WINS hit-testing — a line-for-line port of main.js `_hitBox`.
 * Among boxes under the cursor the smallest is picked so a nested box is
 * reachable. Rejected boxes are never hit.
 *
 * TIE-BREAK matches the original exactly: iterate the list in REVERSE
 * (last-drawn first) and replace only on strict `area < bestArea`, so on an
 * exact-area tie the LAST-DRAWN box wins (preserves the original's
 * topmost-wins-for-duplicates behaviour). The earlier version sorted ascending
 * and returned the FIRST-drawn on a tie — the opposite of the original.
 *
 * `afterId` (click-cycling) is an OPT-IN extension the original does not have;
 * it is only used when a caller explicitly passes it. The reducer's select
 * flow does NOT pass it, so default behaviour equals the original.
 */
export function hitTest(list: Box[], px: number, py: number, afterId?: string | null): Box | null {
  if (afterId) {
    const hits = list
      .filter((b) => !isRejected(b) && contains(b, px, py))
      .sort((a, b) => area(a) - area(b));
    if (!hits.length) return null;
    const i = hits.findIndex((b) => b.id === afterId);
    if (i >= 0) return hits[(i + 1) % hits.length];
    return hits[0];
  }
  let best: Box | null = null;
  let bestArea = Infinity;
  for (let i = list.length - 1; i >= 0; i--) {   // reverse: last-drawn first
    const b = list[i];
    if (isRejected(b)) continue;
    if (!contains(b, px, py)) continue;
    const a = Math.max(1, b.w * b.h);
    if (a < bestArea) { best = b; bestArea = a; } // strict < → tie keeps last-drawn
  }
  return best;
}

/** Editing a suggestion IS acceptance. Returns true if the state changed. */
export function accept(b: Box): boolean {
  if (b.state === 'confirmed') return false;
  b.state = 'confirmed';
  delete b.conf; // confirmed boxes never carry a score
  return true;
}

export function reject(b: Box): boolean {
  if (b.state === 'rejected') return false;
  b.state = 'rejected';
  return true;
}

export interface Detection {
  cls: number; x: number; y: number; w: number; h: number; conf?: number;
  type?: 'bbox' | 'polygon';
}

export interface ReconcileSummary {
  added: number; refreshed?: number; replaced?: number;
  skippedConfirmed?: number; skippedRejected?: number;
}

/**
 * REVIEW mode reconciliation (ported). Detections arrive as suggestions.
 *   overlaps confirmed → DISCARD (never touch human work)
 *   overlaps suggested → refresh coords/confidence
 *   overlaps rejected  → skip (don't re-suggest what was turned down)
 *   no overlap         → add as suggested
 */
export function reconcile(existing: Box[], detections: Detection[], iouThr = IOU_THRESHOLD)
  : { boxes: Box[]; summary: ReconcileSummary } {
  const out = existing.slice();
  const s: ReconcileSummary = { added: 0, refreshed: 0, skippedConfirmed: 0, skippedRejected: 0 };
  for (const det of detections) {
    const sameClass = out.filter((b) => b.cls === det.cls);
    if (sameClass.some((b) => isConfirmed(b) && iou(b, det as Box) >= iouThr)) { s.skippedConfirmed!++; continue; }
    if (sameClass.some((b) => isRejected(b) && iou(b, det as Box) >= iouThr)) { s.skippedRejected!++; continue; }
    const sug = sameClass.find((b) => isSuggested(b) && iou(b, det as Box) >= iouThr);
    if (sug) {
      sug.x = det.x; sug.y = det.y; sug.w = det.w; sug.h = det.h; sug.conf = det.conf;
      s.refreshed!++;
      continue;
    }
    out.push({ id: newId(), cls: det.cls, x: det.x, y: det.y, w: det.w, h: det.h,
               state: 'suggested', conf: det.conf, type: det.type ?? 'bbox' });
    s.added++;
  }
  return { boxes: out, summary: s };
}

/**
 * AUTO-SAVE reconciliation (ported). No suggestion stage — writes to confirmed.
 *   overlaps confirmed → REPLACE coordinates in place (user opted in)
 *   overlaps rejected  → skip
 *   no overlap         → add as confirmed
 */
export function reconcileAutoSave(existing: Box[], detections: Detection[], iouThr = IOU_THRESHOLD)
  : { boxes: Box[]; summary: ReconcileSummary } {
  const out = existing.slice();
  const s: ReconcileSummary = { added: 0, replaced: 0, skippedRejected: 0 };
  for (const det of detections) {
    const sameClass = out.filter((b) => b.cls === det.cls);
    if (sameClass.some((b) => isRejected(b) && iou(b, det as Box) >= iouThr)) { s.skippedRejected!++; continue; }
    const match = sameClass.find((b) => !isRejected(b) && iou(b, det as Box) >= iouThr);
    if (match) {
      match.x = det.x; match.y = det.y; match.w = det.w; match.h = det.h;
      match.state = 'confirmed'; delete match.conf;
      s.replaced!++;
      continue;
    }
    out.push({ id: newId(), cls: det.cls, x: det.x, y: det.y, w: det.w, h: det.h,
               state: 'confirmed', type: det.type ?? 'bbox' });
    s.added++;
  }
  return { boxes: out, summary: s };
}

/** Wire format for the save endpoint: confirmed → .txt, suggested/rejected → sidecar. */
export function serialize(list: Box[], W: number, H: number) {
  return list.map((b) => {
    const base = { class_id: b.cls, state: b.state, type: b.type ?? 'bbox' as const };
    if (b.type === 'polygon' && b.points) {
      return { ...base, points: b.points.map((p) => ({ x: p.x / W, y: p.y / H })) };
    }
    return {
      ...base,
      x_center: (b.x + b.w / 2) / W, y_center: (b.y + b.h / 2) / H,
      width: b.w / W, height: b.h / H,
      ...(b.conf !== undefined ? { conf: b.conf } : {}),
    };
  });
}

/** Parse a box coming back from the API (normalized) into pixel coords. */
export function deserialize(raw: any, W: number, H: number): Box {
  const w = (raw.width ?? 0) * W;
  const h = (raw.height ?? 0) * H;
  return {
    id: newId(),
    cls: raw.class_id ?? raw.cls ?? 0,
    x: (raw.x_center ?? 0) * W - w / 2,
    y: (raw.y_center ?? 0) * H - h / 2,
    w, h,
    state: raw.state ?? 'confirmed',
    conf: raw.conf ?? raw.confidence,
    type: raw.type ?? 'bbox',
  };
}
