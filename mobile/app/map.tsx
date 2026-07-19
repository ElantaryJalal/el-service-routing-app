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
import { DayPickerSheet, type DayOption } from '../src/components/DayPickerSheet';
import { FeedbackHistorySheet } from '../src/components/FeedbackHistorySheet';
import {
  bumpStoreFeedbackCount,
  completionProgress,
  composeOptimisedTour,
  dayColor,
  etaNearClosing,
  setStopCompletion,
  setStoreAttributesComplete,
  type OptimisedStop,
  type OptimisedTour,
} from '../src/domain/optimisedTour';
import { outbox } from '../src/state/outbox';
import { tourCache } from '../src/state/tourCache';
import { useOutboxStatus } from '../src/state/useOutboxStatus';

import { Button, SyncState } from '../src/components/ui';
import { color as tk } from '../src/theme';

/** Marker colour for stops already serviced (day colour otherwise). */
const COMPLETED_GREY = tk.textFaint;

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
  const [history, setHistory] = useState<{
    storeId: number;
    title: string;
  } | null>(null);
  const [replanOpen, setReplanOpen] = useState(false);
  const [moveTarget, setMoveTarget] = useState<OptimisedStop | null>(null);
  const [planBusy, setPlanBusy] = useState(false);
  const outboxStatus = useOutboxStatus();

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
      const outcome = await outbox.enqueue({
        kind: 'complete',
        payload: { stop_id: stop.stop_id, completed: true },
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
      await outbox.enqueue({
        kind: 'complete',
        payload: { stop_id: stop.stop_id, completed: false },
      });
    } catch (err) {
      updateTour((t) => setStopCompletion(t, stop.stop_id, stop.completed_at));
      const message = err instanceof ApiError ? err.message : String(err);
      Alert.alert('Could not undo completion', message);
    }
  }

  /** Refetch the stored plan (never re-solves) and repaint + recache it. */
  async function refreshPlan(): Promise<OptimisedTour> {
    const [result, stops] = await Promise.all([
      api.getPlan(tourId),
      api.getStops(tourId),
    ]);
    const refreshed = composeOptimisedTour(result, stops);
    await tourCache.save(refreshed);
    setLoad({ state: 'ready', tour: refreshed });
    return refreshed;
  }

  async function changeDateMode(next: DateMode) {
    if (modeBusy) return;
    setModeBusy(true);
    try {
      await api.patchTour(tourId, { date_mode: next });
      await api.optimiseTour(tourId);
      await refreshPlan();
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

  /** Mid-week re-plan: unfinished stops spread over `fromDate` onwards. */
  async function replanFrom(fromDate: string) {
    setPlanBusy(true);
    try {
      const result = await api.replanTour(tourId, fromDate);
      await refreshPlan();
      setReplanOpen(false);
      setDay('all');
      setSelected(null);
      if (result.unassigned.length > 0) {
        Alert.alert(
          'Not everything fits',
          `${result.unassigned.length} stop${result.unassigned.length === 1 ? '' : 's'} don't fit into the remaining days — see the banner for details.`,
        );
      }
    } catch (err) {
      const message = err instanceof ApiError ? err.message : String(err);
      Alert.alert('Could not re-plan', message);
    } finally {
      setPlanBusy(false);
    }
  }

  /** Manual edit: move a stop to a day (end of it) or off the plan. */
  async function moveStopTo(stop: OptimisedStop, dayValue: string | null) {
    setPlanBusy(true);
    try {
      await api.moveStopPlan(stop.stop_id, dayValue);
      await refreshPlan();
      setMoveTarget(null);
      setDay('all');
      setSelected(null);
    } catch (err) {
      const message = err instanceof ApiError ? err.message : String(err);
      Alert.alert('Could not move the stop', message);
    } finally {
      setPlanBusy(false);
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
      // Replay any writes recorded offline BEFORE refetching, so the fresh
      // data already reflects them.
      await outbox.flush().catch(() => {});
      try {
        // Read-only: the stored plan, not a fresh solve — reloading the map
        // must never undo manual edits or reshuffle a week in progress.
        const [result, stops] = await Promise.all([
          api.getPlan(tourId),
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

  // Fit the map when the shown stop set changes — never on mere redraws
  // (completions, sync ticks), which must not snatch the user's zoom away.
  const lastFitRef = useRef<string>('');
  useEffect(() => {
    if (visibleStops.length === 0) return;
    const fitKey = `${day}:${visibleStops.map((s) => s.stop_id).join(',')}`;
    if (fitKey === lastFitRef.current) return;
    lastFitRef.current = fitKey;
    const coords = visibleStops.map((s) => ({ latitude: s.lat, longitude: s.lng }));
    mapRef.current?.fitToCoordinates(coords, {
      // Top padding keeps markers out from under the chip overlay.
      edgePadding: { top: 220, right: 60, bottom: 260, left: 60 },
      animated: true,
    });
  }, [visibleStops, day]);

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

  const todayISO = new Date().toISOString().slice(0, 10);
  const weekDayOptions: DayOption[] = (tour?.days ?? []).map((d) => ({
    value: d.date,
    label: formatDay(d.date),
    caption: d.date === todayISO ? 'Today' : undefined,
  }));

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
                // Amber ring: this stop has writes not yet on the server.
                outboxStatus.pendingStopIds.has(s.stop_id) && styles.pinPendingSync,
              ]}
            >
              <Text style={styles.pinText}>
                {s.completed_at ? '✓' : s.sequence}
              </Text>
            </View>
          </Marker>
        ))}
      </MapView>

      {/* Top overlay: unassigned banner + day filter. box-none: only the
          chips/buttons catch touches; the map stays pannable underneath. */}
      <View
        style={[styles.topOverlay, { paddingTop: insets.top + 8 }]}
        pointerEvents="box-none"
      >
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

        <View style={styles.controlRow} pointerEvents="box-none">
          <View style={styles.controlColumn} pointerEvents="box-none">
            <DateModeControl
              mode={tour!.date_mode}
              busy={modeBusy}
              onChange={changeDateMode}
            />
            <Pressable style={styles.replanChip} onPress={() => setReplanOpen(true)}>
              <Text style={styles.replanChipText}>🔁 Re-plan the rest…</Text>
            </Pressable>
          </View>
          <View style={styles.pillColumn} pointerEvents="box-none">
            {progress.total > 0 && (
              <View style={styles.progressPill}>
                <Text style={styles.progressText}>
                  {progress.done} of {progress.total} done
                </Text>
              </View>
            )}
            {outboxStatus.pending > 0 && (
              <SyncState
                state="pending"
                label={`${outboxStatus.pending} change${outboxStatus.pending === 1 ? '' : 's'} pending sync`}
              />
            )}
          </View>
        </View>
      </View>

      {/* Bottom overlay: tapped-stop detail */}
      {selected && (
        <StopDetailCard
          stop={selected}
          pendingSync={outboxStatus.pendingStopIds.has(selected.stop_id)}
          onClose={() => setSelected(null)}
          bottomInset={insets.bottom}
          onMarkDone={() => markDone(selected)}
          onMarkNotDone={() => markNotDone(selected)}
          onMove={() => setMoveTarget(selected)}
          onShowHistory={() =>
            selected.store_id !== null &&
            setHistory({
              storeId: selected.store_id,
              title: selected.customer ?? `Stop ${selected.stop_id}`,
            })
          }
        />
      )}

      {/* Plan editing: mid-week re-plan and manual move-to-day */}
      {replanOpen && (
        <DayPickerSheet
          title="Re-plan the rest of the week"
          message="Pick the first day to re-plan. Stops not yet done — including ones missed on earlier days — are spread over that day and after, starting from the last completed stop. Completed stops keep their history."
          options={weekDayOptions}
          busy={planBusy}
          onSelect={(value) => value && replanFrom(value)}
          onClose={() => setReplanOpen(false)}
        />
      )}
      {moveTarget && (
        <DayPickerSheet
          title={`Move ${moveTarget.customer ?? `stop ${moveTarget.stop_id}`}`}
          message="The stop is added to the end of the chosen day. Its ETA refreshes on the next re-plan."
          options={[
            ...weekDayOptions.filter((o) => o.value !== moveTarget.assigned_day),
            { value: null, label: 'Take off the plan', destructive: true },
          ]}
          busy={planBusy}
          onSelect={(value) => moveStopTo(moveTarget, value)}
          onClose={() => setMoveTarget(null)}
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
          onFeedbackSent={(s) =>
            s.store_id !== null &&
            updateTour((t) => bumpStoreFeedbackCount(t, s.store_id!))
          }
        />
      )}

      {/* Read-only visit-feedback history for the tapped stop's store */}
      {history && (
        <FeedbackHistorySheet
          storeId={history.storeId}
          title={history.title}
          onClose={() => setHistory(null)}
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
            <Button title="Close" onPress={() => setShowUnassigned(false)} />
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
  pendingSync,
  onClose,
  bottomInset,
  onMarkDone,
  onMarkNotDone,
  onMove,
  onShowHistory,
}: {
  stop: OptimisedStop;
  pendingSync: boolean;
  onClose: () => void;
  bottomInset: number;
  onMarkDone: () => void;
  onMarkNotDone: () => void;
  onMove: () => void;
  onShowHistory: () => void;
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
        {stop.store_id !== null && stop.store_feedback_count > 0 && (
          <Pressable style={styles.notesBadge} onPress={onShowHistory}>
            <Text style={styles.notesBadgeText}>
              🗒 {stop.store_feedback_count} past note
              {stop.store_feedback_count === 1 ? '' : 's'}
            </Text>
          </Pressable>
        )}
        {pendingSync && <SyncState state="pending" label="Not yet synced" />}
      </View>

      <View style={[styles.etaRow, urgent && styles.etaRowUrgent]}>
        <Text style={styles.etaLabel}>ETA</Text>
        <Text style={[styles.etaValue, urgent && styles.etaValueUrgent]}>
          {stop.eta ? toHHMM(stop.eta) : '—'}
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

      {/* Thumb row: the screen's ONE primary action (Mark done) beside
          Navigate; everything else stays quiet below. */}
      <View style={styles.actionRow}>
        <Button title="Navigate" onPress={navigate} style={styles.flex} />
        {stop.completed_at === null && (
          <Button
            title="Mark done ✓"
            variant="primary"
            onPress={onMarkDone}
            style={styles.flex}
          />
        )}
      </View>
      {stop.completed_at === null ? (
        <Button title="Move to another day…" variant="ghost" onPress={onMove} />
      ) : (
        <Button
          title="Completed — mark as not done"
          variant="ghost"
          onPress={onMarkNotDone}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  centered: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 12, padding: 24 },
  muted: { fontSize: 15, color: tk.textMuted, textAlign: 'center' },
  errorText: { fontSize: 15, color: tk.danger, textAlign: 'center' },

  pin: {
    minWidth: 26,
    height: 26,
    borderRadius: 13,
    paddingHorizontal: 6,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 2,
    borderColor: tk.onBrand,
  },
  pinText: { color: tk.onBrand, fontWeight: '700', fontSize: 13 },
  pinCompleted: { opacity: 0.7 },
  pinPendingSync: { borderColor: tk.warning },

  pillColumn: { gap: 6, alignItems: 'flex-end' },

  controlRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    gap: 8,
  },
  controlColumn: { gap: 6, alignItems: 'flex-start' },
  replanChip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    backgroundColor: tk.surface,
    borderRadius: 18,
    paddingVertical: 8,
    paddingHorizontal: 14,
    borderWidth: 1,
    borderColor: tk.border,
    elevation: 2,
  },
  replanChipText: { fontWeight: '600', color: tk.text, fontSize: 13 },
  progressPill: {
    backgroundColor: tk.surface,
    borderRadius: 18,
    paddingVertical: 8,
    paddingHorizontal: 14,
    borderWidth: 1,
    borderColor: tk.border,
    elevation: 2,
  },
  progressText: { fontWeight: '700', color: tk.status.done, fontSize: 13 },

  topOverlay: { position: 'absolute', top: 0, left: 0, right: 0, gap: 8, paddingHorizontal: 12 },
  banner: {
    backgroundColor: tk.warningBg,
    borderColor: tk.warningBorder,
    borderWidth: 1,
    borderRadius: 10,
    paddingVertical: 10,
    paddingHorizontal: 14,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  bannerText: { color: tk.warningText, fontWeight: '600', fontSize: 14, flex: 1 },
  bannerLink: { color: tk.brand, fontWeight: '700' },

  chips: { gap: 8, paddingRight: 12 },
  chip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    backgroundColor: tk.surface,
    borderRadius: 18,
    paddingVertical: 8,
    paddingHorizontal: 14,
    borderWidth: 1,
    borderColor: tk.border,
    elevation: 2,
  },
  chipActive: { backgroundColor: tk.brand, borderColor: tk.brand },
  chipText: { fontWeight: '600', color: tk.text },
  chipTextActive: { color: tk.onBrand },
  chipDot: { width: 10, height: 10, borderRadius: 5 },

  detailCard: {
    position: 'absolute',
    left: 12,
    right: 12,
    bottom: 12,
    backgroundColor: tk.surface,
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
  actionRow: { flexDirection: 'row', gap: 8 },
  detailTitle: { fontSize: 18, fontWeight: '700' },
  detailAddress: { fontSize: 14, color: tk.textMuted, marginTop: 2 },
  close: { fontSize: 18, color: tk.textFaint, paddingHorizontal: 4 },
  metaRow: { flexDirection: 'row', gap: 8, alignItems: 'center' },
  dayBadge: { borderRadius: 8, paddingVertical: 4, paddingHorizontal: 10 },
  dayBadgeText: { color: tk.onBrand, fontWeight: '700', fontSize: 13 },
  notesBadge: {
    borderRadius: 8,
    paddingVertical: 4,
    paddingHorizontal: 10,
    backgroundColor: tk.soft,
  },
  notesBadgeText: { color: tk.brand, fontWeight: '600', fontSize: 13 },
  etaRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    flexWrap: 'wrap',
    backgroundColor: tk.bg,
    borderRadius: 8,
    padding: 10,
  },
  etaRowUrgent: { backgroundColor: tk.dangerBg },
  etaLabel: { fontSize: 12, color: tk.textMuted },
  etaValue: { fontSize: 16, fontWeight: '700', color: tk.text },
  etaValueUrgent: { color: tk.danger },
  urgentHint: { color: tk.danger, fontSize: 13, fontWeight: '600' },
  remarks: {
    backgroundColor: tk.warningBg,
    borderLeftWidth: 3,
    borderLeftColor: tk.warning,
    paddingHorizontal: 8,
    paddingVertical: 4,
    fontSize: 13,
    color: tk.warningText,
  },
  taskChips: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  taskChip: { backgroundColor: tk.soft, borderRadius: 14, paddingVertical: 4, paddingHorizontal: 10 },
  taskChipText: { fontSize: 13, color: tk.text },


  modalBackdrop: { flex: 1, backgroundColor: tk.scrim, justifyContent: 'flex-end' },
  modalCard: {
    backgroundColor: tk.surface,
    borderTopLeftRadius: 16,
    borderTopRightRadius: 16,
    padding: 20,
    gap: 12,
    maxHeight: '70%',
  },
  modalTitle: { fontSize: 20, fontWeight: '700' },
  modalList: { flexGrow: 0 },
  unassignedRow: { paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: tk.border },
  unassignedLabel: { fontSize: 15, fontWeight: '600' },
  unassignedReason: { fontSize: 13, color: tk.danger, marginTop: 2 },
});
