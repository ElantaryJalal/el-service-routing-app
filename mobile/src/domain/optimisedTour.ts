/**
 * The optimised tour as the Map screen consumes it: the backend's OptimiseResult
 * (day assignment, sequence, ETA, unassigned + reason) joined with each stop's
 * detail (coordinate, address, tasks, closing time). This composed shape is what
 * we cache for offline use — see src/state/tourCache.ts.
 */
import type { DateMode, StopDetail } from '../api/client';
import type { components } from '../api/types';

type OptimiseResult = components['schemas']['OptimiseResult'];
type HoursSource = components['schemas']['HoursSource'];

export interface OptimisedStop {
  stop_id: number;
  sequence: number;
  /** ETA as HH:MM:SS (local, from the backend). */
  eta: string;
  assigned_day: string; // ISO date of the day this stop belongs to
  dayIndex: number;
  customer: string | null;
  street: string | null;
  postal_code: string | null;
  city: string | null;
  tasks: string[];
  /** Free-text instructions from the plan's remark column. */
  remarks: string | null;
  lat: number;
  lng: number;
  service_minutes: number | null;
  closing_time: string | null;
  hours_source: HoursSource;
  /** ISO timestamp when the crew marked the stop done; null = still open. */
  completed_at: string | null;
  /** Catalog store link (null when the stop wasn't matched). */
  store_id: number | null;
  /** False = the completion sheet should ask for the store's attributes. */
  store_attributes_complete: boolean | null;
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

/** Distinct, high-contrast colours cycled per assigned day. */
const DAY_COLORS = [
  '#1f6feb', // blue
  '#e8590c', // orange
  '#2f9e44', // green
  '#9c36b5', // purple
  '#e03131', // red
  '#0c8599', // teal
  '#f08c00', // amber
];

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
    d.customer ||
    `Stop ${d.id}`
  );
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
  eta: string,
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
          customer: d?.customer ?? null,
          street: d?.street ?? null,
          postal_code: d?.postal_code ?? null,
          city: d?.city ?? null,
          tasks: tasksToChips(d?.tasks ?? null),
          remarks: d?.remarks ?? null,
          lat: d?.lat ?? 0,
          lng: d?.lng ?? 0,
          service_minutes: d?.service_minutes ?? null,
          closing_time: d?.closing_time ?? null,
          hours_source: d?.hours_source ?? 'default',
          completed_at: d?.completed_at ?? null,
          store_id: d?.store_id ?? null,
          store_attributes_complete: d?.store_attributes_complete ?? null,
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
