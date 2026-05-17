import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  FlatList,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { router, useLocalSearchParams } from 'expo-router';
import { useFocusEffect } from '@react-navigation/native';
import { BackHeader } from '@/components/ui/AppHeader';
import { Card } from '@/components/ui/Card';
import { EmptyState, ErrorState, LoadingBlock, SectionTitle } from '@/components/ui/States';
import { useAuth } from '@/context/AuthContext';
import {
  ApiError,
  fetchFarmerActivityPage,
  fetchFarmerDetail,
  fetchFarmerVisitsPage,
  VisitDto,
} from '@/lib/api';
import { formatVisitDateTime, normalizeVisitStatus, visitCropLabel, visitFarmerLabel } from '@/lib/visitDisplay';
import { palette, space, typography } from '@/constants/theme';

type Tab = 'overview' | 'fields' | 'visits' | 'activity';

export default function FarmerDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const farmerId = Number(id);
  const { token } = useAuth();
  const [tab, setTab] = useState<Tab>('overview');
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null);
  const [visits, setVisits] = useState<VisitDto[]>([]);
  const [activity, setActivity] = useState<Record<string, unknown>[]>([]);

  const loadDetail = useCallback(async () => {
    if (!token || !farmerId) return;
    setErr(null);
    setLoading(true);
    try {
      const d = await fetchFarmerDetail(token, farmerId);
      setDetail(d);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : 'Could not load farmer.');
    } finally {
      setLoading(false);
    }
  }, [token, farmerId]);

  const loadVisits = useCallback(async () => {
    if (!token || !farmerId) return;
    const p = await fetchFarmerVisitsPage(token, farmerId, 1);
    setVisits(p.results);
  }, [token, farmerId]);

  const loadActivity = useCallback(async () => {
    if (!token || !farmerId) return;
    const p = await fetchFarmerActivityPage(token, farmerId, 1);
    setActivity(p.results);
  }, [token, farmerId]);

  useFocusEffect(
    useCallback(() => {
      void loadDetail();
    }, [loadDetail]),
  );

  useEffect(() => {
    if (tab === 'visits') void loadVisits();
    if (tab === 'activity') void loadActivity();
  }, [tab, loadVisits, loadActivity]);

  const name = (detail?.name as string) || 'Farmer';
  const fields = (detail?.fields as Record<string, unknown>[]) || [];

  const tabs = useMemo(
    () =>
      [
        { key: 'overview' as const, label: 'Overview' },
        { key: 'fields' as const, label: 'Fields' },
        { key: 'visits' as const, label: 'Visits' },
        { key: 'activity' as const, label: 'Activity' },
      ],
    [],
  );

  if (loading && !detail) return <LoadingBlock />;
  if (err || !detail) return <ErrorState message={err || 'Missing'} onRetry={loadDetail} />;

  return (
    <View style={styles.screen}>
      <BackHeader title={name} onBack={() => router.back()} />
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        style={styles.tabBar}
        contentContainerStyle={{ paddingHorizontal: space.md, paddingVertical: space.sm }}>
        {tabs.map((t) => (
          <Pressable
            key={t.key}
            onPress={() => setTab(t.key)}
            style={[styles.tab, tab === t.key && styles.tabOn]}>
            <Text style={[typography.caption, tab === t.key && styles.tabLabelOn]}>{t.label}</Text>
          </Pressable>
        ))}
      </ScrollView>

      {tab === 'overview' ? (
        <ScrollView
          contentContainerStyle={{ padding: space.md }}
          refreshControl={<RefreshControl refreshing={loading} onRefresh={loadDetail} colors={[palette.primary]} />}>
          <Card>
            <SectionTitle>Contact</SectionTitle>
            <Text style={typography.body}>Phone: {(detail.phone as string) || '—'}</Text>
            <Text style={[typography.body, { marginTop: space.xs }]}>
              Address: {(detail.address as string) || '—'}
            </Text>
            <Text style={[typography.caption, { marginTop: space.sm }]}>
              Assigned: {(detail.assigned_employee_name as string) || '—'}
            </Text>
          </Card>
          <Card style={{ marginTop: space.md }}>
            <SectionTitle>Land</SectionTitle>
            <Text style={typography.body}>
              Total area: {detail.total_land_area != null ? String(detail.total_land_area) : '—'}
            </Text>
            <Text style={typography.caption}>Irrigation: {(detail.irrigation_type as string) || '—'}</Text>
            <Text style={typography.caption}>Soil: {(detail.soil_type as string) || '—'}</Text>
          </Card>
          <Pressable
            style={{ marginTop: space.lg }}
            onPress={() => router.push('/visit/create')}>
            <Text style={{ textAlign: 'center', color: palette.primary, fontWeight: '700' }}>
              Log a visit for this farmer
            </Text>
          </Pressable>
        </ScrollView>
      ) : null}

      {tab === 'fields' ? (
        <FlatList
          data={fields}
          keyExtractor={(item) => String(item.id)}
          contentContainerStyle={{ padding: space.md, gap: space.sm }}
          refreshControl={<RefreshControl refreshing={loading} onRefresh={loadDetail} colors={[palette.primary]} />}
          ListEmptyComponent={<EmptyState title="No plots on file" />}
          renderItem={({ item }) => (
            <Card>
              <Text style={typography.subtitle}>{String(item.land_name || 'Plot')}</Text>
              <Text style={typography.caption}>Size: {item.land_size != null ? String(item.land_size) : '—'}</Text>
              <Text style={typography.caption}>Soil: {(item.soil_type as string) || '—'}</Text>
            </Card>
          )}
        />
      ) : null}

      {tab === 'visits' ? (
        <FlatList
          data={visits}
          keyExtractor={(item) => String(item.id)}
          contentContainerStyle={{ padding: space.md, gap: space.sm }}
          refreshControl={
            <RefreshControl refreshing={false} onRefresh={loadVisits} colors={[palette.primary]} />
          }
          ListEmptyComponent={<EmptyState title="No visits yet" />}
          renderItem={({ item }) => (
            <Pressable onPress={() => router.push(`/visit/${item.id}`)}>
              <Card>
                <Text style={typography.subtitle}>{visitFarmerLabel(item)}</Text>
                <Text style={typography.caption}>{visitCropLabel(item)}</Text>
                <Text style={typography.caption}>
                  {formatVisitDateTime(item)} · {normalizeVisitStatus(item.status)}
                </Text>
              </Card>
            </Pressable>
          )}
        />
      ) : null}

      {tab === 'activity' ? (
        <FlatList
          data={activity}
          keyExtractor={(item) => String(item.id)}
          contentContainerStyle={{ padding: space.md, gap: space.sm }}
          refreshControl={
            <RefreshControl refreshing={false} onRefresh={loadActivity} colors={[palette.primary]} />
          }
          ListEmptyComponent={<EmptyState title="No timeline events" />}
          renderItem={({ item }) => (
            <Card>
              <Text style={typography.caption}>
                {String(item.activity_type_display || item.activity_type || 'Event')}
              </Text>
              <Text style={[typography.body, { marginTop: space.xs }]}>
                {String(item.notes || item.description || '')}
              </Text>
              <Text style={[typography.caption, { marginTop: space.sm }]}>
                {item.created_at ? String(item.created_at) : ''}
              </Text>
            </Card>
          )}
        />
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: palette.background },
  tabBar: { maxHeight: 52, flexGrow: 0 },
  tab: {
    paddingHorizontal: space.md,
    paddingVertical: space.xs,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: palette.border,
    marginRight: space.xs,
    backgroundColor: palette.surface,
  },
  tabOn: { backgroundColor: palette.accentSoft, borderColor: palette.primary },
  tabLabelOn: { color: palette.primary, fontWeight: '700' },
});
