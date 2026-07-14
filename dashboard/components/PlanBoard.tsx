"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import TourMap from "@/components/TourMap";
import {
  api,
  type DateMode,
  type Plan,
  type StopDetail,
  type Tour,
  type User,
} from "@/lib/api";
import { dayColor, formatDriveTime, weekday } from "@/lib/planView";

interface Props {
  tour: Tour;
  workers: User[];
  readOnly: boolean;
  initialDuplicates: number[][];
  onTourChange: (tour: Tour) => void;
}

/** Post-commit workspace: date mode, optimise, route preview, assignment. */
export default function PlanBoard({
  tour,
  workers,
  readOnly,
  initialDuplicates,
  onTourChange,
}: Props) {
  const [stops, setStops] = useState<StopDetail[]>([]);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [duplicates, setDuplicates] = useState<number[][]>(initialDuplicates);
  const [optimising, setOptimising] = useState(false);
  const [assigning, setAssigning] = useState(false);
  const [selectedWorker, setSelectedWorker] = useState<number | "">("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const reload = useCallback(async () => {
    const [s, p] = await Promise.all([
      api.listStops(tour.id),
      api.getPlan(tour.id),
    ]);
    setStops(s);
    setPlan(p);
  }, [tour.id]);

  useEffect(() => {
    reload().catch((e) => setError(String(e.message ?? e)));
  }, [reload]);

  const stopById = useMemo(() => new Map(stops.map((s) => [s.id, s])), [stops]);
  const assignee = useMemo(
    () => workers.find((w) => w.id === tour.assigned_user_id) ?? null,
    [workers, tour.assigned_user_id],
  );
  const hasPlan = (plan?.days.length ?? 0) > 0;

  async function changeDateMode(mode: DateMode) {
    try {
      onTourChange(await api.updateTour(tour.id, { date_mode: mode }));
      setNotice("Date mode changed — run Optimise to reschedule.");
    } catch (e) {
      setError(String((e as Error).message ?? e));
    }
  }

  async function optimise() {
    setOptimising(true);
    setError(null);
    setNotice(null);
    try {
      setPlan(await api.optimise(tour.id));
      setStops(await api.listStops(tour.id));
      onTourChange(await api.getTour(tour.id));
    } catch (e) {
      setError(`Optimise failed: ${String((e as Error).message ?? e)}`);
    } finally {
      setOptimising(false);
    }
  }

  async function assign() {
    if (selectedWorker === "") return;
    setAssigning(true);
    setError(null);
    try {
      const updated = await api.assign(tour.id, selectedWorker);
      onTourChange(updated);
      const name = workers.find((w) => w.id === selectedWorker)?.name;
      setNotice(
        `Assigned to ${name ?? "worker"} — the tour is now on their phone.`,
      );
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setAssigning(false);
    }
  }

  async function unassign() {
    setAssigning(true);
    setError(null);
    try {
      onTourChange(await api.unassign(tour.id));
      setNotice("Assignment removed.");
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setAssigning(false);
    }
  }

  async function resolveDuplicate(stopId: number) {
    try {
      await api.deleteStop(stopId);
      setDuplicates((prev) =>
        prev
          .map((group) => group.filter((id) => id !== stopId))
          .filter((group) => group.length > 1),
      );
      await reload();
    } catch (e) {
      setError(String((e as Error).message ?? e));
    }
  }

  const dupLabel = (id: number) => {
    const s = stopById.get(id);
    return s
      ? `#${id} ${s.customer ?? ""} — ${[s.street, s.city].filter(Boolean).join(", ")}`
      : `stop #${id}`;
  };

  return (
    <>
      {error && <div className="banner banner-error">{error}</div>}
      {notice && <div className="banner banner-ok">{notice}</div>}

      {duplicates.length > 0 && (
        <div className="banner banner-warn">
          <strong>Possible duplicates found on commit.</strong> The same market
          seems to appear more than once — keep one row per group and delete
          the extras:
          {duplicates.map((group, gi) => (
            <div key={gi} style={{ marginTop: 8 }}>
              {group.map((id) => (
                <div
                  key={id}
                  style={{
                    display: "flex",
                    gap: 8,
                    alignItems: "center",
                    marginTop: 4,
                  }}
                >
                  <span>{dupLabel(id)}</span>
                  {!readOnly && (
                    <button
                      className="btn btn-sm btn-danger"
                      onClick={() => void resolveDuplicate(id)}
                    >
                      Delete this row
                    </button>
                  )}
                </div>
              ))}
            </div>
          ))}
        </div>
      )}

      <div className="split">
        <div>
          <div className="card">
            <div
              style={{
                display: "flex",
                gap: 10,
                alignItems: "center",
                flexWrap: "wrap",
                marginBottom: 12,
              }}
            >
              <h2 style={{ margin: 0, flex: 1 }}>Route preview</h2>
              {!readOnly && (
                <>
                  <label className="muted small" htmlFor="datemode">
                    Date mode
                  </label>
                  <select
                    id="datemode"
                    className="input"
                    style={{ minHeight: 30, padding: "3px 8px" }}
                    value={tour.date_mode}
                    onChange={(e) => void changeDateMode(e.target.value as DateMode)}
                  >
                    <option value="fixed">Plan dates</option>
                    <option value="optimized">Optimize days (experimental)</option>
                  </select>
                  <button
                    className="btn btn-primary"
                    disabled={optimising}
                    onClick={() => void optimise()}
                  >
                    {optimising ? <span className="spinner" /> : null}
                    {hasPlan ? "Re-optimise" : "Optimise"}
                  </button>
                </>
              )}
            </div>
            {!hasPlan && (
              <p className="muted small" style={{ marginTop: 0 }}>
                No schedule yet — run Optimise to distribute the stops over the
                week and order each day&apos;s route.
              </p>
            )}
            <TourMap stops={stops} plan={plan} />
          </div>

          {hasPlan && plan && (
            <div className="card">
              <h2>Day by day</h2>
              <div className="table-wrap">
                <table className="data">
                  <thead>
                    <tr>
                      <th>Day</th>
                      <th>Stops</th>
                      <th>Drive</th>
                      <th>Day end</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {plan.days.map((day, i) => (
                      <tr key={day.date}>
                        <td>
                          <span className="day-chip">
                            <span
                              className="day-dot"
                              style={{ background: dayColor(i) }}
                            />
                            {weekday(day.date)} {day.date}
                          </span>
                        </td>
                        <td className="num">{day.stops.length}</td>
                        <td className="num">{formatDriveTime(day.drive_seconds)}</td>
                        <td className="num">{day.day_end ?? "—"}</td>
                        <td>
                          {day.near_limit && (
                            <span className="badge badge-in_progress">
                              near limit
                            </span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {plan.unassigned.length > 0 && (
                <div className="banner banner-warn" style={{ marginTop: 12 }}>
                  <strong>
                    {plan.unassigned.length} stop
                    {plan.unassigned.length > 1 ? "s" : ""} could not be
                    scheduled:
                  </strong>
                  <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
                    {plan.unassigned.map((u) => (
                      <li key={u.stop_id}>
                        {dupLabel(u.stop_id)} — {u.reason}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>

        <div>
          <div className="card">
            <h2>Assignment</h2>
            {assignee ? (
              <>
                <p style={{ marginTop: 0 }}>
                  Assigned to <strong>{assignee.name}</strong>
                  <span className="muted"> · {assignee.email}</span>
                </p>
                {!readOnly && (
                  <button
                    className="btn"
                    disabled={assigning}
                    onClick={() => void unassign()}
                  >
                    Unassign
                  </button>
                )}
              </>
            ) : readOnly ? (
              <p className="muted" style={{ margin: 0 }}>
                Not assigned yet.
              </p>
            ) : (
              <>
                <p className="muted small" style={{ marginTop: 0 }}>
                  Hand the week to a field worker; the tour appears on their
                  phone immediately.
                </p>
                <div className="field">
                  <label htmlFor="worker">Worker</label>
                  <select
                    id="worker"
                    className="input"
                    value={selectedWorker}
                    onChange={(e) =>
                      setSelectedWorker(
                        e.target.value === "" ? "" : Number(e.target.value),
                      )
                    }
                  >
                    <option value="">Select a worker…</option>
                    {workers.map((w) => (
                      <option key={w.id} value={w.id}>
                        {w.name} ({w.email})
                      </option>
                    ))}
                  </select>
                </div>
                <button
                  className="btn btn-primary"
                  disabled={assigning || selectedWorker === "" || !hasPlan}
                  onClick={() => void assign()}
                >
                  {assigning ? <span className="spinner" /> : null}
                  Assign tour
                </button>
                {!hasPlan && (
                  <p className="muted small">Optimise the route first.</p>
                )}
              </>
            )}
          </div>

          <div className="card">
            <h2>Stops ({stops.length})</h2>
            <div className="table-wrap" style={{ maxHeight: 420, overflowY: "auto" }}>
              <table className="data">
                <tbody>
                  {stops.map((s) => (
                    <tr key={s.id}>
                      <td className="num muted">
                        {s.assigned_day ? weekday(s.assigned_day) : "—"}
                        {s.sequence != null ? ` ${s.sequence}` : ""}
                      </td>
                      <td>
                        {s.customer ?? <span className="muted">unnamed</span>}
                        <div className="muted small">
                          {[s.street, s.city].filter(Boolean).join(", ")}
                        </div>
                      </td>
                      <td
                        className="num small"
                        title={s.unassigned_reason ?? undefined}
                      >
                        {s.completed_at ? "✓" : s.unassigned_reason ? "⚠" : ""}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
