"use client";

/** Management analytics: the analytical layer above the operational overview.
 * Read-only by construction — everything renders existing reporting reads
 * (multi-week /reports/overview, the P4 learned service times from /stores,
 * and the field-feedback trail). Managers and admins only; dispatchers work
 * in Overview/Tours. */

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import AppShell from "@/components/AppShell";
import WeeklyTrendChart, { type WeekTrendPoint } from "@/components/WeeklyTrendChart";
import { Protected } from "@/lib/auth";
import { api, type Feedback, type OverviewReport, type Store } from "@/lib/api";

const TREND_WEEKS = 6;

function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function mondayOf(offsetWeeks: number): Date {
  const now = new Date();
  const monday = new Date(now);
  monday.setDate(now.getDate() - ((now.getDay() + 6) % 7) + offsetWeeks * 7);
  monday.setHours(12, 0, 0, 0);
  return monday;
}

function isoWeekNumber(d: Date): number {
  const date = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const day = date.getUTCDay() || 7;
  date.setUTCDate(date.getUTCDate() + 4 - day);
  const yearStart = new Date(Date.UTC(date.getUTCFullYear(), 0, 1));
  return Math.ceil(((date.getTime() - yearStart.getTime()) / 86400000 + 1) / 7);
}

function tagLabel(tag: string): string {
  return tag.replace(/_/g, " ");
}

function Kpi({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="card kpi">
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{value}</div>
      {sub && <div className="kpi-sub">{sub}</div>}
    </div>
  );
}

/** The fallback the optimiser uses when a store has no better estimate. */
const DEFAULT_SERVICE_MINUTES = 45;

