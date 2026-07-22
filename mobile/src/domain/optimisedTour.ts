/**
 * The optimised tour as the Map screen consumes it: the backend's OptimiseResult
 * (day assignment, sequence, ETA, unassigned + reason) joined with each stop's
 * detail (coordinate, address, tasks, closing time). This composed shape is what
 * we cache for offline use — see src/state/tourCache.ts.
 */
import type { DateMode, StopDetail } from '../api/client';
import { color } from '../theme';
import type { components } from '../api/types';

type OptimiseResult = components['schemas']['OptimiseResult'];
type HoursSource = components['schemas']['HoursSource'];
export type StoreSize = components['schemas']['StoreSize'];
/** Where a stop's service-time estimate came from (see backend ServiceEstimate). */
export type ServiceEstimateSource =
  components['schemas']['StopDetail']['service_estimate_source'];

export interface OptimisedStop {
  stop_id: number;
  sequence: number;
  /** ETA as HH:MM:SS (local); null after a manual move until re-optimised. */
  eta: string | null;
  assigned_day: string; // ISO date of the day this stop belongs to
  dayIndex: number;
  /** Auftrag/VST — the office's order/job number for this row (their reference
   * and likely invoicing key); null when the plan printed none. */
  order_no: string | null;
  /** The client named on the plan row (Kunde) — a per-row fact, never coerced
   * to a tour-wide default. Shown alongside the store, not instead of it. */
  customer: string | null;
  /** The specific physical store serviced (from the catalog); null when the
   * row was never matched to a catalog store. */
  store_name: string | null;
  street: string | null;
  postal_code: string | null;
  city: string | null;
  tasks: string[];
  /** pending | done | rework | skip | unknown — 'rework' = Nachbessern. */
  status_hint: string;
  /** Free-text instructions from the plan's remark column. */
  remarks: string | null;
  lat: number;
  lng: number;
  service_minutes: number | null;
  /** Best service-time estimate for this visit's task set (always a number). */
  service_estimate_minutes: number;
  /** Where that estimate came from — lets the card label a default honestly. */
  service_estimate_source: ServiceEstimateSource;
  closing_time: string | null;
  hours_source: HoursSource;
  /** ISO timestamp when the crew marked the stop done; null = still open. */
  completed_at: string | null;
  /** Catalog store link (null when the stop wasn't matched). */
  store_id: number | null;
  /** False = the completion sheet should ask for the store's attributes. */
  store_attributes_complete: boolean | null;
  /** The store's crowdsourced attributes (null = not captured; card prompts). */
  store_size: StoreSize | null;
  store_in_mall: boolean | null;
  store_has_parking: boolean | null;
  /** Past visit-feedback notes for the store ("N past notes" indicator). */
  store_feedback_count: number;
}

export interface OptimisedDay {
  date: string;
  dayIndex: number;
  stops: OptimisedStop[];
  drive_seconds: number;
  service_seconds: number;
  day_end: string | null;
  near_limit: boolean;
}

export interface UnassignedDetail {
  stop_id: number;
  reason: string;
  label: string;
}

export interface OptimisedTour {
  tour_id: number;
  /** The mode this schedule was computed under (fixed = plan dates bind). */
  date_mode: DateMode;
  days: OptimisedDay[];
  unassigned: UnassignedDetail[];
  /** epoch ms when this was composed/cached. */
  cached_at: number;
}

/** Distinct, high-contrast colours cycled per assigned day — the shared
 * day scale from the design tokens (see DESIGN.md). */
const DAY_COLORS = color.day;

export function dayColor(dayIndex: number): string {
  return DAY_COLORS[dayIndex % DAY_COLORS.length];
}

/** Split a free-text tasks field into individual chips. */
export function tasksToChips(tasks: string | null): string[] {
  if (!tasks) return [];
  return tasks
    .split(/[\n,;]+/)
    .map((t) => t.trim())
    .filter((t) => t.length > 0);
}

function addressLabel(d: StopDetail): string {
  return (
    [d.street, [d.postal_code, d.city].filter(Boolean).join(' ')]
      .filter(Boolean)
      .join(', ') ||
    d.store_name ||
    d.customer ||
    `Stop ${d.id}`
  );
}

/**
 * The name to show for a stop: the linked store's real name when matched
 * (the source of truth), else the plan's printed claim, else a placeholder.
 * The printed claim can be generically wrong — some plans stamp one chain name
 * (e.g. "ALDI NORD BEUCHA") on every row even where the real store differs — so
 * a matched stop must be labelled by its store, never the claim.
 */
export function stopTitle(stop: {
  store_name: string | null;
  customer: string | null;
  stop_id: number;
}): string {
  return stop.store_name ?? stop.customer ?? `Stop ${stop.stop_id}`;
}

/**
 * The client (Kunde) to show beneath the store title — the per-row plan claim,
 * returned only when it adds information: present, and different from the store
 * name already used as the title. Null when there is nothing extra to say (no
 * client, or the title already IS the client because no store matched).
 */
export function stopClient(stop: {
  store_name: string | null;
  customer: string | null;
}): string | null {
  if (!stop.customer) return null;
  if (!stop.store_name) return null; // customer is already the title
  if (stop.customer === stop.store_name) return null;
  return stop.customer;
}

/** "HH:MM[:SS]" → minutes since midnight, or null if unparseable. */
export function timeToMinutes(time: string | null): number | null {
  if (!time) return null;
  const m = /^(\d{1,2}):(\d{2})/.exec(time);
  if (!m) return null;
  return parseInt(m[1], 10) * 60 + parseInt(m[2], 10);
}

/**
 * True when a stop's ETA lands within `withinMin` minutes of (or after) its
 * closing time — the risky, must-schedule-early case worth flagging.
 */
