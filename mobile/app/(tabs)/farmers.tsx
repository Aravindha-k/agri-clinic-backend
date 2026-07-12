import { useCallback, useRef, useState } from 'react';
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
  const { token, ready } = useAuth();
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [searchInput, setSearchInput] = useState('');
  const [query, setQuery] = useState('');
  const [rows, setRows] = useState<FarmerListItem[]>([]);
  const [page, setPage] = useState(1);
  const [totalCount, setTotalCount] = useState(0);
  const inFlightRef = useRef(false);
  const queryRef = useRef(query);
  queryRef.current = query;

  const loadPage = useCallback(
    async (pageNum: number, search: string, append: boolean) => {
      if (!ready || !token || inFlightRef.current) return;
      inFlightRef.current = true;
      setErr(null);
      if (append) {
        setLoadingMore(true);
      } else {
        setLoading(true);
      }
      try {
        const result = await fetchFarmersPage(token, pageNum, search);
        setTotalCount(result.count);
        setPage(pageNum);
        setRows((prev) => (append ? [...prev, ...result.results] : result.results));
      } catch (e) {
        if (!append) {
          setRows([]);
        }
        setErr(e instanceof ApiError ? e.message : 'Could not load farmers.');
      } finally {
        inFlightRef.current = false;
        setLoading(false);
        setLoadingMore(false);
      }
    },
    [ready, token],
  );

  useFocusEffect(
    useCallback(() => {
      void loadPage(1, queryRef.current, false);
    }, [loadPage]),
  );

  const submitSearch = useCallback(() => {
    const next = searchInput.trim();
    setQuery(next);
    void loadPage(1, next, false);
  }, [loadPage, searchInput]);

  const hasMore = rows.length < totalCount;

  if (loading && !rows.length) return <LoadingBlock />;

  return (
    <View style={styles.screen}>
      <AppHeader title="Farmers" subtitle="Your territory" />
      <View style={{ paddingHorizontal: space.md, marginBottom: space.sm }}>
        <View style={styles.searchWrap}>
          <Ionicons name="search" size={18} color={palette.textMuted} />
          <TextInput
            value={searchInput}
            onChangeText={setSearchInput}
            onSubmitEditing={submitSearch}
            returnKeyType="search"
            placeholder="Search name or phone…"
            placeholderTextColor={palette.textMuted}
            style={styles.search}
          />
          <Pressable onPress={submitSearch} hitSlop={8}>
            <Text style={{ color: palette.primary, fontWeight: '700' }}>Go</Text>
          </Pressable>
        </View>
      </View>
      {err && !rows.length ? (
        <ErrorState message={err} onRetry={() => void loadPage(1, query, false)} />
      ) : (
        <FlatList
          data={rows}
          keyExtractor={(item) => String(item.id)}
          contentContainerStyle={{ paddingHorizontal: space.md, paddingBottom: 32, gap: space.sm }}
          refreshControl={
            <RefreshControl
              refreshing={loading}
              onRefresh={() => void loadPage(1, query, false)}
              colors={[palette.primary]}
            />
          }
          onEndReached={() => {
            if (!hasMore || loading || loadingMore) return;
            void loadPage(page + 1, query, true);
          }}
          onEndReachedThreshold={0.4}
          ListEmptyComponent={
            <EmptyState
              title="No farmers yet"
              detail="Pull to refresh or adjust search."
              onAction={() => void loadPage(1, query, false)}
              actionLabel="Retry"
            />
          }
          ListFooterComponent={
            loadingMore ? (
              <Text style={[typography.caption, { textAlign: 'center', paddingVertical: space.md }]}>
                Loading more…
              </Text>
            ) : null
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
