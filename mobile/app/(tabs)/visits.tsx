import { useCallback, useMemo, useState } from 'react';
import {
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { router, useFocusEffect } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { AppHeader } from '@/components/ui/AppHeader';
import { Card } from '@/components/ui/Card';
import { ChipRow } from '@/components/ui/Chip';
import { EmptyState, ErrorState, LoadingBlock } from '@/components/ui/States';
import { useAuth } from '@/context/AuthContext';
import { ApiError, fetchMyVisits, VisitDto } from '@/lib/api';
import {
  formatVisitDateTime,
  visitCropLabel,
  visitFarmerLabel,
  visitHasGps,
  visitVillageLabel,
} from '@/lib/visitDisplay';
import { palette, radius, space, typography } from '@/constants/theme';

type ChipKey = 'today' | 'all';

export default function VisitsScreen() {
  const { token } = useAuth();
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [list, setList] = useState<VisitDto[]>([]);
  const [search, setSearch] = useState('');
  const [chip, setChip] = useState<ChipKey>('all');

  const load = useCallback(async () => {
    if (!token) return;
    setErr(null);
    setLoading(true);
    try {
      const rows = await fetchMyVisits(token);
      setList(rows);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : 'Could not load visits.');
    } finally {
      setLoading(false);
    }
  }, [token]);

  useFocusEffect(
    useCallback(() => {
      void load();
    }, [load]),
  );

  const todayStr = useMemo(() => new Date().toISOString().slice(0, 10), []);

  const filtered = useMemo(() => {
    let rows = list;
    const q = search.trim().toLowerCase();
    if (q) {
      rows = rows.filter((v) => {
        const blob = [visitFarmerLabel(v), visitVillageLabel(v), visitCropLabel(v)]
          .join(' ')
          .toLowerCase();
        return blob.includes(q);
      });
    }
    if (chip === 'today') {
      rows = rows.filter((v) => v.visit_date === todayStr);
    }
    return rows;
  }, [list, search, chip, todayStr]);

  if (loading && !list.length) return <LoadingBlock />;

  return (
    <View style={styles.screen}>
      <AppHeader title="Visits" subtitle="Your completed field visits" />
      <View style={{ paddingHorizontal: space.md }}>
        <View style={styles.searchWrap}>
          <Ionicons name="search" size={18} color={palette.textMuted} />
          <TextInput
            value={search}
            onChangeText={setSearch}
            placeholder="Search farmer, village, crop…"
            placeholderTextColor={palette.textMuted}
            style={styles.search}
          />
        </View>
        <ChipRow
          options={[
            { key: 'today', label: 'Today' },
            { key: 'all', label: 'All' },
          ]}
          value={chip}
          onChange={(k) => setChip(k as ChipKey)}
        />
      </View>
      {err && !list.length ? (
        <ErrorState message={err} onRetry={load} />
      ) : (
        <FlatList
          data={filtered}
          keyExtractor={(item) => String(item.id)}
          contentContainerStyle={{ padding: space.md, paddingBottom: 40, gap: space.sm }}
          refreshControl={
            <RefreshControl refreshing={loading} onRefresh={load} colors={[palette.primary]} />
          }
          ListEmptyComponent={
            <EmptyState
              title="No visits yet"
              detail="Record a visit from a farmer profile or Add Visit."
              actionLabel="Add visit"
              onAction={() => router.push('/visit/create')}
            />
          }
          renderItem={({ item }) => (
            <Pressable onPress={() => router.push(`/visit/${item.id}`)}>
              <Card>
                <Text style={typography.subtitle}>{visitFarmerLabel(item)}</Text>
                <Text style={typography.caption}>
                  {visitVillageLabel(item)} · {visitCropLabel(item)}
                </Text>
                <View style={styles.meta}>
                  <Text style={typography.caption}>{formatVisitDateTime(item)}</Text>
                  {visitHasGps(item) ? (
                    <View style={styles.gps}>
                      <Ionicons name="location" size={14} color={palette.primary} />
                      <Text style={[typography.caption, { color: palette.primary, fontWeight: '600' }]}>
                        GPS
                      </Text>
                    </View>
                  ) : (
                    <Text style={[typography.caption, { color: palette.textMuted }]}>No GPS</Text>
                  )}
                </View>
              </Card>
            </Pressable>
          )}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: palette.background },
  searchWrap: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: palette.surface,
    borderRadius: radius.md,
    paddingHorizontal: space.sm,
    borderWidth: 1,
    borderColor: palette.border,
    marginBottom: space.sm,
  },
  search: { flex: 1, paddingVertical: space.sm, paddingHorizontal: space.xs, fontSize: 15, color: palette.text },
  meta: { flexDirection: 'row', justifyContent: 'space-between', marginTop: space.sm, alignItems: 'center' },
  gps: { flexDirection: 'row', alignItems: 'center', gap: 4 },
});
