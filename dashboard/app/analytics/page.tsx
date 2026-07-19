"use client";

/** Management analytics: the analytical layer above the operational overview.
 * Read-only by construction — everything renders existing reporting reads
 * (multi-week /reports/overview, the P4 learned service times from /stores,
 * and the field-feedback trail). Managers and admins only; dispatchers work
 * in Overview/Tours. */

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import AppShell from "@/components/AppShell";
import DemoToggle, { useShowDemo } from "@/components/DemoToggle";
import WeeklyTrendChart, { type WeekTrendPoint } from "@/components/WeeklyTrendChart";
import {
  Card,
  EmptyState,
  KpiCard,
  Skeleton,
  Table,
  Td,
  Th,
} from "@/components/ui";
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

/** The fallback the optimiser uses when a store has no better estimate. */
const DEFAULT_SERVICE_MINUTES = 45;

function AnalyticsPage() {
  const showDemo = useShowDemo();
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
    // The demo toggle re-runs this effect; a late response from the previous
    // run must not overwrite the current one.
    let stale = false;
    const fail = (e: Error) => {
      if (!stale) setError(String(e.message ?? e));
    };
    Promise.all(weekRanges.map((r) => api.overview(r.from, r.to, showDemo)))
      .then((r) => !stale && setReports(r))
      .catch(fail);
    api
      .listStores(undefined, showDemo)
      .then((s) => !stale && setStores(s))
      .catch(fail);
    api
      .listFeedback({ includeDemo: showDemo })
      .then((f) => !stale && setFeedback(f))
      .catch(fail);
    return () => {
      stale = true;
    };
  }, [weekRanges, showDemo]);

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
    <AppShell
      title="Analytics"
      subtitle={`Trends, learned service times and field feedback · last ${TREND_WEEKS} weeks`}
      actions={<DemoToggle />}
    >
      <details className="card" style={{ marginBottom: "var(--space-4)" }}>
        <summary
          className="small"
          style={{ cursor: "pointer", fontWeight: "var(--weight-semibold)" as never }}
        >
          How to read this
        </summary>
        <p className="muted small" style={{ margin: "var(--space-2) 0 0" }}>
          These figures are built from completion history over the last 6 weeks.
          Service times are learned per store and task profile — the same store
          can take different times depending on the visit&apos;s tasks. Because
          early ETAs use a 45-minute default, the on-time rate reflects
          estimates that are still being learned; it tightens as more stores
          gather history.
        </p>
      </details>

      {error && <div className="banner banner-error">{error}</div>}
      {loading && (
        <div className="kpi-row">
          {Array.from({ length: 5 }, (_, i) => (
            <Card key={i}>
              <Skeleton width="60%" height={12} />
              <Skeleton width="40%" height={28} style={{ marginTop: "var(--space-2)" }} />
            </Card>
          ))}
        </div>
      )}

      {reports && thisWeek && (
        <>
          <div className="kpi-row">
            <KpiCard
              label="Stops completed"
              value={`${thisWeek.stops_completed} / ${thisWeek.stops_planned}`}
              sub={
                completedDelta !== null
                  ? `${completedDelta >= 0 ? "+" : ""}${completedDelta} vs last week`
                  : "this week"
              }
            />
            <KpiCard
              label="On-time completions"
              value={
                thisWeek.on_time.on_time_rate !== null
                  ? `${Math.round(thisWeek.on_time.on_time_rate * 100)}%`
                  : "—"
              }
              sub={
                avgDelta !== null && avgDelta !== undefined
                  ? `Ø ${avgDelta >= 0 ? "+" : ""}${Math.round(avgDelta)} min vs ETA · ±${thisWeek.on_time.tolerance_minutes} min tolerance · ${thisWeek.on_time.sample_count} timed`
                  : "no timed completions yet"
              }
              note="ETAs seed from a 45-min default until a store has enough visits to be learned from history. Accuracy improves as more stores are modelled."
            />
            <KpiCard
              label="Tours done"
              value={String(thisWeek.tours.done)}
              sub={`${thisWeek.tours.in_progress} in progress`}
            />
            <KpiCard
              label="Service times learned"
              value={stores ? `${learned.length} / ${stores.length}` : "—"}
              sub="stores modelled from history"
            />
            <KpiCard
              label="Feedback reports"
              value={feedback ? String(feedback.length) : "—"}
              sub={
                tagCounts[0]
                  ? `most frequent: ${tagLabel(tagCounts[0][0])}`
                  : "none reported yet"
              }
            />
          </div>

          <Card title="Six-week trend" style={{ marginBottom: "var(--space-4)" }}>
            {trend && <WeeklyTrendChart weeks={trend} />}
          </Card>

          <div className="split">
            <Card title="Learned service times">
              <p className="muted small" style={{ marginTop: 0 }}>
                Durations modelled from completion history, per store <em>and</em>{" "}
                service profile — the same store can take a different time
                depending on the visit&apos;s tasks. Δ compares against the store
                default ({DEFAULT_SERVICE_MINUTES} min where none is set).
                Largest corrections first.
              </p>
              <p className="muted small" style={{ marginTop: 0 }}>
                Estimates below 3 visits are provisional and sharpen as history
                accumulates.
              </p>
              {serviceRows.length === 0 ? (
                <EmptyState
                  title="Nothing learned yet"
                  hint="Recompute after the first completed weeks."
                />
              ) : (
                <Table>
                  <thead>
                    <tr>
                      <Th>Store</Th>
                      <Th>Service</Th>
                      <Th numeric>Default</Th>
                      <Th numeric>Learned</Th>
                      <Th numeric>Δ</Th>
                      <Th numeric>Samples</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {serviceRows.map(({ store, service, samples, base, learned, delta }) => {
                      const provisional = samples < 3;
                      return (
                        <tr key={`${store.id}-${service}`}>
                          <Td>
                            <Link href={`/stores/${store.id}`}>{store.name}</Link>
                          </Td>
                          <Td>{service}</Td>
                          <Td numeric>{base} min</Td>
                          <Td numeric>
                            <strong>{learned} min</strong>
                            {provisional && (
                              <span
                                className="muted"
                                style={{
                                  fontSize: "var(--text-xs)",
                                  marginLeft: "var(--space-2)",
                                }}
                              >
                                provisional
                              </span>
                            )}
                          </Td>
                          <Td
                            numeric
                            className={provisional ? "muted" : undefined}
                            style={
                              provisional
                                ? { fontWeight: "var(--weight-regular)" as never }
                                : undefined
                            }
                          >
                            {delta >= 0 ? "+" : ""}
                            {delta} min
                          </Td>
                          <Td numeric>{samples}</Td>
                        </tr>
                      );
                    })}
                  </tbody>
                </Table>
              )}
            </Card>

            <Card title="Field feedback">
              {tagCounts.length === 0 ? (
                <EmptyState title="No feedback reported yet" />
              ) : (
                <>
                  <div
                    style={{
                      display: "grid",
                      gap: "var(--space-2)",
                      marginBottom: "var(--space-3)",
                    }}
                  >
                    {tagCounts.map(([tag, count]) => (
                      <div
                        key={tag}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: "var(--space-2)",
                        }}
                      >
                        <span className="small" style={{ width: 150, flexShrink: 0 }}>
                          {tagLabel(tag)}
                        </span>
                        <span
                          aria-hidden
                          style={{
                            height: "var(--space-2)",
                            width: `${(count / maxTagCount) * 60}%`,
                            minWidth: "var(--space-1)",
                            borderRadius: "var(--radius-sm)",
                            background: "var(--color-brand)",
                          }}
                        />
                        <span className="small muted">{count}</span>
                      </div>
                    ))}
                  </div>
                  <h3 className="small" style={{ margin: "0 0 var(--space-1)" }}>
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
                        style={{
                          borderTop: "1px solid var(--color-border)",
                          padding: "var(--space-2) 0",
                        }}
                      >
                        <div className="small">
                          <strong>{f.employee ?? "unknown"}</strong>{" "}
                          <span className="muted">
                            {new Date(f.created_at).toLocaleString("de-DE", {
                              dateStyle: "medium",
                              timeStyle: "short",
                            })}
                          </span>
                          {" · "}
                          {f.store_id !== null && f.store_name ? (
                            <Link href={`/stores/${f.store_id}`}>
                              {f.store_name}
                              {f.store_city ? ` (${f.store_city})` : ""}
                            </Link>
                          ) : (
                            <span className="muted">unknown store</span>
                          )}
                        </div>
                        <div className="small">{f.note}</div>
                      </div>
                    ))
                  )}
                </>
              )}
            </Card>
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
