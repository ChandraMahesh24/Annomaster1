/**
 * Canvas interaction state machine.
 *
 * The original's canvas bugs came from scattered boolean flags (drawing,
 * dragging, resizing, selectedId…) that leaked across modes. This reducer makes
 * the machine explicit and total:
 *
 *     idle ──START_DRAW──▶ drawing ──COMMIT_DRAW──▶ idle   (never 'selected')
 *     idle ──SELECT─────▶ selected
 *     selected ──START_MOVE / START_RESIZE──▶ moving / resizing ──COMMIT──▶ selected
 *     * ──CANCEL(Esc)──▶ idle, dropping any in-progress draft
 *
 * Two ported invariants encoded here, not left to call sites:
 *   • A freshly drawn box commits straight to `idle` — it must NEVER
 *     auto-transition to `selected` (that made nested drawing impossible).
 *   • Editing a suggestion (move/resize/reclass) promotes it to `confirmed`
 *     via Boxes.accept — editing is acceptance.
 */
import {
  accept, hitTest, isSuggested, newId, reconcile, reconcileAutoSave,
  type Box, type Detection,
} from './boxes';

const isSug = isSuggested;

export type Mode = 'draw' | 'select';
export type Phase = 'idle' | 'drawing' | 'moving' | 'resizing';
export type Handle = 'nw' | 'ne' | 'sw' | 'se' | 'n' | 's' | 'e' | 'w';

export interface CanvasState {
  boxes: Box[];
  mode: Mode;
  phase: Phase;
  selectedId: string | null;
  currentCls: number;
  draft: Box | null;          // box being drawn
  handle: Handle | null;      // active resize handle
  origin: { x: number; y: number } | null;  // drag start (image coords)
  moved: boolean;             // did the pointer actually move during a drag?
  justDrawn: string | null;   // id of a box just drawn → open the class popup for it
}

export const initialState: CanvasState = {
  boxes: [], mode: 'draw', phase: 'idle', selectedId: null,
  currentCls: 0, draft: null, handle: null, origin: null, moved: false,
  justDrawn: null,
};

export type Action =
  | { t: 'SET_BOXES'; boxes: Box[] }
  | { t: 'SET_MODE'; mode: Mode }
  | { t: 'SET_CLASS'; cls: number }
  | { t: 'POINTER_DOWN'; x: number; y: number; handle?: Handle | null }
  | { t: 'POINTER_MOVE'; x: number; y: number }
  | { t: 'POINTER_UP'; x: number; y: number }
  | { t: 'CANCEL' }
  | { t: 'DELETE_SELECTED' }
  | { t: 'RECLASS_SELECTED'; cls: number }
  | { t: 'ACCEPT'; id: string }
  | { t: 'REJECT'; id: string }
  | { t: 'APPLY_DETECTIONS'; detections: Detection[]; autoSave: boolean; iou: number }
  | { t: 'ACCEPT_ALL' }
  | { t: 'REJECT_ALL' }
  // Draw → class popup flow (matches the original: a fresh box opens a popup to
  // assign its class; the box is NOT selected, per the edit-to-accept fix).
  | { t: 'ASSIGN_CLASS'; id: string; cls: number }   // set class of a box, close popup
  | { t: 'DISCARD_DRAWN' }                             // cancel popup → remove the box
  | { t: 'CLEAR_JUST_DRAWN' }                          // keep box with current class
  | { t: 'SELECT'; id: string }                        // select a box (from the list)
  | { t: 'SET_BOX'; id: string; patch: Partial<Box> }; // properties-panel edits

const MIN = 4; // px — ignore accidental micro-drags