export function etaNearClosing(
  eta: string | null,
  closing: string | null,
  withinMin = 30,
): boolean {
  const e = timeToMinutes(eta);
  const c = timeToMinutes(closing);
  if (e === null || c === null) return false;
  return c - e <= withinMin;
}

/** Join the optimiser output with per-stop detail into the cached model. */
export function composeOptimisedTour(
  result: OptimiseResult,
  details: StopDetail[],
): OptimisedTour {
  const byId = new Map<number, StopDetail>(details.map((d) => [d.id, d]));

  const days: OptimisedDay[] = result.days.map((day, dayIndex) => ({
    date: day.date,
    dayIndex,
    drive_seconds: day.drive_seconds,
    service_seconds: day.service_seconds,
    day_end: day.day_end,
    near_limit: day.near_limit,
    stops: day.stops
      .slice()
      .sort((a, b) => a.sequence - b.sequence)
      .map((s) => {
        const d = byId.get(s.stop_id);
        return {
          stop_id: s.stop_id,
          sequence: s.sequence,
          eta: s.eta,
          assigned_day: day.date,
          dayIndex,
          order_no: d?.order_no ?? null,
          customer: d?.customer ?? null,
          store_name: d?.store_name ?? null,
          street: d?.street ?? null,
          postal_code: d?.postal_code ?? null,
          city: d?.city ?? null,
          tasks: tasksToChips(d?.tasks ?? null),
          status_hint: d?.status_hint ?? 'unknown',
          remarks: d?.remarks ?? null,
          lat: d?.lat ?? 0,
          lng: d?.lng ?? 0,
          service_minutes: d?.service_minutes ?? null,
          service_estimate_minutes: d?.service_estimate_minutes ?? 0,
          service_estimate_source: d?.service_estimate_source ?? 'default',
          closing_time: d?.closing_time ?? null,
          hours_source: d?.hours_source ?? 'default',
          completed_at: d?.completed_at ?? null,
          store_id: d?.store_id ?? null,
          store_attributes_complete: d?.store_attributes_complete ?? null,
          store_size: d?.store_size ?? null,
          store_in_mall: d?.store_in_mall ?? null,
          store_has_parking: d?.store_has_parking ?? null,
          store_feedback_count: d?.store_feedback_count ?? 0,
        };
      }),
  }));

  const unassigned: UnassignedDetail[] = result.unassigned.map((u) => {
    const d = byId.get(u.stop_id);
    return {
      stop_id: u.stop_id,
      reason: u.reason,
      label: d ? addressLabel(d) : `Stop ${u.stop_id}`,
    };
  });

  return {
    tour_id: result.tour_id,
    date_mode: result.date_mode,
    days,
    unassigned,
    cached_at: Date.now(),
  };
}

/**
 * A copy of the tour with one stop's completion state changed. Local-first:
 * the Map applies this (and caches it) immediately, whether or not the API
 * call has reached the backend yet.
 */
export function setStopCompletion(
  tour: OptimisedTour,
  stopId: number,
  completedAt: string | null,
): OptimisedTour {
  return {
    ...tour,
    days: tour.days.map((day) => ({
      ...day,
      stops: day.stops.map((s) =>
        s.stop_id === stopId ? { ...s, completed_at: completedAt } : s,
      ),
    })),
  };
}

/**
 * A copy of the tour with one stop's store attributes marked captured, so a
 * later tap on the same store (or another stop of it) stops prompting.
 */
export function setStoreAttributesComplete(
  tour: OptimisedTour,
  storeId: number,
  complete: boolean,
): OptimisedTour {
  return {
    ...tour,
    days: tour.days.map((day) => ({
      ...day,
      stops: day.stops.map((s) =>
        s.store_id === storeId ? { ...s, store_attributes_complete: complete } : s,
      ),
    })),
  };
}

/**
 * A copy of the tour with a store's attributes updated in place across every
 * stop of that store, so a value the worker just captured on the detail card
 * shows immediately (and stops prompting) without a refetch. `complete` is
 * recomputed from whether all three are now set.
 */
export function setStoreAttributes(
  tour: OptimisedTour,
  storeId: number,
  fields: {
    size?: StoreSize | null;
    in_mall?: boolean | null;
    has_parking?: boolean | null;
  },
): OptimisedTour {
  return {
    ...tour,
    days: tour.days.map((day) => ({
      ...day,
      stops: day.stops.map((s) => {
        if (s.store_id !== storeId) return s;
        const store_size = fields.size ?? s.store_size;
        const store_in_mall = fields.in_mall ?? s.store_in_mall;
        const store_has_parking = fields.has_parking ?? s.store_has_parking;
        return {
          ...s,
          store_size,
          store_in_mall,
          store_has_parking,
          store_attributes_complete:
            store_size !== null &&
            store_in_mall !== null &&
            store_has_parking !== null,
        };
      }),
    })),
  };
}

/**
 * A copy of the tour with the store's past-notes count bumped, so the "N past
 * notes" indicator reflects feedback sent this session without a refetch.
 */
export function bumpStoreFeedbackCount(
  tour: OptimisedTour,
  storeId: number,
): OptimisedTour {
  return {
    ...tour,
    days: tour.days.map((day) => ({
      ...day,
      stops: day.stops.map((s) =>
        s.store_id === storeId
          ? { ...s, store_feedback_count: s.store_feedback_count + 1 }
          : s,
      ),
    })),
  };
}

/** "5 of 9 done" numbers for a set of stops. */
export function completionProgress(stops: OptimisedStop[]): {
  done: number;
  total: number;
} {
  return {
    done: stops.filter((s) => s.completed_at !== null).length,
    total: stops.length,
  };
}
