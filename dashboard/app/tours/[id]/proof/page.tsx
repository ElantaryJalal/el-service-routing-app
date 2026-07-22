"use client";

/** Proof-of-work: the accountability artifact for a tour. Every stop with its
 * completion timestamp, ETA delta, and the crew's feedback incl. photos.
 * Strictly read-only. */

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import AppShell from "@/components/AppShell";
import StatusBadge from "@/components/StatusBadge";
import { Protected } from "@/lib/auth";
import { api, API_BASE, type Feedback, type StopDetail, type Tour } from "@/lib/api";

function fmtDateTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("de-DE", { dateStyle: "short", timeStyle: "short" });
}

function fmtDay(iso: string | null): string {
  if (!iso) return "unscheduled";
  return new Date(`${iso}T00:00:00`).toLocaleDateString("de-DE", {
    weekday: "long",
    day: "2-digit",
    month: "2-digit",
  });
}

function deltaMinutes(eta: string | null, completedAt: string | null): number | null {
  if (!eta || !completedAt) return null;
  return Math.round((new Date(completedAt).getTime() - new Date(eta).getTime()) / 60000);
}

function ProofOfWorkPage() {
  const params = useParams<{ id: string }>();
  const tourId = Number(params.id);

  const [tour, setTour] = useState<Tour | null>(null);
  const [stops, setStops] = useState<StopDetail[]>([]);
  const [feedback, setFeedback] = useState<Feedback[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!Number.isFinite(tourId)) return;
    api.getTour(tourId).then(setTour).catch((e) => setError(String(e.message ?? e)));
    api.listStops(tourId).then(setStops).catch((e) => setError(String(e.message ?? e)));
    api.listFeedback({ tourId }).then(setFeedback).catch(() => setFeedback([]));
  }, [tourId]);

  if (error) {
    return (
      <AppShell>
        <div className="banner banner-error">{error}</div>
        <Link href="/tours">← Back to tours</Link>
      </AppShell>
    );
  }
  if (!tour) {
    return (
      <AppShell>
        <p className="muted">Loading…</p>
      </AppShell>
    );
  }

  const byStop = new Map<number, Feedback[]>();
  for (const f of feedback) {
    if (f.stop_id === null) continue;
    byStop.set(f.stop_id, [...(byStop.get(f.stop_id) ?? []), f]);
  }
  const orphanFeedback = feedback.filter((f) => f.stop_id === null);

  const ordered = [...stops].sort((a, b) => {
    const dayA = a.assigned_day ?? "9999-12-31";
    const dayB = b.assigned_day ?? "9999-12-31";
    if (dayA !== dayB) return dayA.localeCompare(dayB);
    return (a.sequence ?? 0) - (b.sequence ?? 0);
  });
  const days = [...new Set(ordered.map((s) => s.assigned_day))];
  const completedCount = stops.filter((s) => s.completed_at).length;

  return (
    <AppShell
      title={
        <span style={{ display: "inline-flex", gap: "var(--space-3)", alignItems: "center" }}>
          {tour.customer} — proof of work
          <StatusBadge status={tour.status} />
        </span>
      }
      subtitle={
        <>
          <Link href="/tours">Tours</Link> / <Link href={`/tours/${tour.id}`}>#{tour.id}</Link>{" "}
          / proof of work · KW {tour.calendar_week} · {tour.date_from} → {tour.date_to} ·{" "}
          {completedCount} of {stops.length} stops completed
        </>
      }
    >

      {days.map((day) => (
        <div className="card" key={day ?? "unscheduled"}>
          <h2>{fmtDay(day)}</h2>
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th style={{ width: 28 }}>#</th>
                  <th>Market</th>
                  <th>ETA</th>
                  <th>Completed</th>
                  <th>Δ vs ETA</th>
                  <th>Field feedback</th>
                </tr>
              </thead>
              <tbody>
                {ordered
                  .filter((s) => s.assigned_day === day)
                  .map((s) => {
                    const eta = s.eta;
                    const delta = deltaMinutes(eta, s.completed_at);
                    const rows = byStop.get(s.id) ?? [];
                    return (
                      <tr key={s.id}>
                        <td className="num">{s.sequence ?? "—"}</td>
                        <td>
                          <div>{s.store_name ?? s.customer ?? "—"}</div>
                          <div className="muted small">
                            {[s.street, [s.postal_code, s.city].filter(Boolean).join(" ")]
                              .filter(Boolean)
                              .join(", ")}
                          </div>
                        </td>
                        <td className="num">{fmtDateTime(eta)}</td>
                        <td>
                          {s.completed_at ? (
                            <span className="badge badge-done">{fmtDateTime(s.completed_at)}</span>
                          ) : (
                            <span className="badge badge-in_progress">open</span>
                          )}
                        </td>
                        <td className="num">
                          {delta === null ? (
                            <span className="muted">—</span>
                          ) : (
                            `${delta >= 0 ? "+" : ""}${delta} min`
                          )}
                        </td>
                        <td>
                          {rows.length === 0 ? (
                            <span className="muted">—</span>
                          ) : (
                            rows.map((f) => (
                              <div key={f.id} style={{ marginBottom: 6 }}>
                                <div className="small">
                                  {f.tags.map((t) => (
                                    <span key={t} className="chip">
                                      {t.replace(/_/g, " ")}
                                    </span>
                                  ))}
                                  {f.note && <span> {f.note}</span>}
                                </div>
                                {f.photo_path && (
                                  <a
                                    href={`${API_BASE}/${f.photo_path}`}
                                    target="_blank"
                                    rel="noreferrer"
                                  >
                                    {/* eslint-disable-next-line @next/next/no-img-element */}
                                    <img
                                      src={`${API_BASE}/${f.photo_path}`}
                                      alt={`Photo from ${f.employee ?? "crew"}`}
                                      style={{
                                        height: 56,
                                        borderRadius: 6,
                                        border: "1px solid var(--border)",
                                        display: "block",
                                        marginTop: 4,
                                      }}
                                    />
                                  </a>
                                )}
                              </div>
                            ))
                          )}
                        </td>
                      </tr>
                    );
                  })}
              </tbody>
            </table>
          </div>
        </div>
      ))}

      {orphanFeedback.length > 0 && (
        <div className="card">
          <h2>Feedback no longer linked to a stop</h2>
          {orphanFeedback.map((f) => (
            <div key={f.id} className="small" style={{ padding: "4px 0" }}>
              <strong>{f.employee ?? "unknown"}</strong>{" "}
              <span className="muted">{fmtDateTime(f.created_at)}</span>{" "}
              {f.tags.map((t) => (
                <span key={t} className="chip">
                  {t.replace(/_/g, " ")}
                </span>
              ))}
              {f.note && <span> {f.note}</span>}
            </div>
          ))}
        </div>
      )}
    </AppShell>
  );
}

export default function Page() {
  return (
    <Protected roles={["manager", "dispatcher", "admin"]}>
      <ProofOfWorkPage />
    </Protected>
  );
}
