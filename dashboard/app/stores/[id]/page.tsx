"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import AppShell from "@/components/AppShell";
import { Protected, useAuth } from "@/lib/auth";
import {
  api,
  API_BASE,
  type Feedback,
  type Store,
  type StoreVisit,
} from "@/lib/api";

function StoreDetailPage() {
  const params = useParams<{ id: string }>();
  const storeId = Number(params.id);
  const { user } = useAuth();
  const readOnly = user?.role === "manager";

  const [store, setStore] = useState<Store | null>(null);
  const [visits, setVisits] = useState<StoreVisit[]>([]);
  const [feedback, setFeedback] = useState<Feedback[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(() => {
    api.getStore(storeId).then(setStore).catch((e) => setError(String(e.message ?? e)));
    api.storeVisits(storeId).then(setVisits).catch(() => setVisits([]));
    api.storeFeedback(storeId).then(setFeedback).catch(() => setFeedback([]));
  }, [storeId]);

  useEffect(load, [load]);

  async function saveAttributes(patch: {
    size?: Store["size"];
    in_mall?: boolean | null;
    has_parking?: boolean | null;
  }) {
    setSaving(true);
    setError(null);
    try {
      setStore(await api.updateStoreAttributes(storeId, patch));
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setSaving(false);
    }
  }

  if (!store) {
    return (
      <AppShell>
        {error ? <div className="banner banner-error">{error}</div> : <p className="muted">Loading…</p>}
      </AppShell>
    );
  }

  const address = [store.street, [store.postal_code, store.city].filter(Boolean).join(" ")]
    .filter(Boolean)
    .join(", ");

  // Tag frequency across the store's whole feedback history; a tag reported
  // 3+ times is a recurring issue worth calling out.
  const counts = new Map<string, number>();
  for (const f of feedback) {
    for (const t of f.tags) counts.set(t, (counts.get(t) ?? 0) + 1);
  }
  const tagCounts = [...counts.entries()].sort((a, b) => b[1] - a[1]);
  const recurring = tagCounts.filter(([, count]) => count >= 3);

  return (
    <AppShell>
      <div className="page-head">
        <div>
          <div className="small" style={{ marginBottom: 2 }}>
            <Link href="/stores">Stores</Link>{" "}
            <span className="muted">/ #{store.id}</span>
          </div>
          <h1>{store.name}</h1>
          <div className="muted small">{address || "no address"}</div>
        </div>
        {store.attributes_complete ? (
          <span className="badge badge-done">facts complete</span>
        ) : (
          <span className="badge badge-in_progress">facts missing</span>
        )}
      </div>

      {error && <div className="banner banner-error">{error}</div>}

      <div className="split">
        <div>
          <div className="card">
            <h2>Visit history</h2>
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Week</th>
                    <th>Tour</th>
                    <th>Employee</th>
                    <th>ETA</th>
                    <th>Completed</th>
                  </tr>
                </thead>
                <tbody>
                  {visits.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="muted">
                        No visits recorded yet.
                      </td>
                    </tr>
                  ) : (
                    visits.map((v) => (
                      <tr key={v.stop_id}>
                        <td className="num">{v.date ?? "—"}</td>
                        <td className="num">KW {v.calendar_week}</td>
                        <td>
                          <Link href={`/tours/${v.tour_id}`}>#{v.tour_id}</Link>
                        </td>
                        <td>{v.employee ?? <span className="muted">—</span>}</td>
                        <td className="num">{v.eta ?? "—"}</td>
                        <td>
                          {v.completed_at ? (
                            <span className="badge badge-done">
                              {new Date(v.completed_at).toLocaleString("de-DE", {
                                dateStyle: "short",
                                timeStyle: "short",
                              })}
                            </span>
                          ) : (
                            <span className="muted">—</span>
                          )}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <div className="card">
            <h2>Visit feedback</h2>
            {tagCounts.length > 0 && (
              <div style={{ marginBottom: 8 }}>
                {tagCounts.map(([tag, count]) => (
                  <span key={tag} className="chip">
                    {tag.replace(/_/g, " ")} ×{count}
                  </span>
                ))}
              </div>
            )}
            {recurring.map(([tag, count]) => (
              <div key={tag} className="banner banner-warn" style={{ marginBottom: 8 }}>
                <strong>Recurring issue:</strong> “{tag.replace(/_/g, " ")}” has been
                reported {count} times at this store.
              </div>
            ))}
            {feedback.length === 0 ? (
              <p className="muted" style={{ margin: 0 }}>
                No feedback yet.
              </p>
            ) : (
              feedback.map((f) => (
                <div
                  key={f.id}
                  style={{
                    borderBottom: "1px solid var(--border)",
                    padding: "8px 0",
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
                  </div>
                  <div>
                    {f.tags.map((t) => (
                      <span key={t} className="chip">
                        {t.replace(/_/g, " ")}
                      </span>
                    ))}
                  </div>
                  {f.note && <div className="small">{f.note}</div>}
                  {f.photo_path && (
                    <a
                      href={`${API_BASE}/${f.photo_path}`}
                      target="_blank"
                      rel="noreferrer"
                      className="small"
                    >
                      photo
                    </a>
                  )}
                </div>
              ))
            )}
          </div>
        </div>

        <div>
          <div className="card">
            <h2>Store facts</h2>
            <div className="field">
              <label htmlFor="size">Size</label>
              <select
                id="size"
                className="input"
                disabled={readOnly || saving}
                value={store.size ?? ""}
                onChange={(e) =>
                  void saveAttributes({
                    size: (e.target.value || null) as Store["size"],
                  })
                }
              >
                <option value="">not captured</option>
                <option value="small">small</option>
                <option value="medium">medium</option>
                <option value="large">large</option>
              </select>
            </div>
            {(
              [
                ["in_mall", "In a mall / shopping centre", store.in_mall],
                ["has_parking", "Has parking", store.has_parking],
              ] as const
            ).map(([key, label, value]) => (
              <div className="field" key={key}>
                <label htmlFor={key}>{label}</label>
                <select
                  id={key}
                  className="input"
                  disabled={readOnly || saving}
                  value={value === null ? "" : value ? "yes" : "no"}
                  onChange={(e) =>
                    void saveAttributes({
                      [key]:
                        e.target.value === "" ? null : e.target.value === "yes",
                    })
                  }
                >
                  <option value="">not captured</option>
                  <option value="yes">yes</option>
                  <option value="no">no</option>
                </select>
              </div>
            ))}
            <p className="muted small" style={{ marginBottom: 0 }}>
              {store.attributes_updated_by
                ? `Last updated by ${store.attributes_updated_by}`
                : "Never updated"}
              {store.attributes_updated_at
                ? ` · ${new Date(store.attributes_updated_at).toLocaleDateString("de-DE")}`
                : ""}
            </p>
          </div>

          <div className="card">
            <h2>Service time</h2>
            <p style={{ margin: 0 }}>
              {store.learned_service_minutes != null ? (
                <>
                  <strong className="num">
                    {store.learned_service_minutes} min
                  </strong>{" "}
                  <span className="muted small">
                    learned from {store.service_time_samples} completed visits
                  </span>
                </>
              ) : (
                <>
                  <strong className="num">
                    {store.default_service_minutes ?? 60} min
                  </strong>{" "}
                  <span className="muted small">
                    default — not enough completion history yet
                  </span>
                </>
              )}
            </p>
            {store.default_tasks && store.default_tasks.length > 0 && (
              <div style={{ marginTop: 8 }}>
                {store.default_tasks.map((t) => (
                  <span key={t} className="chip">
                    {t}
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </AppShell>
  );
}

export default function Page() {
  return (
    <Protected roles={["dispatcher", "admin", "manager"]}>
      <StoreDetailPage />
    </Protected>
  );
}
