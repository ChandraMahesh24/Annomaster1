import { useState } from 'react';
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { useMe, useLogout } from '../api/auth';
import { useTheme } from '../theme/ThemeProvider';

/**
 * Shared navbar — ports layout/navbar.html markup (.navbar / .account-btn /
 * .account-dropdown) so the ported layout.css styles it exactly like the
 * original. Theme toggle added to the dropdown.
 */
export function AppLayout({ children }: { children: ReactNode }) {
  const { data: me } = useMe();
  const logout = useLogout();
  const { theme, toggle } = useTheme();
  const [open, setOpen] = useState(false);
  const initial = (me?.username || 'U')[0].toUpperCase();

  return (
    <>
      <nav className="navbar">
        <div className="navbar-brand">
          <Link to="/" className="brand-link">
            <span className="brand-icon">⬡</span>
            <span className="brand-name">Anno<span className="brand-accent">Master</span></span>
          </Link>
        </div>
        <div className="navbar-center" />
        <div className="navbar-actions">
          <div className={`account-btn${open ? ' open' : ''}`} onClick={() => setOpen((o) => !o)}
               onBlur={() => setTimeout(() => setOpen(false), 150)} tabIndex={0}>
            <div className="user-avatar">{initial}</div>
            <span className="user-name">{me?.username}</span>
            <i className="fas fa-chevron-down nav-chevron" />
            <div className="account-dropdown">
              <div className="account-dropdown-header">
                <div className="account-dropdown-avatar">{initial}</div>
                <div>
                  <div className="account-dropdown-name">{me?.username}</div>
                  <div className="account-dropdown-email">{me?.email}</div>
                </div>
              </div>
              <div className="account-dropdown-divider" />
              <button className="account-dropdown-item" onClick={(e) => { e.stopPropagation(); toggle(); }}>
                <i className="fas fa-circle-half-stroke" /> {theme === 'dark' ? 'Light' : 'Dark'} theme
              </button>
              <Link className="account-dropdown-item" to="/settings">
                <i className="fas fa-user-cog" /> Account Settings
              </Link>
              <Link className="account-dropdown-item" to="/">
                <i className="fas fa-th-large" /> Dashboard
              </Link>
              <div className="account-dropdown-divider" />
              <button className="account-dropdown-item danger" onClick={(e) => { e.stopPropagation(); logout.mutate(); }}>
                <i className="fas fa-sign-out-alt" /> Sign Out
              </button>
            </div>
          </div>
        </div>
      </nav>
      {children}
    </>
  );
}
