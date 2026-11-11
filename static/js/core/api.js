/**
 * api.js — centralised fetch wrapper
 * Always reads JWT from localStorage and sends as Authorization: Bearer <token>
 * Redirects to /login on 401.
 */
const API = (() => {

  function _token() {
    return localStorage.getItem('am_token') || '';
  }

  function _jsonHeaders() {
    const h = { 'Content-Type': 'application/json' };
    const t = _token();
    if (t) h['Authorization'] = 'Bearer ' + t;
    return h;
  }

  function _fdHeaders() {
    // For FormData — browser sets Content-Type with boundary automatically
    const h = {};
    const t = _token();
    if (t) h['Authorization'] = 'Bearer ' + t;
    return h;
  }

  async function _fetch(method, url, body, isFormData) {
    const opts = {
      method,
      headers: isFormData ? _fdHeaders() : _jsonHeaders(),
    };
    if (body !== null && body !== undefined) {
      opts.body = isFormData ? body : JSON.stringify(body);
    }
    let res;
    try {
      res = await fetch(url, opts);
    } catch (err) {
      console.error('Network error:', url, err);
      throw err;
    }
    if (res.status === 401) {
      localStorage.removeItem('am_token');
      window.location.href = '/login';
      return null;
    }
    return res;
  }

  return {
    get:    (url)            => _fetch('GET',    url, null,  false),
    post:   (url, body)      => _fetch('POST',   url, body,  false),
    put:    (url, body)      => _fetch('PUT',    url, body,  false),
    del:    (url, body)      => _fetch('DELETE', url, body,  false),
    upload: (url, formData)  => _fetch('POST',   url, formData, true),

    /** Build a workspace-scoped base URL */
    wsUrl(path) {
      return `/api/workspaces/${window.AM_WORKSPACE_ID || ''}${path}`;
    },

    /** Build a project-scoped URL */
    projectUrl(path) {
      const wsId = window.AM_WORKSPACE_ID || '';
      const proj = window.AM_PROJECT || '';
      return `/api/workspaces/${wsId}/projects/${encodeURIComponent(proj)}${path}`;
    },

    /** Return the auth header object (for use outside this module) */
    authHeaders: _jsonHeaders,
    fdHeaders:   _fdHeaders,
  };
})();
