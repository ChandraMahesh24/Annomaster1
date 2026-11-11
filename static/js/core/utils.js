/**
 * utils.js — small shared helpers
 */

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function roleBadge(role) {
  return `<span class="badge badge-${role}">${role}</span>`;
}

function formatDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });
}

function showModal(id)  { const el = document.getElementById(id); if (el) el.style.display = 'flex'; }
function hideModal(id)  { const el = document.getElementById(id); if (el) el.style.display = 'none'; }
function setError(id, msg)   { const el = document.getElementById(id); if (el) el.textContent = msg || ''; }
function setSuccess(id, msg) { const el = document.getElementById(id); if (el) el.textContent = msg || ''; }

// Close modal on overlay click
document.addEventListener('click', e => {
  if (e.target.classList.contains('modal-overlay')) {
    e.target.style.display = 'none';
  }
});


/* ═══════════════════════════════════════════════════════════════════════════
   KebabMenu — the shared ⋮ card-actions menu
   ───────────────────────────────────────────────────────────────────────────
   One implementation for the dashboard project cards and the upload page's
   Active Work / Completed Datasets cards. Styled by .kmenu* in base.css.

   Usage:
     KebabMenu.attach(buttonEl, () => [
       { icon: 'fa-pen', label: 'Rename…', onClick: () => … },
       'sep',
       { icon: 'fa-trash-alt', label: 'Delete', danger: true, onClick: … },
     ]);

   The items are built on each open, so they can reflect current state.
   Falsy entries are skipped, which makes conditional items a plain `&&`.

   Two behaviours here are load-bearing, both learned the hard way:
   • The menu is appended to <body>, NOT to the card. Every card using this
     has a `transform` on :hover, and a transformed element is the containing
     block for `position:fixed` descendants — inside the card, viewport
     coordinates resolve against the card and the menu lands off-screen.
     Cards with `overflow:hidden` would clip it as well.
   • Placement is clamped to the viewport on all four edges, so the menu is
     never cut off by the window, however low or far right the card sits.
═══════════════════════════════════════════════════════════════════════════ */
const KebabMenu = (() => {
  const GAP = 6, EDGE = 8;
  let _open = null;            // { menu, btn }

  function closeAll() {
    if (!_open) return;
    _open.menu.remove();
    _open.btn.setAttribute('aria-expanded', 'false');
    _open.btn.closest('.kmenu-host')?.classList.remove('kmenu-open');
    _open = null;
    document.removeEventListener('mousedown', _onOutside, true);
    window.removeEventListener('scroll', closeAll, true);
    window.removeEventListener('resize', closeAll);
  }

  function _onOutside(e) {
    if (!e.target.closest('.kmenu') && !e.target.closest('.kmenu-btn')) closeAll();
  }

  function _place(btn, menu) {
    const b  = btn.getBoundingClientRect();
    const m  = menu.getBoundingClientRect();
    const vw = document.documentElement.clientWidth;
    const vh = document.documentElement.clientHeight;

    const below = vh - b.bottom - GAP - EDGE;
    const above = b.top - GAP - EDGE;
    const up    = m.height > below && above > below;

    let top  = up ? b.top - GAP - m.height : b.bottom + GAP;
    let left = b.right - m.width;                       // right-aligned
    top  = Math.max(EDGE, Math.min(top,  vh - m.height - EDGE));
    left = Math.max(EDGE, Math.min(left, vw - m.width  - EDGE));

    menu.style.top  = `${Math.round(top)}px`;
    menu.style.left = `${Math.round(left)}px`;
  }

  function open(btn, items) {
    closeAll();
    const menu = document.createElement('div');
    menu.className = 'kmenu';
    menu.setAttribute('role', 'menu');

    (items || []).filter(Boolean).forEach(it => {
      if (it === 'sep') {
        // Never start with, end with, or double up a separator.
        if (menu.lastElementChild && !menu.lastElementChild.classList.contains('kmenu-sep')) {
          menu.appendChild(Object.assign(document.createElement('div'),
                                         { className: 'kmenu-sep' }));
        }
        return;
      }
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'kmenu-item' + (it.danger ? ' danger' : '');
      b.setAttribute('role', 'menuitem');
      if (it.disabled) b.disabled = true;
      if (it.title) b.title = it.title;
      // Built as nodes rather than an HTML string: the label goes in via
      // textContent, so a project or batch name containing < or " can never
      // break the markup or inject anything.
      const ico  = document.createElement('i');
      ico.className = 'fas ' + (it.icon || 'fa-circle');
      const span = document.createElement('span');
      span.textContent = it.label;
      b.appendChild(ico);
      b.appendChild(span);
      b.addEventListener('click', ev => {
        ev.stopPropagation();
        closeAll();
        it.onClick?.(ev);
      });
      menu.appendChild(b);
    });
    while (menu.lastElementChild?.classList.contains('kmenu-sep')) {
      menu.lastElementChild.remove();
    }
    if (!menu.children.length) return;

    document.body.appendChild(menu);
    btn.setAttribute('aria-expanded', 'true');
    btn.closest('.kmenu-host')?.classList.add('kmenu-open');
    _open = { menu, btn };
    _place(btn, menu);

    // Deferred, or the click that opened the menu would immediately close it.
    setTimeout(() => {
      document.addEventListener('mousedown', _onOutside, true);
      window.addEventListener('scroll', closeAll, true);
      window.addEventListener('resize', closeAll);
    }, 0);
  }

  /** Wire a ⋮ button. `buildItems` runs on every open, so items stay current. */
  function attach(btn, buildItems) {
    if (!btn) return;
    btn.setAttribute('aria-haspopup', 'true');
    btn.setAttribute('aria-expanded', 'false');
    btn.addEventListener('click', e => {
      e.preventDefault();
      e.stopPropagation();          // don't trigger the card's own click
      if (_open && _open.btn === btn) { closeAll(); return; }
      open(btn, buildItems());
    });
  }

  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeAll(); });

  return { attach, open, closeAll };
})();
