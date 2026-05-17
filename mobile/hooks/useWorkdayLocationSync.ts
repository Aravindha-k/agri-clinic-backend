import { useCallback, useEffect, useRef } from 'react';
import { AppState, AppStateStatus } from 'react-native';
import { pingTracking } from '@/lib/api';
import { captureSilentLocation } from '@/lib/geo';
import { setLastLocationSyncAt } from '@/lib/authStorage';
import { LOCATION_SYNC_INTERVAL_MS } from '@/lib/config';

/** Periodic location ping when workday is active; refreshes parent via onMetaChange. */
export function useWorkdayLocationSync(
  token: string | null,
  enabled: boolean,
  onMetaChange: () => void,
) {
  const appState = useRef(AppState.currentState);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const runPing = useCallback(async () => {
    if (!token || !enabled) return;
    const loc = await captureSilentLocation();
    if (!loc) return;
    try {
      await pingTracking(token, loc);
      await setLastLocationSyncAt(new Date().toISOString());
      onMetaChange();
    } catch {
      /* server may reject if workday ended */
    }
  }, [token, enabled, onMetaChange]);

  useEffect(() => {
    if (!token || !enabled) {
      if (timer.current) clearInterval(timer.current);
      timer.current = null;
      return;
    }
    void runPing();
    timer.current = setInterval(runPing, LOCATION_SYNC_INTERVAL_MS);
    return () => {
      if (timer.current) clearInterval(timer.current);
      timer.current = null;
    };
  }, [token, enabled, runPing]);

  useEffect(() => {
    const sub = AppState.addEventListener('change', (next: AppStateStatus) => {
      if (appState.current.match(/inactive|background/) && next === 'active' && enabled && token) {
        void runPing();
      }
      appState.current = next;
    });
    return () => sub.remove();
  }, [enabled, token, runPing]);

  return { runPing };
}
