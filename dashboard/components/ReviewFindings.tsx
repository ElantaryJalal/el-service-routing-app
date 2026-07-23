"use client";

import { useState } from "react";
import Link from "next/link";
import { api, type StopDetail } from "@/lib/api";

interface Props {
  stops: StopDetail[];
  readOnly: boolean;
  onResolved: () => void;
}

function addr(street: string | null, plz: string | null, city: string | null) {
  return (
    [street, [plz, city].filter(Boolean).join(" ")].filter(Boolean).join(", ") ||
    "(no address printed)"
  );
}

/** Catalog-resolution findings the dispatcher should settle before optimising:
 * plan-vs-store address disagreements (one click to resolve), rows the
 * matcher refused to auto-link, and freshly created store candidates. */
export default function ReviewFindings({ stops, readOnly, onResolved }: Props) {
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const mismatches = stops.filter(
    (s) => s.address_matches_store === false && !s.address_review_resolved_at,
  );
  const unlinked = stops.filter((s) => s.store_id === null);
  const candidates = stops.filter(
    (s) =>
      s.store_id !== null &&
      (s.store_address_provenance === "printed" ||
        s.store_address_provenance === "geocoded"),
  );

  if (!mismatches.length && !unlinked.length && !candidates.length) return null;

  async function resolve(stopId: number, action: "keep_store" | "use_claim") {
    setBusy(stopId);
    setError(null);
    try {
      await api.resolveAddress(stopId, action);
      onResolved();
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="card">
      <h2>Plan vs. catalog</h2>
      {error && <div className="banner banner-error">{error}</div>}

      {mismatches.length > 0 && (
        <>
          <p className="muted small" style={{ marginTop: 0 }}>
            The printed plan disagrees with the store record for these stops.
            The store is the source of truth — routing already uses its
            verified address; decide whether the paper knew better.
          </p>
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Stop</th>
                  <th>Plan printed</th>
                  <th>Store (verified)</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {mismatches.map((s) => (
                  <tr key={s.id}>
                    <td>{s.store_name ?? s.customer ?? `#${s.id}`}</td>
                    <td className="muted">
                      {addr(s.claimed_street, s.claimed_postal_code, s.claimed_city)}
                    </td>
                    <td>{addr(s.street, s.postal_code, s.city)}</td>
                    <td>
                      {!readOnly && (
                        <div style={{ display: "flex", gap: 6 }}>
                          <button
                            className="btn btn-sm btn-primary"
                            disabled={busy === s.id}
                            onClick={() => void resolve(s.id, "keep_store")}
                          >
                            Store is correct
                          </button>
                          <button
                            className="btn btn-sm"
                            disabled={busy === s.id}
                            onClick={() => void resolve(s.id, "use_claim")}
                          >
                            Update the store
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {unlinked.length > 0 && (
        <div className="banner banner-warn" style={{ marginTop: 10 }}>
          <strong>No catalog store matched:</strong>{" "}
          {unlinked.map((s) => s.store_name ?? s.customer ?? `#${s.id}`).join(", ")} — the match
          was ambiguous or nothing fit. These stops have no routable location
          until resolved (fix the row and re-commit); optimise will leave them
          unassigned.
        </div>
      )}

      {candidates.length > 0 && (
        <div className="banner banner-warn" style={{ marginTop: 10 }}>
          <strong>New store candidates from this plan:</strong> commit created
          these store records from the printed rows — verify their address
          before trusting the route.
          <div style={{ marginTop: 6 }}>
            {candidates.map((s) => (
              <div key={s.id}>
                <Link href={`/stores/${s.store_id}`}>
                  {s.store_name ?? s.customer ?? "unknown store"}
                </Link>{" "}
                <span className="muted small">
                  ({s.store_address_provenance})
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
