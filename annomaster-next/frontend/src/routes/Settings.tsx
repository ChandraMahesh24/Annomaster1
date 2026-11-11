import { useState } from 'react';
import { AppLayout } from '../components/AppLayout';
import { useMe } from '../api/auth';
import { api, ApiError } from '../api/client';
import { useTheme } from '../theme/ThemeProvider';

type Tab = 'profile' | 'theme' | 'security' | 'notifications' | 'layout' | 'danger';

/** Settings — ports pages/settings.html (.settings-wrapper sidebar + panels).
 *  Profile / Theme / Security implemented; other original tabs come in U7. */
export function Settings() {
  const { data: me } = useMe();
  const { theme, setTheme } = useTheme();
  const [tab, setTab] = useState<Tab>('profile');
  const [cur, setCur] = useState('');
  const [next, setNext] = useState('');
  const [msg, setMsg] = useState('');

  async function changePassword() {
    setMsg('');
    try {
      await api('/auth/change-password', { body: { current_password: cur, new_password: next } });
      setMsg('Password updated'); setCur(''); setNext('');
    } catch (e) { setMsg(e instanceof ApiError ? e.message : 'Failed'); }
  }

  const NAV: { id: Tab; icon: string; label: string; danger?: boolean }[] = [
    { id: 'profile', icon: 'fa-user-circle', label: 'Profile Management' },
    { id: 'theme', icon: 'fa-palette', label: 'Theme & Colors' },
    { id: 'security', icon: 'fa-lock', label: 'Security & Sessions' },
    { id: 'notifications', icon: 'fa-bell', label: 'Notifications' },
    { id: 'layout', icon: 'fa-columns', label: 'Layout Preferences' },
    { id: 'danger', icon: 'fa-trash-alt', label: 'Reset & Danger', danger: true },
  ];

  return (
    <AppLayout>
      <div className="settings-page">
        <div className="settings-wrapper">
          <aside className="settings-sidebar">
            <div className="settings-sidebar-header">
              <h2>Settings</h2>
              <p>Manage your account preferences</p>
            </div>
            <nav className="settings-nav">
              {NAV.map((n) => (
                <button key={n.id} className={`settings-nav-btn${n.danger ? ' danger-nav' : ''}${tab === n.id ? ' active' : ''}`} onClick={() => setTab(n.id)}>
                  <i className={`fas ${n.icon}`} /> {n.label}
                </button>
              ))}
            </nav>
          </aside>

          <main className="settings-main">
            {tab === 'profile' && (
              <section className="settings-panel active">
                <div className="panel-header">
                  <h2>Profile Management</h2>
                  <p>Update your personal information and public profile presence.</p>
                </div>
                <div className="profile-avatar-section">
                  <div className="avatar-large">{(me?.username || 'U')[0].toUpperCase()}</div>
                  <div className="avatar-upload-info">
                    <h4>{me?.username}</h4>
                    <p>{me?.email}</p>
                    <p style={{ fontSize: '.72rem', color: 'var(--tx3)' }}>ID {me?.public_id}</p>
                  </div>
                </div>
              </section>
            )}

            {tab === 'theme' && (
              <section className="settings-panel active">
                <div className="panel-header">
                  <h2>Theme &amp; Colors</h2>
                  <p>Choose how AnnoMaster looks. Dark is the default; light is derived.</p>
                </div>
                <div className="settings-card">
                  <div className="theme-mode-grid">
                    {(['dark', 'light'] as const).map((t) => (
                      <div key={t} className={`theme-mode-card${theme === t ? ' active' : ''}`} onClick={() => setTheme(t)}>
                        <div className={`theme-preview ${t}-preview`} />
                        <div className="section-subtitle" style={{ textTransform: 'capitalize', margin: 0 }}>{t}</div>
                      </div>
                    ))}
                  </div>
                </div>
              </section>
            )}

            {tab === 'security' && (
              <section className="settings-panel active">
                <div className="panel-header">
                  <h2>Security &amp; Sessions</h2>
                  <p>Change your password.</p>
                </div>
                <div className="settings-card">
                  <div className="form-group">
                    <label className="form-label">Current password</label>
                    <input className="form-input" type="password" value={cur} onChange={(e) => setCur(e.target.value)} />
                  </div>
                  <div className="form-group">
                    <label className="form-label">New password</label>
                    <input className="form-input" type="password" value={next} onChange={(e) => setNext(e.target.value)} />
                  </div>
                  <button className="btn btn-primary" disabled={!cur || next.length < 8} onClick={changePassword}>Update password</button>
                  {msg && <p className="text-muted" style={{ marginTop: '.5rem' }}>{msg}</p>}
                </div>
              </section>
            )}

            {tab === 'notifications' && (
              <section className="settings-panel active">
                <div className="panel-header"><h2>Notifications</h2><p>Choose what you're notified about.</p></div>
                <div className="settings-card">
                  {['Assignment updates', 'New members', 'Export ready'].map((l) => (
                    <label key={l} className="toggle-control-row" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '.6rem 0' }}>
                      <span>{l}</span>
                      <label className="switch"><input type="checkbox" defaultChecked /><span className="slider" /></label>
                    </label>
                  ))}
                </div>
              </section>
            )}

            {tab === 'layout' && (
              <section className="settings-panel active">
                <div className="panel-header"><h2>Layout Preferences</h2><p>Density of the interface.</p></div>
                <div className="settings-card">
                  <label className="toggle-control-row" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span>Compact mode</span>
                    <label className="switch">
                      <input type="checkbox" defaultChecked={document.documentElement.classList.contains('compact-mode')}
                             onChange={(e) => document.documentElement.classList.toggle('compact-mode', e.target.checked)} />
                      <span className="slider" />
                    </label>
                  </label>
                </div>
              </section>
            )}

            {tab === 'danger' && (
              <section className="settings-panel active">
                <div className="panel-header"><h2>Reset &amp; Danger</h2><p>Irreversible actions.</p></div>
                <div className="danger-zone-card">
                  <div className="danger-zone-title"><i className="fas fa-exclamation-triangle" /> Delete account</div>
                  <div className="danger-zone-desc">Permanently remove your account and all workspaces you own. This cannot be undone.</div>
                  <button className="btn btn-danger-solid" onClick={() => alert('Account deletion is not enabled in this build.')}>Delete my account</button>
                </div>
              </section>
            )}
          </main>
        </div>
      </div>
    </AppLayout>
  );
}
