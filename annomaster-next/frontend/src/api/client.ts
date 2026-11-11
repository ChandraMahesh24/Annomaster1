/**
 * API client — fetch wrapper.
 *
 * Ports the original core/api.js behaviour: attach the JWT from localStorage as
 * a Bearer header, send cookies too, and on 401 clear the token and bounce to
 * /login. Every request goes through here so auth handling lives in one place.
 */
const TOKEN_KEY = 'am_token';

export function getToken(): string | null {
  try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
}
export function setToken(t: string) {
  try { localStorage.setItem(TOKEN_KEY, t); } catch { /* ignore */ }
}
export function clearToken() {
  try { localStorage.removeItem(TOKEN_KEY); } catch { /* ignore */ }
}

/**
 * URL for an auth-protected image, for use in <img src>. Appends the JWT as a
 * query param because <img> tags can't send an Authorization header (the backend
 * accepts `?token=` for exactly this).
 */
export function imageUrl(base: string, path: string): string {
  const t = getToken();
  const q = `path=${encodeURIComponent(path)}${t ? `&token=${encodeURIComponent(t)}` : ''}`;
  return `/api${base}/image?${q}`;
}

export class ApiError extends Error {
  constructor(public status: number, message: string, public detail?: unknown) {
    super(message);
  }
}

interface Opts {
  method?: string;
  body?: unknown;
  // FormData for uploads; skips JSON encoding
  form?: FormData;
}

export async function api<T = unknown>(path: string, opts: Opts = {}): Promise<T> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;

  let body: BodyInit | undefined;
  if (opts.form) {
    body = opts.form;
  } else if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(opts.body);
  }

  const res = await fetch(`/api${path}`, {
    method: opts.method ?? (opts.body || opts.form ? 'POST' : 'GET'),
    headers,
    body,
    credentials: 'include', // JWT cookie flows too
  });

  if (res.status === 401 && !path.startsWith('/auth/login')) {
    clearToken();
    if (location.pathname !== '/login') location.href = '/login';
    throw new ApiError(401, 'Authentication required');
  }

  const isJson = res.headers.get('content-type')?.includes('application/json');
  const payload = isJson ? await res.json().catch(() => null) : await res.text();

  if (!res.ok) {
    const msg =
      (isJson && payload && typeof payload === 'object' && 'detail' in payload)
        ? typeof (payload as any).detail === 'string'
          ? (payload as any).detail
          : JSON.stringify((payload as any).detail)
        : `Request failed (${res.status})`;
    throw new ApiError(res.status, msg, payload);
  }
  return payload as T;
}
