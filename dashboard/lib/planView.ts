/** Day palette shared with the mobile map (mobile/src/domain/optimisedTour.ts). */
const DAY_COLORS = [
  "#1f6feb", // blue
  "#e8590c", // orange
  "#2f9e44", // green
  "#9c36b5", // purple
  "#e03131", // red
  "#0c8599", // teal
  "#f08c00", // amber
];

export function dayColor(dayIndex: number): string {
  return DAY_COLORS[dayIndex % DAY_COLORS.length];
}

export function formatDriveTime(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  return h > 0 ? `${h}h ${m.toString().padStart(2, "0")}m` : `${m}m`;
}

export function weekday(dateStr: string): string {
  return new Date(dateStr + "T00:00:00").toLocaleDateString("en-GB", {
    weekday: "short",
  });
}
