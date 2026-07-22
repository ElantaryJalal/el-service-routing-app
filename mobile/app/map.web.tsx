/**
 * Web-only Map route (react-native-maps is native-only, so the browser build
 * gets this Leaflet version). Same data path as the native map: reads the
 * composed OptimisedTour from the offline cache (written when Optimise runs),
 * falling back to the network. Renders day-coloured numbered markers, a per-day
 * route polyline, click popups with a Navigate link, and the unassigned banner.
 *
 * Deliberately lightweight — Leaflet is pulled from a CDN at runtime — as the
 * seed of the office dashboard.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { useLocalSearchParams } from 'expo-router';

import { ApiError, api, type DateMode, type PullCandidate } from '../src/api/client';
import {
  CompletionSheet,
  type CompletionSync,
} from '../src/components/CompletionSheet';
import { DateModeControl } from '../src/components/DateModeControl';
import { SyncState } from '../src/components/ui';
import { DayPickerSheet, type DayOption } from '../src/components/DayPickerSheet';
import { FeedbackHistorySheet } from '../src/components/FeedbackHistorySheet';
import { StopDetailSheet } from '../src/components/StopDetailSheet';
import { AddStopSheet } from '../src/components/AddStopSheet';
import {
  bumpStoreFeedbackCount,
  completionProgress,
  composeOptimisedTour,
  dayColor,
  setStopCompletion,
  setStoreAttributes,
  setStoreAttributesComplete,
  stopTitle,
  type OptimisedStop,
  type OptimisedTour,
} from '../src/domain/optimisedTour';
import { outbox } from '../src/state/outbox';
import { useSession } from '../src/state/session';
import { tourCache } from '../src/state/tourCache';
import { useOutboxStatus } from '../src/state/useOutboxStatus';

import { color as tk } from '../src/theme';

const COMPLETED_GREY = tk.textFaint;

type Load =
  | { state: 'loading' }
  | { state: 'ready'; tour: OptimisedTour }
  | { state: 'error'; message: string };

type DayFilter = number | 'all';

const LEAFLET_JS = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
const LEAFLET_CSS = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';

let leafletPromise: Promise<any> | null = null;

/** Load Leaflet from the CDN once and resolve the global `L`. */
function loadLeaflet(): Promise<any> {
  if (typeof window === 'undefined') return Promise.reject(new Error('no window'));
  const w = window as any;
  if (w.L) return Promise.resolve(w.L);
  if (leafletPromise) return leafletPromise;
  leafletPromise = new Promise((resolve, reject) => {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = LEAFLET_CSS;
    document.head.appendChild(link);
    const script = document.createElement('script');
    script.src = LEAFLET_JS;
    script.onload = () => resolve(w.L);
    script.onerror = () => reject(new Error('failed to load Leaflet'));
    document.head.appendChild(script);
  });
  return leafletPromise;
}

function formatDay(date: string): string {
  const d = new Date(`${date}T00:00:00`);
  const wd = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][d.getDay()];
  return `${wd} ${String(d.getDate()).padStart(2, '0')}.${String(d.getMonth() + 1).padStart(2, '0')}`;
}

