import { useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Linking,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import MapView, { Marker, Polyline, PROVIDER_GOOGLE } from 'react-native-maps';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useLocalSearchParams } from 'expo-router';

import { ApiError, api, type DateMode } from '../src/api/client';
import {
  CompletionSheet,
  type CompletionSync,
} from '../src/components/CompletionSheet';
import { DateModeControl } from '../src/components/DateModeControl';
import {
  completionProgress,
  composeOptimisedTour,
  dayColor,
  etaNearClosing,
  setStopCompletion,
  setStoreAttributesComplete,
  type OptimisedStop,
  type OptimisedTour,
} from '../src/domain/optimisedTour';
import { mutationQueue } from '../src/state/mutationQueue';
import { tourCache } from '../src/state/tourCache';

/** Marker colour for stops already serviced (day colour otherwise). */
const COMPLETED_GREY = '#9aa0a6';

type Load =
  | { state: 'loading' }
  | { state: 'ready'; tour: OptimisedTour }
  | { state: 'error'; message: string };

type DayFilter = number | 'all';

const LEIPZIG = { latitude: 51.3397, longitude: 12.3731 };

function toHHMM(time: string): string {
  const m = /^(\d{1,2}):(\d{2})/.exec(time);
  return m ? `${m[1].padStart(2, '0')}:${m[2]}` : time;
}

function formatDay(date: string): string {
  const d = new Date(`${date}T00:00:00`);
  const wd = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][d.getDay()];
  const dd = String(d.getDate()).padStart(2, '0');
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  return `${wd} ${dd}.${mm}`;
}

function regionFor(stops: OptimisedStop[]) {
  if (stops.length === 0) {
    return { ...LEIPZIG, latitudeDelta: 0.4, longitudeDelta: 0.4 };
  }
  const lats = stops.map((s) => s.lat);
  const lngs = stops.map((s) => s.lng);
  const minLat = Math.min(...lats);
  const maxLat = Math.max(...lats);
  const minLng = Math.min(...lngs);
  const maxLng = Math.max(...lngs);
  return {
    latitude: (minLat + maxLat) / 2,
    longitude: (minLng + maxLng) / 2,
    latitudeDelta: Math.max((maxLat - minLat) * 1.4, 0.02),
    longitudeDelta: Math.max((maxLng - minLng) * 1.4, 0.02),
  };
}

