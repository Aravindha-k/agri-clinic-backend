import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';
import {
  clearTokens,
  getStoredAuth,
  saveAuthSession,
} from '@/lib/authStorage';
import { mobileLogin } from '@/lib/api';
import { setSessionInvalidatedListener } from '@/lib/authEvents';
import { appLog } from '@/lib/logger';
import { Platform } from 'react-native';

type User = { id: number; username: string; employee_id: string; phone?: string };

type AuthContextValue = {
  ready: boolean;
  token: string | null;
  user: User | null;
  deviceSessionId: string | null;
  signIn: (employeeId: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
};

const Ctx = createContext<AuthContextValue | undefined>(undefined);

function parseUser(u: Record<string, unknown> | null | undefined): User | null {
  if (!u) return null;
  return {
    id: Number(u.id),
    username: String(u.username ?? ''),
    employee_id: String(u.employee_id ?? ''),
    phone: u.phone != null ? String(u.phone) : undefined,
  };
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = useState(false);
  const [token, setToken] = useState<string | null>(null);
  const [deviceSessionId, setDeviceSessionId] = useState<string | null>(null);
  const [user, setUser] = useState<User | null>(null);

  const clearLocalAuth = useCallback(async () => {
    await clearTokens();
    setToken(null);
    setDeviceSessionId(null);
    setUser(null);
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const stored = await getStoredAuth();
        if (cancelled) return;
        if (stored.access && stored.deviceSessionId) {
          setToken(stored.access);
          setDeviceSessionId(stored.deviceSessionId);
          appLog.info('auth.restore_ok', { hasRefresh: Boolean(stored.refresh) });
        } else if (stored.access && !stored.deviceSessionId) {
          // Incomplete session after upgrade — force re-login rather than 409 loops.
          appLog.warn('auth.restore_missing_device_session');
          await clearTokens();
          setToken(null);
          setDeviceSessionId(null);
        } else {
          appLog.info('auth.restore_empty');
        }
      } catch {
        appLog.error('auth.restore_failed');
      } finally {
        if (!cancelled) setReady(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    setSessionInvalidatedListener((reason) => {
      appLog.warn('auth.session_invalidated', { reason });
      setToken(null);
      setDeviceSessionId(null);
      setUser(null);
    });
    return () => setSessionInvalidatedListener(null);
  }, []);

  const signIn = useCallback(async (employeeId: string, password: string) => {
    const res = await mobileLogin({
      employee_id: employeeId.trim(),
      password,
      platform: Platform.OS,
      device_name: Platform.OS,
    });
    await saveAuthSession({
      access: res.access,
      refresh: res.refresh,
      deviceSessionId: res.device_session_id,
    });
    setToken(res.access);
    setDeviceSessionId(res.device_session_id);
    setUser(parseUser(res.user));
    appLog.info('auth.sign_in_state_ready', {
      userId: typeof res.user?.id === 'number' ? res.user.id : undefined,
    });
  }, []);

  const signOut = useCallback(async () => {
    appLog.info('auth.sign_out');
    await clearLocalAuth();
  }, [clearLocalAuth]);

  const value = useMemo(
    () => ({
      ready,
      token,
      user,
      deviceSessionId,
      signIn,
      signOut,
    }),
    [ready, token, user, deviceSessionId, signIn, signOut],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const v = useContext(Ctx);
  if (!v) throw new Error('useAuth must be used within AuthProvider');
  return v;
}
