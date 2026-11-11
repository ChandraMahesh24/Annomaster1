"""Annotation read/write — updates SQLite index on every save.

Additions over baseline:
  • Soft lock check: if another user holds an active AnnotationLock for the
    same image, the POST is rejected with HTTP 409 so their work is not silently
    overwritten.
  • Audit log: every successful annotation save is written to the audit_log
    table (user_id, workspace, project, image_path, bbox_count, timestamp).
"""
from datetime import datetime
from flask import Blueprint, request, jsonify, g
from app.utils.security import login_required, workspace_role_required
from app.core.yolo import parse_yolo_label, write_yolo_label, is_valid_annotation_file
from app.core.suggestions import (
    read_suggestions, write_suggestions, delete_suggestions,
)
from app.core.paths import project_dir, label_path_for_image
from app.models.workspace import Workspace

annotations_bp = Blueprint('annotations', __name__)


def _wsf(wid):
    return Workspace.query.get_or_404(int(wid)).folder_name


@annotations_bp.route(
    '/api/workspaces/<int:workspace_id>/projects/<project>/annotations',
    methods=['GET', 'POST'])
@login_required
@workspace_role_required('owner', 'editor', 'viewer')
def api_annotations(workspace_id, project):
    wsf = _wsf(workspace_id)
    pd  = project_dir(wsf, project)

    # ── GET: return current annotations ──────────────────────────────────────
    if request.method == 'GET':
        rel     = request.args.get('path', '')
        lbl     = label_path_for_image(pd / rel, create_dir=False)
        _lbl_txt = lbl.read_text(encoding='utf-8', errors='ignore').strip() if lbl.exists() else None
        is_null  = _lbl_txt is not None and (_lbl_txt == '' or _lbl_txt == '__null__')

        # Include lock info so the client knows whether this image is locked
        lock_info = _get_lock(workspace_id, project, rel)

        # Everything in the .txt is, by definition, human-confirmed ground
        # truth. Tag it explicitly so the client never has to infer state.
        confirmed = parse_yolo_label(lbl)
        for b in confirmed:
            b['state'] = 'confirmed'

        return jsonify({
            'bboxes':  confirmed,
            # Unreviewed model output + boxes the user explicitly rejected.
            # Rejected boxes are returned so the client can suppress
            # re-suggesting them, even though it never renders them.
            'suggestions': read_suggestions(lbl),
            'is_null': is_null,
            'lock':    lock_info,
        })

    # ── POST: save annotations ────────────────────────────────────────────────
    if g.member_role not in ('owner', 'editor'):
        return jsonify({'error': 'Viewers cannot edit annotations'}), 403

    data  = request.json or {}
    rel   = data.get('path', '')
    boxes = data.get('bboxes', [])

    # Soft-lock enforcement ─────────────────────────────────────────────────
    conflict = _check_lock_conflict(workspace_id, project, rel)
    if conflict:
        return jsonify(conflict), 409

    # ── Split by review state ────────────────────────────────────────────────
    # The label file holds CONFIRMED boxes only. This is the single guarantee
    # that unreviewed model predictions can never reach an export, a dataset
    # build, or a training run — every one of those reads the .txt.
    #
    # Boxes with no `state` are treated as confirmed: that covers every
    # annotation written before this feature existed, plus any older client
    # still posting the previous payload shape.
    confirmed, pending = [], []
    for b in boxes:
        st = (b.get('state') or 'confirmed') if isinstance(b, dict) else 'confirmed'
        if st == 'confirmed':
            confirmed.append(b)
        elif st in ('suggested', 'rejected'):
            pending.append(b)
        # anything else is malformed → dropped

    # A client that doesn't know about suggestions omits the key entirely;
    # in that case leave the existing sidecar untouched rather than wiping it.
    suggestions_sent = 'suggestions' in data or any(
        isinstance(b, dict) and b.get('state') for b in boxes
    )
    pending.extend(
        b for b in (data.get('suggestions') or [])
        if isinstance(b, dict) and b.get('state') in ('suggested', 'rejected')
    )

    # Write label file (atomic) — confirmed only ────────────────────────────
    lbl = label_path_for_image(pd / rel, create_dir=True)
    write_yolo_label(lbl, confirmed)

    if suggestions_sent:
        write_suggestions(lbl, pending)

    # Keep `boxes` meaning "what landed in the label file" for the audit log
    # and index update below, so is_annotated tracks confirmed work only.
    boxes = confirmed

    # Update fast SQLite index ──────────────────────────────────────────────
    is_annotated = is_valid_annotation_file(lbl)
    try:
        from app.core.db_index import set_annotated
        set_annotated(pd, rel, is_annotated=is_annotated, is_null=False)
    except Exception:
        pass  # index is best-effort; .txt file is the source of truth

    # Audit log ─────────────────────────────────────────────────────────────
    try:
        from app.models.audit_log import log_action
        log_action(
            'annotation.save',
            user_id=g.current_user.id,
            workspace_id=workspace_id,
            project=project,
            image_path=rel,
            detail={'bbox_count': len(boxes)},
            ip=request.remote_addr,
        )
    except Exception:
        pass

    # Update images tracking table ──────────────────────────────────────────
    # Pass the SAME computed `is_annotated` the media index just got, instead
    # of an unconditional True. Saving an image with every box deleted leaves
    # an empty/invalid label file → is_annotated is False; the old code still
    # flipped the central table to True, so the two DB mirrors permanently
    # disagreed for any cleared image.
    try:
        from app import db
        from app.models.image import Image as ImageModel
        img_row = ImageModel.query.filter_by(
            workspace_id=workspace_id, project=project, rel_path=rel,
        ).first()
        if img_row:
            img_row.is_annotated = is_annotated
            img_row.is_null      = False
            if is_annotated:
                img_row.annotated_by = g.current_user.id
                img_row.annotated_at = datetime.utcnow()
            db.session.commit()
    except Exception:
        pass

    return jsonify({'success': True})


