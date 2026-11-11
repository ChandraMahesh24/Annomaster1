import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, clearToken, setToken } from './client';

export interface User {
  id: number;
  public_id: string;
  email: string;
  username: string;
  avatar_url?: string | null;
  bio?: string | null;
  last_login?: string | null;
}
interface TokenOut { access_token: string; user: User; }

/** Current user; null when unauthenticated. Cached as the auth source of truth. */
export function useMe() {
  return useQuery({
    queryKey: ['me'],
    queryFn: () => api<User>('/auth/me'),
    retry: false,
    staleTime: 5 * 60 * 1000,
  });
}

export function useLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { email: string; password: string }) =>
      api<TokenOut>('/auth/login', { body }),
    onSuccess: (data) => {
      setToken(data.access_token);
      qc.setQueryData(['me'], data.user);
    },
  });
}

export function useRegister() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { email: string; username: string; password: string }) =>
      api<TokenOut>('/auth/register', { body }),
    onSuccess: (data) => {
      setToken(data.access_token);
      qc.setQueryData(['me'], data.user);
    },
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api('/auth/logout', { method: 'POST' }),
    onSettled: () => {
      clearToken();
      qc.clear();
    },
  });
}
