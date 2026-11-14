/* ═══════════════════════════════════════════════════════════════
   UI — shared behaviour for the design-system components.
   ───────────────────────────────────────────────────────────────
   Styles: static/css/components.css (.ui-toast, .modal, .ui-tabs).
   Loaded on every page by templates/layout/head_assets.html, so
   any page can call UI.toast()/UI.confirm()/UI.tabs() without
   building its own copy. Plain script, no build step, no deps.

   Text passed in is always inserted as TEXT, never as HTML — an
   earlier per-page toast used innerHTML with server messages.
═══════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  const ICONS = { success: 'fa-check-circle', error: 'fa-exclamation-circle',
                  warning: 'fa-exclamation-triangle', info: 'fa-info-circle' };

  function stack() {
    let el = document.querySelector('.ui-toast-stack');
    if (!el) {
      el = document.createElement('div');
      el.className = 'ui-toast-stack';
      el.setAttribute('role', 'status');
      el.setAttribute('aria-live', 'polite');
      document.body.appendChild(el);
    }
    return el;
  }

  /** UI.toast('Saved') · UI.toast('Failed', 'error') · {duration: ms} */
  function toast(message, type = 'success', opts = {}) {
    const kind = ICONS[type] ? type : 'info';
    const el = document.createElement('div');
    el.className = `ui-toast ui-toast-${kind}`;
    const icon = document.createElement('i');
    icon.className = `fas ${ICONS[kind]}`;
    icon.setAttribute('aria-hidden', 'true');
    const text = document.createElement('span');
    text.textContent = String(message ?? '');
    el.append(icon, text);
    const host = stack();
    host.appendChild(el);
    // Never let a burst of toasts cover the page.
    while (host.children.length > 4) host.firstElementChild.remove();
    const ms = opts.duration ?? (kind === 'error' ? 4500 : 2700);
    setTimeout(() => {
      el.classList.add('leaving');
      setTimeout(() => el.remove(), 250);
    }, ms);
    return el;
  }

  /** await UI.confirm({title, message, confirmText, danger}) → true/false.
      Uses the shared .modal markup; Escape/backdrop/Cancel resolve false. */
  function confirm(opts = {}) {
    const o = typeof opts === 'string' ? { message: opts } : opts;
    return new Promise(resolve => {
      const prev = document.activeElement;
      const overlay = document.createElement('div');
      overlay.className = 'modal-overlay';
      overlay.style.display = 'flex';
      const modal = document.createElement('div');
      modal.className = 'modal';
      modal.setAttribute('role', 'alertdialog');
      modal.setAttribute('aria-modal', 'true');
      const head = document.createElement('div');
      head.className = 'modal-header';
      const h = document.createElement('h3');
      h.id = 'ui-confirm-title-' + Date.now();
      h.textContent = o.title || 'Are you sure?';
      modal.setAttribute('aria-labelledby', h.id);
      head.appendChild(h);
      const body = document.createElement('div');
      body.className = 'modal-body ui-confirm-body';
      body.textContent = o.message || '';
      const foot = document.createElement('div');
      foot.className = 'modal-footer';
      const cancel = document.createElement('button');
      cancel.type = 'button';
      cancel.className = 'btn btn-secondary';
      cancel.textContent = o.cancelText || 'Cancel';
      const ok = document.createElement('button');
      ok.type = 'button';
      ok.className = 'btn ' + (o.danger ? 'btn-danger-solid' : 'btn-primary');
      ok.textContent = o.confirmText || 'Confirm';
      foot.append(cancel, ok);
      modal.append(head, body, foot);
      overlay.appendChild(modal);
      document.body.appendChild(overlay);
      ok.focus();

      function done(value) {
        document.removeEventListener('keydown', onKey, true);
        overlay.remove();
        if (prev && prev.focus) prev.focus();
        resolve(value);
      }
      function onKey(e) {
        if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); done(false); }
        if (e.key === 'Tab') {               // keep focus inside the dialog
          e.preventDefault();
          (document.activeElement === ok ? cancel : ok).focus();
        }
      }
      document.addEventListener('keydown', onKey, true);
      overlay.addEventListener('mousedown', e => { if (e.target === overlay) done(false); });
      cancel.addEventListener('click', () => done(false));
      ok.addEventListener('click', () => done(true));
    });
  }

  /** UI.tabs(tablistEl, onChange) — click + Left/Right/Home/End keys,
      maintains aria-selected/tabindex. onChange(tabEl, index). */
  function tabs(list, onChange) {
    const items = () => [...list.querySelectorAll('[role="tab"], .ui-tab')];
    function select(tab, focus) {
      items().forEach(t => {
        const on = t === tab;
        t.setAttribute('aria-selected', on ? 'true' : 'false');
        t.tabIndex = on ? 0 : -1;
        t.classList.toggle('active', on);
      });
      if (focus) tab.focus();
      if (onChange) onChange(tab, items().indexOf(tab));
    }
    list.addEventListener('click', e => {
      const tab = e.target.closest('[role="tab"], .ui-tab');
      if (tab && list.contains(tab)) select(tab, false);
    });
    list.addEventListener('keydown', e => {
      const all = items(); const i = all.indexOf(document.activeElement);
      if (i < 0) return;
      const next = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: all.length - 1 }[e.key];
      if (next === undefined) return;
      e.preventDefault();
      select(all[(next + all.length) % all.length], true);
    });
    return { select: t => select(t, false) };
  }

  /* Themed tooltips for every element with a `title` (or data-tooltip),
     app-wide, with no markup changes. On hover/focus the native title is
     parked in data-ui-title (so the OS tooltip doesn't double up) and
     restored on leave; an aria-label is added only if the element had no
     accessible name besides the title. Styled by .ui-tooltip in
     components.css (--tooltip-bg/-tx). */
  let tipEl = null, tipFor = null, tipTimer = 0;
  function tipText(el) { return el.getAttribute('data-ui-title') || el.getAttribute('title') || ''; }
  function showTip(el) {
    const text = tipText(el).trim();
    if (!text) return;
    if (el.hasAttribute('title')) {
      el.setAttribute('data-ui-title', el.getAttribute('title'));
      el.removeAttribute('title');
      if (!el.getAttribute('aria-label') && !el.textContent.trim()) {
        el.setAttribute('aria-label', text); el.setAttribute('data-ui-aria', '1');
      }
    }
    if (!tipEl) {
      tipEl = document.createElement('div');
      tipEl.className = 'ui-tooltip'; tipEl.setAttribute('role', 'tooltip'); tipEl.id = 'ui-tooltip';
      document.body.appendChild(tipEl);
    }
    tipEl.textContent = text;
    tipEl.classList.add('show');
    const r = el.getBoundingClientRect(), t = tipEl.getBoundingClientRect();
    let x = r.left + r.width / 2 - t.width / 2, y = r.top - t.height - 8;
    if (y < 4) y = r.bottom + 8;
    x = Math.max(4, Math.min(x, innerWidth - t.width - 4));
    tipEl.style.left = x + 'px'; tipEl.style.top = y + 'px';
    el.setAttribute('aria-describedby', 'ui-tooltip');
    tipFor = el;
  }
  function hideTip() {
    clearTimeout(tipTimer);
    if (tipEl) tipEl.classList.remove('show');
    const el = tipFor; tipFor = null;
    if (!el) return;
    if (el.hasAttribute('data-ui-title')) {
      el.setAttribute('title', el.getAttribute('data-ui-title'));
      el.removeAttribute('data-ui-title');
    }
    if (el.getAttribute('data-ui-aria')) { el.removeAttribute('aria-label'); el.removeAttribute('data-ui-aria'); }
    if (el.getAttribute('aria-describedby') === 'ui-tooltip') el.removeAttribute('aria-describedby');
  }
  function tipTarget(node) {
    return node && node.closest ? node.closest('[title]:not(iframe):not(svg *), [data-ui-title]') : null;
  }
  document.addEventListener('pointerover', e => {
    const el = tipTarget(e.target);
    if (el === tipFor) return;
    hideTip();
    if (el && e.pointerType !== 'touch') tipTimer = setTimeout(() => showTip(el), 350);
  }, true);
  document.addEventListener('pointerout', e => {
    if (tipFor && !tipFor.contains(e.relatedTarget)) hideTip();
    else if (!tipFor) clearTimeout(tipTimer);
  }, true);
  document.addEventListener('focusin', e => { const el = tipTarget(e.target); if (el && el.matches(':focus-visible')) { hideTip(); showTip(el); } });
  document.addEventListener('focusout', hideTip);
  ['pointerdown', 'keydown', 'scroll'].forEach(t => document.addEventListener(t, hideTip, true));

  window.UI = Object.freeze({ toast, confirm, tabs });
})();
