"""Button role registry: make every button family of the same ROLE share one
shape, defined by tokens in tokens.css.

python scripts/apply_button_roles.py [--dry-run]

ROLES maps a page class (a "family") to a role. For every CSS rule whose
selector SUBJECT is that family (e.g. `.primary-btn`, `#page-upload
.ubd-browse-btn:hover`; not `.primary-btn i`), the shape declarations are
rewritten to the role's tokens:

  role        radius               size / weight                 height          padding
  action      --btn-radius         --text-button / --fw-button   --btn-min-h     --btn-pad-y --btn-pad-x
  action-sm   --btn-radius         --text-button-sm / --fw-button --btn-min-h-sm --btn-pad-y-sm --btn-pad-x-sm
  icon        --icon-btn-radius    (unchanged)                   --icon-btn-size  (width too)
  icon-sm     --icon-btn-radius    (unchanged)                   --icon-btn-size-sm
  chip        --chip-radius        --text-chip / --fw-chip       --chip-h        0 --chip-pad-x

Colours are NOT touched (variants keep their own token colours). Rules that
mix families of different roles in one selector list, compounds with a size
modifier (.sm/.lg/.xs), and anything scoped inside the approved class picker
(.cls-popup) are skipped and reported. Idempotent.

To add a new button family: add it to ROLES and re-run. To restyle a whole
role on every page: change its tokens in tokens.css.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = ROOT / 'static/css'

ROLES = {
    # primary / secondary / ghost actions, default size
    'btn': 'action', 'primary-btn': 'action', 'ghost-btn': 'action',
    'vs-start-btn': 'action', 'ubd-browse-btn': 'action', 'proj-create-btn': 'action',
    # compact actions: header, toolbars, card actions
    'ah-complete-btn': 'action-sm', 'tb-btn': 'action-sm', 'vs-new-btn': 'action-sm',
    'proj-card-open-btn': 'action-sm', 'ds-sel-toggle': 'action-sm', 'mini-btn': 'action-sm',
    'ct-btn': 'action-sm', 'btn-sm': 'action-sm',
    'vw-foot-btn': 'action',
    # icon-only buttons
    'btn-icon': 'icon', 'dash-icon-btn': 'icon', 'up-icon-btn': 'icon', 'rn-toggle-btn': 'icon',
    'sb-collapse-btn': 'icon-sm', 'section-collapse-btn': 'icon-sm', 'cc-del': 'icon-sm',
    'cc-eye': 'icon-sm', 'proj-card-del-btn': 'icon-sm', 'kmenu-btn': 'icon-sm',
    # chips / filter pills / segmented toggles
    'ds-pill': 'chip', 'ftab': 'chip', 'pill-btn': 'chip', 'view-list': 'chip', 'view-grid': 'chip',
}
# Deliberately NOT in ROLES (specialized controls with their own geometry, all
# still token-driven for colour/font/radius steps): dt-btn / dt-btn-ai (drawing
# toolbar), rn-item (project nav rail), ah-nav-btn & zc-btn (round image-nav
# and zoom pills), rp-tab (panel tabs), settings-nav-btn (vertical nav),
# cp-* (approved class picker), l-* (auth brand surface), avatar-preset,
# ghost-card / project-card (cards, not buttons).

SHAPE = {
    'action':    {'border-radius': 'var(--btn-radius)', 'font-size': 'var(--text-button)',
                  'font-weight': 'var(--fw-button)', 'height': 'var(--btn-min-h)',
                  'min-height': 'var(--btn-min-h)', 'padding': 'var(--btn-pad-y) var(--btn-pad-x)'},
    'action-sm': {'border-radius': 'var(--btn-radius)', 'font-size': 'var(--text-button-sm)',
                  'font-weight': 'var(--fw-button)', 'height': 'var(--btn-min-h-sm)',
                  'min-height': 'var(--btn-min-h-sm)', 'padding': 'var(--btn-pad-y-sm) var(--btn-pad-x-sm)'},
    'icon':      {'border-radius': 'var(--icon-btn-radius)', 'width': 'var(--icon-btn-size)',
                  'height': 'var(--icon-btn-size)', 'min-width': 'var(--icon-btn-size)',
                  'min-height': 'var(--icon-btn-size)'},
    'icon-sm':   {'border-radius': 'var(--icon-btn-radius)', 'width': 'var(--icon-btn-size-sm)',
                  'height': 'var(--icon-btn-size-sm)', 'min-width': 'var(--icon-btn-size-sm)',
                  'min-height': 'var(--icon-btn-size-sm)'},
    'chip':      {'border-radius': 'var(--chip-radius)', 'font-size': 'var(--text-chip)',
                  'font-weight': 'var(--fw-chip)', 'height': 'var(--chip-h)',
                  'min-height': 'var(--chip-h)', 'padding': '0 var(--chip-pad-x)'},
}
# base.css/components.css define .btn and its own sizes already from tokens.
SKIP_FILES = {'tokens.css', 'components.css', 'base.css', 'auth-3d.css', 'modes.css'}
SIZE_MODS = re.compile(r'\.(sm|lg|xs|small|large)\b')
BLOCK = re.compile(r'([^{}]*)\{([^{}]*)\}')
DECL = re.compile(r'(?<![\w-])(border-radius|font-size|font-weight|height|min-height|width|min-width|padding)'
                  r'(\s*:\s*)([^;]+?)(\s*(?:!important)?\s*)(;|$)')
CLASS = re.compile(r'\.([\w-]+)')
COMMENT = re.compile(r'/\*.*?\*/', re.S)


def subject_role(selector):
    """Role of a single selector's subject compound, or None."""
    sel = re.sub(r'::?[\w-]+(\([^)]*\))?', '', selector).strip()
    if not sel or 'cls-popup' in sel or 'clsPopup' in sel:
        return None, 'picker' if sel else None
    last = re.split(r'[\s>+~]+', sel)[-1]
    if SIZE_MODS.search(last):
        return None, 'size-mod'
    roles = {ROLES[c] for c in CLASS.findall(last) if c in ROLES}
    if len(roles) == 1:
        return roles.pop(), None
    return None, ('mixed' if roles else None)


