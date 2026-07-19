import StatusChip from "@/components/ui/StatusChip";
import type { TourStatus } from "@/lib/api";

/** Legacy name kept for existing call sites — renders the shared ui
 * StatusChip so a status is one color everywhere. */
export default function StatusBadge({ status }: { status: TourStatus }) {
  return <StatusChip status={status} />;
}
