import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';
import { clearTokens, getAccessToken, saveTokens } from '@/lib/authStorage';
import { mobileLogin } from '@/lib/api';

type User = { id: number; username: string; employee_id: string; phone?: string };

type AuthContextValue = {
  ready: boolean;
  token: string | null;
  user: User | null;
  signIn: (employeeId: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
};

const Ctx = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = useState(false);
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const t = await getAccessToken();
      if (!cancelled) {
        setToken(t);
        setReady(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const signIn = useCallback(async (employeeId: string, password: string) => {
    const res = await mobileLogin({
      employee_id: employeeId.trim(),
      password,
    });
    await saveTokens(res.access, res.refresh);
    setToken(res.access);
    const u = res.user as Record<string, unknown>;
    setUser({
      id: Number(u.id),
      username: String(u.username ?? ''),
      employee_id: String(u.employee_id ?? ''),
      phone: u.phone != null ? String(u.phone) : undefined,
    });
  }, []);

  const signOut = useCallback(async () => {
    await clearTokens();
    setToken(null);
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({ ready, token, user, signIn, signOut }),
    [ready, token, user, signIn, signOut],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const v = useContext(Ctx);
  if (!v) throw new Error('useAuth must be used within AuthProvider');
  return v;
}
