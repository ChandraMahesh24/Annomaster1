import type { ReactNode } from 'react';
import { Navigate } from 'react-router-dom';
import { useMe } from '../api/auth';
import { getToken } from '../api/client';

/** Route guard: no token → straight to /login; otherwise verify via /me. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const hasToken = !!getToken();
  const { data, isLoading, isError } = useMe();

  if (!hasToken) return <Navigate to="/login" replace />;
  if (isLoading) {
    return <div style={{ padding: 'var(--sp-16)', textAlign: 'center', color: 'var(--tx2)' }}>Loading…</div>;
  }
  if (isError || !data) return <Navigate to="/login" replace />;
  return <>{children}</>;
}