export default function MapWebScreen() {
  const params = useLocalSearchParams<{ tourId?: string }>();
  const tourId = Number(params.tourId);

  const [load, setLoad] = useState<Load>({ state: 'loading' });
  const [day, setDay] = useState<DayFilter>('all');
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
  const [detail, setDetail] = useState<OptimisedStop | null>(null);
  const [planBusy, setPlanBusy] = useState(false);
  const outboxStatus = useOutboxStatus();

  // Planning how the week is scheduled is the dispatcher's job — the worker
  // executes it. Hide date-mode + re-plan from workers; keep per-stop moves.
  const { user } = useSession();
  const isOffice = user != null && user.role !== 'worker';

  // Keep the selected day chip scrolled into view so it never hides off-edge.
  const chipScrollRef = useRef<ScrollView | null>(null);
  const chipPos = useRef<Record<string, number>>({});
  useEffect(() => {
    const x = chipPos.current[String(day)];
    if (x != null) chipScrollRef.current?.scrollTo({ x: Math.max(0, x - 16), animated: true });
  }, [day]);

  // "Add another stop" (smart pull-forward) — needs a connection to route.
  const [online, setOnline] = useState(
    typeof navigator === 'undefined' ? true : navigator.onLine,
  );
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const on = () => setOnline(true);
    const off = () => setOnline(false);
    window.addEventListener('online', on);
    window.addEventListener('offline', off);
    return () => {
      window.removeEventListener('online', on);
      window.removeEventListener('offline', off);
    };
  }, []);
  const [addStopOpen, setAddStopOpen] = useState(false);
  const [pull, setPull] = useState<{
    loading: boolean;
    candidates: PullCandidate[] | null;
    error: string | null;
  }>({ loading: false, candidates: null, error: null });
  const [pullBusyId, setPullBusyId] = useState<number | null>(null);

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
      window.alert(`Could not mark done: ${message}`);
    }
  }

  /** Undo a mis-tap: clear completed_at (works offline like completion). */
  async function markNotDone(stop: OptimisedStop) {
    updateTour((t) => setStopCompletion(t, stop.stop_id, null));
    try {
      await outbox.enqueue({
        kind: 'complete',
        payload: { stop_id: stop.stop_id, completed: false },
      });
    } catch (err) {
      updateTour((t) => setStopCompletion(t, stop.stop_id, stop.completed_at));
      const message = err instanceof ApiError ? err.message : String(err);
      window.alert(`Could not undo completion: ${message}`);
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
    } catch (err) {
      // Keep the current schedule; mode changes need the backend.
      const message = err instanceof ApiError ? err.message : String(err);
      window.alert(`Could not change date mode: ${message}`);
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
      if (result.unassigned.length > 0) {
        window.alert(
          `${result.unassigned.length} stop${result.unassigned.length === 1 ? '' : 's'} don't fit into the remaining days — see the banner for details.`,
        );
      }
    } catch (err) {
      const message = err instanceof ApiError ? err.message : String(err);
      window.alert(`Could not re-plan: ${message}`);
    } finally {
      setPlanBusy(false);
    }
  }

  /** Manual edit: move a stop to a day (end of it) or off the plan. */
  async function moveStopTo(stop: OptimisedStop, dayValue: string | null) {
    setPlanBusy(true);
    try {
      await api.moveStopPlan(stop.stop_id, dayValue);
      const refreshed = await refreshPlan();
      setMoveTarget(null);
      // Land on the day the stop moved to: the route line is drawn per-day, so
      // the 'all' overview would hide it. Off-plan moves fall back to 'all'.
      const target = dayValue
        ? refreshed.days.find((d) => d.date === dayValue)
        : undefined;
      setDay(target ? target.dayIndex : 'all');
    } catch (err) {
      const message = err instanceof ApiError ? err.message : String(err);
      window.alert(`Could not move the stop: ${message}`);
    } finally {
      setPlanBusy(false);
    }
  }

  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<any>(null);
  const layerRef = useRef<any>(null);
  // Which stop set the view was last fitted to: re-fit only when it changes,
  // never on mere redraws (completions, sync ticks) — those must not snatch
  // the user's zoom/pan away.
  const lastFitRef = useRef<string>('');

  useEffect(() => {
    if (!Number.isFinite(tourId)) {
      setLoad({ state: 'error', message: 'Missing tour id.' });
      return;
    }
    let alive = true;
    (async () => {
      // Offline-first, then revalidate: paint the cached schedule immediately,
      // but always try to refresh from the network — otherwise a re-optimised
      // plan never reaches the screen.
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
  const allStops = useMemo(() => tour?.days.flatMap((d) => d.stops) ?? [], [tour]);
  const visibleStops = useMemo(() => {
    if (!tour) return [];
    return day === 'all' ? allStops : (tour.days[day]?.stops ?? []);
  }, [tour, day, allStops]);

  const progress = completionProgress(visibleStops);
  // Finish-early prompt: offered once the worker is down to the last stop of
  // the day in view (and while it stays done), so "Add another stop" appears
  // as they're wrapping up — never as a mid-route distraction.
  const onLastStop = progress.total > 0 && progress.total - progress.done <= 1;

  // The worker's "today": the day in view, else the day of their latest
  // completed stop, else the first day. Pull-forward adds to this day.
  function currentDayISO(): string | null {
    if (!tour) return null;
    if (day !== 'all') return tour.days[day]?.date ?? null;
    let latestAt: string | null = null;
    let latestDate: string | null = tour.days[0]?.date ?? null;
    for (const d of tour.days)
      for (const s of d.stops)
        if (s.completed_at && (!latestAt || s.completed_at > latestAt)) {
          latestAt = s.completed_at;
          latestDate = d.date;
        }
    return latestDate;
  }

  // Fallback position when geolocation is unavailable: the last stop finished.
  function lastCompletedCoord(): { lat: number; lng: number } | null {
    if (!tour) return null;
    let latestAt: string | null = null;
    let coord: { lat: number; lng: number } | null = null;
    for (const d of tour.days)
      for (const s of d.stops)
        if (
          s.completed_at &&
          (s.lat !== 0 || s.lng !== 0) &&
          (!latestAt || s.completed_at > latestAt)
        ) {
          latestAt = s.completed_at;
          coord = { lat: s.lat, lng: s.lng };
        }
    return coord;
  }

  function currentPosition(): Promise<{ lat: number; lng: number } | null> {
    return new Promise((resolve) => {
      if (typeof navigator === 'undefined' || !navigator.geolocation)
        return resolve(null);
      navigator.geolocation.getCurrentPosition(
        (p) => resolve({ lat: p.coords.latitude, lng: p.coords.longitude }),
        () => resolve(null),
        { timeout: 8000, maximumAge: 60000 },
      );
    });
  }

  async function openAddStop() {
    setAddStopOpen(true);
    setPull({ loading: true, candidates: null, error: null });
    const today = currentDayISO();
    if (!today) {
      setPull({ loading: false, candidates: [], error: 'No day to add to yet.' });
      return;
    }
    const from = (await currentPosition()) ?? lastCompletedCoord();
    if (!from) {
      setPull({
        loading: false,
        candidates: null,
        error: "Can't tell where you are — turn on location, or finish a stop first.",
      });
      return;
    }
    try {
      const candidates = await api.pullCandidates(tourId, from.lat, from.lng, today);
      setPull({ loading: false, candidates, error: null });
    } catch (err) {
      const message = err instanceof ApiError ? err.message : String(err);
      setPull({ loading: false, candidates: null, error: message });
    }
  }

  async function addCandidate(stopId: number) {
    const today = currentDayISO();
    if (!today) return;
    setPullBusyId(stopId);
    try {
      await api.pullStopIntoToday(tourId, stopId, today);
      const refreshed = await refreshPlan();
      const target = refreshed.days.find((d) => d.date === today);
      setDay(target ? target.dayIndex : 'all');
      setAddStopOpen(false);
    } catch (err) {
      const message = err instanceof ApiError ? err.message : String(err);
      window.alert(`Could not add the stop: ${message}`);
    } finally {
      setPullBusyId(null);
    }
  }

  const todayISO = new Date().toISOString().slice(0, 10);
  const weekDayOptions: DayOption[] = (tour?.days ?? []).map((d) => ({
    value: d.date,
    label: formatDay(d.date),
    caption: d.date === todayISO ? 'Today' : undefined,
  }));

  // Draw markers + polyline whenever the tour or the day filter changes.
  useEffect(() => {
    if (!tour || !containerRef.current) return;
    let cancelled = false;
    loadLeaflet()
      .then((L) => {
        if (cancelled || !containerRef.current) return;
        if (!mapRef.current) {
          // Zoom buttons live bottom-right: Leaflet's default top-left spot
          // sits underneath the day-chip overlay.
          mapRef.current = L.map(containerRef.current, { zoomControl: false }).setView(
            [51.34, 12.37],
            10,
          );
          L.control.zoom({ position: 'bottomright' }).addTo(mapRef.current);
          L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '© OpenStreetMap contributors',
            maxZoom: 19,
          }).addTo(mapRef.current);
        }
        const map = mapRef.current;
        setTimeout(() => map.invalidateSize(), 0); // container may have just sized

        if (layerRef.current) layerRef.current.remove();
        const group = L.layerGroup().addTo(map);
        layerRef.current = group;

        const stops = visibleStops.filter((s) => s.lat !== 0 || s.lng !== 0);

        // One route line per day, coloured by day. In a single-day view only
        // that day is drawn; in the 'all' overview every day's line shows, so
        // the week always reads as linked routes. Completed stops drop out of
        // the active line (still tappable).
        const daysToDraw = day === 'all' ? tour.days : [tour.days[day]];
        for (const d of daysToDraw) {
          if (!d) continue;
          const active = d.stops.filter(
            (s) => s.completed_at === null && (s.lat !== 0 || s.lng !== 0),
          );
          if (active.length > 1) {
            L.polyline(
              active.map((s) => [s.lat, s.lng]),
              { color: dayColor(d.dayIndex), weight: 3, opacity: 0.8 },
            ).addTo(group);
          }
        }

        for (const s of stops) {
          const completed = s.completed_at !== null;
          const pendingSync = outboxStatus.pendingStopIds.has(s.stop_id);
          const color = completed ? COMPLETED_GREY : dayColor(s.dayIndex);
          // Amber ring: this stop has writes not yet on the server.
          const ring = pendingSync ? tk.warning : tk.onBrand;
          const icon = L.divIcon({
            className: '',
            html: `<div style="background:${color};width:24px;height:24px;border-radius:12px;border:2px solid ${ring};color:${tk.onBrand};font-weight:700;display:flex;align-items:center;justify-content:center;font-size:12px;box-shadow:0 1px 3px rgba(0,0,0,.4);${completed ? 'opacity:.75' : ''}">${completed ? '✓' : s.sequence}</div>`,
            iconSize: [24, 24],
            iconAnchor: [12, 12],
          });
          // Tapping a marker opens the stop detail as a bottom sheet (see
          // StopDetailSheet) rather than a desktop-sized Leaflet popup.
          L.marker([s.lat, s.lng], { icon })
            .on('click', () => setDetail(s))
            .addTo(group);
        }

        const fitKey = `${day}:${stops.map((s) => s.stop_id).join(',')}`;
        if (stops.length > 0 && fitKey !== lastFitRef.current) {
          lastFitRef.current = fitKey;
          // Extra top padding keeps markers out from under the chip overlay.
          map.fitBounds(
            L.latLngBounds(stops.map((s) => [s.lat, s.lng])),
            {
              paddingTopLeft: [50, 210],
              paddingBottomRight: [50, 50],
              maxZoom: 14,
            },
          );
        }
      })
      .catch((err) => {
        if (!cancelled) setLoad({ state: 'error', message: String(err) });
      });
    return () => {
      cancelled = true;
    };
  }, [tour, day, visibleStops, outboxStatus]);

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
        <Text style={styles.muted}>Run Optimise while online first.</Text>
      </View>
    );
  }

  return (
    <View style={styles.flex}>
      {/* Leaflet renders into this DOM node (react-native-web View === div). */}
      <View ref={containerRef as any} style={styles.map} />

      {/* box-none: only the chips/buttons themselves catch the pointer, so
          markers and the zoom control underneath stay clickable. */}
      <View style={styles.topOverlay} pointerEvents="box-none">
        {tour!.unassigned.length > 0 && (
          <Pressable style={styles.banner} onPress={() => setShowUnassigned((v) => !v)}>
            <Text style={styles.bannerText}>
              ⚠︎ {tour!.unassigned.length} market
              {tour!.unassigned.length === 1 ? '' : 's'} don’t fit this week
            </Text>
            <Text style={styles.bannerLink}>{showUnassigned ? 'Hide' : 'View'}</Text>
          </Pressable>
        )}
        {showUnassigned && (
          <View style={styles.unassignedBox}>
            {tour!.unassigned.map((u) => (
              <Text key={u.stop_id} style={styles.unassignedRow}>
                • {u.label} — <Text style={styles.unassignedReason}>{u.reason}</Text>
              </Text>
            ))}
          </View>
        )}

        <ScrollView
          ref={chipScrollRef}
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.chips}
        >
          <Chip
            label="All"
            active={day === 'all'}
            onPress={() => setDay('all')}
            onLayoutX={(x) => (chipPos.current.all = x)}
          />
          {tour!.days
            .filter((d) => d.stops.length > 0)
            .map((d) => (
              <Chip
                key={d.date}
                label={formatDay(d.date)}
                color={dayColor(d.dayIndex)}
                active={day === d.dayIndex}
                onPress={() => setDay(d.dayIndex)}
                onLayoutX={(x) => (chipPos.current[d.dayIndex] = x)}
              />
            ))}
        </ScrollView>

        <View style={styles.controlRow} pointerEvents="box-none">
          {/* Planning controls are office-only; workers execute the plan. */}
          {isOffice && (
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
          )}
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

        {/* Smart pull-forward: shown only once the worker is on the last stop
            of the day in view — they're finishing early and can pull a later
            stop into today. Disabled offline since it routes live. */}
        {onLastStop && (
          <Pressable
            style={[styles.addStop, styles.addStopHot, !online && styles.addStopOff]}
            onPress={online ? openAddStop : undefined}
            disabled={!online}
          >
            <Text style={[styles.addStopText, styles.addStopTextHot]}>
              ＋ Add another stop{online ? '' : ' · needs signal'}
            </Text>
          </Pressable>
        )}
      </View>

      {/* Add-another-stop (smart pull-forward) sheet. */}
      {addStopOpen && (
        <AddStopSheet
          loading={pull.loading}
          candidates={pull.candidates}
          error={pull.error}
          online={online}
          addingId={pullBusyId}
          onAdd={addCandidate}
          onClose={() => setAddStopOpen(false)}
        />
      )}

      {/* Tapped-stop detail as a dismissible bottom sheet. */}
      {detail && (
        <StopDetailSheet
          stop={detail}
          pendingSync={outboxStatus.pendingStopIds.has(detail.stop_id)}
          onClose={() => setDetail(null)}
          onMarkDone={() => {
            const s = detail;
            setDetail(null);
            markDone(s);
          }}
          onMarkNotDone={() => {
            const s = detail;
            setDetail(null);
            markNotDone(s);
          }}
          onMove={() => {
            setMoveTarget(detail);
            setDetail(null);
          }}
          onShowHistory={() => {
            if (detail.store_id !== null) {
              setHistory({
                storeId: detail.store_id,
                title: stopTitle(detail),
              });
            }
            setDetail(null);
          }}
          onAttributesSaved={(storeId, fields) =>
            updateTour((t) => setStoreAttributes(t, storeId, fields))
          }
        />
      )}

      {/* Plan editing: mid-week re-plan and manual move-to-day */}
      {isOffice && replanOpen && (
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
          title={`Move ${stopTitle(moveTarget)}`}
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
    </View>
  );
}

