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

import { ApiError, api, type DateMode } from '../src/api/client';
import {
  CompletionSheet,
  type CompletionSync,
} from '../src/components/CompletionSheet';
import { DateModeControl } from '../src/components/DateModeControl';
import { SyncState } from '../src/components/ui';
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

function toHHMM(time: string): string {
  const m = /^(\d{1,2}):(\d{2})/.exec(time);
  return m ? `${m[1].padStart(2, '0')}:${m[2]}` : time;
}

function formatDay(date: string): string {
  const d = new Date(`${date}T00:00:00`);
  const wd = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][d.getDay()];
  return `${wd} ${String(d.getDate()).padStart(2, '0')}.${String(d.getMonth() + 1).padStart(2, '0')}`;
}

function escapeHtml(s: string): string {
  return s.replace(/[&<>"]/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c] as string,
  );
}

/** Build the popup HTML for a stop. The completion button carries a
 * data-action attribute; the popupopen handler wires it back into React. */
function popupHtml(s: OptimisedStop, pendingSync: boolean): string {
  const address = escapeHtml(
    [s.street, [s.postal_code, s.city].filter(Boolean).join(' ')]
      .filter(Boolean)
      .join(', '),
  );
  const urgent = etaNearClosing(s.eta, s.closing_time);
  const chips = s.tasks
    .map(
      (t) =>
        `<span style="background:${tk.soft};border-radius:10px;padding:1px 7px;margin:1px;display:inline-block;font-size:11px">${escapeHtml(t)}</span>`,
    )
    .join(' ');
  const remarks = s.remarks
    ? `<div style="background:${tk.warningBg};border-left:3px solid ${tk.warning};padding:3px 7px;margin:4px 0;font-size:12px">${escapeHtml(s.remarks)}</div>`
    : '';
  const nav = `https://www.google.com/maps/dir/?api=1&destination=${s.lat},${s.lng}`;
  const etaStyle = urgent ? `color:${tk.danger};font-weight:700` : 'font-weight:600';
  return `
    <div style="min-width:180px;font-family:system-ui,sans-serif">
      <div style="font-weight:700;font-size:14px">${escapeHtml(s.customer ?? `Stop ${s.stop_id}`)}</div>
      ${address ? `<div style="color:${tk.textMuted};font-size:12px;margin-bottom:4px">${address}</div>` : ''}
      <div style="font-size:12px;margin:2px 0">
        <b>${formatDay(s.assigned_day)}</b> · #${s.sequence} ·
        <span style="${etaStyle}">ETA ${s.eta ? toHHMM(s.eta) : '—'}</span>
        ${s.closing_time ? ` · closes ${toHHMM(s.closing_time)}` : ''}
        ${s.service_minutes != null ? ` · ${s.service_minutes} min` : ''}
      </div>
      ${urgent ? `<div style="color:${tk.danger};font-size:11px;font-weight:600">Tight — arrives close to closing.</div>` : ''}
      ${remarks}
      <div style="margin:4px 0">${chips}</div>
      ${s.completed_at ? `<div style="color:${tk.status.done};font-size:12px;font-weight:600;margin:2px 0">✓ Completed</div>` : ''}
      ${pendingSync ? `<div style="color:${tk.warningText};font-size:12px;font-weight:600;margin:2px 0">⇅ not yet synced</div>` : ''}
      ${
        s.store_id !== null && s.store_feedback_count > 0
          ? `<button data-action="show-history" type="button"
               style="background:${tk.brandSoft};color:${tk.brand};border:none;padding:4px 10px;border-radius:8px;font-size:12px;font-weight:600;cursor:pointer;margin:2px 0">
               🗒 ${s.store_feedback_count} past note${s.store_feedback_count === 1 ? '' : 's'}
             </button>`
          : ''
      }
      <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
        <a href="${nav}" target="_blank" rel="noopener"
           style="display:inline-block;background:${tk.surface};color:${tk.text};border:1px solid ${tk.borderStrong};padding:6px 12px;border-radius:6px;text-decoration:none;font-size:13px;font-weight:600">Navigate</a>
        <button data-action="toggle-complete" type="button"
                style="background:${s.completed_at ? tk.bg : tk.brand};color:${s.completed_at ? tk.textMuted : tk.onBrand};border:1px solid ${s.completed_at ? tk.borderStrong : tk.brand};padding:6px 12px;border-radius:6px;font-size:13px;font-weight:600;cursor:pointer">
          ${s.completed_at ? 'Mark as not done' : 'Mark done ✓'}
        </button>
        ${
          s.completed_at
            ? ''
            : `<button data-action="move-stop" type="button"
                style="background:${tk.bg};color:${tk.text};border:1px solid ${tk.borderStrong};padding:6px 12px;border-radius:6px;font-size:13px;font-weight:600;cursor:pointer">Move day…</button>`
        }
      </div>
    </div>`;
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
      await refreshPlan();
      setMoveTarget(null);
      setDay('all');
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

        // Completed stops drop out of the active route line (still tappable).
        const active = stops.filter((s) => s.completed_at === null);
        if (day !== 'all' && active.length > 1) {
          L.polyline(
            active.map((s) => [s.lat, s.lng]),
            { color: dayColor(day as number), weight: 3, opacity: 0.8 },
          ).addTo(group);
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
          const marker = L.marker([s.lat, s.lng], { icon })
            .bindPopup(popupHtml(s, pendingSync))
            .addTo(group);
          // Bridge the popup's buttons back into React.
          marker.on('popupopen', (e: any) => {
            const root = e.popup.getElement() as HTMLElement | null;
            if (!root) return;
            const toggle = root.querySelector(
              '[data-action="toggle-complete"]',
            ) as HTMLButtonElement | null;
            if (toggle) {
              toggle.onclick = () => {
                map.closePopup();
                if (s.completed_at === null) markDone(s);
                else markNotDone(s);
              };
            }
            const notes = root.querySelector(
              '[data-action="show-history"]',
            ) as HTMLButtonElement | null;
            if (notes && s.store_id !== null) {
              notes.onclick = () => {
                map.closePopup();
                setHistory({
                  storeId: s.store_id!,
                  title: s.customer ?? `Stop ${s.stop_id}`,
                });
              };
            }
            const move = root.querySelector(
              '[data-action="move-stop"]',
            ) as HTMLButtonElement | null;
            if (move) {
              move.onclick = () => {
                map.closePopup();
                setMoveTarget(s);
              };
            }
          });
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
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.chips}
        >
          <Chip label="All" active={day === 'all'} onPress={() => setDay('all')} />
          {tour!.days
            .filter((d) => d.stops.length > 0)
            .map((d) => (
              <Chip
                key={d.date}
                label={formatDay(d.date)}
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
});
