import { useCallback, useState } from 'react';
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useFocusEffect } from '@react-navigation/native';
import { router } from 'expo-router';
import { AppHeader } from '@/components/ui/AppHeader';
import { Card } from '@/components/ui/Card';
import { ErrorState, LoadingBlock } from '@/components/ui/States';
import { useAuth } from '@/context/AuthContext';
import { ApiError, fetchProfile } from '@/lib/api';
import { palette, space, typography } from '@/constants/theme';

export default function ProfileScreen() {
  const { token, user, signOut } = useAuth();
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [me, setMe] = useState<Awaited<ReturnType<typeof fetchProfile>> | null>(null);

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

  if (loading && !me) return <LoadingBlock />;

  return (
    <View style={styles.screen}>
      <AppHeader title="Profile" subtitle="Account" />
      <ScrollView
        contentContainerStyle={{ padding: space.md }}
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
        <Pressable style={styles.link} onPress={() => router.push('/(tabs)/visits')}>
          <Text style={styles.linkText}>View my visits</Text>
        </Pressable>
        <Pressable style={[styles.link, { marginTop: space.sm }]} onPress={() => signOut()}>
          <Text style={[styles.linkText, { color: palette.danger }]}>Sign out</Text>
        </Pressable>
      </ScrollView>
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
});
