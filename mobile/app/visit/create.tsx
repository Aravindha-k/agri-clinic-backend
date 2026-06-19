import { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { router } from 'expo-router';
import { BackHeader } from '@/components/ui/AppHeader';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { useAuth } from '@/context/AuthContext';
import {
  ApiError,
  createVisit,
  createFarmer,
  FarmerListItem,
  fetchFarmersPage,
  fetchVillages,
} from '@/lib/api';
import { useMasters } from '@/hooks/useMasters';
import {
  captureLocation,
  locationFailureMessage,
  locationFailureTitle,
  openLocationSettings,
} from '@/lib/geo';
import { palette, space, typography } from '@/constants/theme';

type Step = 0 | 1 | 2 | 3;

export default function CreateVisitWizard() {
  const { token } = useAuth();
  const { districts, crops, reload: reloadMasters } = useMasters(token);
  const [step, setStep] = useState<Step>(0);
  const [farmers, setFarmers] = useState<FarmerListItem[]>([]);
  const [farmerSearch, setFarmerSearch] = useState('');
  const [selectedFarmer, setSelectedFarmer] = useState<FarmerListItem | null>(null);
  const [qcOpen, setQcOpen] = useState(false);
  const [qcName, setQcName] = useState('');
  const [qcPhone, setQcPhone] = useState('');
  const [qcDistrict, setQcDistrict] = useState<number | null>(null);
  const [villages, setVillages] = useState<{ id: number; name: string }[]>([]);
  const [qcVillage, setQcVillage] = useState<number | null>(null);
  const [selectedFieldId, setSelectedFieldId] = useState<number | null>(null);
  const [selectedCropId, setSelectedCropId] = useState<number | null>(null);
  const [pest, setPest] = useState(false);
  const [disease, setDisease] = useState(false);
  const [notes, setNotes] = useState('');
  const [busy, setBusy] = useState(false);

  const loadFarmers = useCallback(async () => {
    if (!token) return;
    const page = await fetchFarmersPage(token, 1, farmerSearch);
    setFarmers(page.results);
  }, [token, farmerSearch]);

  const loadVillages = useCallback(async () => {
    if (!token || !qcDistrict) {
      setVillages([]);
      return;
    }
    const v = await fetchVillages(token, qcDistrict);
    setVillages(v.map((x) => ({ id: x.id, name: x.name })));
  }, [token, qcDistrict]);

  useEffect(() => {
    void loadVillages();
  }, [loadVillages]);

  const today = useMemo(() => new Date().toISOString().slice(0, 10), []);

  async function quickCreateFarmer() {
    if (!token) return;
    if (!qcName.trim() || !qcPhone.trim()) {
      Alert.alert('Missing', 'Name and phone are required.');
      return;
    }
    setBusy(true);
    try {
      const f = await createFarmer(token, {
        name: qcName.trim(),
        phone: qcPhone.trim(),
        district: qcDistrict,
        village: qcVillage,
      });
      setSelectedFarmer(f);
      setQcOpen(false);
      setStep(1);
      await loadFarmers();
    } catch (e) {
      Alert.alert('Could not create farmer', e instanceof ApiError ? e.message : 'Error');
    } finally {
      setBusy(false);
    }
  }

  async function submit() {
    if (!token || !selectedFarmer) return;
    if (!selectedCropId) {
      Alert.alert('Crop required', 'Pick a crop for this visit.');
      return;
    }
    setBusy(true);
    const loc = await captureSilentLocation();
    if (!loc) {
      Alert.alert(
        'Location needed',
        'Enable location permission so we can attach a visit fix (coordinates are not shown in the form).',
      );
      setBusy(false);
      return;
    }
    try {
      const body: Record<string, unknown> = {
        farmer: selectedFarmer.id,
        crop: selectedCropId,
        visit_date: today,
        notes: notes.trim() || undefined,
        pest_issue: pest,
        disease_issue: disease,
        latitude: loc.latitude,
        longitude: loc.longitude,
      };
      if (selectedFieldId) body.field = selectedFieldId;
      await createVisit(token, body);
      Alert.alert('Visit saved', 'Field visit recorded successfully.', [
        { text: 'OK', onPress: () => router.replace('/(tabs)/visits') },
      ]);
    } catch (e) {
      Alert.alert('Could not save visit', e instanceof ApiError ? e.message : 'Error');
    } finally {
      setBusy(false);
    }
  }

  const fields = selectedFarmer?.fields as { id: number; land_name: string }[] | undefined;

  return (
    <View style={styles.screen}>
      <BackHeader title="New visit" onBack={() => router.back()} />
      <ScrollView contentContainerStyle={{ padding: space.md, paddingBottom: 48 }}>
        <Text style={typography.caption}>
          Step {step + 1} of 4 — {['Farmer', 'Field', 'Crop & issues', 'Review'][step]}
        </Text>

        {step === 0 ? (
          <Card style={{ marginTop: space.md }}>
            <Text style={typography.subtitle}>Farmer</Text>
            <TextInput
              value={farmerSearch}
              onChangeText={setFarmerSearch}
              onSubmitEditing={() => loadFarmers()}
              placeholder="Search then load list"
              placeholderTextColor={palette.textMuted}
              style={styles.input}
            />
            <Button title="Load farmers" variant="secondary" onPress={() => loadFarmers()} />
            <View style={{ maxHeight: 240, marginTop: space.sm }}>
              {farmers.slice(0, 50).map((item) => (
                <Pressable
                  key={item.id}
                  style={[styles.pick, selectedFarmer?.id === item.id && styles.pickOn]}
                  onPress={() => setSelectedFarmer(item)}>
                  <Text style={typography.body}>{item.name}</Text>
                  <Text style={typography.caption}>{item.phone}</Text>
                </Pressable>
              ))}
            </View>
            <Pressable onPress={() => setQcOpen(!qcOpen)} style={{ marginTop: space.md }}>
              <Text style={[typography.caption, { color: palette.primary }]}>
                {qcOpen ? 'Hide quick add farmer' : '+ Quick add farmer'}
              </Text>
            </Pressable>
            {qcOpen ? (
              <View style={{ marginTop: space.sm, gap: space.sm }}>
                <TextInput
                  value={qcName}
                  onChangeText={setQcName}
                  placeholder="Farmer name"
                  placeholderTextColor={palette.textMuted}
                  style={styles.input}
                />
                <TextInput
                  value={qcPhone}
                  onChangeText={setQcPhone}
                  placeholder="Phone"
                  keyboardType="phone-pad"
                  placeholderTextColor={palette.textMuted}
                  style={styles.input}
                />
                <Text style={typography.caption}>District</Text>
                {districts.map((d) => (
                  <Pressable
                    key={d.id}
                    style={[styles.pick, qcDistrict === d.id && styles.pickOn]}
                    onPress={() => setQcDistrict(d.id)}>
                    <Text style={typography.body}>{d.name}</Text>
                  </Pressable>
                ))}
                {villages.length ? (
                  <>
                    <Text style={typography.caption}>Village</Text>
                    {villages.map((v) => (
                      <Pressable
                        key={v.id}
                        style={[styles.pick, qcVillage === v.id && styles.pickOn]}
                        onPress={() => setQcVillage(v.id)}>
                        <Text style={typography.body}>{v.name}</Text>
                      </Pressable>
                    ))}
                  </>
                ) : null}
                <Button title="Save farmer" onPress={quickCreateFarmer} loading={busy} />
              </View>
            ) : null}
            <Button
              title="Next"
              style={{ marginTop: space.md }}
              disabled={!selectedFarmer}
              onPress={() => setStep(1)}
            />
          </Card>
        ) : null}

        {step === 1 ? (
          <Card style={{ marginTop: space.md }}>
            <Text style={typography.subtitle}>Field (optional)</Text>
            {(fields?.length ? fields : [{ id: 0, land_name: 'No named field' }]).map((f) => (
              <Pressable
                key={f.id}
                style={[
                  styles.pick,
                  (selectedFieldId === f.id || (!selectedFieldId && f.id === 0)) && styles.pickOn,
                ]}
                onPress={() => setSelectedFieldId(f.id === 0 ? null : f.id)}>
                <Text style={typography.body}>{f.land_name}</Text>
              </Pressable>
            ))}
            <View style={styles.row}>
              <Button title="Back" variant="secondary" onPress={() => setStep(0)} />
              <Button title="Next" onPress={() => setStep(2)} />
            </View>
          </Card>
        ) : null}

        {step === 2 ? (
          <Card style={{ marginTop: space.md }}>
            <Text style={typography.subtitle}>Crop & observations</Text>
            {crops.map((c) => (
              <Pressable
                key={c.id}
                style={[styles.pick, selectedCropId === c.id && styles.pickOn]}
                onPress={() => setSelectedCropId(c.id)}>
                <Text style={typography.body}>{c.name_en}</Text>
              </Pressable>
            ))}
            <Pressable style={styles.checkRow} onPress={() => setPest(!pest)}>
              <Text style={typography.body}>Pest issue</Text>
              <Text style={typography.caption}>{pest ? 'Yes' : 'No'}</Text>
            </Pressable>
            <Pressable style={styles.checkRow} onPress={() => setDisease(!disease)}>
              <Text style={typography.body}>Disease issue</Text>
              <Text style={typography.caption}>{disease ? 'Yes' : 'No'}</Text>
            </Pressable>
            <TextInput
              value={notes}
              onChangeText={setNotes}
              placeholder="Notes"
              multiline
              placeholderTextColor={palette.textMuted}
              style={[styles.input, { minHeight: 80 }]}
            />
            <View style={styles.row}>
              <Button title="Back" variant="secondary" onPress={() => setStep(1)} />
              <Button title="Next" onPress={() => setStep(3)} />
            </View>
          </Card>
        ) : null}

        {step === 3 ? (
          <Card style={{ marginTop: space.md }}>
            <Text style={typography.subtitle}>Review & submit</Text>
            <Text style={typography.body}>Farmer: {selectedFarmer?.name}</Text>
            <Text style={typography.caption}>Date: {today}</Text>
            <Text style={[typography.caption, { marginTop: space.sm }]}>
              GPS is captured when you submit. The visit is saved as a completed field record.
            </Text>
            <View style={[styles.row, { marginTop: space.md }]}>
              <Button title="Back" variant="secondary" onPress={() => setStep(2)} />
              <Button title="Submit visit" onPress={submit} loading={busy} />
            </View>
          </Card>
        ) : null}

        <Button
          title="Reload crops"
          variant="secondary"
          style={{ marginTop: space.lg }}
          onPress={() => reloadMasters()}
        />
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
    marginTop: space.xs,
    color: palette.text,
    backgroundColor: palette.surface,
  },
  pick: {
    padding: space.sm,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: palette.border,
    marginTop: space.xs,
    backgroundColor: palette.surface,
  },
  pickOn: { borderColor: palette.primary, backgroundColor: palette.accentSoft },
  row: { flexDirection: 'row', gap: space.sm, marginTop: space.md },
  checkRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingVertical: space.sm,
    borderBottomWidth: 1,
    borderBottomColor: palette.border,
  },
});