export default function MapScreen() {
  const params = useLocalSearchParams<{ tourId?: string }>();
  const tourId = Number(params.tourId);
  const insets = useSafeAreaInsets();
  const mapRef = useRef<MapView>(null);

  const [load, setLoad] = useState<Load>({ state: 'loading' });
  const [day, setDay] = useState<DayFilter>('all');
  const [selected, setSelected] = useState<OptimisedStop | null>(null);
  const [showUnassigned, setShowUnassigned] = useState(false);
  const [modeBusy, setModeBusy] = useState(false);
  const [sheet, setSheet] = useState<{
    stop: OptimisedStop;
    sync: CompletionSync;
  } | null>(null);

  /** Apply a local tour change and persist it to the offline cache. */
  function updateTour(fn: (t: OptimisedTour) => OptimisedTour) {
    setLoad((prev) => {
      if (prev.state !== 'ready') return prev;
      const updated = fn(prev.tour);
      tourCache.save(updated).catch(() => {});
      return { state: 'ready', tour: updated };
    });
  }

  /** Tier 1: local-first completion, then sheet with tiers 2/3. */
  async function markDone(stop: OptimisedStop) {
    updateTour((t) => setStopCompletion(t, stop.stop_id, new Date().toISOString()));
    setSelected(null);
    setSheet({ stop, sync: 'pending' });
    try {
      const outcome = await mutationQueue.run({
        kind: 'complete',
        stopId: stop.stop_id,
      });
      setSheet((s) =>
        s && s.stop.stop_id === stop.stop_id ? { ...s, sync: outcome } : s,
      );
    } catch (err) {
      // Backend rejected it outright (not an offline hiccup): roll back.
      updateTour((t) => setStopCompletion(t, stop.stop_id, null));
      setSheet(null);
      const message = err instanceof ApiError ? err.message : String(err);
      Alert.alert('Could not mark done', message);
    }
  }

  /** Undo a mis-tap: clear completed_at (works offline like completion). */
  async function markNotDone(stop: OptimisedStop) {
    updateTour((t) => setStopCompletion(t, stop.stop_id, null));
    setSelected(null);
    try {
      await mutationQueue.run({ kind: 'uncomplete', stopId: stop.stop_id });
    } catch (err) {
      updateTour((t) => setStopCompletion(t, stop.stop_id, stop.completed_at));
      const message = err instanceof ApiError ? err.message : String(err);
      Alert.alert('Could not undo completion', message);
    }
  }

  async function changeDateMode(next: DateMode) {
    if (modeBusy) return;
    setModeBusy(true);
    try {
      await api.patchTour(tourId, { date_mode: next });
      const [result, stops] = await Promise.all([
        api.optimiseTour(tourId),
        api.getStops(tourId),
      ]);
      const refreshed = composeOptimisedTour(result, stops);
      await tourCache.save(refreshed);
      setLoad({ state: 'ready', tour: refreshed });
      setDay('all'); // day contents shifted; a kept index would mislead
      setSelected(null);
    } catch (err) {
      // Keep the current schedule; mode changes need the backend.
      const message = err instanceof ApiError ? err.message : String(err);
      Alert.alert('Could not change date mode', message);
    } finally {
      setModeBusy(false);
    }
  }

  useEffect(() => {
    if (!Number.isFinite(tourId)) {
      setLoad({ state: 'error', message: 'Missing tour id.' });
      return;
    }
    let alive = true;
    (async () => {
      // Offline-first, then revalidate: paint the cached schedule immediately
      // so the map works with no signal, but always try to refresh from the
      // network — otherwise a re-optimised plan never reaches the screen.
      const cached = await tourCache.load(tourId);
      if (cached && alive) setLoad({ state: 'ready', tour: cached });
      // Replay any completions/feedback recorded offline BEFORE refetching,
      // so the fresh data already reflects them.
      await mutationQueue.flush().catch(() => {});
      try {
        const [result, stops] = await Promise.all([
          api.optimiseTour(tourId),
          api.getStops(tourId),
        ]);
        const tour = composeOptimisedTour(result, stops);
        await tourCache.save(tour);
        if (alive) setLoad({ state: 'ready', tour });
      } catch (err) {
        // Offline (or backend down): stay on the cached schedule if we have
        // one; only surface the error on a cold open.
        if (!cached && alive) {
          const message = err instanceof ApiError ? err.message : String(err);
          setLoad({ state: 'error', message });
        }
      }
    })();
    return () => {
      alive = false;
    };
  }, [tourId]);

  const tour = load.state === 'ready' ? load.tour : null;

  const allStops = useMemo(
    () => tour?.days.flatMap((d) => d.stops) ?? [],
    [tour],
  );

  const visibleStops = useMemo(() => {
    if (!tour) return [];
    if (day === 'all') return allStops;
    return tour.days[day]?.stops ?? [];
  }, [tour, day, allStops]);

  // Fit the map to whatever is currently shown.
  useEffect(() => {
    if (visibleStops.length === 0) return;
    const coords = visibleStops.map((s) => ({ latitude: s.lat, longitude: s.lng }));
    mapRef.current?.fitToCoordinates(coords, {
      edgePadding: { top: 140, right: 60, bottom: 260, left: 60 },
      animated: true,
    });
  }, [visibleStops]);

  if (load.state === 'loading') {
    return (
      <View style={styles.centered}>
        <ActivityIndicator size="large" />
        <Text style={styles.muted}>Loading route…</Text>
      </View>
    );
  }
  if (load.state === 'error') {
    return (
      <View style={styles.centered}>
        <Text style={styles.errorText}>{load.message}</Text>
        <Text style={styles.muted}>
          No cached route for this tour — run Optimise while online first.
        </Text>
      </View>
    );
  }

  // Completed stops drop out of the active route line (but stay tappable).
  const routeCoords =
    day !== 'all'
      ? visibleStops
          .filter((s) => s.completed_at === null)
          .map((s) => ({ latitude: s.lat, longitude: s.lng }))
      : [];

  const progress = completionProgress(visibleStops);

  return (
    <View style={styles.flex}>
      <MapView
        ref={mapRef}
        style={StyleSheet.absoluteFill}
        provider={Platform.OS === 'android' ? PROVIDER_GOOGLE : undefined}
        initialRegion={regionFor(allStops)}
        onPress={() => setSelected(null)}
      >
        {/* Single-day route line. v1 connects stops in sequence with straight
            segments. TODO(backend): expose OSRM route geometry per day (e.g.
            GET /tours/{id}/route?date=) and draw the real driven path. */}
        {routeCoords.length > 1 && (
          <Polyline
            coordinates={routeCoords}
            strokeColor={dayColor(day as number)}
            strokeWidth={3}
          />
        )}

        {visibleStops.map((s) => (
          <Marker
            key={s.stop_id}
            coordinate={{ latitude: s.lat, longitude: s.lng }}
            onPress={() => setSelected(s)}
            anchor={{ x: 0.5, y: 0.5 }}
          >
            <View
              style={[
                styles.pin,
                {
                  backgroundColor: s.completed_at
                    ? COMPLETED_GREY
                    : dayColor(s.dayIndex),
                },
                s.completed_at !== null && styles.pinCompleted,
              ]}
            >
              <Text style={styles.pinText}>
                {s.completed_at ? '✓' : s.sequence}
              </Text>
            </View>
          </Marker>
        ))}
      </MapView>

      {/* Top overlay: unassigned banner + day filter */}
      <View style={[styles.topOverlay, { paddingTop: insets.top + 8 }]}>
        {tour!.unassigned.length > 0 && (
          <Pressable style={styles.banner} onPress={() => setShowUnassigned(true)}>
            <Text style={styles.bannerText}>
              ⚠︎ {tour!.unassigned.length} market
              {tour!.unassigned.length === 1 ? '' : 's'} don’t fit this week
            </Text>
            <Text style={styles.bannerLink}>View</Text>
          </Pressable>
        )}

        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.chips}
        >
          <Chip label="All" active={day === 'all'} onPress={() => setDay('all')} />
          {tour!.days.map((d) => (
            <Chip
              key={d.date}
              label={`${formatDay(d.date)}`}
              color={dayColor(d.dayIndex)}
              active={day === d.dayIndex}
              onPress={() => setDay(d.dayIndex)}
            />
          ))}
        </ScrollView>

        <View style={styles.controlRow}>
          <DateModeControl
            mode={tour!.date_mode}
            busy={modeBusy}
            onChange={changeDateMode}
          />
          {progress.total > 0 && (
            <View style={styles.progressPill}>
              <Text style={styles.progressText}>
                {progress.done} of {progress.total} done
              </Text>
            </View>
          )}
        </View>
      </View>

      {/* Bottom overlay: tapped-stop detail */}
      {selected && (
        <StopDetailCard
          stop={selected}
          onClose={() => setSelected(null)}
          bottomInset={insets.bottom}
          onMarkDone={() => markDone(selected)}
          onMarkNotDone={() => markNotDone(selected)}
        />
      )}

      {/* Completion sheet: tier 1 status + optional store info + feedback */}
      {sheet && (
        <CompletionSheet
          stop={sheet.stop}
          sync={sheet.sync}
          onClose={() => setSheet(null)}
          onAttributesSaved={(storeId) =>
            updateTour((t) => setStoreAttributesComplete(t, storeId, true))
          }
        />
      )}

      {/* Unassigned list */}
      <Modal visible={showUnassigned} transparent animationType="slide">
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Doesn’t fit this week</Text>
            <ScrollView style={styles.modalList}>
              {tour!.unassigned.map((u) => (
                <View key={u.stop_id} style={styles.unassignedRow}>
                  <Text style={styles.unassignedLabel}>{u.label}</Text>
                  <Text style={styles.unassignedReason}>{u.reason}</Text>
                </View>
              ))}
            </ScrollView>
            <Pressable style={styles.button} onPress={() => setShowUnassigned(false)}>
              <Text style={styles.buttonText}>Close</Text>
            </Pressable>
          </View>
        </View>
      </Modal>
    </View>
  );
}

