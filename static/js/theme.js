/**
 * AnnoMaster Global Theme Engine
 * Automatically runs on page load before DOM parsing to prevent flashing
 */

(function() {
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
    root.style.setProperty('--tx2', `rgba(${tr}, ${tg}, ${tb}, 0.72)`);
    root.style.setProperty('--tx3', `rgba(${tr}, ${tg}, ${tb}, 0.45)`);
    
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
    if (document.documentElement.classList.contains('light-mode')) {
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
