/**
 * The worker home screen: tours assigned to the signed-in user
 * (GET /me/tours), each opening its map. Planning (capture/extract) is an
 * office-role flow and never shows here.
 */
import { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  AppState,
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { router, useFocusEffect } from 'expo-router';

import { ApiError, api, type TourRead } from '../api/client';

const STATUS_LABEL: Partial<Record<TourRead['status'], string>> = {
  assigned: 'Ready to start',
  in_progress: 'In progress',
};

/** "2026-07-13" → "13.07." (German short date, as on the printed plans). */
function shortDate(iso: string): string {
  const [, month, day] = iso.split('-');
  return `${day}.${month}.`;
}

export function MyToursList() {
  const [tours, setTours] = useState<TourRead[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const result = await api.myTours();
      setTours(result);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }, []);

  // Refresh whenever the screen regains focus (coming back from the map) and
  // when the app returns to the foreground, so a tour assigned while the
  // phone was pocketed appears without a reinstall.
  // TODO: push notifications on assignment would make this instant.
  useFocusEffect(
    useCallback(() => {
      void load();
    }, [load]),
  );

  useEffect(() => {
    const sub = AppState.addEventListener('change', (state) => {
      if (state === 'active') void load();
    });
    return () => sub.remove();
  }, [load]);

  async function refresh() {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }

  if (tours === null && error === null) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator size="large" />
      </View>
    );
  }

  if (error !== null && (tours === null || tours.length === 0)) {
    return (
      <View style={styles.centered}>
        <Text style={styles.errorText}>Couldn’t load your tours.</Text>
        <Text style={styles.errorDetail}>{error}</Text>
        <Pressable style={styles.button} onPress={() => void load()}>
          <Text style={styles.buttonText}>Retry</Text>
        </Pressable>
      </View>
    );
  }

  return (
    <FlatList
      data={tours}
      keyExtractor={(tour) => String(tour.id)}
      contentContainerStyle={styles.list}
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={refresh} />
      }
      ListEmptyComponent={
        <View style={styles.centered}>
          <Text style={styles.emptyTitle}>No tours assigned</Text>
          <Text style={styles.emptyDetail}>
            Your dispatcher assigns tours to you — pull down to check again.
          </Text>
        </View>
      }
      renderItem={({ item: tour }) => (
        <Pressable
          style={styles.card}
          onPress={() =>
            router.push({
              pathname: '/map',
              params: { tourId: String(tour.id) },
            })
          }
        >
          <View style={styles.cardHeader}>
            <Text style={styles.customer}>{tour.customer}</Text>
            <Text
              style={[
                styles.status,
                tour.status === 'in_progress' && styles.statusActive,
              ]}
            >
              {STATUS_LABEL[tour.status] ?? tour.status}
            </Text>
          </View>
          <Text style={styles.dates}>
            KW {tour.calendar_week} · {shortDate(tour.date_from)} –{' '}
            {shortDate(tour.date_to)}
          </Text>
        </Pressable>
      )}
    />
  );
}

const styles = StyleSheet.create({
  list: { padding: 16, gap: 12, flexGrow: 1 },
  centered: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    padding: 24,
  },
  card: {
    borderWidth: 1,
    borderColor: '#d0d7de',
    borderRadius: 12,
    backgroundColor: '#fff',
    padding: 16,
    gap: 6,
  },
  cardHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: 8,
  },
  customer: { fontSize: 17, fontWeight: '600', flexShrink: 1 },
  status: { fontSize: 13, fontWeight: '600', color: '#555' },
  statusActive: { color: '#1a7f37' },
  dates: { fontSize: 14, color: '#555' },
  emptyTitle: { fontSize: 18, fontWeight: '600' },
  emptyDetail: { fontSize: 14, color: '#555', textAlign: 'center' },
  errorText: { fontSize: 16, fontWeight: '600', color: '#b00020' },
  errorDetail: { fontSize: 13, color: '#8a2b2b', textAlign: 'center' },
  button: {
    backgroundColor: '#1f6feb',
    paddingVertical: 12,
    paddingHorizontal: 28,
    borderRadius: 8,
    alignItems: 'center',
    marginTop: 8,
  },
  buttonText: { color: '#fff', fontWeight: '600', fontSize: 15 },
});
