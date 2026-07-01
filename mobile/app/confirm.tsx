import { useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Image,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { router, useLocalSearchParams } from 'expo-router';

import {
  ApiError,
  api,
  type DraftConfidence,
  type DraftStop,
  type DraftStopUpdate,
  type DuplicateGroup,
  type DuplicateResolution,
  type TourDraft,
} from '../src/api/client';
import { draftStore } from '../src/state/draftStore';
import { DraftStopCard } from '../src/components/DraftStopCard';

type Load =
  | { state: 'loading' }
  | { state: 'ready'; draft: TourDraft }
  | { state: 'error'; message: string };

export default function ConfirmScreen() {
  const params = useLocalSearchParams<{ tourId?: string }>();
  const tourId = Number(params.tourId);

  const [load, setLoad] = useState<Load>({ state: 'loading' });
  const [stops, setStops] = useState<DraftStop[]>([]);
  const [committing, setCommitting] = useState(false);

  // Duplicate merge/keep prompt.
  const [dupes, setDupes] = useState<DuplicateGroup[] | null>(null);
  const [resolutions, setResolutions] = useState<Record<string, 'merge' | 'keep'>>({});

  useEffect(() => {
    if (!Number.isFinite(tourId)) {
      setLoad({ state: 'error', message: 'Missing tour id.' });
      return;
    }
    const cached = draftStore.get(tourId);
    if (cached) {
      setStops(cached.stops);
      setLoad({ state: 'ready', draft: cached });
      return;
    }
    // Fallback: reloaded/deep-linked without the in-memory draft.
    let alive = true;
    api
      .getDraft(tourId)
      .then((draft) => {
        if (!alive) return;
        draftStore.set(draft);
        setStops(draft.stops);
        setLoad({ state: 'ready', draft });
      })
      .catch((err) => {
        if (!alive) return;
        const message = err instanceof ApiError ? err.message : String(err);
        setLoad({ state: 'error', message });
      });
    return () => {
      alive = false;
    };
  }, [tourId]);

  async function handlePatch(stopId: number, fields: DraftStopUpdate) {
    try {
      const updated = await api.patchDraftStop(tourId, stopId, fields);
      // Editing a field verifies it — drop its low-confidence flag locally.
      const confidence: DraftConfidence = { ...updated.confidence };
      for (const key of Object.keys(fields) as (keyof DraftStopUpdate)[]) {
        delete confidence[key];
      }
      const merged: DraftStop = { ...updated, confidence };
      setStops((prev) => prev.map((s) => (s.id === stopId ? merged : s)));
      draftStore.setStop(tourId, merged);
    } catch (err) {
      const message = err instanceof ApiError ? err.message : String(err);
      Alert.alert('Save failed', `${message}\n\nYour edit was not saved.`);
    }
  }

  async function commit(res?: DuplicateResolution[]) {
    setCommitting(true);
    try {
      const result = await api.commitTour(tourId, res);
      if (result.duplicate_groups && result.duplicate_groups.length > 0) {
        const initial: Record<string, 'merge' | 'keep'> = {};
        for (const g of result.duplicate_groups) initial[g.key] = 'merge';
        setResolutions(initial);
        setDupes(result.duplicate_groups);
        setCommitting(false);
        return;
      }
      draftStore.clear(tourId);
      router.replace({ pathname: '/review', params: { tourId: String(tourId) } });
    } catch (err) {
      const message = err instanceof ApiError ? err.message : String(err);
      Alert.alert('Commit failed', message);
      setCommitting(false);
    }
  }

  function applyResolutions() {
    if (!dupes) return;
    const list: DuplicateResolution[] = dupes.map((g) => ({
      key: g.key,
      action: resolutions[g.key] ?? 'merge',
    }));
    setDupes(null);
    commit(list);
  }

  if (load.state === 'loading') {
    return (
      <View style={styles.centered}>
        <ActivityIndicator size="large" />
        <Text style={styles.muted}>Loading draft…</Text>
      </View>
    );
  }

  if (load.state === 'error') {
    return (
      <View style={styles.centered}>
        <Text style={styles.errorText}>{load.message}</Text>
        <Pressable style={styles.button} onPress={() => router.back()}>
          <Text style={styles.buttonText}>Back to Capture</Text>
        </Pressable>
      </View>
    );
  }

  const photoUri = load.draft.photo_uri;

  return (
    <View style={styles.flex}>
      <ScrollView contentContainerStyle={styles.container}>
        <Text style={styles.title}>Confirm stops</Text>
        <Text style={styles.subtitle}>
          Check each row against the photo. Fields flagged in amber were read with
          low confidence. Set how long each market takes — it drives the plan.
        </Text>

        {photoUri && (
          <Image source={{ uri: photoUri }} style={styles.photo} resizeMode="contain" />
        )}

        {stops.map((stop, i) => (
          <DraftStopCard
            key={stop.id}
            index={i}
            stop={stop}
            onPatch={(fields) => handlePatch(stop.id, fields)}
          />
        ))}

        {stops.length === 0 && (
          <Text style={styles.muted}>No stops were extracted from this plan.</Text>
        )}
      </ScrollView>

      <View style={styles.footer}>
        <Pressable
          style={[styles.button, (committing || stops.length === 0) && styles.buttonDisabled]}
          onPress={() => commit()}
          disabled={committing || stops.length === 0}
        >
          {committing ? (
            <ActivityIndicator color="#fff" />
          ) : (
            <Text style={styles.buttonText}>Commit tour</Text>
          )}
        </Pressable>
      </View>

      {/* Duplicate merge/keep prompt */}
      <Modal visible={dupes !== null} transparent animationType="fade">
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Possible duplicates</Text>
            <Text style={styles.modalSubtitle}>
              These stops look like the same market. Merge them into one, or keep
              them separate.
            </Text>
            <ScrollView style={styles.modalList}>
              {dupes?.map((g) => (
                <View key={g.key} style={styles.dupeRow}>
                  <View style={styles.dupeInfo}>
                    <Text style={styles.dupeLabel}>{g.label}</Text>
                    <Text style={styles.dupeCount}>{g.stop_ids.length} stops</Text>
                  </View>
                  <View style={styles.toggle}>
                    {(['merge', 'keep'] as const).map((action) => (
                      <Pressable
                        key={action}
                        style={[
                          styles.toggleBtn,
                          resolutions[g.key] === action && styles.toggleBtnActive,
                        ]}
                        onPress={() =>
                          setResolutions((r) => ({ ...r, [g.key]: action }))
                        }
                      >
                        <Text
                          style={[
                            styles.toggleText,
                            resolutions[g.key] === action && styles.toggleTextActive,
                          ]}
                        >
                          {action === 'merge' ? 'Merge' : 'Keep'}
                        </Text>
                      </Pressable>
                    ))}
                  </View>
                </View>
              ))}
            </ScrollView>
            <Pressable style={styles.button} onPress={applyResolutions}>
              <Text style={styles.buttonText}>Apply and commit</Text>
            </Pressable>
            <Pressable style={styles.linkBtn} onPress={() => setDupes(null)}>
              <Text style={styles.linkText}>Back to editing</Text>
            </Pressable>
          </View>
        </View>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  container: { padding: 16, gap: 14, paddingBottom: 24 },
  centered: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 12, padding: 24 },
  title: { fontSize: 24, fontWeight: '700' },
  subtitle: { fontSize: 14, color: '#555' },
  muted: { fontSize: 15, color: '#555' },
  photo: {
    width: '100%',
    height: 200,
    borderRadius: 10,
    backgroundColor: '#f0f0f0',
  },
  footer: {
    padding: 16,
    borderTopWidth: 1,
    borderTopColor: '#eee',
    backgroundColor: '#fff',
  },
  button: {
    backgroundColor: '#1f6feb',
    paddingVertical: 14,
    borderRadius: 8,
    alignItems: 'center',
  },
  buttonDisabled: { opacity: 0.5 },
  buttonText: { color: '#fff', fontWeight: '700', fontSize: 16 },
  errorText: { fontSize: 15, color: '#b00020', textAlign: 'center' },
  modalBackdrop: {
    flex: 1,
    backgroundColor: '#00000088',
    justifyContent: 'center',
    padding: 20,
  },
  modalCard: {
    backgroundColor: '#fff',
    borderRadius: 14,
    padding: 20,
    gap: 12,
    maxHeight: '80%',
  },
  modalTitle: { fontSize: 20, fontWeight: '700' },
  modalSubtitle: { fontSize: 14, color: '#555' },
  modalList: { flexGrow: 0 },
  dupeRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: '#eee',
    gap: 8,
  },
  dupeInfo: { flex: 1 },
  dupeLabel: { fontSize: 15, fontWeight: '600' },
  dupeCount: { fontSize: 13, color: '#777' },
  toggle: { flexDirection: 'row', borderWidth: 1, borderColor: '#1f6feb', borderRadius: 8, overflow: 'hidden' },
  toggleBtn: { paddingVertical: 8, paddingHorizontal: 14 },
  toggleBtnActive: { backgroundColor: '#1f6feb' },
  toggleText: { color: '#1f6feb', fontWeight: '600' },
  toggleTextActive: { color: '#fff' },
  linkBtn: { alignItems: 'center', paddingVertical: 6 },
  linkText: { color: '#1f6feb', fontSize: 15 },
});