export function reducer(s: CanvasState, a: Action): CanvasState {
  switch (a.t) {
    case 'SET_BOXES':
      return { ...s, boxes: a.boxes, selectedId: null, phase: 'idle', draft: null };
    case 'SET_MODE':
      // switching tools always returns to a clean idle
      return { ...s, mode: a.mode, phase: 'idle', draft: null, selectedId: a.mode === 'draw' ? null : s.selectedId };
    case 'SET_CLASS':
      return { ...s, currentCls: a.cls };

    case 'POINTER_DOWN': {
      if (s.mode === 'draw') {
        // A resize handle of the just-drawn/selected box stays active in draw
        // mode; everything else starts a NEW box (even inside an existing one).
        if (a.handle && s.selectedId) {
          return { ...s, phase: 'resizing', handle: a.handle, origin: { x: a.x, y: a.y }, moved: false };
        }
        const draft: Box = { id: newId(), cls: s.currentCls, x: a.x, y: a.y, w: 0, h: 0, state: 'confirmed', type: 'bbox' };
        return { ...s, phase: 'drawing', draft, selectedId: null, origin: { x: a.x, y: a.y }, moved: false };
      }
      // select mode
      if (a.handle && s.selectedId) {
        return { ...s, phase: 'resizing', handle: a.handle, origin: { x: a.x, y: a.y }, moved: false };
      }
      // No afterId → matches the original _hitBox exactly (always the smallest
      // under the cursor, last-drawn on a tie). The original has no click-cycle.
      const hit = hitTest(s.boxes, a.x, a.y);
      if (hit) {
        return { ...s, selectedId: hit.id, phase: 'moving', origin: { x: a.x, y: a.y }, moved: false };
      }
      return { ...s, selectedId: null, phase: 'idle' };
    }

    case 'POINTER_MOVE': {
      if (s.phase === 'drawing' && s.draft && s.origin) {
        const x = Math.min(s.origin.x, a.x), y = Math.min(s.origin.y, a.y);
        const w = Math.abs(a.x - s.origin.x), h = Math.abs(a.y - s.origin.y);
        return { ...s, draft: { ...s.draft, x, y, w, h }, moved: true };
      }
      if (s.phase === 'moving' && s.origin && s.selectedId) {
        const dx = a.x - s.origin.x, dy = a.y - s.origin.y;
        const boxes = s.boxes.map((b) => b.id === s.selectedId ? { ...b, x: b.x + dx, y: b.y + dy } : b);
        return { ...s, boxes, origin: { x: a.x, y: a.y }, moved: true };
      }
      if (s.phase === 'resizing' && s.handle && s.selectedId) {
        const boxes = s.boxes.map((b) => b.id === s.selectedId ? applyResize(b, s.handle!, a.x, a.y) : b);
        return { ...s, boxes, moved: true };
      }
      return s;
    }

    case 'POINTER_UP': {
      if (s.phase === 'drawing' && s.draft) {
        // Commit only if big enough. Commit → IDLE, never selected. `justDrawn`
        // opens the class popup for this box (as the original does), WITHOUT
        // selecting it (no edit handles) — the edit-to-accept fix stays intact.
        if (s.draft.w >= MIN && s.draft.h >= MIN) {
          return { ...s, boxes: [...s.boxes, s.draft], draft: null, phase: 'idle', selectedId: null, justDrawn: s.draft.id };
        }
        return { ...s, draft: null, phase: 'idle' };
      }
      if ((s.phase === 'moving' || s.phase === 'resizing') && s.selectedId) {
        // Editing geometry is acceptance: promote a suggestion if it moved.
        let boxes = s.boxes;
        if (s.moved) {
          boxes = s.boxes.map((b) => {
            if (b.id !== s.selectedId) return b;
            const c = { ...b }; accept(c); return c;
          });
        }
        // Back to idle-with-selection (our "selected" state = phase idle + selectedId set).
        return { ...s, boxes, phase: 'idle', handle: null, origin: null };
      }
      return { ...s, phase: 'idle', handle: null, origin: null };
    }

    case 'CANCEL':
      // Escape: drop any in-progress draft/drag WITHOUT committing.
      return { ...s, phase: 'idle', draft: null, handle: null, origin: null };

    case 'DELETE_SELECTED':
      if (!s.selectedId) return s;
      return { ...s, boxes: s.boxes.filter((b) => b.id !== s.selectedId), selectedId: null, phase: 'idle' };

    case 'RECLASS_SELECTED': {
      if (!s.selectedId) return s;
      // Reclassing a suggestion is review → accept it too.
      const boxes = s.boxes.map((b) => {
        if (b.id !== s.selectedId) return b;
        const c = { ...b, cls: a.cls }; accept(c); return c;
      });
      return { ...s, boxes };
    }

    case 'ACCEPT': {
      const boxes = s.boxes.map((b) => { if (b.id !== a.id) return b; const c = { ...b }; accept(c); return c; });
      return { ...s, boxes };
    }
    case 'REJECT': {
      // Rejected boxes are soft-kept (never rendered), so a re-run won't re-suggest.
      const boxes = s.boxes.map((b) => b.id === a.id ? { ...b, state: 'rejected' as const } : b);
      return { ...s, boxes, selectedId: s.selectedId === a.id ? null : s.selectedId };
    }

    case 'APPLY_DETECTIONS': {
      // Reconcile detections against SAVED state (the live boxes), never a
      // session flag — so a re-run/revisit never duplicates. Which reconciler
      // runs is the ONLY thing the mode changes.
      const { boxes } = a.autoSave
        ? reconcileAutoSave(s.boxes, a.detections, a.iou)
        : reconcile(s.boxes, a.detections, a.iou);
      return { ...s, boxes: boxes.slice() };
    }

    case 'ACCEPT_ALL': {
      const boxes = s.boxes.map((b) => { if (!isSug(b)) return b; const c = { ...b }; accept(c); return c; });
      return { ...s, boxes };
    }
    case 'REJECT_ALL': {
      const boxes = s.boxes.map((b) => isSug(b) ? { ...b, state: 'rejected' as const } : b);
      return { ...s, boxes };
    }

    case 'ASSIGN_CLASS': {
      // Popup confirmed a class for a box. Assigning a class IS review, so a
      // suggestion is also accepted here (same rule as RECLASS_SELECTED).
      const boxes = s.boxes.map((b) => {
        if (b.id !== a.id) return b;
        const c = { ...b, cls: a.cls }; accept(c); return c;
      });
      return { ...s, boxes, justDrawn: null, currentCls: a.cls };
    }
    case 'DISCARD_DRAWN':
      return { ...s, boxes: s.boxes.filter((b) => b.id !== s.justDrawn), justDrawn: null };
    case 'CLEAR_JUST_DRAWN':
      return { ...s, justDrawn: null };

    case 'SELECT':
      return { ...s, selectedId: a.id, mode: 'select', phase: 'idle' };
    case 'SET_BOX': {
      const boxes = s.boxes.map((b) => {
        if (b.id !== a.id) return b;
        const c = { ...b, ...a.patch }; accept(c); return c;
      });
      return { ...s, boxes };
    }

    default:
      return s;
  }
}

export function applyResize(b: Box, h: Handle, px: number, py: number): Box {
  let { x, y, w, hgt } = { x: b.x, y: b.y, w: b.w, hgt: b.h };
  const r = x + w, btm = y + hgt;
  if (h.includes('w')) { x = Math.min(px, r - MIN); w = r - x; }
  if (h.includes('e')) { w = Math.max(MIN, px - x); }
  if (h.includes('n')) { y = Math.min(py, btm - MIN); hgt = btm - y; }
  if (h.includes('s')) { hgt = Math.max(MIN, py - y); }
  return { ...b, x, y, w, h: hgt };
}
