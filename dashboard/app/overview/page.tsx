"use client";

/** Executive this-week overview: work completed across active tours.
 * Read-only by construction — it only renders GET /reports/overview.
 * Leads with the "is everything okay?" KPIs; detail sits below the fold. */

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import AppShell from "@/components/AppShell";
import DemoToggle, { useShowDemo } from "@/components/DemoToggle";
import WeekLoadChart from "@/components/WeekLoadChart";
import {
  Button,
  Card,
  EmptyState,
  KpiCard,
  Skeleton,
  Table,
  Td,
  Th,
} from "@/components/ui";
import { Protected } from "@/lib/auth";
import { api, type OverviewReport } from "@/lib/api";

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

function fmtDay(iso: string | null): string {
  if (!iso) return "—";
  return new Date(`${iso}T00:00:00`).toLocaleDateString("de-DE", {
    weekday: "short",
    day: "2-digit",
    month: "2-digit",
  });
}

function fmtTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
}

function KpiSkeletons() {
  return (
    <div className="kpi-row">
      {Array.from({ length: 6 }, (_, i) => (
        <Card key={i}>
          <Skeleton width="60%" height={12} />
          <Skeleton width="40%" height={28} style={{ marginTop: "var(--space-2)" }} />
        </Card>
      ))}
    </div>
  );
}

function OverviewPage() {
  const showDemo = useShowDemo();
  const [weekOffset, setWeekOffset] = useState(0);
  const [report, setReport] = useState<OverviewReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  const range = useMemo(() => {
    const from = mondayOf(weekOffset);
    const to = new Date(from);
    to.setDate(from.getDate() + 6);
    return { from: isoDate(from), to: isoDate(to), week: isoWeekNumber(from) };
  }, [weekOffset]);

  useEffect(() => {
    setReport(null);
    setError(null);
    // Week paging and the demo toggle re-run this effect; a late response
    // from the previous run must not overwrite the current one.
    let stale = false;
    api
      .overview(range.from, range.to, showDemo)
      .then((r) => !stale && setReport(r))
      .catch((e) => !stale && setError(String(e.message ?? e)));
    return () => {
      stale = true;
    };
  }, [range, showDemo]);

  const onTime = report?.on_time;
  const avgDelta = onTime?.average_delta_minutes;

  return (
    <AppShell
      title="This week"
      subtitle={`Work completed across active tours · KW ${range.week} · ${fmtDay(range.from)} – ${fmtDay(range.to)}`}
      actions={
        <>
          <DemoToggle />
          <Button size="sm" onClick={() => setWeekOffset((w) => w - 1)}>
            ← Previous
          </Button>
          <Button
            size="sm"
            disabled={weekOffset === 0}
            onClick={() => setWeekOffset(0)}
          >
            Current week
          </Button>
          <Button size="sm" onClick={() => setWeekOffset((w) => w + 1)}>
            Next →
          </Button>
        </>
      }
    >
      {error && <div className="banner banner-error">{error}</div>}
      {!report && !error && <KpiSkeletons />}

      {report && (
        <>
          <div className="kpi-row">
            <KpiCard
              label="Tours planned"
              value={String(report.tours.planned)}
              sub="confirmed, awaiting assignment"
            />
            <KpiCard
              label="Tours underway"
              value={String(report.tours.assigned + report.tours.in_progress)}
              sub={`${report.tours.in_progress} in progress`}
            />
            <KpiCard
              label="Tours completed"
              value={String(report.tours.done)}
              sub="every stop done"
            />
            <KpiCard
              label="Stops completed"
              value={`${report.stops_completed} / ${report.stops_planned}`}
              sub="across all active tours"
            />
            <KpiCard
              label="On-time completions"
              value={
                onTime && onTime.on_time_rate !== null
                  ? `${Math.round(onTime.on_time_rate * 100)}%`
                  : "—"
              }
              sub={
                onTime && avgDelta !== null && avgDelta !== undefined
                  ? `Ø ${avgDelta >= 0 ? "+" : ""}${Math.round(avgDelta)} min vs ETA · ±${onTime.tolerance_minutes} min tolerance · ${onTime.sample_count} timed`
                  : "no timed completions yet"
              }
              note="ETAs seed from a 45-min default until a store has enough visits to be learned from history. Accuracy improves as more stores are modelled."
            />
            <KpiCard
              label="Markets outstanding"
              value={String(report.outstanding.length)}
              sub="still to be serviced"
            />
          </div>

          <Card title="Stops per day" style={{ marginBottom: "var(--space-4)" }}>
            <WeekLoadChart days={report.days} />
          </Card>

          <Card title="Markets still outstanding">
            {report.outstanding.length === 0 ? (
              <EmptyState
                title="Nothing outstanding"
                hint="The week's work is complete."
              />
            ) : (
              <Table>
                <thead>
                  <tr>
                    <Th>Market</Th>
                    <Th>City</Th>
                    <Th>Planned day</Th>
                    <Th>ETA</Th>
                    <Th>Tour</Th>
                  </tr>
                </thead>
                <tbody>
                  {report.outstanding.map((s) => (
                    <tr key={s.stop_id}>
                      <Td>{s.customer ?? <span className="muted">—</span>}</Td>
                      <Td>{s.city ?? <span className="muted">—</span>}</Td>
                      <Td numeric>{fmtDay(s.assigned_day)}</Td>
                      <Td numeric>{fmtTime(s.eta)}</Td>
                      <Td>
                        <Link href={`/tours/${s.tour_id}`}>#{s.tour_id}</Link>
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </Card>
        </>
      )}
    </AppShell>
  );
}

export default function Page() {
  return (
    <Protected roles={["manager", "dispatcher", "admin"]}>
      <OverviewPage />
    </Protected>
  );
}
