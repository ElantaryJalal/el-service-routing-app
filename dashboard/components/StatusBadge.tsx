import type { TourStatus } from "@/lib/api";

const LABELS: Record<TourStatus, string> = {
  draft: "Draft",
  planned: "Planned",
  assigned: "Assigned",
  in_progress: "In progress",
  done: "Done",
};

export default function StatusBadge({ status }: { status: TourStatus }) {
  return <span className={`badge badge-${status}`}>{LABELS[status]}</span>;
}
