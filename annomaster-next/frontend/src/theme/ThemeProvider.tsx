import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import type { ReactNode } from 'react';

type Theme = 'dark' | 'light';

interface ThemeCtx {
  theme: Theme;
  toggle: () => void;
  setTheme: (t: Theme) => void;
}

const Ctx = createContext<ThemeCtx | null>(null);
const KEY = 'am_theme';

/**
 * Dark is the default; light is derived (data-theme="light" on <html>).
 * The pre-paint <script> in index.html sets the attribute before React mounts,
 * so there's no flash; this provider keeps it in sync at runtime and persists.
 */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(() =>
    (typeof document !== 'undefined' &&
      document.documentElement.classList.contains('light-mode'))
      ? 'light' : 'dark',
  );

  const apply = useCallback((t: Theme) => {
    const root = document.documentElement;
    // The ported (original) CSS keys light styles off `.light-mode`; the token
    // layer also accepts [data-theme="light"]. Set both so every rule matches.
    if (t === 'light') { root.classList.add('light-mode'); root.setAttribute('data-theme', 'light'); }
    else { root.classList.remove('light-mode'); root.removeAttribute('data-theme'); }
    try { localStorage.setItem(KEY, t); } catch { /* ignore */ }
  }, []);

  useEffect(() => { apply(theme); }, [theme, apply]);

  const setTheme = useCallback((t: Theme) => setThemeState(t), []);
  const toggle = useCallback(
    () => setThemeState((t) => (t === 'dark' ? 'light' : 'dark')),
    [],
  );

  return <Ctx.Provider value={{ theme, toggle, setTheme }}>{children}</Ctx.Provider>;
}

export function useTheme(): ThemeCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error('useTheme must be used within ThemeProvider');
  return v;
}
