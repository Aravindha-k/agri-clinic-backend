import { useCallback, useState } from 'react';
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useFocusEffect } from '@react-navigation/native';
import { router } from 'expo-router';
import { AppHeader } from '@/components/ui/AppHeader';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { ErrorState, LoadingBlock } from '@/components/ui/States';
import { useAuth } from '@/context/AuthContext';
import { ApiError, fetchProfile } from '@/lib/api';
import {
  ConnectivityDiagnostic,
  runConnectivityDiagnostic,
} from '@/lib/diagnostics';
import { palette, space, typography } from '@/constants/theme';

export default function ProfileScreen() {
  const { token, user, signOut, ready, deviceSessionId } = useAuth();
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [me, setMe] = useState<Awaited<ReturnType<typeof fetchProfile>> | null>(null);
  const [diag, setDiag] = useState<ConnectivityDiagnostic | null>(null);
  const [diagBusy, setDiagBusy] = useState(false);

  const load = useCallback(async () => {
    if (!token) return;
    setErr(null);
    setLoading(true);
    try {
      const p = await fetchProfile(token);
      setMe(p);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : 'Profile unavailable.');
    } finally {
      setLoading(false);
    }
  }, [token]);

  useFocusEffect(
    useCallback(() => {
      void load();
    }, [load]),
  );

  async function runDiag() {
    setDiagBusy(true);
    try {
      setDiag(await runConnectivityDiagnostic());
    } finally {
      setDiagBusy(false);
    }
  }

  if (loading && !me) return <LoadingBlock />;

  return (
    <View style={styles.screen}>
      <AppHeader title="Profile" subtitle="Account" />
      <ScrollView
        contentContainerStyle={{ padding: space.md, paddingBottom: 48 }}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={load} colors={[palette.primary]} />}>
        {err && !me ? <ErrorState message={err} onRetry={load} /> : null}
        <Card>
          <Text style={typography.overline}>Employee</Text>
          <Text style={[typography.subtitle, { marginTop: space.xs }]}>{me?.username || user?.username}</Text>
          <Text style={[typography.caption, { marginTop: space.sm }]}>ID: {me?.employee_id || user?.employee_id}</Text>
          {me?.phone ? <Text style={typography.caption}>Phone: {me.phone}</Text> : null}
          <Text style={[typography.caption, { marginTop: space.sm, color: palette.textMuted }]}>
            Status:{' '}
            {me?.is_active_employee === false ? 'Inactive' : 'Active'}
          </Text>
        </Card>

        <Card style={{ marginTop: space.md }}>
          <Text style={typography.overline}>Connectivity</Text>
          <Text style={[typography.caption, { marginTop: space.xs }]}>
            Safe diagnostics for device smoke tests. Tokens and full session IDs are never shown.
          </Text>
          <View style={{ marginTop: space.md }}>
            <Button title="Run API check" onPress={() => void runDiag()} loading={diagBusy} />
          </View>
          {diag ? (
            <View style={{ marginTop: space.md, gap: 6 }}>
              <DiagRow label="API host" value={diag.apiHost} />
              <DiagRow label="API path" value={diag.apiBasePath} />
              <DiagRow label="Environment" value={diag.environment} />
              <DiagRow label="App version" value={diag.appVersion} />
              <DiagRow
                label="API reachable"
                value={
                  diag.reachable == null
                    ? '—'
                    : diag.reachable
                      ? `Yes (${diag.httpStatus ?? 'OK'})`
                      : `No${diag.httpStatus != null ? ` (${diag.httpStatus})` : ''}`
                }
              />
              <DiagRow label="Health" value={diag.healthMessage} />
              <DiagRow label="Auth restored" value={diag.authRestored || (ready && !!token) ? 'Yes' : 'No'} />
              <DiagRow label="Access token" value={diag.hasAccessToken ? 'Present' : 'Missing'} />
              <DiagRow label="Refresh token" value={diag.hasRefreshToken ? 'Present' : 'Missing'} />
              <DiagRow
                label="Device session"
                value={
                  diag.hasDeviceSession || !!deviceSessionId
                    ? `Present (${diag.deviceSessionMasked || '••••'})`
                    : 'Missing'
                }
              />
              <DiagRow label="Checked at" value={diag.checkedAt} />
              {diag.configWarnings.length ? (
                <View style={{ marginTop: space.sm }}>
                  <Text style={[typography.caption, { color: palette.danger }]}>Config warnings</Text>
                  {diag.configWarnings.map((w) => (
                    <Text key={w} style={[typography.caption, { marginTop: 4, color: palette.danger }]}>
                      • {w}
                    </Text>
                  ))}
                </View>
              ) : null}
            </View>
          ) : null}
        </Card>

        <Pressable style={styles.link} onPress={() => router.push('/(tabs)/visits')}>
          <Text style={styles.linkText}>View my visits</Text>
        </Pressable>
        <Pressable
          style={[styles.link, { marginTop: space.sm }]}
          onPress={async () => {
            await signOut();
            router.replace('/login');
          }}>
          <Text style={[styles.linkText, { color: palette.danger }]}>Sign out</Text>
        </Pressable>
      </ScrollView>
    </View>
  );
}

function DiagRow({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.diagRow}>
      <Text style={styles.diagLabel}>{label}</Text>
      <Text style={styles.diagValue}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: palette.background },
  link: {
    padding: space.md,
    backgroundColor: palette.surface,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: palette.border,
    marginTop: space.lg,
  },
  linkText: { ...typography.subtitle, color: palette.primary, textAlign: 'center' },
  diagRow: { marginTop: 4 },
  diagLabel: { ...typography.caption, color: palette.textMuted },
  diagValue: { ...typography.body, color: palette.text },
});
