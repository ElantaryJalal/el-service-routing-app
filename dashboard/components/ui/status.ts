/** The one status vocabulary. Colors live in tokens.css (--color-status-*);
 * mobile mirrors both in src/theme.ts + src/components/ui/StatusChip.tsx. */
export const STATUSES = [
  "draft",
  "planned",
  "assigned",
  "in_progress",
  "done",
  "overdue",
] as const;

export type Status = (typeof STATUSES)[number];

export const STATUS_LABELS: Record<Status, string> = {
  draft: "Draft",
  planned: "Planned",
  assigned: "Assigned",
  in_progress: "In progress",
  done: "Done",
  overdue: "Overdue",
};
