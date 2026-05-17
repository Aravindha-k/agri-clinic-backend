import { useCallback, useState } from 'react';
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
import { EmptyState, ErrorState, LoadingBlock } from '@/components/ui/States';
import { useAuth } from '@/context/AuthContext';
import { ApiError, FarmerListItem, fetchFarmersPage } from '@/lib/api';
import { palette, radius, space, typography } from '@/constants/theme';

export default function FarmersScreen() {
  const { token } = useAuth();
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [rows, setRows] = useState<FarmerListItem[]>([]);

  const load = useCallback(async () => {
    if (!token) return;
    setErr(null);
    setLoading(true);
    try {
      const page = await fetchFarmersPage(token, 1, search);
      setRows(page.results);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : 'Could not load farmers.');
    } finally {
      setLoading(false);
    }
  }, [token, search]);

  useFocusEffect(
    useCallback(() => {
      void load();
    }, [load]),
  );

  if (loading && !rows.length) return <LoadingBlock />;

  return (
    <View style={styles.screen}>
      <AppHeader title="Farmers" subtitle="Your territory" />
      <View style={{ paddingHorizontal: space.md, marginBottom: space.sm }}>
        <View style={styles.searchWrap}>
          <Ionicons name="search" size={18} color={palette.textMuted} />
          <TextInput
            value={search}
            onChangeText={setSearch}
            onSubmitEditing={() => load()}
            returnKeyType="search"
            placeholder="Search name or phone…"
            placeholderTextColor={palette.textMuted}
            style={styles.search}
          />
          <Pressable onPress={() => load()} hitSlop={8}>
            <Text style={{ color: palette.primary, fontWeight: '700' }}>Go</Text>
          </Pressable>
        </View>
      </View>
      {err && !rows.length ? (
        <ErrorState message={err} onRetry={load} />
      ) : (
        <FlatList
          data={rows}
          keyExtractor={(item) => String(item.id)}
          contentContainerStyle={{ paddingHorizontal: space.md, paddingBottom: 32, gap: space.sm }}
          refreshControl={
            <RefreshControl refreshing={loading} onRefresh={load} colors={[palette.primary]} />
          }
          ListEmptyComponent={
            <EmptyState title="No farmers yet" detail="Pull to refresh or adjust search." onAction={load} actionLabel="Retry" />
          }
          renderItem={({ item }) => (
            <Pressable onPress={() => router.push(`/farmer/${item.id}`)}>
              <Card>
                <Text style={typography.subtitle}>{item.name}</Text>
                <Text style={typography.caption}>{item.phone}</Text>
                <Text style={[typography.caption, { marginTop: space.xs }]}>
                  {[item.village_name, item.district_name].filter(Boolean).join(' · ') || '—'}
                </Text>
                {item.fields && item.fields.length ? (
                  <Text style={[typography.caption, { marginTop: 4, color: palette.primary }]}>
                    {item.fields.length} field{item.fields.length > 1 ? 's' : ''}
                  </Text>
                ) : null}
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
    gap: space.xs,
  },
  search: { flex: 1, paddingVertical: space.sm, fontSize: 15, color: palette.text },
});