function Chip({
  label,
  active,
  color,
  onPress,
  onLayoutX,
}: {
  label: string;
  active: boolean;
  color?: string;
  onPress: () => void;
  onLayoutX?: (x: number) => void;
}) {
  return (
    <Pressable
      style={[styles.chip, active && styles.chipActive]}
      onPress={onPress}
      onLayout={(e) => onLayoutX?.(e.nativeEvent.layout.x)}
      hitSlop={8}
    >
      {color && <View style={[styles.chipDot, { backgroundColor: color }]} />}
      <Text style={[styles.chipText, active && styles.chipTextActive]}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  map: { flex: 1 },
  centered: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 12, padding: 24 },
  muted: { fontSize: 15, color: tk.textMuted, textAlign: 'center' },
  errorText: { fontSize: 15, color: tk.danger, textAlign: 'center' },
  topOverlay: { position: 'absolute', top: 0, left: 0, right: 0, gap: 8, padding: 12, zIndex: 1000 },
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
  unassignedBox: {
    backgroundColor: tk.surface,
    borderRadius: 10,
    padding: 12,
    gap: 4,
    borderWidth: 1,
    borderColor: tk.border,
  },
  unassignedRow: { fontSize: 13, color: tk.text },
  unassignedReason: { color: tk.danger },
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
  },
  replanChipText: { fontWeight: '600', color: tk.text, fontSize: 13 },
  progressPill: {
    backgroundColor: tk.surface,
    borderRadius: 18,
    paddingVertical: 8,
    paddingHorizontal: 14,
    borderWidth: 1,
    borderColor: tk.border,
  },
  progressText: { fontWeight: '700', color: tk.status.done, fontSize: 13 },
  pillColumn: { gap: 6, alignItems: 'flex-end' },
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
  },
  chipActive: { backgroundColor: tk.brand, borderColor: tk.brand },
  chipText: { fontWeight: '600', color: tk.text },
  chipTextActive: { color: tk.onBrand },
  chipDot: { width: 10, height: 10, borderRadius: 5 },
  addStop: {
    alignSelf: 'flex-start',
    backgroundColor: tk.surface,
    borderRadius: 20,
    paddingVertical: 10,
    paddingHorizontal: 16,
    borderWidth: 1,
    borderColor: tk.border,
  },
  addStopHot: { backgroundColor: tk.brand, borderColor: tk.brand },
  addStopOff: { opacity: 0.55 },
  addStopText: { fontWeight: '700', color: tk.text, fontSize: 14 },
  addStopTextHot: { color: tk.onBrand },
});
