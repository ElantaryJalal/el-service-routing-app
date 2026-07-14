"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import AppShell from "@/components/AppShell";
import StatusBadge from "@/components/StatusBadge";
import { Protected, useAuth } from "@/lib/auth";
import { api, type Tour, type TourStatus, type User } from "@/lib/api";

const STATUSES: TourStatus[] = [
  "draft",
  "planned",
  "assigned",
  "in_progress",
  "done",
];

function ToursPage() {
  const { user } = useAuth();
  const router = useRouter();
  const [tours, setTours] = useState<Tour[] | null>(null);
  const [users, setUsers] = useState<User[]>([]);
  const [status, setStatus] = useState<TourStatus | "all">("all");
  const [assignee, setAssignee] = useState<number | "all">("all");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.listTours(), api.listUsers()])
      .then(([t, u]) => {
        setTours(t);
        setUsers(u);
      })
      .catch((e) => setError(String(e.message ?? e)));
  }, []);

  const byId = useMemo(
    () => new Map(users.map((u) => [u.id, u])),
    [users],
  );
  const assignees = useMemo(
    () =>
      users.filter((u) =>
        (tours ?? []).some((t) => t.assigned_user_id === u.id),
      ),
    [users, tours],
  );

  const visible = (tours ?? []).filter(
    (t) =>
      (status === "all" || t.status === status) &&
      (assignee === "all" || t.assigned_user_id === assignee),
  );

  const canPlan = user?.role === "dispatcher" || user?.role === "admin";

  return (
    <AppShell>
      <div className="page-head">
        <h1>Tours</h1>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <select
            className="input"
            aria-label="Filter by status"
            value={status}
            onChange={(e) => setStatus(e.target.value as TourStatus | "all")}
          >
            <option value="all">All statuses</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s.replace("_", " ")}
              </option>
            ))}
          </select>
          <select
            className="input"
            aria-label="Filter by assignee"
            value={assignee}
            onChange={(e) =>
              setAssignee(e.target.value === "all" ? "all" : Number(e.target.value))
            }
          >
            <option value="all">All assignees</option>
            {assignees.map((u) => (
              <option key={u.id} value={u.id}>
                {u.name}
              </option>
            ))}
          </select>
          {canPlan && (
            <Link href="/tours/new" className="btn btn-primary">
              New tour
            </Link>
          )}
        </div>
      </div>

      {error && <div className="banner banner-error">{error}</div>}

      <div className="card" style={{ padding: 0 }}>
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Tour</th>
                <th>Customer</th>
                <th>Week</th>
                <th>Dates</th>
                <th>Status</th>
                <th>Assignee</th>
              </tr>
            </thead>
            <tbody>
              {tours === null ? (
                <tr>
                  <td colSpan={6} className="muted">
                    Loading…
                  </td>
                </tr>
              ) : visible.length === 0 ? (
                <tr>
                  <td colSpan={6} className="muted">
                    No tours match the current filters.
                  </td>
                </tr>
              ) : (
                visible.map((t) => (
                  <tr
                    key={t.id}
                    className="clickable"
                    onClick={() => router.push(`/tours/${t.id}`)}
                  >
                    <td className="num">#{t.id}</td>
                    <td>
                      <Link href={`/tours/${t.id}`}>{t.customer}</Link>
                    </td>
                    <td className="num">KW {t.calendar_week}</td>
                    <td className="num">
                      {t.date_from} → {t.date_to}
                    </td>
                    <td>
                      <StatusBadge status={t.status} />
                    </td>
                    <td>
                      {t.assigned_user_id
                        ? (byId.get(t.assigned_user_id)?.name ??
                          `user ${t.assigned_user_id}`)
                        : <span className="muted">—</span>}
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
      <ToursPage />
    </Protected>
  );
}
