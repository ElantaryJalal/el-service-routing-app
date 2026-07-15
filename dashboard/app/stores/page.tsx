"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import AppShell from "@/components/AppShell";
import { Protected, useAuth } from "@/lib/auth";
import { api, type Store } from "@/lib/api";

type Filter = "all" | "needs" | "complete";

function tri(v: boolean | null): string {
  return v === null ? "?" : v ? "yes" : "no";
}

function StoresPage() {
  const router = useRouter();
  const { user } = useAuth();
  const [stores, setStores] = useState<Store[] | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [error, setError] = useState<string | null>(null);
  const [recomputing, setRecomputing] = useState(false);
  const [recomputeResult, setRecomputeResult] = useState<string | null>(null);

  useEffect(() => {
    const needs =
      filter === "all" ? undefined : filter === "needs" ? true : false;
    setStores(null);
    api
      .listStores(needs)
      .then(setStores)
      .catch((e) => setError(String(e.message ?? e)));
  }, [filter]);

  async function recompute() {
    setRecomputing(true);
    setError(null);
    setRecomputeResult(null);
    try {
      const entries = await api.recomputeServiceTimes();
      const learned = entries.filter(
        (e) => e.learned_service_minutes !== null,
      ).length;
      const samples = entries.reduce((sum, e) => sum + e.samples, 0);
      setRecomputeResult(
        `Learned service times for ${learned} of ${entries.length} stores ` +
          `from ${samples} completed-visit observations.`,
      );
      const needs =
        filter === "all" ? undefined : filter === "needs" ? true : false;
      setStores(await api.listStores(needs));
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setRecomputing(false);
    }
  }

  return (
    <AppShell>
      <div className="page-head">
        <h1>Stores</h1>
        <div style={{ display: "flex", gap: 6 }}>
          {(user?.role === "dispatcher" || user?.role === "admin") && (
            <button
              className="btn btn-sm"
              disabled={recomputing}
              onClick={recompute}
              title="Re-learn per-store service durations from completion history"
            >
              {recomputing ? "Recomputing…" : "Recompute service times"}
            </button>
          )}
          {(
            [
              ["all", "All"],
              ["needs", "Needs attributes"],
              ["complete", "Complete"],
            ] as [Filter, string][]
          ).map(([value, label]) => (
            <button
              key={value}
              className={`btn btn-sm${filter === value ? " btn-primary" : ""}`}
              onClick={() => setFilter(value)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {error && <div className="banner banner-error">{error}</div>}
      {recomputeResult && (
        <div className="banner banner-ok">{recomputeResult}</div>
      )}

      <div className="card" style={{ padding: 0 }}>
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Store</th>
                <th>Address</th>
                <th>Size</th>
                <th>Mall</th>
                <th>Parking</th>
                <th>Service time</th>
                <th>Facts</th>
              </tr>
            </thead>
            <tbody>
              {stores === null ? (
                <tr>
                  <td colSpan={7} className="muted">
                    Loading…
                  </td>
                </tr>
              ) : stores.length === 0 ? (
                <tr>
                  <td colSpan={7} className="muted">
                    No stores in this view.
                  </td>
                </tr>
              ) : (
                stores.map((s) => (
                  <tr
                    key={s.id}
                    className="clickable"
                    onClick={() => router.push(`/stores/${s.id}`)}
                  >
                    <td>
                      <Link href={`/stores/${s.id}`}>{s.name}</Link>
                    </td>
                    <td className="muted">
                      {[s.street, [s.postal_code, s.city].filter(Boolean).join(" ")]
                        .filter(Boolean)
                        .join(", ")}
                    </td>
                    <td>{s.size ?? <span className="muted">?</span>}</td>
                    <td>{tri(s.in_mall)}</td>
                    <td>{tri(s.has_parking)}</td>
                    <td className="num">
                      {s.learned_service_minutes != null
                        ? `${s.learned_service_minutes} min (learned ×${s.service_time_samples})`
                        : s.default_service_minutes != null
                          ? `${s.default_service_minutes} min`
                          : "—"}
                    </td>
                    <td>
                      {s.attributes_complete ? (
                        <span className="badge badge-done">complete</span>
                      ) : (
                        <span className="badge badge-in_progress">missing</span>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </AppShell>
  );
}

export default function Page() {
  return (
    <Protected roles={["dispatcher", "admin", "manager"]}>
      <StoresPage />
    </Protected>
  );
}