def main():
    dry = '--dry-run' in sys.argv
    changed, skipped, rules_done = {}, [], 0
    for path in sorted(CSS.glob('*.css')):
        if path.name in SKIP_FILES:
            continue
        src = path.read_text(encoding='utf-8')
        count = 0

        def rewrite(m):
            nonlocal count, rules_done
            head, body = m.group(1), m.group(2)
            sel_text = COMMENT.sub('', head).strip()
            if not sel_text or sel_text.startswith('@'):
                return m.group(0)
            selectors = [s.strip() for s in sel_text.split(',') if s.strip()]
            results = [subject_role(s) for s in selectors]
            roles = {r for r, _ in results}
            if roles == {None}:
                return m.group(0)
            if len(roles) != 1:
                skipped.append((path.name, sel_text[:90], 'selector list mixes roles/non-buttons'))
                return m.group(0)
            role = roles.pop()
            shape = SHAPE[role]

            def decl(d):
                nonlocal count
                prop = d.group(1)
                if prop not in shape:
                    return d.group(0)
                new = shape[prop]
                if prop == 'font-weight' and d.group(3).strip() in ('400', 'normal'):
                    return d.group(0)  # a deliberately regular-weight variant
                if d.group(3).strip() == new:
                    return d.group(0)
                count += 1
                return f'{prop}{d.group(2)}{new}{d.group(4)}{d.group(5)}'
            new_body = DECL.sub(decl, body)
            if new_body != body:
                rules_done += 1
            return head + '{' + new_body + '}'
        out = BLOCK.sub(rewrite, src)
        if count:
            changed[path.name] = count
            if not dry:
                path.write_text(out, encoding='utf-8', newline='')
    print(f"{'would rewrite' if dry else 'rewrote'} {sum(changed.values())} declarations in {rules_done} rules: {changed}")
    for row in skipped:
        print('  skipped', *row)


if __name__ == '__main__':
    main()
