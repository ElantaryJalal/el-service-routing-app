"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import AppShell from "@/components/AppShell";
import StatusBadge from "@/components/StatusBadge";
import { Card, EmptyState, Skeleton, Table, Td, Th } from "@/components/ui";
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
    <AppShell
      title="Tours"
      actions={
        <>
          <select
            className="ui-input"
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
            className="ui-input"
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
            <Link href="/tours/new" className="ui-btn ui-btn-primary">
              New tour
            </Link>
          )}
        </>
      }
    >
      {error && <div className="banner banner-error">{error}</div>}

      <Card style={{ padding: 0 }}>
        <Table>
          <thead>
            <tr>
              <Th numeric>Tour</Th>
              <Th>Customer</Th>
              <Th numeric>Week</Th>
              <Th numeric>Dates</Th>
              <Th>Status</Th>
              <Th>Assignee</Th>
              <Th></Th>
            </tr>
          </thead>
          <tbody>
            {tours === null ? (
              Array.from({ length: 4 }, (_, i) => (
                <tr key={i}>
                  {Array.from({ length: 7 }, (_, j) => (
                    <Td key={j}>
                      <Skeleton />
                    </Td>
                  ))}
                </tr>
              ))
            ) : visible.length === 0 ? (
              <tr>
                <Td colSpan={7}>
                  <EmptyState
                    title="No tours match the current filters"
                    hint={canPlan ? "Create a tour from a plan photo." : undefined}
                  />
                </Td>
              </tr>
            ) : (
              visible.map((t) => (
                <tr
                  key={t.id}
                  className="ui-row-click"
                  onClick={() => router.push(`/tours/${t.id}`)}
                >
                  <Td numeric>#{t.id}</Td>
                  <Td>
                    <Link href={`/tours/${t.id}`}>{t.customer}</Link>
                  </Td>
                  <Td numeric>KW {t.calendar_week}</Td>
                  <Td numeric>
                    {t.date_from} → {t.date_to}
                  </Td>
                  <Td>
                    <StatusBadge status={t.status} />
                  </Td>
                  <Td>
                    {t.assigned_user_id
                      ? (byId.get(t.assigned_user_id)?.name ??
                        `user ${t.assigned_user_id}`)
                      : <span className="muted">—</span>}
                  </Td>
                  <Td onClick={(e) => e.stopPropagation()}>
                    {(t.status === "in_progress" || t.status === "done") && (
                      <Link className="small" href={`/tours/${t.id}/proof`}>
                        Proof of work
                      </Link>
                    )}
                  </Td>
                </tr>
              ))
            )}
          </tbody>
        </Table>
      </Card>
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
