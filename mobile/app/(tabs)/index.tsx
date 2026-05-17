import { useCallback, useMemo, useState } from 'react';
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { router } from 'expo-router';
import { useFocusEffect } from '@react-navigation/native';
import { AppHeader } from '@/components/ui/AppHeader';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { ErrorState, LoadingBlock } from '@/components/ui/States';
import { useAuth } from '@/context/AuthContext';
import {
  ApiError,
  fetchDashboard,
  fetchProfile,
  fetchVisitStats,
  fetchWorkStatus,
} from '@/lib/api';
import { captureSilentLocation } from '@/lib/geo';
import { getWorkdayStartedAt, setWorkdayStartedAt } from '@/lib/authStorage';
import { palette, space, typography } from '@/constants/theme';
import { WORKDAY_AUTO_STOP_HOURS } from '@/lib/config';
import { Ionicons } from '@expo/vector-icons';

export default function HomeScreen() {
  const { token, user } = useAuth();
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [dash, setDash] = useState<Awaited<ReturnType<typeof fetchDashboard>> | null>(null);
  const [stats, setStats] = useState<Awaited<ReturnType<typeof fetchVisitStats>> | null>(null);
  const [work, setWork] = useState<'started' | 'not_started'>('not_started');
  const [profileName, setProfileName] = useState('');

  const load = useCallback(async () => {
    if (!token) return;
    setErr(null);
    setLoading(true);
    try {
      const [d, s, w, me] = await Promise.all([
        fetchDashboard(token),
        fetchVisitStats(token),
        fetchWorkStatus(token),
        fetchProfile(token).catch(() => null),
      ]);
      setDash(d);
      setStats(s);
      setWork(w.work_status === 'started' ? 'started' : 'not_started');
      if (w.work_status === 'started') {
        const existing = await getWorkdayStartedAt();
        if (!existing) await setWorkdayStartedAt(new Date().toISOString());
      } else {
        await setWorkdayStartedAt(null);
      }
      setProfileName(me?.employee_id ? `${me.employee_id}` : user?.employee_id || '');
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : 'Could not load home.');
    } finally {
      setLoading(false);
    }
  }, [token, user?.employee_id]);

  useFocusEffect(
    useCallback(() => {
      void load();
    }, [load]),
  );

  const greeting = useMemo(() => {
    const h = new Date().getHours();
    if (h < 12) return 'Good morning';
    if (h < 17) return 'Good afternoon';
    return 'Good evening';
  }, []);

  async function startDayQuick() {
    if (!token) return;
    const loc = await captureSilentLocation();
    const { startWork } = await import('@/lib/api');
    await startWork(token, loc ?? undefined);
    await setWorkdayStartedAt(new Date().toISOString());
    await load();
  }

  if (loading && !dash) return <LoadingBlock />;
  if (err && !dash) return <ErrorState message={err} onRetry={load} />;

  return (
    <View style={styles.screen}>
      <AppHeader
        title="Home"
        subtitle={profileName || user?.employee_id || 'Field team'}
        right={
          <View style={styles.badge}>
            <Ionicons name="leaf" size={18} color={palette.primary} />
          </View>
        }
      />
      <ScrollView
        contentContainerStyle={styles.body}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={load} colors={[palette.primary]} />}>
        <Text style={styles.greet}>
          {greeting},{'\n'}
          <Text style={styles.name}>{user?.username || ' teammate'}</Text>
        </Text>

        <Card style={{ marginBottom: space.md }}>
          <Text style={typography.overline}>Workday</Text>
          <Text style={[typography.subtitle, { marginTop: space.xs }]}>
            {work === 'started' ? 'Day in progress' : 'You are off the clock'}
          </Text>
          <Text style={[typography.caption, { marginTop: space.xs }]}>
            {work === 'started'
              ? `Tracking syncs about every 30 minutes while the app is open. Field sessions auto-end after ${WORKDAY_AUTO_STOP_HOURS} hours.`
              : 'Start your day to record visits and share location with the team.'}
          </Text>
          <View style={{ flexDirection: 'row', gap: space.sm, marginTop: space.md }}>
            {work === 'not_started' ? (
              <View style={{ flex: 1 }}>
                <Button title="Start Day" onPress={startDayQuick} />
              </View>
            ) : (
              <View style={{ flex: 1 }}>
                <Button
                  title="Open tracking"
                  variant="secondary"
                  onPress={() => router.push('/(tabs)/tracking')}
                />
              </View>
            )}
          </View>
        </Card>

        <Text style={[typography.overline, { marginBottom: space.sm }]}>Today</Text>
        <View style={styles.statsRow}>
          <Card style={styles.statCard}>
            <Text style={styles.statNum}>{stats?.today_visits ?? dash?.today_visits ?? '—'}</Text>
            <Text style={typography.caption}>Visits today</Text>
          </Card>
          <Card style={styles.statCard}>
            <Text style={styles.statNum}>{stats?.completed ?? dash?.completed_visits ?? '—'}</Text>
            <Text style={typography.caption}>Recorded</Text>
          </Card>
        </View>

        <Text style={[typography.overline, { marginTop: space.lg, marginBottom: space.sm }]}>
          Quick actions
        </Text>
        <View style={styles.actions}>
          <Pressable style={styles.action} onPress={startDayQuick}>
            <Ionicons name="sunny-outline" size={22} color={palette.primary} />
            <Text style={styles.actionLabel}>Start Day</Text>
          </Pressable>
          <Pressable style={styles.action} onPress={() => router.push('/visit/create')}>
            <Ionicons name="add-circle-outline" size={22} color={palette.primary} />
            <Text style={styles.actionLabel}>Add Visit</Text>
          </Pressable>
          <Pressable style={styles.action} onPress={() => router.push('/(tabs)/visits')}>
            <Ionicons name="calendar-outline" size={22} color={palette.primary} />
            <Text style={styles.actionLabel}>My Visits</Text>
          </Pressable>
          <Pressable style={styles.action} onPress={() => router.push('/(tabs)/farmers')}>
            <Ionicons name="people-outline" size={22} color={palette.primary} />
            <Text style={styles.actionLabel}>Farmers</Text>
          </Pressable>
        </View>

        <Card style={{ marginTop: space.lg }}>
          <Text style={typography.overline}>Tracking status</Text>
          <View style={{ flexDirection: 'row', alignItems: 'center', marginTop: space.sm, gap: space.sm }}>
            <View
              style={[
                styles.dot,
                { backgroundColor: work === 'started' ? palette.success : palette.textMuted },
              ]}
            />
            <Text style={typography.body}>
              {work === 'started' ? 'Live session · syncing when active' : 'Inactive · start day to enable'}
            </Text>
          </View>
        </Card>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: palette.background },
  body: { padding: space.md, paddingBottom: space.xxl },
  greet: { ...typography.title, marginBottom: space.md },
  name: { color: palette.primary },
  statsRow: { flexDirection: 'row', gap: space.sm },
  statCard: { flex: 1, alignItems: 'center' },
  statNum: { ...typography.title, color: palette.primary },
  actions: { flexDirection: 'row', flexWrap: 'wrap', gap: space.sm },
  action: {
    width: '47%',
    backgroundColor: palette.surface,
    borderRadius: 12,
    padding: space.md,
    borderWidth: 1,
    borderColor: palette.border,
    alignItems: 'center',
    gap: space.xs,
  },
  actionLabel: { ...typography.caption, fontWeight: '600', color: palette.primary },
  badge: {
    width: 36,
    height: 36,
    borderRadius: 10,
    backgroundColor: palette.accentSoft,
    alignItems: 'center',
    justifyContent: 'center',
  },
  dot: { width: 10, height: 10, borderRadius: 5 },
});
