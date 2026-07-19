"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import AppShell from "@/components/AppShell";
import DemoToggle, { useShowDemo } from "@/components/DemoToggle";
import ProvenanceBadge from "@/components/ProvenanceBadge";
import {
  Button,
  Card,
  EmptyState,
  Skeleton,
  StatusChip,
  Table,
  Td,
  Th,
} from "@/components/ui";
import { Protected, useAuth } from "@/lib/auth";
import { api, type Store } from "@/lib/api";

type Filter = "all" | "needs" | "complete";

function tri(v: boolean | null): string {
  return v === null ? "?" : v ? "yes" : "no";
}

/** "3 h 25 min" / "45 min" — total recorded time across the service ledger. */
function fmtTotal(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h > 0 ? `${h} h${m > 0 ? ` ${m} min` : ""}` : `${m} min`;
}

function StoresPage() {
  const router = useRouter();
  const { user } = useAuth();
  const showDemo = useShowDemo();
  const [stores, setStores] = useState<Store[] | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [error, setError] = useState<string | null>(null);
  const [recomputing, setRecomputing] = useState(false);
  const [recomputeResult, setRecomputeResult] = useState<string | null>(null);

  useEffect(() => {
    const needs =
      filter === "all" ? undefined : filter === "needs" ? true : false;
    setStores(null);
    // Filter changes and the demo toggle re-run this effect; a late response
    // from the previous run must not overwrite the current one.
    let stale = false;
    api
      .listStores(needs, showDemo)
      .then((s) => !stale && setStores(s))
      .catch((e) => !stale && setError(String(e.message ?? e)));
    return () => {
      stale = true;
    };
  }, [filter, showDemo]);

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
      setStores(await api.listStores(needs, showDemo));
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setRecomputing(false);
    }
  }

  return (
    <AppShell
      title="Stores"
      actions={
        <>
          <DemoToggle />
          {(user?.role === "dispatcher" || user?.role === "admin") && (
            <Button
              size="sm"
              loading={recomputing}
              onClick={recompute}
              title="Re-learn per-store service durations from completion history"
            >
              {recomputing ? "Recomputing…" : "Recompute service times"}
            </Button>
          )}
          {(
            [
              ["all", "All"],
              ["needs", "Needs attributes"],
              ["complete", "Complete"],
            ] as [Filter, string][]
          ).map(([value, label]) => (
            <Button
              key={value}
              size="sm"
              variant={filter === value ? "primary" : "secondary"}
              onClick={() => setFilter(value)}
            >
              {label}
            </Button>
          ))}
        </>
      }
    >
      {error && <div className="banner banner-error">{error}</div>}
      {recomputeResult && (
        <div className="banner banner-ok">{recomputeResult}</div>
      )}

      <Card style={{ padding: 0 }}>
        <Table>
          <thead>
            <tr>
              <Th>Store</Th>
              <Th>Address</Th>
              <Th>Size</Th>
              <Th>Mall</Th>
              <Th>Parking</Th>
              <Th numeric>Time spent</Th>
              <Th numeric>Services</Th>
              <Th>Facts</Th>
            </tr>
          </thead>
          <tbody>
            {stores === null ? (
              Array.from({ length: 5 }, (_, i) => (
                <tr key={i}>
                  {Array.from({ length: 8 }, (_, j) => (
                    <Td key={j}>
                      <Skeleton />
                    </Td>
                  ))}
                </tr>
              ))
            ) : stores.length === 0 ? (
              <tr>
                <Td colSpan={8}>
                  <EmptyState title="No stores in this view" />
                </Td>
              </tr>
            ) : (
              stores.map((s) => (
                <tr
                  key={s.id}
                  className="ui-row-click"
                  onClick={() => router.push(`/stores/${s.id}`)}
                >
                  <Td>
                    <Link href={`/stores/${s.id}`}>{s.name}</Link>
                  </Td>
                  <Td className="muted">
                    {[s.street, [s.postal_code, s.city].filter(Boolean).join(" ")]
                      .filter(Boolean)
                      .join(", ")}{" "}
                    <ProvenanceBadge store={s} />
                  </Td>
                  <Td>{s.size ?? <span className="muted">?</span>}</Td>
                  <Td>{tri(s.in_mall)}</Td>
                  <Td>{tri(s.has_parking)}</Td>
                  <Td numeric>
                    {s.services_recorded > 0
                      ? fmtTotal(s.total_service_minutes)
                      : "—"}
                  </Td>
                  <Td numeric>
                    {s.services_recorded > 0 ? s.services_recorded : "—"}
                  </Td>
                  <Td>
                    {s.attributes_complete ? (
                      <StatusChip status="done" label="complete" />
                    ) : (
                      <StatusChip status="in_progress" label="missing" />
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
      <StoresPage />
    </Protected>
  );
}
