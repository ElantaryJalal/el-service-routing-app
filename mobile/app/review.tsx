import { useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { router, useLocalSearchParams } from 'expo-router';

import { ApiError, api, type StopDetail } from '../src/api/client';
import type { components } from '../src/api/types';
import { ReviewStopCard } from '../src/components/ReviewStopCard';
import { composeOptimisedTour } from '../src/domain/optimisedTour';
import { tourCache } from '../src/state/tourCache';

type StopUpdate = components['schemas']['StopUpdate'];

type Load =
  | { state: 'loading' }
  | { state: 'ready' }
  | { state: 'error'; message: string };

export default function ReviewScreen() {
  const params = useLocalSearchParams<{ tourId?: string }>();
  const tourId = Number(params.tourId);

  const [load, setLoad] = useState<Load>({ state: 'loading' });
  const [stops, setStops] = useState<StopDetail[]>([]);
  const [optimising, setOptimising] = useState(false);

  useEffect(() => {
    if (!Number.isFinite(tourId)) {
      setLoad({ state: 'error', message: 'Missing tour id.' });
      return;
    }
    let alive = true;
    api
      .getStops(tourId)
      .then((s) => {
        if (!alive) return;
        setStops(s);
        setLoad({ state: 'ready' });
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

  async function handlePatch(stopId: number, fields: StopUpdate) {
    try {
      const updated = await api.patchStop(stopId, fields);
      // patchStop returns StopRead (no coords/address); keep our detail fields.
      setStops((prev) =>
        prev.map((s) =>
          s.id === stopId
            ? {
                ...s,
                closing_time: updated.closing_time,
                opening_time: updated.opening_time,
                service_minutes: updated.service_minutes,
                hours_source: updated.hours_source,
                status: updated.status,
              }
            : s,
        ),
      );
    } catch (err) {
      const message = err instanceof ApiError ? err.message : String(err);
      Alert.alert('Save failed', `${message}\n\nYour edit was not saved.`);
    }
  }

  async function optimise() {
    setOptimising(true);
    try {
      const result = await api.optimiseTour(tourId);
      const tour = composeOptimisedTour(result, stops);
      await tourCache.save(tour); // refresh offline cache on every optimise
      router.push({ pathname: '/map', params: { tourId: String(tourId) } });
    } catch (err) {
      const message = err instanceof ApiError ? err.message : String(err);
      Alert.alert('Optimise failed', message);
    } finally {
      setOptimising(false);
    }
  }

  if (load.state === 'loading') {
    return (
      <View style={styles.centered}>
        <ActivityIndicator size="large" />
        <Text style={styles.muted}>Loading committed stops…</Text>
      </View>
    );
  }

  if (load.state === 'error') {
    return (
      <View style={styles.centered}>
        <Text style={styles.errorText}>{load.message}</Text>
        <Pressable style={styles.button} onPress={() => router.replace('/')}>
          <Text style={styles.buttonText}>Back to Capture</Text>
        </Pressable>
      </View>
    );
  }

  return (
    <View style={styles.flex}>
      <ScrollView contentContainerStyle={styles.container}>
        <Text style={styles.title}>Review & schedule</Text>
        <Text style={styles.subtitle}>
          Check each market’s closing time — a wrong one can make a whole day
          impossible. Adjust service times too, then optimise.
        </Text>

        {stops.map((stop) => (
          <ReviewStopCard
            key={stop.id}
            stop={stop}
            onPatch={(fields) => handlePatch(stop.id, fields)}
          />
        ))}

        {stops.length === 0 && (
          <Text style={styles.muted}>This tour has no committed stops.</Text>
        )}
      </ScrollView>

      <View style={styles.footer}>
        <Pressable
          style={[styles.button, (optimising || stops.length === 0) && styles.buttonDisabled]}
          onPress={optimise}
          disabled={optimising || stops.length === 0}
        >
          {optimising ? (
            <ActivityIndicator color="#fff" />
          ) : (
            <Text style={styles.buttonText}>Optimise route</Text>
          )}
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  container: { padding: 16, gap: 12, paddingBottom: 24 },
  centered: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 12, padding: 24 },
  title: { fontSize: 24, fontWeight: '700' },
  subtitle: { fontSize: 14, color: '#555' },
  muted: { fontSize: 15, color: '#555' },
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
});
