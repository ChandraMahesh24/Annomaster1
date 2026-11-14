/**
 * AnnoMaster Settings Page Feature Engine
 */

const SettingsPage = (() => {
  let currentUser = null;
  // Professional translations dictionary to dynamically change panel titles
  const translations = {
    en: {
      profile: "Profile Management",
      theme: "Theme Settings",
      security: "Security & Sessions",
      notifications: "Notification Settings",
      language: "Language & Region",
      layout: "Layout Preferences",
      danger: "Reset & Danger",
      saved: "✓ Settings updated successfully!",
      error: "❌ An error occurred. Please try again."
    },
    es: {
      profile: "Gestión de Perfil",
      theme: "Ajustes de Tema",
      security: "Seguridad y Sesiones",
      notifications: "Ajustes de Notificación",
      language: "Idioma y Región",
      layout: "Preferencias de Diseño",
      danger: "Restablecer y Peligro",
      saved: "✓ ¡Ajustes actualizados correctamente!",
      error: "❌ Ocurrió un error. Inténtelo de nuevo."
    },
    fr: {
      profile: "Gestion du Profil",
      theme: "Paramètres de Thème",
      security: "Sécurité & Sessions",
      notifications: "Notifications",
      language: "Langue & Région",
      layout: "Préférences de Disposition",
      danger: "Réinitialisation & Danger",
      saved: "✓ Paramètres mis à jour avec succès !",
      error: "❌ Une erreur est survenue. Veuillez réessayer."
    },
    de: {
      profile: "Profilverwaltung",
      theme: "Design-Einstellungen",
      security: "Sicherheit & Sitzungen",
      notifications: "Benachrichtigungen",
      language: "Sprache & Region",
      layout: "Layout-Einstellungen",
      danger: "Zurücksetzen & Gefahr",
      saved: "✓ Einstellungen erfolgreich aktualisiert!",
      error: "❌ Ein Fehler ist aufgetreten. Bitte versuchen Sie es erneut."
    },
    jp: {
      profile: "プロファイル管理",
      theme: "テーマ設定",
      security: "セキュリティとセッション",
      notifications: "通知設定",
      language: "言語と地域",
      layout: "レイアウト設定",
      danger: "リセットと危険ゾーン",
      saved: "✓ 設定が正常に更新されました！",
      error: "❌ エラーが発生しました。もう一度お試しください。"
    },
    cn: {
      profile: "个人资料管理",
      theme: "主题配色设置",
      security: "安全与登录会话",
      notifications: "通知消息设置",
      language: "语言与地区选项",
      layout: "布局与显示密度",
      danger: "重置与危险操作",
      saved: "✓ 设置已成功更新并保存！",
      error: "❌ 发生错误，请稍后重试。"
    }
  };

  function init(user) {
    currentUser = user;
    
    // Load local storage custom preferences
    loadSavedPreferences();

    // Fill form elements
    const nameEl = document.getElementById('profile-username');
    const emailEl = document.getElementById('profile-email');
    if (nameEl) nameEl.value = user.username || '';
    if (emailEl) emailEl.value = user.email || '';

    // Load additional custom fields (bio, phone) from localStorage
    const localBio = localStorage.getItem(`am_bio_${user.id}`);
    const localPhone = localStorage.getItem(`am_phone_${user.id}`);
    const bioEl = document.getElementById('profile-bio');
    const phoneEl = document.getElementById('profile-phone');
    if (bioEl && localBio) bioEl.value = localBio;
    if (phoneEl && localPhone) phoneEl.value = localPhone;

    // Render active sessions
    renderSessions();
  }

  // Switch Settings Sidebar Tabs
  let _wsLoaded = false;

  function switchTab(name, btn) {
    document.querySelectorAll('.settings-panel').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.settings-nav-btn').forEach(b => b.classList.remove('active'));

    const panel = document.getElementById('panel-' + name);
    if (panel) panel.classList.add('active');
    if (btn) btn.classList.add('active');

    // Workspace data is fetched lazily, on first open of that tab — three API
    // calls on every Settings load would be wasted for anyone who never opens it.
    if (name === 'workspace' && !_wsLoaded) {
      _wsLoaded = true;
      loadWorkspaces();
    }
  }

  // Set preset avatar emojis
  function setPresetAvatar(avatarKey) {
    const avatarMap = {
      astronaut: '👨‍🚀',
      detective: '🕵️‍♂️',
      coder: '👨‍💻',
      robot: '🤖',
      cat: '🐱'
    };
    const emoji = avatarMap[avatarKey] || 'U';
    
    // Save avatar representation in localStorage
    localStorage.setItem(`am_avatar_${currentUser.id}`, emoji);
    applyAvatarDisplay(emoji);
    showToast("Profile avatar updated!", false);
  }

  function resetAvatarInitials() {
    localStorage.removeItem(`am_avatar_${currentUser.id}`);
    const initial = (currentUser.username ? currentUser.username[0] : 'U').toUpperCase();
    applyAvatarDisplay(initial);
    showToast("Avatar reset to username initial.", false);
  }

  function applyAvatarDisplay(symbol) {
    const avatarDisplay = document.getElementById('profile-avatar-display');
    const navAvatar = document.getElementById('user-avatar');
    const ddAvatar = document.getElementById('dd-avatar');

    if (avatarDisplay) avatarDisplay.textContent = symbol;
    if (navAvatar) navAvatar.textContent = symbol;
    if (ddAvatar) ddAvatar.textContent = symbol;
  }

  // Save profile username, email, and additional metadata
  async function saveProfile() {
    const username = document.getElementById('profile-username').value.trim();
    const email    = document.getElementById('profile-email').value.trim().toLowerCase();
    const bio      = document.getElementById('profile-bio').value.trim();
    const phone    = document.getElementById('profile-phone').value.trim();
    
    const errEl    = document.getElementById('profile-error');
    const okEl     = document.getElementById('profile-success');
    errEl.textContent = ''; okEl.textContent = '';

    if (!username || !email) {
      errEl.textContent = 'Username and Email are required.';
      showToast('Fill in all required fields.', true);
      return;
    }

    try {
      // Use standard backend endpoint for profile updates
      const token = localStorage.getItem('am_token') || sessionStorage.getItem('am_token');
      const res = await fetch('/api/auth/update-profile', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ username, email })
      });

      if (!res.ok) {
        const data = await res.json();
        errEl.textContent = data.error || 'Failed to save changes.';
        showToast(data.error || 'Saving profile failed.', true);
        return;
      }

      const data = await res.json();
      
      // Save bio/phone extra fields locally
      localStorage.setItem(`am_bio_${currentUser.id}`, bio);
      localStorage.setItem(`am_phone_${currentUser.id}`, phone);

      okEl.textContent = '✓ Profile saved successfully!';
      showToast('Profile updated!', false);

      // Sync user dropdown headers
      const navName = document.getElementById('user-name');
      const ddName = document.getElementById('dd-name');
      const ddEmail = document.getElementById('dd-email');

      if (navName) navName.textContent = data.user.username;
      if (ddName) ddName.textContent = data.user.username;
      if (ddEmail) ddEmail.textContent = data.user.email;

      // Update State model if loaded
      if (typeof State !== 'undefined') {
        State.set('user', data.user);
      }
      currentUser = data.user;

    } catch (e) {
      console.error(e);
      errEl.textContent = 'Connection error. Please try again.';
      showToast('Profile save failed.', true);
    }
  }

  // Change Password API hook
  async function changePassword() {
    const cur  = document.getElementById('security-current-pw').value;
    const nw   = document.getElementById('security-new-pw').value;
    const conf = document.getElementById('security-confirm-pw').value;
    
    const errEl = document.getElementById('security-pw-error');
    const okEl  = document.getElementById('security-pw-ok');
    errEl.textContent = ''; okEl.textContent = '';

    if (!cur || !nw || !conf) {
      errEl.textContent = 'Fill in all password fields.';
      showToast('Passwords cannot be empty.', true);
      return;
    }
    if (nw.length < 8) {
      errEl.textContent = 'New password must be at least 8 characters.';
      showToast('Password is too short.', true);
      return;
    }
    if (nw !== conf) {
      errEl.textContent = 'Passwords do not match.';
      showToast('Passwords must match.', true);
      return;
    }

    try {
      const token = localStorage.getItem('am_token') || sessionStorage.getItem('am_token');
      const res = await fetch('/api/auth/change-password', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ current_password: cur, new_password: nw })
      });

      const data = await res.json();
      if (!res.ok) {
        errEl.textContent = data.error || 'Current password incorrect.';
        showToast(data.error || 'Password update failed.', true);
        return;
      }

      // If new token is issued, store it
      if (data.token) {
        if (localStorage.getItem('am_token')) localStorage.setItem('am_token', data.token);
        if (sessionStorage.getItem('am_token')) sessionStorage.setItem('am_token', data.token);
      }

      okEl.textContent = '✓ Password changed successfully!';
      showToast('Password changed!', false);

      document.getElementById('security-current-pw').value = '';
      document.getElementById('security-new-pw').value     = '';
      document.getElementById('security-confirm-pw').value = '';

    } catch (e) {
      console.error(e);
      errEl.textContent = 'Connection error. Please try again.';
      showToast('Password update failed.', true);
    }
  }

  // Theme Modes & Styling variables
  // `silent` = applying the already-saved mode on page load: no toast and
  // no "unsaved changes" marker (both used to fire on every Settings visit).
  function setThemeMode(mode, silent = false) {
    document.querySelectorAll('.theme-mode-card').forEach(c => c.classList.remove('active'));
    const targetCard = document.getElementById('theme-mode-' + mode);
    if (targetCard) targetCard.classList.add('active');

    const customRow = document.getElementById('custom-theme-colors-row');
    if (mode === 'custom') {
      if (customRow) customRow.style.display = 'flex';
      // Load current colors and apply
      const bg = document.getElementById('custom-theme-bg')?.value || '#1e1e24';
      const text = document.getElementById('custom-theme-text')?.value || '#e4e4e7';
      ThemeEngine.setThemeMode('custom');
      ThemeEngine.applyCustomTheme(bg, text);
    } else {
      if (customRow) customRow.style.display = 'none';
      ThemeEngine.setThemeMode(mode);
    }

    localStorage.setItem(`am_theme_mode_${currentUser.id}`, mode);
    localStorage.setItem('am_theme_mode', mode);
    const darkRow = document.getElementById('dark-style-row');
    if (darkRow) darkRow.style.display = mode === 'dark' ? '' : 'none';
    if (silent) return;
    markThemeUnsaved();
    showToast(`Interface mode → ${mode.toUpperCase()}`, false);
  }

  // Dark style = a variant of Dark Mode (Classic / Midnight Blue / Navy /
  // Carbon), defined once in tokens.css. Choosing one switches to Dark Mode
  // and drops a previously picked accent so the style's own accent shows;
  // the accent picker still works afterwards.
  const DARK_STYLE_NAMES = { classic: 'Classic', midnight: 'Midnight Blue', navy: 'Navy', carbon: 'Carbon' };
  function markDarkStyle(name) {
    document.querySelectorAll('.dsty-opt').forEach(b => {
      const on = b.dataset.style === name;
      b.classList.toggle('active', on);
      b.setAttribute('aria-checked', on ? 'true' : 'false');
    });
  }
  function setDarkStyle(name, silent = false) {
    if (!DARK_STYLE_NAMES[name]) name = 'classic';
    ThemeEngine.setDarkStyle(name);
    localStorage.setItem(`am_dark_style_${currentUser.id}`, name);
    localStorage.setItem('am_dark_style', name);
    markDarkStyle(name);
    if (silent) return;
    ['am_accent_color', `am_accent_color_${currentUser.id}`].forEach(k => localStorage.removeItem(k));
    ThemeEngine.clearAccent();
    document.querySelectorAll('.color-circle').forEach(c => c.classList.remove('active'));
    if ((localStorage.getItem('am_theme_mode') || 'dark') !== 'dark') setThemeMode('dark', true);
    markThemeUnsaved();
    showToast(`Dark style → ${DARK_STYLE_NAMES[name]}`, false);
  }

  function onCustomThemeChange() {
    const bg = document.getElementById('custom-theme-bg').value;
    const text = document.getElementById('custom-theme-text').value;

    ThemeEngine.applyCustomTheme(bg, text);

    localStorage.setItem(`am_custom_bg_${currentUser.id}`, bg);
    localStorage.setItem('am_custom_bg', bg);
    localStorage.setItem(`am_custom_text_${currentUser.id}`, text);
    localStorage.setItem('am_custom_text', text);
    markThemeUnsaved();
  }

  function setAccentColor(hexCode, element) {
    document.querySelectorAll('.color-circle').forEach(c => c.classList.remove('active'));
    if (element) element.classList.add('active');

    ThemeEngine.applyAccentColor(hexCode);

    localStorage.setItem(`am_accent_color_${currentUser.id}`, hexCode);
    localStorage.setItem('am_accent_color', hexCode);
    markThemeUnsaved();
    showToast("Accent color applied!", false);
  }

  function onCustomColorPick(hexCode) {
    ThemeEngine.applyAccentColor(hexCode);
    localStorage.setItem(`am_accent_color_${currentUser.id}`, hexCode);
    localStorage.setItem('am_accent_color', hexCode);
    
    // Remove active state from preset circles
    document.querySelectorAll('.color-circle').forEach(c => c.classList.remove('active'));
    markThemeUnsaved();
    showToast("Custom accent applied!", false);
  }

  // Interactive 2FA Mock Setup
  // Retained for old callers; these controls never provided server security.
  function toggleTwoFactor() { showToast('Two-factor authentication is not available.', true); }
  function verifyTwoFactor() { showToast('Two-factor authentication is not available.', true); }
  function revokeSession() { showToast('Remote session revocation is not available.', true); }
  function renderSessions() {
    const container = document.getElementById('sessions-list');
    if (container) container.innerHTML = '<p>You are signed in on this browser.</p><button class="btn btn-secondary btn-sm" onclick="AuthFeature.logout()">Sign out this browser</button>';
  }

  // Save localized configuration variables
  function saveNotifPref() {
    const weeklyDigest = document.getElementById('notif-email-digest').checked;
    const projectShared = document.getElementById('notif-email-shared').checked;
    const pushExport = document.getElementById('notif-push-export').checked;
    const pushServer = document.getElementById('notif-push-server').checked;

    const notifObj = { weeklyDigest, projectShared, pushExport, pushServer };
    localStorage.setItem(`am_notif_${currentUser.id}`, JSON.stringify(notifObj));
    showToast("Notification preferences updated.", false);
  }

  // dynamic multi-language text replacement
  function onLanguageChange(lang) {
    localStorage.setItem(`am_language_${currentUser.id}`, lang);
    applyLanguageTranslations(lang);
    showToast(`Display Language set to ${lang.toUpperCase()}!`, false);
  }

  function applyLanguageTranslations(lang) {
    const dict = translations[lang] || translations['en'];

    // Update panel titles
    const profileTitle = document.getElementById('txt-profile-title');
    const themeTitle = document.getElementById('txt-theme-title');
    const securityTitle = document.getElementById('txt-security-title');
    const notificationsTitle = document.getElementById('txt-notifications-title');
    const languageTitle = document.getElementById('txt-language-title');
    const layoutTitle = document.getElementById('txt-layout-title');
    const dangerTitle = document.getElementById('txt-danger-title');

    if (profileTitle) profileTitle.textContent = dict.profile;
    if (themeTitle) themeTitle.textContent = dict.theme;
    if (securityTitle) securityTitle.textContent = dict.security;
    if (notificationsTitle) notificationsTitle.textContent = dict.notifications;
    if (languageTitle) languageTitle.textContent = dict.language;
    if (layoutTitle) layoutTitle.textContent = dict.layout;
    if (dangerTitle) dangerTitle.textContent = dict.danger;

    // Update navigation items
    const navProfile = document.getElementById('nav-btn-profile');
    const navTheme = document.getElementById('nav-btn-theme');
    const navSecurity = document.getElementById('nav-btn-security');
    const navNotifications = document.getElementById('nav-btn-notifications');
    const navLanguage = document.getElementById('nav-btn-language');
    const navLayout = document.getElementById('nav-btn-layout');
    const navDanger = document.getElementById('nav-btn-danger');

    if (navProfile) navProfile.innerHTML = `<i class="fas fa-user-circle"></i> ${dict.profile}`;
    if (navTheme) navTheme.innerHTML = `<i class="fas fa-palette"></i> ${dict.theme}`;
    if (navSecurity) navSecurity.innerHTML = `<i class="fas fa-lock"></i> ${dict.security}`;
    if (navNotifications) navNotifications.innerHTML = `<i class="fas fa-bell"></i> ${dict.notifications}`;
    if (navLanguage) navLanguage.innerHTML = `<i class="fas fa-globe"></i> ${dict.language}`;
    if (navLayout) navLayout.innerHTML = `<i class="fas fa-columns"></i> ${dict.layout}`;
    if (navDanger) navDanger.innerHTML = `<i class="fas fa-trash-alt"></i> ${dict.danger}`;
  }

  // Display Spacing density layouts
  function setLayoutMode(mode) {
    document.querySelectorAll('.layout-card').forEach(c => c.classList.remove('active'));
    const targetCard = document.getElementById('layout-mode-' + mode);
    if (targetCard) targetCard.classList.add('active');

    ThemeEngine.setLayoutMode(mode);

    localStorage.setItem(`am_layout_mode_${currentUser.id}`, mode);
    localStorage.setItem('am_layout_mode', mode);
    showToast(`Spacing Layout set to ${mode.toUpperCase()}!`, false);
  }

  // Reset Storage back to default system values
  async function restoreSystemDefaults() {
    if (!await UI.confirm({ title: 'Restore default settings?', confirmText: 'Restore defaults',
      message: 'All custom colors, layout density, and notification selections will be reset.' })) return;

    // Clear local storage keys
    const keysToRemove = [
      `am_theme_mode_${currentUser.id}`,
      `am_accent_color_${currentUser.id}`,
      `am_notif_${currentUser.id}`,
      `am_language_${currentUser.id}`,
      `am_layout_mode_${currentUser.id}`,
      `am_avatar_${currentUser.id}`,
      `am_bio_${currentUser.id}`,
      `am_phone_${currentUser.id}`,
      `am_2fa_${currentUser.id}`,
      `am_custom_bg_${currentUser.id}`,
      `am_custom_bg`,
      `am_custom_text_${currentUser.id}`,
      `am_custom_text`,
      'am_theme_mode',
      'am_accent_color',
      'am_dark_style',
      `am_dark_style_${currentUser.id}`,
      'am_layout_mode',
      `am_card_bg_${currentUser.id}`,
      `am_card_bg`,
      `am_card_tx_${currentUser.id}`,
      `am_card_tx`,
      `am_card_border_${currentUser.id}`,
      `am_card_border`,
      `am_card_radius_${currentUser.id}`,
      `am_card_radius`,
      `am_card_shadow_${currentUser.id}`,
      `am_card_shadow`,
      `am_card_padding_${currentUser.id}`,
      `am_card_padding`,
      `am_card_hover_${currentUser.id}`,
      `am_card_hover`,
      `am_card_opacity_${currentUser.id}`,
      `am_card_opacity`
    ];
    keysToRemove.forEach(k => localStorage.removeItem(k));

    // Reset default visuals
    ThemeEngine.setDarkStyle('classic');
    markDarkStyle('classic');
    ThemeEngine.applyAccentColor('#00e5b0');
    ThemeEngine.setThemeMode('dark');
    ThemeEngine.setLayoutMode('expanded');
    ThemeEngine.clearCardCustomization();

    // UI elements update
    document.querySelectorAll('.theme-mode-card').forEach(c => c.classList.remove('active'));
    const darkCard = document.getElementById('theme-mode-dark');
    if (darkCard) darkCard.classList.add('active');

    document.querySelectorAll('.layout-card').forEach(c => c.classList.remove('active'));
    const expandedCard = document.getElementById('layout-mode-expanded');
    if (expandedCard) expandedCard.classList.add('active');

    document.querySelectorAll('.color-circle').forEach(c => c.classList.remove('active'));
    const tealCircle = document.querySelector('.color-circle[style*="00e5b0"]');
    if (tealCircle) tealCircle.classList.add('active');

    const defaultInitial = (currentUser.username ? currentUser.username[0] : 'U').toUpperCase();
    applyAvatarDisplay(defaultInitial);

    // Reset 2FA
    const twofaSwitch = document.getElementById('twofa-switch');
    if (twofaSwitch) twofaSwitch.checked = false;


    // Reset Language
    const langSelect = document.getElementById('language-select');
    if (langSelect) langSelect.value = 'en';
    applyLanguageTranslations('en');

    // Reset Notification switches
    ['notif-email-digest', 'notif-email-shared', 'notif-push-export'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.checked = true;
    });
    const pushServer = document.getElementById('notif-push-server');
    if (pushServer) pushServer.checked = false;

    // Reset Card Customization values in UI
    const cardBgEl = document.getElementById('card-custom-bg');
    const cardTxEl = document.getElementById('card-custom-tx');
    const cardBorderEl = document.getElementById('card-custom-border');
    const cardRadiusEl = document.getElementById('card-custom-radius');
    const cardShadowEl = document.getElementById('card-custom-shadow');
    const cardPaddingEl = document.getElementById('card-custom-padding');
    const cardHoverEl = document.getElementById('card-custom-hover');
    const cardOpacityEl = document.getElementById('card-custom-opacity');
    const cardOpacityValEl = document.getElementById('card-custom-opacity-val');

    if (cardBgEl) cardBgEl.value = '#16161f';
    if (cardTxEl) cardTxEl.value = '#e4e4e7';
    if (cardBorderEl) cardBorderEl.value = '#2d2d3d';
    if (cardRadiusEl) cardRadiusEl.value = '12px';
    if (cardShadowEl) cardShadowEl.value = 'medium';
    if (cardPaddingEl) cardPaddingEl.value = '1.5rem';
    if (cardHoverEl) cardHoverEl.value = 'both';
    if (cardOpacityEl) cardOpacityEl.value = '1.0';
    if (cardOpacityValEl) cardOpacityValEl.textContent = '100%';

    const preview = document.getElementById('live-preview-card');
    if (preview) {
      preview.style.background = '#16161f';
      preview.style.color = '#e4e4e7';
      preview.style.borderColor = '#2d2d3d';
      preview.style.borderRadius = '12px';
      preview.style.padding = '1.5rem';
      preview.style.opacity = '1.0';
    }

    showToast("⚙️ Restore Complete. System defaulted.", false);
  }

  // Account Termination API Hook
  async function deleteAccount() {
    if (!await UI.confirm({ title: 'Delete your account permanently?', danger: true, confirmText: 'Continue',
      message: 'This wipes your profile, owned workspaces, datasets and annotations. This cannot be undone.' })) return;
    if (!await UI.confirm({ title: 'Final confirmation', danger: true, confirmText: 'Delete my account',
      message: 'Are you absolutely sure? Your account and its data will be deleted now.' })) return;

    try {
      const token = localStorage.getItem('am_token') || sessionStorage.getItem('am_token');
      const res = await fetch('/api/auth/delete-account', {
        method: 'DELETE',
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });

      if (!res.ok) {
        showToast('Error removing account.', true);
        return;
      }

      // Wipes local tokens and redirect to login
      localStorage.removeItem('am_token');
      sessionStorage.removeItem('am_token');
      showToast("Account removed.", false);
      window.location.href = '/login';

    } catch (e) {
      console.error(e);
      showToast('Error sending account removal request.', true);
    }
  }

  // Toasts come from the shared UI.toast (static/js/core/ui.js, styled in
  // components.css). It inserts text, never HTML.
  function showToast(msg, isError) {
    UI.toast(msg, isError ? 'error' : 'success');
  }

  // Loading preferences from localstorage on initialization
  function loadSavedPreferences() {
    const uid = currentUser.id;

    // Theme Mode — same precedence as theme.js (global key first). Reading
    // the per-user key first re-applied a stale mode and, because
    // setThemeMode writes both keys, flipped the whole app back to it.
    const savedTheme = localStorage.getItem('am_theme_mode') || localStorage.getItem(`am_theme_mode_${uid}`);
    if (savedTheme) {
      setThemeMode(savedTheme, true);
    }

    const savedStyle = localStorage.getItem('am_dark_style') || localStorage.getItem(`am_dark_style_${uid}`) || 'classic';
    markDarkStyle(savedStyle);
    if (!savedTheme) { const r = document.getElementById('dark-style-row'); if (r) r.style.display = ''; }

    const customBg = localStorage.getItem('am_custom_bg') || localStorage.getItem(`am_custom_bg_${uid}`);
    const customText = localStorage.getItem('am_custom_text') || localStorage.getItem(`am_custom_text_${uid}`);
    const bgPicker = document.getElementById('custom-theme-bg');
    const textPicker = document.getElementById('custom-theme-text');
    if (bgPicker && customBg) bgPicker.value = customBg;
    if (textPicker && customText) textPicker.value = customText;

    // Color picker
    const savedAccent = localStorage.getItem('am_accent_color') || localStorage.getItem(`am_accent_color_${uid}`);
    if (savedAccent) {
      // set active circle class
      document.querySelectorAll('.color-circle').forEach(c => {
        if (c.style.background.includes(savedAccent) || c.getAttribute('title')?.toLowerCase().includes(savedAccent)) {
          c.classList.add('active');
        } else {
          c.classList.remove('active');
        }
      });
      ThemeEngine.applyAccentColor(savedAccent);
    }

    // Avatar Selection
    const savedAvatar = localStorage.getItem(`am_avatar_${uid}`);
    if (savedAvatar) {
      applyAvatarDisplay(savedAvatar);
    }

    // Clear the obsolete simulated flag; it never enabled server-side 2FA.
    localStorage.removeItem(`am_2fa_${uid}`);

    // Notification Toggles
    const savedNotifs = localStorage.getItem(`am_notif_${uid}`);
    if (savedNotifs) {
      try {
        const notifObj = JSON.parse(savedNotifs);
        const digest = document.getElementById('notif-email-digest');
        const shared = document.getElementById('notif-email-shared');
        const pExport = document.getElementById('notif-push-export');
        const pServer = document.getElementById('notif-push-server');

        if (digest) digest.checked = !!notifObj.weeklyDigest;
        if (shared) shared.checked = !!notifObj.projectShared;
        if (pExport) pExport.checked = !!notifObj.pushExport;
        if (pServer) pServer.checked = !!notifObj.pushServer;
      } catch (e) {
        console.error("Failed to parse notifications storage settings", e);
      }
    }

    // Language Dropdown
    const savedLang = localStorage.getItem(`am_language_${uid}`);
    const langSelect = document.getElementById('language-select');
    if (savedLang) {
      if (langSelect) langSelect.value = savedLang;
      applyLanguageTranslations(savedLang);
    }

    // Layout compact preference
    const savedLayout = localStorage.getItem('am_layout_mode') || localStorage.getItem(`am_layout_mode_${uid}`);
    if (savedLayout) {
      setLayoutMode(savedLayout);
    }

    // Card Customizations
    const cardBg = localStorage.getItem('am_card_bg') || localStorage.getItem(`am_card_bg_${uid}`);
    const cardTx = localStorage.getItem('am_card_tx') || localStorage.getItem(`am_card_tx_${uid}`);
    const cardBorder = localStorage.getItem('am_card_border') || localStorage.getItem(`am_card_border_${uid}`);
    const cardRadius = localStorage.getItem('am_card_radius') || localStorage.getItem(`am_card_radius_${uid}`);
    const cardShadow = localStorage.getItem('am_card_shadow') || localStorage.getItem(`am_card_shadow_${uid}`);
    const cardPadding = localStorage.getItem('am_card_padding') || localStorage.getItem(`am_card_padding_${uid}`);
    const cardHover = localStorage.getItem('am_card_hover') || localStorage.getItem(`am_card_hover_${uid}`);
    const cardOpacity = localStorage.getItem('am_card_opacity') || localStorage.getItem(`am_card_opacity_${uid}`);

    const cardBgEl = document.getElementById('card-custom-bg');
    const cardTxEl = document.getElementById('card-custom-tx');
    const cardBorderEl = document.getElementById('card-custom-border');
    const cardRadiusEl = document.getElementById('card-custom-radius');
    const cardShadowEl = document.getElementById('card-custom-shadow');
    const cardPaddingEl = document.getElementById('card-custom-padding');
    const cardHoverEl = document.getElementById('card-custom-hover');
    const cardOpacityEl = document.getElementById('card-custom-opacity');
    const cardOpacityValEl = document.getElementById('card-custom-opacity-val');

    if (cardBgEl && cardBg) cardBgEl.value = cardBg;
    if (cardTxEl && cardTx) cardTxEl.value = cardTx;
    if (cardBorderEl && cardBorder) cardBorderEl.value = cardBorder;
    if (cardRadiusEl && cardRadius) cardRadiusEl.value = cardRadius;
    if (cardShadowEl && cardShadow) cardShadowEl.value = cardShadow;
    if (cardPaddingEl && cardPadding) cardPaddingEl.value = cardPadding;
    if (cardHoverEl && cardHover) cardHoverEl.value = cardHover;
    if (cardOpacityEl && cardOpacity) {
      cardOpacityEl.value = cardOpacity;
      if (cardOpacityValEl) cardOpacityValEl.textContent = `${Math.round(cardOpacity * 100)}%`;
    }

    const preview = document.getElementById('live-preview-card');
    if (preview) {
      if (cardBg) preview.style.background = cardBg;
      if (cardTx) preview.style.color = cardTx;
      if (cardBorder) preview.style.borderColor = cardBorder;
      if (cardRadius) preview.style.borderRadius = cardRadius;
      if (cardPadding) preview.style.padding = cardPadding;
      if (cardOpacity) preview.style.opacity = cardOpacity;
    }
  }

  function onCardCustomChange() {
    const bg = document.getElementById('card-custom-bg').value;
    const tx = document.getElementById('card-custom-tx').value;
    const border = document.getElementById('card-custom-border').value;
    const radius = document.getElementById('card-custom-radius').value;
    const shadow = document.getElementById('card-custom-shadow').value;
    const padding = document.getElementById('card-custom-padding').value;
    const hover = document.getElementById('card-custom-hover').value;
    const opacity = document.getElementById('card-custom-opacity').value;

    const opacityValEl = document.getElementById('card-custom-opacity-val');
    if (opacityValEl) opacityValEl.textContent = `${Math.round(opacity * 100)}%`;

    const opts = { bg, tx, border, radius, shadow, padding, hover, opacity };
    ThemeEngine.applyCardCustomization(opts);

    // Save to localStorage
    const uid = currentUser.id;
    localStorage.setItem(`am_card_bg`, bg);
    localStorage.setItem(`am_card_bg_${uid}`, bg);
    localStorage.setItem(`am_card_tx`, tx);
    localStorage.setItem(`am_card_tx_${uid}`, tx);
    localStorage.setItem(`am_card_border`, border);
    localStorage.setItem(`am_card_border_${uid}`, border);
    localStorage.setItem(`am_card_radius`, radius);
    localStorage.setItem(`am_card_radius_${uid}`, radius);
    localStorage.setItem(`am_card_shadow`, shadow);
    localStorage.setItem(`am_card_shadow_${uid}`, shadow);
    localStorage.setItem(`am_card_padding`, padding);
    localStorage.setItem(`am_card_padding_${uid}`, padding);
    localStorage.setItem(`am_card_hover`, hover);
    localStorage.setItem(`am_card_hover_${uid}`, hover);
    localStorage.setItem(`am_card_opacity`, opacity);
    localStorage.setItem(`am_card_opacity_${uid}`, opacity);

    // Update live preview card directly
    const preview = document.getElementById('live-preview-card');
    if (preview) {
      preview.style.background = bg;
      preview.style.color = tx;
      preview.style.borderColor = border;
      preview.style.borderRadius = radius;
      preview.style.padding = padding;
      preview.style.opacity = opacity;
    }
    markThemeUnsaved();
  }

  // Mark unsaved theme changes with pulsing dot indicator
  function markThemeUnsaved() {
    const dot = document.getElementById('theme-unsaved-dot');
    const status = document.getElementById('theme-save-status');
    const btn = document.getElementById('btn-save-theme');
    if (dot) dot.style.display = 'inline-block';
    if (status) {
      status.textContent = 'Unsaved changes — click Save to confirm.';
      status.style.color = 'var(--accent)';
    }
    if (btn) btn.style.boxShadow = '0 0 14px var(--accent-glow)';
  }

  function markThemeSaved() {
    const dot = document.getElementById('theme-unsaved-dot');
    const status = document.getElementById('theme-save-status');
    const btn = document.getElementById('btn-save-theme');
    if (dot) dot.style.display = 'none';
    if (status) {
      status.textContent = '✓ Theme saved — changes apply globally across all pages.';
      status.style.color = 'var(--tx2)';
    }
    if (btn) btn.style.boxShadow = 'none';
  }

  // Explicit save - confirms all current theme state into localStorage
  function saveThemeChanges() {
    const uid = currentUser.id;
    const mode = localStorage.getItem('am_theme_mode') || 'dark';
    const accent = localStorage.getItem('am_accent_color') || '#00e5b0';
    const bg = localStorage.getItem('am_custom_bg') || '';
    const text = localStorage.getItem('am_custom_text') || '';

    // Re-persist all theme keys under user ID
    localStorage.setItem(`am_theme_mode_${uid}`, mode);
    localStorage.setItem(`am_accent_color_${uid}`, accent);
    localStorage.setItem(`am_dark_style_${uid}`, localStorage.getItem('am_dark_style') || 'classic');
    if (bg) localStorage.setItem(`am_custom_bg_${uid}`, bg);
    if (text) localStorage.setItem(`am_custom_text_${uid}`, text);

    // Re-persist card customization under user ID
    const keys = ['card_bg','card_tx','card_border','card_radius','card_shadow','card_padding','card_hover','card_opacity'];
    keys.forEach(k => {
      const v = localStorage.getItem(`am_${k}`);
      if (v) localStorage.setItem(`am_${k}_${uid}`, v);
    });

    markThemeSaved();
    showToast('✓ Theme saved — active on all pages!', false);
  }

  // Reset only theme/color without touching profile/notif/security
  async function restoreThemeDefaults() {
    if (!await UI.confirm({ title: 'Reset theme?', confirmText: 'Reset theme',
      message: 'Reset theme to default Dark Mode + Teal accent?\nCard customizations will also reset.' })) return;
    const uid = currentUser.id;

    // Clear theme keys
    ['am_theme_mode','am_accent_color','am_custom_bg','am_custom_text','am_dark_style',`am_dark_style_${uid}`,
     `am_theme_mode_${uid}`,`am_accent_color_${uid}`,`am_custom_bg_${uid}`,`am_custom_text_${uid}`,
     'am_card_bg','am_card_tx','am_card_border','am_card_radius','am_card_shadow','am_card_padding','am_card_hover','am_card_opacity',
     `am_card_bg_${uid}`,`am_card_tx_${uid}`,`am_card_border_${uid}`,`am_card_radius_${uid}`,
     `am_card_shadow_${uid}`,`am_card_padding_${uid}`,`am_card_hover_${uid}`,`am_card_opacity_${uid}`
    ].forEach(k => localStorage.removeItem(k));

    // Apply defaults
    ThemeEngine.setDarkStyle('classic');
    markDarkStyle('classic');
    ThemeEngine.applyAccentColor('#00e5b0');
    ThemeEngine.setThemeMode('dark');
    ThemeEngine.clearCardCustomization();

    // Reset UI controls
    document.querySelectorAll('.theme-mode-card').forEach(c => c.classList.remove('active'));
    const darkCard = document.getElementById('theme-mode-dark');
    if (darkCard) darkCard.classList.add('active');
    document.querySelectorAll('.color-circle').forEach(c => c.classList.remove('active'));
    const tealCircle = document.querySelector('.color-circle[style*="00e5b0"]');
    if (tealCircle) tealCircle.classList.add('active');

    // Reset card controls
    const defaults = { 'card-custom-bg':'#16161f','card-custom-tx':'#e4e4e7','card-custom-border':'#2d2d3d',
      'card-custom-radius':'12px','card-custom-shadow':'medium','card-custom-padding':'1.5rem',
      'card-custom-hover':'both','card-custom-opacity':'1.0' };
    Object.entries(defaults).forEach(([id, val]) => {
      const el = document.getElementById(id);
      if (el) el.value = val;
    });
    const opacityValEl = document.getElementById('card-custom-opacity-val');
    if (opacityValEl) opacityValEl.textContent = '100%';

    const preview = document.getElementById('live-preview-card');
    if (preview) {
      preview.style.background = '#16161f';
      preview.style.color = '#e4e4e7';
      preview.style.borderColor = '#2d2d3d';
      preview.style.borderRadius = '12px';
      preview.style.padding = '1.5rem';
      preview.style.opacity = '1.0';
    }

    markThemeSaved();
    showToast('Theme reset to defaults!', false);
  }


  /* =======================================================================
     WORKSPACE SETTINGS
     -----------------------------------------------------------------------
     One home for everything workspace-scoped. All of it already existed via
     the dashboard header / share panel / members page — this panel just puts
     it in Settings, where people look for it.

     Every control is gated on YOUR role in the SELECTED workspace, so the
     panel re-renders on each change of the picker. The gating mirrors the API
     exactly (owner: rename / invite / roles / remove / delete), so the UI
     never offers an action the server will refuse.
  ======================================================================= */

  let _wsList = [];
  let _wsCur  = null;   // selected workspace object, including your role

  async function loadWorkspaces() {
    const pick = document.getElementById('ws-picker');
    if (!pick) return;
    try {
      const r = await API.get('/api/workspaces');
      _wsList = await r.json();
    } catch (e) { _wsList = []; }

    if (!_wsList.length) {
      pick.innerHTML = '<option value="">No workspaces yet</option>';
      _renderWorkspace(null);
      return;
    }
    pick.innerHTML = _wsList.map(w =>
      '<option value="' + w.id + '">' + escapeHtml(w.name) + ' \u2014 ' + w.role + '</option>').join('');

    // Default to the workspace the dashboard was last on, so Settings opens on
    // the one the user is actually working in.
    const last = parseInt(localStorage.getItem('am_last_ws'));
    const ws   = _wsList.find(w => w.id === last) || _wsList[0];
    pick.value = ws.id;
    selectWorkspace(ws.id);
  }

  function selectWorkspace(id) {
    _wsCur = _wsList.find(w => String(w.id) === String(id)) || null;
    _renderWorkspace(_wsCur);
  }

  async function _renderWorkspace(ws) {
    const ov     = document.getElementById('ws-overview');
    const rename = document.getElementById('ws-rename-card');
    const invite = document.getElementById('ws-invite-block');
    const danger = document.getElementById('ws-danger-card');
    const list   = document.getElementById('ws-member-list');
    if (!ov) return;

    if (!ws) {
      ov.innerHTML = '<div class="ws-loading">Create a workspace from the dashboard first.</div>';
      [rename, invite, danger].forEach(el => { if (el) el.style.display = 'none'; });
      if (list) list.innerHTML = '';
      return;
    }

    const isOwner = ws.role === 'owner';
    if (rename) rename.style.display = isOwner ? '' : 'none';
    if (invite) invite.style.display = isOwner ? '' : 'none';
    if (danger) danger.style.display = isOwner ? '' : 'none';

    const rn = document.getElementById('ws-rename-input');
    if (rn) rn.value = ws.name || '';
    const dn = document.getElementById('ws-danger-name');
    if (dn) dn.textContent = ws.name || 'this workspace';
    setError('ws-rename-error', ''); setSuccess('ws-rename-success', '');
    setError('ws-invite-error', ''); setSuccess('ws-invite-success', '');

    // Project count needs its own call — /api/workspaces does not carry it.
    let projects = '\u2014';
    try {
      const r = await API.get('/api/workspaces/' + ws.id + '/projects?workspace_id=' + ws.id);
      if (r && r.ok) projects = (await r.json()).length;
    } catch (e) { /* leave as em-dash */ }

    ov.innerHTML =
      '<div class="ws-stat"><span class="ws-stat-lbl">Workspace ID</span>' +
        '<span class="ws-stat-val mono">' + escapeHtml(ws.public_id || '\u2014') + '</span></div>' +
      '<div class="ws-stat"><span class="ws-stat-lbl">Your role</span>' +
        '<span class="ws-stat-val"><span class="badge badge-' + ws.role + '">' + ws.role + '</span></span></div>' +
      '<div class="ws-stat"><span class="ws-stat-lbl">Projects</span>' +
        '<span class="ws-stat-val">' + projects + '</span></div>' +
      '<div class="ws-stat"><span class="ws-stat-lbl">Members</span>' +
        '<span class="ws-stat-val">' + (ws.member_count != null ? ws.member_count : '\u2014') + '</span></div>' +
      '<div class="ws-stat"><span class="ws-stat-lbl">Created</span>' +
        '<span class="ws-stat-val">' + (ws.created_at ? formatDate(ws.created_at) : '\u2014') + '</span></div>';

    _renderMembers(ws);
  }

  async function _renderMembers(ws) {
    const el = document.getElementById('ws-member-list');
    if (!el) return;
    el.innerHTML = '<div class="ws-loading">Loading\u2026</div>';
    let members = [];
    try {
      const r = await API.get('/api/workspaces/' + ws.id + '/members?workspace_id=' + ws.id);
      if (!r || !r.ok) throw new Error('failed');
      members = await r.json();
    } catch (e) {
      el.innerHTML = '<div class="ws-loading">Could not load members.</div>';
      return;
    }

    const isOwner = ws.role === 'owner';
    el.innerHTML = members.map(m => {
      const isSelf = currentUser && String(m.user_id) === String(currentUser.id);
      const sel = (r) => (m.role === r ? ' selected' : '');
      const ctrl = (isOwner && !isSelf)
        ? '<select class="form-select ws-role-select" onchange="SettingsPage.setMemberRole(' + m.user_id + ', this.value)">' +
            '<option value="owner"' + sel('owner') + '>Owner</option>' +
            '<option value="editor"' + sel('editor') + '>Editor</option>' +
            '<option value="viewer"' + sel('viewer') + '>Viewer</option>' +
          '</select>'
        : '<span class="badge badge-' + m.role + '">' + m.role + '</span>';
      const rm = (isOwner && !isSelf)
        ? '<button class="ws-member-remove" title="Remove from workspace" onclick="SettingsPage.removeMember(' +
            m.user_id + ', ' + JSON.stringify(String(m.username)).replace(/"/g, '&quot;') + ')">' +
            '<i class="fas fa-user-minus"></i></button>'
        : '';
      return '<div class="ws-member-row">' +
        '<div class="ws-member-avatar">' + (m.username || '?')[0].toUpperCase() + '</div>' +
        '<div class="ws-member-id">' +
          '<div class="ws-member-name">' + escapeHtml(m.username) +
            (isSelf ? ' <span class="ws-you">you</span>' : '') + '</div>' +
          '<div class="ws-member-email">' + escapeHtml(m.email || '') + '</div>' +
        '</div>' +
        '<div class="ws-member-actions">' + ctrl + rm + '</div>' +
      '</div>';
    }).join('') || '<div class="ws-loading">No members.</div>';
  }

  async function renameWorkspace() {
    if (!_wsCur) return;
    const name = document.getElementById('ws-rename-input').value.trim();
    setError('ws-rename-error', ''); setSuccess('ws-rename-success', '');
    if (!name) { setError('ws-rename-error', 'Name required'); return; }
    const r = await API.put('/api/workspaces/' + _wsCur.id + '/rename',
                            { name: name, workspace_id: _wsCur.id });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) { setError('ws-rename-error', d.error || 'Rename failed'); return; }
    setSuccess('ws-rename-success', 'Workspace renamed');
    const keep = _wsCur.id;
    await loadWorkspaces();
    const pick = document.getElementById('ws-picker');
    if (pick) { pick.value = keep; selectWorkspace(keep); }
  }

  async function inviteMember() {
    if (!_wsCur) return;
    const email = document.getElementById('ws-invite-email').value.trim();
    const role  = document.getElementById('ws-invite-role').value;
    setError('ws-invite-error', ''); setSuccess('ws-invite-success', '');
    if (!email) { setError('ws-invite-error', 'Enter an email address'); return; }
    const r = await API.post('/api/workspaces/' + _wsCur.id + '/invite',
                             { email: email, role: role, workspace_id: _wsCur.id });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) { setError('ws-invite-error', d.error || 'Invite failed'); return; }
    setSuccess('ws-invite-success', email + ' added as ' + role);
    document.getElementById('ws-invite-email').value = '';
    _renderMembers(_wsCur);
  }

  async function setMemberRole(userId, role) {
    if (!_wsCur) return;
    await API.put('/api/workspaces/' + _wsCur.id + '/members/' + userId + '/role',
                  { role: role, workspace_id: _wsCur.id });
    _renderMembers(_wsCur);
  }

  async function removeMember(userId, name) {
    if (!_wsCur) return;
    if (!await UI.confirm({ title: 'Remove member?', danger: true, confirmText: 'Remove',
      message: 'Remove ' + name + ' from "' + _wsCur.name + '"?' })) return;
    await API.del('/api/workspaces/' + _wsCur.id + '/members/' + userId,
                  { workspace_id: _wsCur.id });
    _renderMembers(_wsCur);
  }

  async function deleteWorkspace() {
    if (!_wsCur) return;
    // Two-step on purpose: this destroys every project and annotation inside
    // and the API has no undo, so the name must be typed, not just OK-clicked.
    const typed = prompt(
      'This deletes "' + _wsCur.name + '" and ALL its projects, images and annotations.\n' +
      'This cannot be undone.\n\nType the workspace name to confirm:');
    if (typed === null) return;
    if (typed.trim() !== _wsCur.name) { UI.toast('Name did not match \u2014 nothing was deleted.', 'error'); return; }
    const r = await API.del('/api/workspaces/' + _wsCur.id, { workspace_id: _wsCur.id });
    if (!r || !r.ok) { UI.toast('Failed to delete workspace.', 'error'); return; }
    try {
      if (parseInt(localStorage.getItem('am_last_ws')) === _wsCur.id) {
        localStorage.removeItem('am_last_ws');
      }
    } catch (e) { /* ignore */ }
    showToast('Workspace deleted', false);
    _wsCur = null;
    await loadWorkspaces();
  }

  return {
    init,
    switchTab,
    setPresetAvatar,
    resetAvatarInitials,
    saveProfile,
    changePassword,
    setThemeMode,
    setDarkStyle,
    setAccentColor,
    onCustomColorPick,
    onCustomThemeChange,
    toggleTwoFactor,
    verifyTwoFactor,
    revokeSession,
    saveNotifPref,
    onLanguageChange,
    setLayoutMode,
    restoreSystemDefaults,
    deleteAccount,
    onCardCustomChange,
    saveThemeChanges,
    restoreThemeDefaults,
    loadWorkspaces,
    selectWorkspace,
    renameWorkspace,
    inviteMember,
    setMemberRole,
    removeMember,
    deleteWorkspace
  };
})();
