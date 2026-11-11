/**
 * auth.js — login check, logout, requireAuth
 */
const AuthFeature = (() => {

  async function getUser() {
    const token = localStorage.getItem('am_token') || sessionStorage.getItem('am_token');
    if (!token) return null;
    try {
      const res = await fetch('/api/auth/me', {
        headers: {
          'Authorization': 'Bearer ' + (localStorage.getItem('am_token') || sessionStorage.getItem('am_token') || ''),
          'Content-Type': 'application/json'
        }
      });
      if (res.status === 401) {
        localStorage.removeItem('am_token');
    sessionStorage.removeItem('am_token');
        return null;
      }
      if (!res.ok) return null;
      return await res.json();
    } catch (e) {
      console.error('getUser error:', e);
      return null;
    }
  }

  async function requireAuth() {
    const user = await getUser();
    if (!user) {
      window.location.href = '/login';
      return null;
    }
    State.set('user', user);
    return user;
  }

  async function logout() {
    try {
      await fetch('/api/auth/logout', {
        method: 'POST',
        headers: { 'Authorization': 'Bearer ' + (localStorage.getItem('am_token') || '') }
      });
    } catch (e) { /* ignore */ }
    localStorage.removeItem('am_token');
    sessionStorage.removeItem('am_token');
    window.location.href = '/login';
  }

  return { getUser, requireAuth, logout };
})();
