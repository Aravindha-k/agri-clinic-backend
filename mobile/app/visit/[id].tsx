import { useCallback, useState } from 'react';
import {
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { router, useLocalSearchParams } from 'expo-router';
import { useFocusEffect } from '@react-navigation/native';
import { BackHeader } from '@/components/ui/AppHeader';
import { Card } from '@/components/ui/Card';
import { SectionTitle, ErrorState, LoadingBlock } from '@/components/ui/States';
import { useAuth } from '@/context/AuthContext';
import { ApiError, fetchVisitDetail, patchVisit, VisitDetailDto } from '@/lib/api';
import {
  formatVisitDateTime,
  visitCropLabel,
  visitFarmerLabel,
  visitHasGps,
  visitVillageLabel,
} from '@/lib/visitDisplay';
import { palette, space, typography } from '@/constants/theme';

export default function VisitDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const visitId = Number(id);
  const { token } = useAuth();
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [v, setV] = useState<VisitDetailDto | null>(null);
  const [notes, setNotes] = useState('');

  const load = useCallback(async () => {
    if (!token || !visitId) return;
    setErr(null);
    setLoading(true);
    try {
      const row = await fetchVisitDetail(token, visitId);
      setV(row);
      setNotes(row.notes || '');
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : 'Could not open visit.');
    } finally {
      setLoading(false);
    }
  }, [token, visitId]);

  useFocusEffect(
    useCallback(() => {
      void load();
    }, [load]),
  );

  async function saveNotes() {
    if (!token || !v) return;
    try {
      await patchVisit(token, v.id, { notes: notes.trim() });
      await load();
    } catch {
      // optional edit — ignore for read-mostly flow
    }
  }

  if (loading && !v) return <LoadingBlock />;
  if (err || !v) return <ErrorState message={err || 'Not found'} onRetry={load} />;

  return (
    <View style={styles.screen}>
      <BackHeader title={`Visit #${v.id}`} onBack={() => router.back()} />
      <ScrollView
        contentContainerStyle={{ padding: space.md }}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={load} colors={[palette.primary]} />}>
        <Card style={{ marginBottom: space.md }}>
          <Text style={typography.overline}>Field visit</Text>
          <Text style={[typography.subtitle, { marginTop: space.xs }]}>
            {formatVisitDateTime(v)}
          </Text>
          <Text style={[typography.caption, { marginTop: space.sm }]}>
            GPS: {visitHasGps(v) ? 'captured' : 'not recorded'}
          </Text>
        </Card>

        <SectionTitle>Farmer & location</SectionTitle>
        <Card style={{ marginBottom: space.md }}>
          <Text style={typography.subtitle}>{visitFarmerLabel(v)}</Text>
          <Text style={typography.caption}>{visitVillageLabel(v)}</Text>
          {v.farmer_phone || v.farmer?.phone ? (
            <Text style={typography.caption}>Phone: {v.farmer_phone || v.farmer?.phone}</Text>
          ) : null}
        </Card>

        <SectionTitle>Field & crop</SectionTitle>
        <Card style={{ marginBottom: space.md }}>
          <Text style={typography.body}>Field: {v.field?.land_name || v.land_name || '—'}</Text>
          <Text style={[typography.body, { marginTop: space.xs }]}>Crop: {visitCropLabel(v)}</Text>
          {v.crop_stage ? (
            <Text style={[typography.caption, { marginTop: space.xs }]}>Stage: {v.crop_stage}</Text>
          ) : null}
        </Card>

        <SectionTitle>Observations</SectionTitle>
        <Card style={{ marginBottom: space.md }}>
          <Text style={typography.caption}>Pest: {v.pest_issue ? 'Yes' : 'No'}</Text>
          <Text style={typography.caption}>Disease: {v.disease_issue ? 'Yes' : 'No'}</Text>
          <TextInput
            value={notes}
            onChangeText={setNotes}
            onBlur={saveNotes}
            placeholder="Notes"
            multiline
            placeholderTextColor={palette.textMuted}
            style={[styles.input, { marginTop: space.sm }]}
          />
        </Card>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: palette.background },
  input: {
    borderWidth: 1,
    borderColor: palette.border,
    borderRadius: 8,
    padding: space.sm,
    color: palette.text,
    backgroundColor: palette.surface,
    minHeight: 72,
  },
});
