/**
 * AnnoMaster Global Theme Engine
 * Automatically runs on page load before DOM parsing to prevent flashing
 */

(function() {
  /* ── Contrast helpers (WCAG 2) ─────────────────────────────────────────
     Used so user choices in Theme Settings (custom colours, custom accent)
     can never produce unreadable text: derived TEXT tokens are nudged until
     they meet AA on the surfaces they sit on. Fills keep the exact colour. */
  const _lin = v => { v /= 255; return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
  const _L = c => 0.2126 * _lin(c[0]) + 0.7152 * _lin(c[1]) + 0.0722 * _lin(c[2]);
  const _cr = (a, c) => { const x = _L(a), y = _L(c); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  const _rgb = str => {
    str = String(str || '').trim();
    if (str[0] === '#') return [1, 3, 5].map(i => parseInt(str.slice(i, i + 2), 16));
    const m = str.match(/(\d+(?:\.\d+)?)\D+(\d+(?:\.\d+)?)\D+(\d+(?:\.\d+)?)/);
    return m ? [+m[1], +m[2], +m[3]] : null;
  };
  // Stock surfaces per base theme (tokens.css): bg, surface, panel, card2, card3
  const BASE_SURFACES = {
    dark:  [[7, 7, 13], [13, 13, 22], [17, 17, 25], [28, 28, 40], [36, 36, 50]],
    light: [[247, 249, 251], [255, 255, 255], [242, 244, 246], [236, 238, 240], [230, 232, 234]],
  };
  let _customSurfaces = null;           // set by applyCustomTheme

  /** The surfaces actually in effect (dark styles change them), read from
      the token layer. tokens.css is loaded before this script runs. */
  function liveSurfaces() {
    try {
      const cs = getComputedStyle(document.documentElement);
      const list = ['--bg', '--surface', '--panel', '--card', '--card2', '--card3']
        .map(n => _rgb(cs.getPropertyValue(n)));
      return list.every(Boolean) ? list : null;
    } catch (e) { return null; }
  }

  /* Dark styles (tokens.css "DARK STYLES"): variants of the dark theme.
     'classic' = the stock dark palette (no attribute). */
  const DARK_STYLES = ['classic', 'midnight', 'navy', 'carbon'];
  function applyDarkStyle(name) {
    const root = document.documentElement;
    if (name && name !== 'classic' && DARK_STYLES.includes(name)) root.setAttribute('data-dark-style', name);
    else root.removeAttribute('data-dark-style');
    syncAccentText();
  }

  /** Drop a user-picked accent so the theme / dark style's own accent shows. */
  function clearAccent() {
    const root = document.documentElement;
    ['--accent', '--accent-dim', '--accent-bg', '--accent-glow', '--accent-text']
      .forEach(p => root.style.removeProperty(p));
    syncAccentText();
  }

  /** --accent-text = the accent, moved toward black (light) / white (dark)
      only as far as needed for ≥ 4.5:1 on every surface + its own tint.
      Without a user accent or custom theme, tokens.css values apply. */
  function syncAccentText() {
    const root = document.documentElement;
    const userAccent = root.style.getPropertyValue('--accent').trim();
    const custom = root.classList.contains('custom-mode');
    if (!userAccent && !custom) { root.style.removeProperty('--accent-text'); return; }
    const light = root.classList.contains('light-mode');
    const surfaces = (custom && _customSurfaces) || liveSurfaces() || BASE_SURFACES[light ? 'light' : 'dark'];
    const acc = _rgb(userAccent) || (light ? [0, 108, 73] : [0, 229, 176]);
    const tints = surfaces.map(s => s.map((v, i) => Math.round(acc[i] * 0.10 + v * 0.90)));   // --accent-bg over a surface
    const all = surfaces.concat(tints), target = light ? 0 : 255;
    let c = acc;
    for (let w = 0; w <= 1.0001; w += 0.04) {
      c = acc.map(v => Math.round(v + (target - v) * w));
      if (all.every(sf => _cr(c, sf) >= 4.5)) break;
    }
    root.style.setProperty('--accent-text', `rgb(${c[0]}, ${c[1]}, ${c[2]})`);
  }

  function applyAccent(hexCode) {
    if (!hexCode) return;
    const root = document.documentElement;
    
    let r = parseInt(hexCode.slice(1, 3), 16);
    let g = parseInt(hexCode.slice(3, 5), 16);
    let b = parseInt(hexCode.slice(5, 7), 16);
    if (isNaN(r) || isNaN(g) || isNaN(b)) return;
    
    let rDim = Math.max(0, Math.floor(r * 0.8));
    let gDim = Math.max(0, Math.floor(g * 0.8));
    let bDim = Math.max(0, Math.floor(b * 0.8));

    root.style.setProperty('--accent', hexCode);
    root.style.setProperty('--accent-dim', `rgb(${rDim}, ${gDim}, ${bDim})`);
    root.style.setProperty('--accent-bg', `rgba(${r}, ${g}, ${b}, 0.08)`);
    root.style.setProperty('--accent-glow', `rgba(${r}, ${g}, ${b}, 0.22)`);
    syncAccentText();
  }

  function applyCustomTheme(bgHex, txHex) {
    if (!bgHex || !txHex) return;
    const root = document.documentElement;
    root.style.setProperty('--bg', bgHex);
    
    let r = parseInt(bgHex.slice(1, 3), 16);
    let g = parseInt(bgHex.slice(3, 5), 16);
    let b = parseInt(bgHex.slice(5, 7), 16);
    if (isNaN(r) || isNaN(g) || isNaN(b)) return;
    
    let tr = parseInt(txHex.slice(1, 3), 16);
    let tg = parseInt(txHex.slice(3, 5), 16);
    let tb = parseInt(txHex.slice(5, 7), 16);
    if (isNaN(tr) || isNaN(tg) || isNaN(tb)) return;

    let isDark = (r * 0.299 + g * 0.587 + b * 0.114) < 128;
    // A custom theme inherits every token it doesn't set (accent, status
    // colours, card2/3, overlay ramps, on-fill) from a BASE theme. That base
    // must match the custom background: a light custom background on the dark
    // base kept bright-teal accents, white hairlines and dark cards.
    // On <html> only: tokens.css also declares the stock light palette on
    // body.light-mode, which would shadow these custom values for the page.
    document.documentElement.classList.toggle('light-mode', !isDark);
    if (document.body) document.body.classList.remove('light-mode');
    let factor = isDark ? 1.08 : 0.95;
    let sr = Math.min(255, Math.max(0, Math.floor(r * factor)));
    let sg = Math.min(255, Math.max(0, Math.floor(g * factor)));
    let sb = Math.min(255, Math.max(0, Math.floor(b * factor)));
    
    let panelFactor = isDark ? 0.92 : 0.98;
    let pr = Math.min(255, Math.max(0, Math.floor(r * panelFactor)));
    let pg = Math.min(255, Math.max(0, Math.floor(g * panelFactor)));
    let pb = Math.min(255, Math.max(0, Math.floor(b * panelFactor)));

    root.style.setProperty('--surface', `rgb(${sr}, ${sg}, ${sb})`);
    root.style.setProperty('--card', `rgb(${sr}, ${sg}, ${sb})`);
    root.style.setProperty('--panel', `rgb(${pr}, ${pg}, ${pb})`);
    root.style.setProperty('--tx', txHex);
    // Secondary/tertiary text: the user's text colour faded toward the
    // background, but never below WCAG contrast on any custom surface
    // (tx2 ≥ 6:1, tx3 ≥ 4.5:1, the same targets as tokens.css). Fixed alphas (0.72 / 0.45) failed for many
    // colour choices, which made labels unreadable.
    const lin = v => { v /= 255; return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    const L = c => 0.2126 * lin(c[0]) + 0.7152 * lin(c[1]) + 0.0722 * lin(c[2]);
    const cr = (a, c) => { const x = L(a), y = L(c); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
    // + the base theme's card2/card3 (inherited) and the deepest hover/chip
    // overlay on the custom background (ink ramp ≈ 10%), where text also sits
    const deep = [r, g, b].map(v => Math.round(isDark ? v + (255 - v) * 0.10 : v * 0.90));
    const surfaces = [[r, g, b], [sr, sg, sb], [pr, pg, pb], deep].concat(isDark
      ? [[0x1c, 0x1c, 0x28], [0x24, 0x24, 0x32]] : [[0xec, 0xee, 0xf0], [0xe6, 0xe8, 0xea]]);
    _customSurfaces = surfaces;
    const mixTx = (w) => [tr, tg, tb].map((t, i) => Math.round(t * w + [r, g, b][i] * (1 - w)));
    const readable = (w, need) => {
      for (; w < 1; w += 0.02) if (surfaces.every(s => cr(mixTx(w), s) >= need)) break;
      const c = mixTx(Math.min(1, w));
      return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
    };
    root.style.setProperty('--tx2', readable(0.72, 6));
    root.style.setProperty('--tx3', readable(0.45, 4.5));
    syncAccentText();
    
    if (isDark) {
      root.style.setProperty('--border', `rgba(255, 255, 255, 0.08)`);
      root.style.setProperty('--border2', `rgba(255, 255, 255, 0.12)`);
      root.style.setProperty('--border3', `rgba(255, 255, 255, 0.18)`);
      root.style.setProperty('--glass', `rgba(255, 255, 255, 0.02)`);
      root.style.setProperty('--glass-hover', `rgba(255, 255, 255, 0.05)`);
      root.style.setProperty('--sh-md', `0 8px 32px rgba(0, 0, 0, 0.4)`);
      root.style.setProperty('--sh-lg', `0 24px 64px rgba(0, 0, 0, 0.6)`);
    } else {
      root.style.setProperty('--border', `rgba(0, 0, 0, 0.06)`);
      root.style.setProperty('--border2', `rgba(0, 0, 0, 0.10)`);
      root.style.setProperty('--border3', `rgba(0, 0, 0, 0.15)`);
      root.style.setProperty('--glass', `rgba(55, 65, 81, 0.03)`);
      root.style.setProperty('--glass-hover', `rgba(55, 65, 81, 0.07)`);
      root.style.setProperty('--sh-md', `0 8px 24px rgba(0, 0, 0, 0.04)`);
      root.style.setProperty('--sh-lg', `0 16px 48px rgba(0, 0, 0, 0.06)`);
    }
  }

  function clearCustomTheme() {
    const root = document.documentElement;
    const props = [
      '--bg', '--surface', '--card', '--panel', '--tx', '--tx2', '--tx3', 
      '--border', '--border2', '--border3', '--glass', '--glass-hover', 
      '--sh-md', '--sh-lg'
    ];
    props.forEach(p => root.style.removeProperty(p));
    _customSurfaces = null;
    syncAccentText();          // a user accent now sits on stock surfaces
  }

  function applyCardCustomization(opts) {
    const root = document.documentElement;
    if (!opts) return;
    if (opts.bg) root.style.setProperty('--card-bg', opts.bg);
    if (opts.tx) root.style.setProperty('--card-tx', opts.tx);
    if (opts.border) root.style.setProperty('--card-border', opts.border);
    if (opts.radius) root.style.setProperty('--card-radius', opts.radius);
    
    // Shadow mapping
    if (opts.shadow === 'none') {
      root.style.setProperty('--card-shadow', 'none');
    } else if (opts.shadow === 'subtle') {
      root.style.setProperty('--card-shadow', '0 2px 8px rgba(0,0,0,0.05), 0 0 0 1px rgba(255,255,255,0.01)');
    } else if (opts.shadow === 'medium') {
      root.style.setProperty('--card-shadow', 'var(--sh-md)');
    } else if (opts.shadow === 'intense') {
      root.style.setProperty('--card-shadow', '0 16px 48px rgba(0,0,0,0.22), 0 0 30px var(--accent-glow)');
    }

    // Padding mapping
    if (opts.padding) root.style.setProperty('--card-padding', opts.padding);
    
    // Opacity mapping
    if (opts.opacity) root.style.setProperty('--card-opacity', opts.opacity);

    // Hover effect mapping
    if (opts.hover === 'none') {
      root.style.setProperty('--card-hover-transform', 'none');
      root.style.setProperty('--card-hover-shadow', opts.shadow === 'none' ? 'none' : 'var(--card-shadow)');
      root.style.setProperty('--card-hover-border', 'var(--card-border)');
    } else if (opts.hover === 'scale') {
      root.style.setProperty('--card-hover-transform', 'translateY(-3px)');
      root.style.setProperty('--card-hover-shadow', '0 8px 24px rgba(0,0,0,0.12)');
      root.style.setProperty('--card-hover-border', 'var(--card-border)');
    } else if (opts.hover === 'glow') {
      root.style.setProperty('--card-hover-transform', 'none');
      root.style.setProperty('--card-hover-shadow', '0 0 20px var(--accent-glow)');
      root.style.setProperty('--card-hover-border', 'var(--accent)');
    } else if (opts.hover === 'both') {
      root.style.setProperty('--card-hover-transform', 'translateY(-4px)');
      root.style.setProperty('--card-hover-shadow', '0 12px 32px rgba(0,0,0,0.18), 0 0 20px var(--accent-glow)');
      root.style.setProperty('--card-hover-border', 'var(--accent)');
    }
  }

  function clearCardCustomization() {
    const root = document.documentElement;
    const props = ['--card-bg', '--card-tx', '--card-border', '--card-radius', '--card-shadow', '--card-padding', '--card-opacity', '--card-hover-transform', '--card-hover-shadow', '--card-hover-border'];
    props.forEach(p => root.style.removeProperty(p));
  }

  // Load and apply theme parameters immediately
  let themeMode = localStorage.getItem('am_theme_mode');
  let accentColor = localStorage.getItem('am_accent_color');
  let layoutMode = localStorage.getItem('am_layout_mode');
  let customBg = localStorage.getItem('am_custom_bg');
  let customText = localStorage.getItem('am_custom_text');
  let darkStyle = localStorage.getItem('am_dark_style');

  let cardBg = localStorage.getItem('am_card_bg');
  let cardTx = localStorage.getItem('am_card_tx');
  let cardBorder = localStorage.getItem('am_card_border');
  let cardRadius = localStorage.getItem('am_card_radius');
  let cardShadow = localStorage.getItem('am_card_shadow');
  let cardPadding = localStorage.getItem('am_card_padding');
  let cardHover = localStorage.getItem('am_card_hover');
  let cardOpacity = localStorage.getItem('am_card_opacity');

  // Fallback to scanning for user-specific keys if global keys aren't set
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i);
    if (key) {
      if (!themeMode && key.startsWith('am_theme_mode_')) {
        themeMode = localStorage.getItem(key);
      }
      if (!accentColor && key.startsWith('am_accent_color_')) {
        accentColor = localStorage.getItem(key);
      }
      if (!layoutMode && key.startsWith('am_layout_mode_')) {
        layoutMode = localStorage.getItem(key);
      }
      if (!customBg && key.startsWith('am_custom_bg_')) {
        customBg = localStorage.getItem(key);
      }
      if (!customText && key.startsWith('am_custom_text_')) {
        customText = localStorage.getItem(key);
      }
      if (!darkStyle && key.startsWith('am_dark_style_')) darkStyle = localStorage.getItem(key);
      if (!cardBg && key.startsWith('am_card_bg_')) cardBg = localStorage.getItem(key);
      if (!cardTx && key.startsWith('am_card_tx_')) cardTx = localStorage.getItem(key);
      if (!cardBorder && key.startsWith('am_card_border_')) cardBorder = localStorage.getItem(key);
      if (!cardRadius && key.startsWith('am_card_radius_')) cardRadius = localStorage.getItem(key);
      if (!cardShadow && key.startsWith('am_card_shadow_')) cardShadow = localStorage.getItem(key);
      if (!cardPadding && key.startsWith('am_card_padding_')) cardPadding = localStorage.getItem(key);
      if (!cardHover && key.startsWith('am_card_hover_')) cardHover = localStorage.getItem(key);
      if (!cardOpacity && key.startsWith('am_card_opacity_')) cardOpacity = localStorage.getItem(key);
    }
  }

  if (themeMode === 'light') {
    document.documentElement.classList.add('light-mode');
    document.documentElement.classList.remove('custom-mode');
    clearCustomTheme();
  } else if (themeMode === 'custom') {
    document.documentElement.classList.add('custom-mode');
    document.documentElement.classList.remove('light-mode');
    if (customBg && customText) {
      applyCustomTheme(customBg, customText);
    }
  } else {
    document.documentElement.classList.remove('light-mode');
    document.documentElement.classList.remove('custom-mode');
    clearCustomTheme();
  }

  // The attribute only takes effect in dark mode (tokens.css guards it with
  // :not(.light-mode):not(.custom-mode)), so it can stay set across switches.
  applyDarkStyle(darkStyle);

  if (layoutMode === 'compact') {
    document.documentElement.classList.add('compact-mode');
  } else {
    document.documentElement.classList.remove('compact-mode');
  }

  if (accentColor) {
    applyAccent(accentColor);
  }

  if (cardBg || cardTx || cardBorder || cardRadius || cardShadow || cardPadding || cardHover || cardOpacity) {
    applyCardCustomization({
      bg: cardBg,
      tx: cardTx,
      border: cardBorder,
      radius: cardRadius,
      shadow: cardShadow,
      padding: cardPadding,
      hover: cardHover,
      opacity: cardOpacity
    });
  }

  // Sync classes to body on DOMContentLoaded for body-specific CSS rules
  document.addEventListener('DOMContentLoaded', () => {
    // Not in custom mode: there <html>.light-mode only picks the BASE palette,
    // and body.light-mode would redeclare stock light tokens over the custom ones.
    if (document.documentElement.classList.contains('light-mode') &&
        !document.documentElement.classList.contains('custom-mode')) {
      document.body.classList.add('light-mode');
    }
    if (document.documentElement.classList.contains('custom-mode')) {
      document.body.classList.add('custom-mode');
    }
    if (document.documentElement.classList.contains('compact-mode')) {
      document.body.classList.add('compact-mode');
    }
  });

  // Expose ThemeEngine globally for runtime switching
  window.ThemeEngine = {
    applyAccentColor: applyAccent,
    applyCustomTheme: applyCustomTheme,
    clearCustomTheme: clearCustomTheme,
    applyCardCustomization: applyCardCustomization,
    clearCardCustomization: clearCardCustomization,
    setDarkStyle: applyDarkStyle,
    clearAccent: clearAccent,
    darkStyles: DARK_STYLES.slice(),

    setThemeMode: function(mode) {
      if (mode === 'light') {
        document.documentElement.classList.add('light-mode');
        document.documentElement.classList.remove('custom-mode');
        if (document.body) {
          document.body.classList.add('light-mode');
          document.body.classList.remove('custom-mode');
        }
        clearCustomTheme();
      } else if (mode === 'custom') {
        document.documentElement.classList.add('custom-mode');
        document.documentElement.classList.remove('light-mode');
        if (document.body) {
          document.body.classList.add('custom-mode');
          document.body.classList.remove('light-mode');
        }
      } else {
        document.documentElement.classList.remove('light-mode');
        document.documentElement.classList.remove('custom-mode');
        if (document.body) {
          document.body.classList.remove('light-mode');
          document.body.classList.remove('custom-mode');
        }
        clearCustomTheme();
      }
      syncAccentText();      // surfaces changed → re-derive accent text
    },

    setLayoutMode: function(mode) {
      if (mode === 'compact') {
        document.documentElement.classList.add('compact-mode');
        if (document.body) document.body.classList.add('compact-mode');
      } else {
        document.documentElement.classList.remove('compact-mode');
        if (document.body) document.body.classList.remove('compact-mode');
      }
    }
  };
})();
