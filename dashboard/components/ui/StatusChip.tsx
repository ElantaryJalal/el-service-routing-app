import { STATUS_LABELS, type Status } from "./status";

export default function StatusChip({
  status,
  label,
}: {
  status: Status;
  /** Override the default label; the color always follows the status. */
  label?: string;
}) {
  return (
    <span className={`ui-chip ui-chip-${status}`}>
      {label ?? STATUS_LABELS[status]}
    </span>
  );
}