function Chip({
  label,
  active,
  color,
  onPress,
}: {
  label: string;
  active: boolean;
  color?: string;
  onPress: () => void;
}) {
  return (
    <Pressable style={[styles.chip, active && styles.chipActive]} onPress={onPress}>
      {color && <View style={[styles.chipDot, { backgroundColor: color }]} />}
      <Text style={[styles.chipText, active && styles.chipTextActive]}>{label}</Text>
    </Pressable>
  );
}

function StopDetailCard({
  stop,
  onClose,
  bottomInset,
  onMarkDone,
  onMarkNotDone,
}: {
  stop: OptimisedStop;
  onClose: () => void;
  bottomInset: number;
  onMarkDone: () => void;
  onMarkNotDone: () => void;
}) {
  const urgent = etaNearClosing(stop.eta, stop.closing_time);
  const address = [
    stop.street,
    [stop.postal_code, stop.city].filter(Boolean).join(' '),
  ]
    .filter(Boolean)
    .join(', ');

  function navigate() {
    const { lat, lng } = stop;
    const fallback = `https://www.google.com/maps/dir/?api=1&destination=${lat},${lng}`;
    const url =
      Platform.select({
        ios: `maps://?daddr=${lat},${lng}&dirflg=d`,
        android: `google.navigation:q=${lat},${lng}`,
      }) ?? fallback;
    Linking.openURL(url).catch(() => Linking.openURL(fallback));
  }

  return (
    <View style={[styles.detailCard, { paddingBottom: 16 + bottomInset }]}>
      <View style={styles.detailHeader}>
        <View style={styles.flex}>
          <Text style={styles.detailTitle}>
            {stop.customer ?? `Stop ${stop.stop_id}`}
          </Text>
          {address ? <Text style={styles.detailAddress}>{address}</Text> : null}
        </View>
        <Pressable onPress={onClose} hitSlop={10}>
          <Text style={styles.close}>✕</Text>
        </Pressable>
      </View>

      <View style={styles.metaRow}>
        <View style={[styles.dayBadge, { backgroundColor: dayColor(stop.dayIndex) }]}>
          <Text style={styles.dayBadgeText}>
            {formatDay(stop.assigned_day)} · #{stop.sequence}
          </Text>
        </View>
      </View>

      <View style={[styles.etaRow, urgent && styles.etaRowUrgent]}>
        <Text style={styles.etaLabel}>ETA</Text>
        <Text style={[styles.etaValue, urgent && styles.etaValueUrgent]}>
          {toHHMM(stop.eta)}
        </Text>
        <Text style={styles.etaLabel}>Closes</Text>
        <Text style={[styles.etaValue, urgent && styles.etaValueUrgent]}>
          {stop.closing_time ? toHHMM(stop.closing_time) : '—'}
        </Text>
        <Text style={styles.etaLabel}>{stop.service_minutes ?? '—'} min on site</Text>
      </View>
      {urgent && (
        <Text style={styles.urgentHint}>Tight — arrives close to closing time.</Text>
      )}

      {stop.remarks && <Text style={styles.remarks}>{stop.remarks}</Text>}

      {stop.tasks.length > 0 && (
        <View style={styles.taskChips}>
          {stop.tasks.map((t, i) => (
            <View key={i} style={styles.taskChip}>
              <Text style={styles.taskChipText}>{t}</Text>
            </View>
          ))}
        </View>
      )}

      <Pressable style={styles.button} onPress={navigate}>
        <Text style={styles.buttonText}>Navigate</Text>
      </Pressable>

      {stop.completed_at === null ? (
        <Pressable style={styles.doneButton} onPress={onMarkDone}>
          <Text style={styles.buttonText}>Mark done ✓</Text>
        </Pressable>
      ) : (
        <Pressable style={styles.undoButton} onPress={onMarkNotDone}>
          <Text style={styles.undoButtonText}>Completed — mark as not done</Text>
        </Pressable>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  centered: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 12, padding: 24 },
  muted: { fontSize: 15, color: '#555', textAlign: 'center' },
  errorText: { fontSize: 15, color: '#b00020', textAlign: 'center' },

  pin: {
    minWidth: 26,
    height: 26,
    borderRadius: 13,
    paddingHorizontal: 6,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 2,
    borderColor: '#fff',
  },
  pinText: { color: '#fff', fontWeight: '700', fontSize: 13 },
  pinCompleted: { opacity: 0.7 },

  controlRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    gap: 8,
  },
  progressPill: {
    backgroundColor: '#fff',
    borderRadius: 18,
    paddingVertical: 8,
    paddingHorizontal: 14,
    borderWidth: 1,
    borderColor: '#ddd',
    elevation: 2,
  },
  progressText: { fontWeight: '700', color: '#1a7f37', fontSize: 13 },

  topOverlay: { position: 'absolute', top: 0, left: 0, right: 0, gap: 8, paddingHorizontal: 12 },
  banner: {
    backgroundColor: '#fff3cd',
    borderColor: '#f0b429',
    borderWidth: 1,
    borderRadius: 10,
    paddingVertical: 10,
    paddingHorizontal: 14,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  bannerText: { color: '#7a5b00', fontWeight: '600', fontSize: 14, flex: 1 },
  bannerLink: { color: '#1f6feb', fontWeight: '700' },

  chips: { gap: 8, paddingRight: 12 },
  chip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    backgroundColor: '#fff',
    borderRadius: 18,
    paddingVertical: 8,
    paddingHorizontal: 14,
    borderWidth: 1,
    borderColor: '#ddd',
    elevation: 2,
  },
  chipActive: { backgroundColor: '#1f6feb', borderColor: '#1f6feb' },
  chipText: { fontWeight: '600', color: '#333' },
  chipTextActive: { color: '#fff' },
  chipDot: { width: 10, height: 10, borderRadius: 5 },

  detailCard: {
    position: 'absolute',
    left: 12,
    right: 12,
    bottom: 12,
    backgroundColor: '#fff',
    borderRadius: 14,
    padding: 16,
    gap: 10,
    elevation: 6,
    shadowColor: '#000',
    shadowOpacity: 0.15,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 4 },
  },
  detailHeader: { flexDirection: 'row', alignItems: 'flex-start', gap: 8 },
  detailTitle: { fontSize: 18, fontWeight: '700' },
  detailAddress: { fontSize: 14, color: '#666', marginTop: 2 },
  close: { fontSize: 18, color: '#999', paddingHorizontal: 4 },
  metaRow: { flexDirection: 'row', gap: 8 },
  dayBadge: { borderRadius: 8, paddingVertical: 4, paddingHorizontal: 10 },
  dayBadgeText: { color: '#fff', fontWeight: '700', fontSize: 13 },
  etaRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    flexWrap: 'wrap',
    backgroundColor: '#f5f7fa',
    borderRadius: 8,
    padding: 10,
  },
  etaRowUrgent: { backgroundColor: '#fdecea' },
  etaLabel: { fontSize: 12, color: '#777' },
  etaValue: { fontSize: 16, fontWeight: '700', color: '#222' },
  etaValueUrgent: { color: '#b00020' },
  urgentHint: { color: '#b00020', fontSize: 13, fontWeight: '600' },
  remarks: {
    backgroundColor: '#fff8e8',
    borderLeftWidth: 3,
    borderLeftColor: '#f6a609',
    paddingHorizontal: 8,
    paddingVertical: 4,
    fontSize: 13,
    color: '#5c4a12',
  },
  taskChips: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  taskChip: { backgroundColor: '#eef2f7', borderRadius: 14, paddingVertical: 4, paddingHorizontal: 10 },
  taskChipText: { fontSize: 13, color: '#334' },

  button: {
    backgroundColor: '#1f6feb',
    paddingVertical: 13,
    borderRadius: 8,
    alignItems: 'center',
  },
  buttonText: { color: '#fff', fontWeight: '700', fontSize: 16 },
  doneButton: {
    backgroundColor: '#1a7f37',
    paddingVertical: 13,
    borderRadius: 8,
    alignItems: 'center',
  },
  undoButton: {
    backgroundColor: '#f1f3f5',
    paddingVertical: 13,
    borderRadius: 8,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: '#ccc',
  },
  undoButtonText: { color: '#555', fontWeight: '600', fontSize: 15 },

  modalBackdrop: { flex: 1, backgroundColor: '#00000088', justifyContent: 'flex-end' },
  modalCard: {
    backgroundColor: '#fff',
    borderTopLeftRadius: 16,
    borderTopRightRadius: 16,
    padding: 20,
    gap: 12,
    maxHeight: '70%',
  },
  modalTitle: { fontSize: 20, fontWeight: '700' },
  modalList: { flexGrow: 0 },
  unassignedRow: { paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: '#eee' },
  unassignedLabel: { fontSize: 15, fontWeight: '600' },
  unassignedReason: { fontSize: 13, color: '#b00020', marginTop: 2 },
});
