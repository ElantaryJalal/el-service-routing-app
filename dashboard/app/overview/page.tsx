"use client";

/** Executive this-week overview: work completed across active tours.
 * Read-only by construction — it only renders GET /reports/overview. */

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import AppShell from "@/components/AppShell";
import DemoToggle, { useShowDemo } from "@/components/DemoToggle";
import WeekLoadChart from "@/components/WeekLoadChart";
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

function Kpi({
  label,
  value,
  sub,
  note,
}: {
  label: string;
  value: string;
  sub?: string;
  note?: string;
}) {
  return (
    <div className="card kpi">
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{value}</div>
      {sub && <div className="kpi-sub">{sub}</div>}
      {note && <div className="kpi-note">{note}</div>}
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
    <AppShell>
      <div className="page-head">
        <div>
          <h1>This week</h1>
          <div className="muted small">
            Work completed across active tours · KW {range.week} · {fmtDay(range.from)} –{" "}
            {fmtDay(range.to)}
          </div>
        </div>
        <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
          <DemoToggle />
          <button className="btn btn-sm" onClick={() => setWeekOffset((w) => w - 1)}>
            ← Previous
          </button>
          <button
            className="btn btn-sm"
            disabled={weekOffset === 0}
            onClick={() => setWeekOffset(0)}
          >
            Current week
          </button>
          <button className="btn btn-sm" onClick={() => setWeekOffset((w) => w + 1)}>
            Next →
          </button>
        </div>
      </div>

      {error && <div className="banner banner-error">{error}</div>}
      {!report && !error && <p className="muted">Loading…</p>}

      {report && (
        <>
          <div className="kpi-row">
            <Kpi
              label="Tours planned"
              value={String(report.tours.planned)}
              sub="confirmed, awaiting assignment"
            />
            <Kpi
              label="Tours underway"
              value={String(report.tours.assigned + report.tours.in_progress)}
              sub={`${report.tours.in_progress} in progress`}
            />
            <Kpi label="Tours completed" value={String(report.tours.done)} sub="every stop done" />
            <Kpi
              label="Stops completed"
              value={`${report.stops_completed} / ${report.stops_planned}`}
              sub="across all active tours"
            />
            <Kpi
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
            <Kpi
              label="Markets outstanding"
              value={String(report.outstanding.length)}
              sub="still to be serviced"
            />
          </div>

          <div className="card">
            <h2>Stops per day</h2>
            <WeekLoadChart days={report.days} />
          </div>

          <div className="card">
            <h2>Markets still outstanding</h2>
            {report.outstanding.length === 0 ? (
              <p className="muted" style={{ margin: 0 }}>
                Nothing outstanding — the week&apos;s work is complete.
              </p>
            ) : (
              <div className="table-wrap">
                <table className="data">
                  <thead>
                    <tr>
                      <th>Market</th>
                      <th>City</th>
                      <th>Planned day</th>
                      <th>ETA</th>
                      <th>Tour</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.outstanding.map((s) => (
                      <tr key={s.stop_id}>
                        <td>{s.customer ?? <span className="muted">—</span>}</td>
                        <td>{s.city ?? <span className="muted">—</span>}</td>
                        <td className="num">{fmtDay(s.assigned_day)}</td>
                        <td className="num">{fmtTime(s.eta)}</td>
                        <td>
                          <Link href={`/tours/${s.tour_id}`}>#{s.tour_id}</Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
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