function AnalyticsPage() {
  const [reports, setReports] = useState<OverviewReport[] | null>(null);
  const [stores, setStores] = useState<Store[] | null>(null);
  const [feedback, setFeedback] = useState<Feedback[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const weekRanges = useMemo(
    () =>
      Array.from({ length: TREND_WEEKS }, (_, idx) => {
        const from = mondayOf(idx - (TREND_WEEKS - 1));
        const to = new Date(from);
        to.setDate(from.getDate() + 6);
        return { from: isoDate(from), to: isoDate(to), week: isoWeekNumber(from) };
      }),
    [],
  );

  useEffect(() => {
    Promise.all(weekRanges.map((r) => api.overview(r.from, r.to)))
      .then(setReports)
      .catch((e) => setError(String(e.message ?? e)));
    api.listStores().then(setStores).catch((e) => setError(String(e.message ?? e)));
    api
      .listFeedback({})
      .then(setFeedback)
      .catch((e) => setError(String(e.message ?? e)));
  }, [weekRanges]);

  const trend: WeekTrendPoint[] | null =
    reports &&
    reports.map((r, i) => ({
      label: `KW ${weekRanges[i].week}`,
      planned: r.stops_planned,
      completed: r.stops_completed,
      onTimeRate: r.on_time.on_time_rate,
    }));

  const thisWeek = reports?.[reports.length - 1];
  const lastWeek = reports?.[reports.length - 2];

  const completedDelta =
    thisWeek && lastWeek ? thisWeek.stops_completed - lastWeek.stops_completed : null;
  const ratePp =
    thisWeek?.on_time.on_time_rate != null && lastWeek?.on_time.on_time_rate != null
      ? Math.round((thisWeek.on_time.on_time_rate - lastWeek.on_time.on_time_rate) * 100)
      : null;
  const avgDelta = thisWeek?.on_time.average_delta_minutes;

  // P4 results, per service profile: the same store can take a different
  // time depending on which tasks (which team) the visit is for. Stores
  // whose only learned value is the store-wide median get one row.
  const learned = (stores ?? []).filter((s) => s.learned_service_minutes !== null);
  const serviceRows = (stores ?? [])
    .flatMap((store) => {
      const base = store.default_service_minutes ?? DEFAULT_SERVICE_MINUTES;
      const profiles = store.service_times.filter((p) => p.learned_minutes !== null);
      if (profiles.length > 0) {
        return profiles.map((p) => ({
          store,
          service: p.tasks_label ?? "No recorded tasks",
          samples: p.samples,
          base,
          learned: p.learned_minutes as number,
          delta: (p.learned_minutes as number) - base,
        }));
      }
      if (store.learned_service_minutes !== null) {
        return [
          {
            store,
            service: "All services",
            samples: store.service_time_samples,
            base,
            learned: store.learned_service_minutes,
            delta: store.learned_service_minutes - base,
          },
        ];
      }
      return [];
    })
    .sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta))
    .slice(0, 10);

  // Feedback: tag frequency over everything reported, plus the latest notes.
  const tagCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const f of feedback ?? []) {
      for (const t of f.tags) counts.set(t, (counts.get(t) ?? 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [feedback]);
  const maxTagCount = tagCounts[0]?.[1] ?? 0;
  const latestNotes = (feedback ?? []).filter((f) => f.note).slice(0, 5);

  const loading = !error && (!reports || !stores || !feedback);

  return (
    <AppShell>
      <div className="page-head">
        <div>
          <h1>Analytics</h1>
          <div className="muted small">
            Trends, learned service times and field feedback · last {TREND_WEEKS} weeks
          </div>
        </div>
      </div>

      {error && <div className="banner banner-error">{error}</div>}
      {loading && <p className="muted">Loading…</p>}

      {reports && thisWeek && (
        <>
          <div className="kpi-row">
            <Kpi
              label="Stops completed"
              value={`${thisWeek.stops_completed} / ${thisWeek.stops_planned}`}
              sub={
                completedDelta !== null
                  ? `${completedDelta >= 0 ? "+" : ""}${completedDelta} vs last week`
                  : "this week"
              }
            />
            <Kpi
              label="On-time rate"
              value={
                thisWeek.on_time.on_time_rate !== null
                  ? `${Math.round(thisWeek.on_time.on_time_rate * 100)}%`
                  : "—"
              }
              sub={
                ratePp !== null
                  ? `${ratePp >= 0 ? "+" : ""}${ratePp} pp vs last week`
                  : thisWeek.on_time.on_time_rate !== null
                    ? "no comparison week"
                    : "no timed completions yet"
              }
            />
            <Kpi
              label="Ø vs ETA"
              value={
                avgDelta !== null && avgDelta !== undefined
                  ? `${avgDelta >= 0 ? "+" : ""}${Math.round(avgDelta)} min`
                  : "—"
              }
              sub={`${thisWeek.on_time.sample_count} timed completions`}
            />
            <Kpi
              label="Tours done"
              value={String(thisWeek.tours.done)}
              sub={`${thisWeek.tours.in_progress} in progress`}
            />
            <Kpi
              label="Service times learned"
              value={stores ? `${learned.length} / ${stores.length}` : "—"}
              sub="stores modelled from history"
            />
            <Kpi
              label="Feedback reports"
              value={feedback ? String(feedback.length) : "—"}
              sub={
                tagCounts[0]
                  ? `most frequent: ${tagLabel(tagCounts[0][0])}`
                  : "none reported yet"
              }
            />
          </div>

          <div className="card">
            <h2>Six-week trend</h2>
            {trend && <WeeklyTrendChart weeks={trend} />}
          </div>

          <div className="split">
            <div className="card">
              <h2>Learned service times</h2>
              <p className="muted small" style={{ marginTop: 0 }}>
                Durations modelled from completion history, per store <em>and</em>{" "}
                service profile — the same store can take a different time
                depending on the visit&apos;s tasks. Δ compares against the store
                default ({DEFAULT_SERVICE_MINUTES} min where none is set).
                Largest corrections first.
              </p>
              {serviceRows.length === 0 ? (
                <p className="muted" style={{ margin: 0 }}>
                  Nothing learned yet — recompute after the first completed weeks.
                </p>
              ) : (
                <div className="table-wrap">
                  <table className="data">
                    <thead>
                      <tr>
                        <th>Store</th>
                        <th>Service</th>
                        <th className="num">Default</th>
                        <th className="num">Learned</th>
                        <th className="num">Δ</th>
                        <th className="num">Samples</th>
                      </tr>
                    </thead>
                    <tbody>
                      {serviceRows.map(({ store, service, samples, base, learned, delta }) => (
                        <tr key={`${store.id}-${service}`}>
                          <td>
                            <Link href={`/stores/${store.id}`}>{store.name}</Link>
                          </td>
                          <td>{service}</td>
                          <td className="num">{base} min</td>
                          <td className="num">
                            <strong>{learned} min</strong>
                          </td>
                          <td className="num">
                            {delta >= 0 ? "+" : ""}
                            {delta} min
                          </td>
                          <td className="num">{samples}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            <div className="card">
              <h2>Field feedback</h2>
              {tagCounts.length === 0 ? (
                <p className="muted" style={{ margin: 0 }}>
                  No feedback reported yet.
                </p>
              ) : (
                <>
                  <div style={{ display: "grid", gap: 6, marginBottom: 12 }}>
                    {tagCounts.map(([tag, count]) => (
                      <div
                        key={tag}
                        style={{ display: "flex", alignItems: "center", gap: 8 }}
                      >
                        <span className="small" style={{ width: 150, flexShrink: 0 }}>
                          {tagLabel(tag)}
                        </span>
                        <span
                          aria-hidden
                          style={{
                            height: 10,
                            width: `${(count / maxTagCount) * 60}%`,
                            minWidth: 4,
                            borderRadius: 3,
                            background: "#1e40af",
                          }}
                        />
                        <span className="small muted">{count}</span>
                      </div>
                    ))}
                  </div>
                  <h3 className="small" style={{ margin: "0 0 4px" }}>
                    Latest notes
                  </h3>
                  {latestNotes.length === 0 ? (
                    <p className="muted small" style={{ margin: 0 }}>
                      No written notes yet.
                    </p>
                  ) : (
                    latestNotes.map((f) => (
                      <div
                        key={f.id}
                        style={{ borderTop: "1px solid var(--border)", padding: "8px 0" }}
                      >
                        <div className="small">
                          <strong>{f.employee ?? "unknown"}</strong>{" "}
                          <span className="muted">
                            {new Date(f.created_at).toLocaleString("de-DE", {
                              dateStyle: "medium",
                              timeStyle: "short",
                            })}
                          </span>
                          {f.store_id !== null && (
                            <>
                              {" · "}
                              <Link href={`/stores/${f.store_id}`}>store #{f.store_id}</Link>
                            </>
                          )}
                        </div>
                        <div className="small">{f.note}</div>
                      </div>
                    ))
                  )}
                </>
              )}
            </div>
          </div>
        </>
      )}
    </AppShell>
  );
}

export default function Page() {
  return (
    <Protected roles={["manager", "admin"]}>
      <AnalyticsPage />
    </Protected>
  );
}
