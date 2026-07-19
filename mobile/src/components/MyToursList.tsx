/**
 * The worker home screen: tours assigned to the signed-in user
 * (GET /me/tours), each opening its map. Planning (capture/extract) is an
 * office-role flow and never shows here.
 */
import { useCallback, useEffect, useState } from 'react';
import { AppState, FlatList, RefreshControl, StyleSheet, Text, View } from 'react-native';
import { router, useFocusEffect } from 'expo-router';

import { ApiError, api, type TourRead } from '../api/client';
import { Button, EmptyState, Loading, StopCard, type Status } from './ui';
import { color, font, space } from '../theme';

const STATUS_LABEL: Partial<Record<TourRead['status'], string>> = {
  assigned: 'Ready to start',
  in_progress: 'In progress',
};

/** Worker tours only carry lifecycle statuses the shared chip knows. */
function chipStatus(status: TourRead['status']): Status {
  return (
    ['draft', 'planned', 'assigned', 'in_progress', 'done'].includes(status)
      ? status
      : 'planned'
  ) as Status;
}

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
        <Loading label="Loading your tours…" />
      </View>
    );
  }

  if (error !== null && (tours === null || tours.length === 0)) {
    return (
      <View style={styles.centered}>
        <Text style={styles.errorText}>Couldn’t load your tours.</Text>
        <Text style={styles.errorDetail}>{error}</Text>
        <Button title="Retry" variant="primary" onPress={() => void load()} />
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
        <EmptyState
          title="No tours assigned"
          hint="Your dispatcher assigns tours to you — pull down to check again."
        />
      }
      renderItem={({ item: tour }) => (
        <StopCard
          title={tour.customer}
          subtitle={`KW ${tour.calendar_week} · ${shortDate(tour.date_from)} – ${shortDate(tour.date_to)}`}
          status={chipStatus(tour.status)}
          statusLabel={STATUS_LABEL[tour.status]}
          onPress={() =>
            router.push({
              pathname: '/map',
              params: { tourId: String(tour.id) },
            })
          }
        />
      )}
    />
  );
}

const styles = StyleSheet.create({
  list: { padding: space.s4, flexGrow: 1 },
  centered: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: space.s2,
    padding: space.s6,
  },
  errorText: {
    fontSize: font.size.md,
    fontWeight: font.weight.semibold,
    color: color.danger,
  },
  errorDetail: {
    fontSize: font.size.sm,
    color: color.dangerText,
    textAlign: 'center',
  },
});
