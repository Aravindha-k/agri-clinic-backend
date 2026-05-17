import { useCallback, useEffect, useState } from 'react';
import { RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useFocusEffect } from '@react-navigation/native';
import { AppHeader } from '@/components/ui/AppHeader';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { ErrorState, LoadingBlock } from '@/components/ui/States';
import { useAuth } from '@/context/AuthContext';
import { ApiError, fetchWorkStatus, startWork, stopWork } from '@/lib/api';
import {
  getLastLocationSyncAt,
  getWorkdayStartedAt,
  setLastLocationSyncAt,
  setWorkdayStartedAt,
} from '@/lib/authStorage';
import { captureSilentLocation } from '@/lib/geo';
import { useWorkdayLocationSync } from '@/hooks/useWorkdayLocationSync';
import { LOCATION_SYNC_INTERVAL_MS, WORKDAY_AUTO_STOP_HOURS } from '@/lib/config';
import { palette, space, typography } from '@/constants/theme';
import { Ionicons } from '@expo/vector-icons';

function formatTime(iso: string | null) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, { hour: '2-digit', minute: '2-digit', day: 'numeric', month: 'short' });
  } catch {
    return '—';
  }
}

export default function TrackingScreen() {
  const { token } = useAuth();
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [work, setWork] = useState<'started' | 'not_started'>('not_started');
  const [busy, setBusy] = useState(false);
  const [metaTick, setMetaTick] = useState(0);
  const [startedAt, setStartedAt] = useState<string | null>(null);
  const [lastSync, setLastSync] = useState<string | null>(null);

  const bumpMeta = useCallback(() => setMetaTick((t) => t + 1), []);

  const load = useCallback(async () => {
    if (!token) return;
    setErr(null);
    setLoading(true);
    try {
      const st = await fetchWorkStatus(token);
      const isOn = st.work_status === 'started';
      setWork(isOn ? 'started' : 'not_started');
      if (isOn) {
        let s = await getWorkdayStartedAt();
        if (!s) {
          s = new Date().toISOString();
          await setWorkdayStartedAt(s);
        }
        setStartedAt(s);
        setLastSync(await getLastLocationSyncAt());
      } else {
        setStartedAt(null);
        setLastSync(null);
        await setWorkdayStartedAt(null);
        await setLastLocationSyncAt(null);
      }
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : 'Could not load tracking.');
    } finally {
      setLoading(false);
    }
  }, [token]);

  useFocusEffect(
    useCallback(() => {
      void load();
    }, [load]),
  );

  useEffect(() => {
    void (async () => {
      setStartedAt(await getWorkdayStartedAt());
      setLastSync(await getLastLocationSyncAt());
    })();
  }, [metaTick, work]);

  useWorkdayLocationSync(token, work === 'started', bumpMeta);

  const nextSyncMs = lastSync
    ? new Date(lastSync).getTime() + LOCATION_SYNC_INTERVAL_MS - Date.now()
    : LOCATION_SYNC_INTERVAL_MS;
  const nextSyncLabel =
    lastSync && nextSyncMs > 0
      ? `in ${Math.max(1, Math.ceil(nextSyncMs / 60000))} min`
      : 'due on next open / interval';

  async function onStart() {
    if (!token) return;
    setBusy(true);
    setErr(null);
    try {
      const loc = await captureSilentLocation();
      await startWork(token, loc ?? undefined);
      const now = new Date().toISOString();
      await setWorkdayStartedAt(now);
      setStartedAt(now);
      setWork('started');
      bumpMeta();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : 'Could not start day.');
    } finally {
      setBusy(false);
    }
  }

  async function onStop() {
    if (!token) return;
    setBusy(true);
    setErr(null);
    try {
      await stopWork(token);
      await setWorkdayStartedAt(null);
      await setLastLocationSyncAt(null);
      setWork('not_started');
      setStartedAt(null);
      setLastSync(null);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : 'Could not end day.');
    } finally {
      setBusy(false);
    }
  }

  if (loading && work === 'not_started' && !startedAt) return <LoadingBlock />;

  return (
    <View style={styles.screen}>
      <AppHeader title="Tracking" subtitle="Field presence" />
      <ScrollView
        contentContainerStyle={{ padding: space.md }}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={load} colors={[palette.primary]} />}>
        {err ? <ErrorState message={err} onRetry={load} /> : null}

        {work === 'not_started' ? (
          <Card>
            <Text style={typography.overline}>Status</Text>
            <Text style={[typography.subtitle, { marginTop: space.xs }]}>Session inactive</Text>
            <Text style={[typography.caption, { marginTop: space.sm }]}>
              Start your workday to allow scheduled location syncs while you use the app. We never show raw coordinates on
              visit forms.
            </Text>
            <View style={{ marginTop: space.lg }}>
              <Button title="Start Day" onPress={onStart} loading={busy} />
            </View>
          </Card>
        ) : (
          <Card>
            <View style={styles.activeRow}>
              <View style={styles.liveDot} />
              <Text style={[typography.subtitle, { color: palette.success }]}>Live</Text>
            </View>
            <Text style={[typography.caption, { marginTop: space.sm }]}>
              Workday started at {formatTime(startedAt)}
            </Text>
            <Text style={[typography.caption, { marginTop: space.xs }]}>
              Last sync: {formatTime(lastSync)}
            </Text>
            <Text style={[typography.caption, { marginTop: space.xs }]}>
              Next sync (~30 min): {nextSyncLabel}
            </Text>
            <Text style={[typography.caption, { marginTop: space.xs, color: palette.textMuted }]}>
              Auto-stop after {WORKDAY_AUTO_STOP_HOURS}h per policy (server enforced).
            </Text>
            <View style={[styles.note, { marginTop: space.md }]}>
              <Ionicons name="location-outline" size={20} color={palette.primary} />
              <Text style={[typography.caption, { flex: 1 }]}>
                Last location: fix stored on the server when sync succeeds; this screen only shows timestamps, not
                coordinates on the device.
              </Text>
            </View>
            <View style={{ marginTop: space.lg }}>
              <Button title="End Day" variant="secondary" onPress={onStop} loading={busy} />
            </View>
          </Card>
        )}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: palette.background },
  activeRow: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  liveDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
    backgroundColor: palette.success,
  },
  note: { flexDirection: 'row', gap: space.sm, alignItems: 'flex-start' },
});
