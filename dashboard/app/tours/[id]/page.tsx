"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import AppShell from "@/components/AppShell";
import DraftEditor from "@/components/DraftEditor";
import PlanBoard from "@/components/PlanBoard";
import StatusBadge from "@/components/StatusBadge";
import { Protected, useAuth } from "@/lib/auth";
import { api, type CommitResult, type Tour, type User } from "@/lib/api";

const STEPS = ["Stops", "Review", "Commit", "Optimise", "Assign"] as const;

function stepIndex(tour: Tour): number {
  switch (tour.status) {
    case "draft":
      return 0;
    case "planned":
      return 3;
    default:
      return 4;
  }
}

function TourWorkspace() {
  const params = useParams<{ id: string }>();
  const tourId = Number(params.id);
  const { user } = useAuth();
  const [tour, setTour] = useState<Tour | null>(null);
  const [workers, setWorkers] = useState<User[]>([]);
  const [duplicates, setDuplicates] = useState<number[][]>([]);
  const [error, setError] = useState<string | null>(null);

  const readOnly = user?.role === "manager";

  useEffect(() => {
    if (!Number.isFinite(tourId)) return;
    api
      .getTour(tourId)
      .then(setTour)
      .catch((e) => setError(String(e.message ?? e)));
    api
      .listUsers("worker")
      .then(setWorkers)
      .catch(() => setWorkers([]));
  }, [tourId]);

  function onCommitted(result: CommitResult) {
    setDuplicates(result.duplicates);
    api.getTour(tourId).then(setTour).catch(() => undefined);
  }

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

  const current = stepIndex(tour);

  return (
    <AppShell
      title={
        <span style={{ display: "inline-flex", gap: "var(--space-3)", alignItems: "center" }}>
          {tour.customer}
          <StatusBadge status={tour.status} />
        </span>
      }
      subtitle={
        <>
          <Link href="/tours">Tours</Link> / #{tour.id} · KW {tour.calendar_week} ·{" "}
          {tour.date_from} → {tour.date_to}
        </>
      }
      actions={
        <>
          {(tour.status === "in_progress" || tour.status === "done") && (
            <Link className="ui-btn ui-btn-secondary ui-btn-sm" href={`/tours/${tour.id}/proof`}>
              Proof of work
            </Link>
          )}
          <div className="step-dots" aria-label="Progress">
            {STEPS.map((label, i) => (
              <span
                key={label}
                className={`step ${i < current ? "done" : i === current ? "current" : ""}`}
              >
                {i < current ? "✓" : `${i + 1}.`} {label}
              </span>
            ))}
          </div>
        </>
      }
    >

      {tour.status === "draft" ? (
        readOnly ? (
          <div className="empty-state">
            This tour is still being prepared by dispatch.
          </div>
        ) : (
          <DraftEditor tour={tour} onCommitted={onCommitted} />
        )
      ) : (
        <PlanBoard
          tour={tour}
          workers={workers}
          readOnly={readOnly}
          initialDuplicates={duplicates}
          onTourChange={setTour}
        />
      )}
    </AppShell>
  );
}

export default function Page() {
  return (
    <Protected roles={["dispatcher", "admin", "manager"]}>
      <TourWorkspace />
    </Protected>
  );
}