@annotations_bp.route(
    '/api/workspaces/<int:workspace_id>/projects/<project>/null',
    methods=['POST', 'DELETE'])
@login_required
@workspace_role_required('owner', 'editor')
def api_null(workspace_id, project):
    data = request.json or {}
    wsf  = _wsf(workspace_id)
    pd   = project_dir(wsf, project)
    rel  = data.get('path', '')
    lbl  = label_path_for_image(pd / rel, create_dir=True)

    if request.method == 'POST':
        lbl.parent.mkdir(parents=True, exist_ok=True)
        lbl.write_text('', encoding='utf-8')  # empty = YOLO background image

        # Marking an image "nothing to annotate" resolves any outstanding
        # suggestions on it — leaving them would show a review banner on a
        # frame the user has already declared empty.
        # `rejected` entries are KEPT: they are the record of what the user
        # turned down, and dropping them would let a later re-run suggest
        # the very same boxes again.
        try:
            kept = [b for b in read_suggestions(lbl) if b.get('state') == 'rejected']
            write_suggestions(lbl, kept)
        except Exception:
            pass

        try:
            from app.core.db_index import set_annotated
            set_annotated(pd, rel, is_annotated=False, is_null=True)
        except Exception:
            pass
        try:
            from app.models.audit_log import log_action
            log_action('annotation.null', user_id=g.current_user.id,
                       workspace_id=workspace_id, project=project, image_path=rel,
                       ip=request.remote_addr)
        except Exception:
            pass
        # Update images tracking table
        try:
            from app import db
            from app.models.image import Image as ImageModel
            img_row = ImageModel.query.filter_by(
                workspace_id=workspace_id, project=project, rel_path=rel,
            ).first()
            if img_row:
                img_row.mark_annotated(g.current_user.id, is_null=True)
                db.session.commit()
        except Exception:
            pass
    else:
        _txt = lbl.read_text(encoding='utf-8', errors='ignore').strip() if lbl.exists() else None
        if _txt is not None and (_txt == '' or _txt == '__null__'):
            lbl.unlink()
        try:
            from app.core.db_index import set_annotated
            set_annotated(pd, rel, is_annotated=False, is_null=False)
        except Exception:
            pass
        # Update images tracking table
        try:
            from app import db
            from app.models.image import Image as ImageModel
            img_row = ImageModel.query.filter_by(
                workspace_id=workspace_id, project=project, rel_path=rel,
            ).first()
            if img_row:
                img_row.is_annotated = False
                img_row.is_null      = False
                img_row.annotated_by = None
                img_row.annotated_at = None
                db.session.commit()
        except Exception:
            pass

    return jsonify({'success': True})


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_lock(workspace_id: int, project: str, image_path: str):
    """Return lock dict if image is actively locked by any user, else None."""
    try:
        from app.models.annotation_lock import AnnotationLock
        lock = AnnotationLock.query.filter_by(
            workspace_id=workspace_id,
            project=project,
            image_path=image_path,
        ).first()
        if lock and not lock.is_expired():
            return lock.to_dict()
    except Exception:
        pass
    return None


def _check_lock_conflict(workspace_id: int, project: str, image_path: str):
    """
    Return an error dict if the image is locked by a different user.
    Return None if the current user holds the lock (or no lock exists).
    """
    try:
        from app.models.annotation_lock import AnnotationLock
        lock = AnnotationLock.query.filter_by(
            workspace_id=workspace_id,
            project=project,
            image_path=image_path,
        ).first()
        if lock and not lock.is_expired() and lock.locked_by != g.current_user.id:
            return {
                'error':     f'Image is currently being edited by @{lock.locker.username}',
                'locked_by': lock.locker.username,
                'lock':      lock.to_dict(),
            }
    except Exception:
        pass
    return None
