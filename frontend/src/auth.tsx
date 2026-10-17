import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { api, setUnauthorizedHandler } from './api';
import type { Me, User } from './types';

interface Auth {
  me: Me | null;
  user: User | null;
  ready: boolean;
  login: (login: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  can: (role: 'operator' | 'supervisor' | 'admin') => boolean;
  refresh: () => Promise<void>;
}
const RANK: Record<string, number> = { operator: 1, supervisor: 2, admin: 3 };
const Ctx = createContext<Auth | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [ready, setReady] = useState(false);

  const refresh = useCallback(async () => {
    try { setMe(await api<Me>('/ui/api/auth/me', { silent401: true })); }
    catch { setMe(null); }
    finally { setReady(true); }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => {
    setUnauthorizedHandler(() => setMe(null));
    return () => setUnauthorizedHandler(null);
  }, []);

  const login = useCallback(async (login: string, password: string) => {
    await api('/ui/api/auth/login', { method: 'POST', json: { login, password }, silent401: true });
    await refresh();
  }, [refresh]);

  const logout = useCallback(async () => {
    try { await api('/ui/api/auth/logout', { method: 'POST' }); } catch { /* ignore */ }
    setMe(null);
  }, []);

  const value = useMemo<Auth>(() => ({
    me, user: me?.user ?? null, ready, login, logout, refresh,
    can: role => (RANK[me?.user.role ?? ''] ?? 0) >= RANK[role],
  }), [me, ready, login, logout, refresh]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): Auth {
  const v = useContext(Ctx);
  if (!v) throw new Error('useAuth outside provider');
  return v;
}
