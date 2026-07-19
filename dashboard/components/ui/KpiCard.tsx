import Card from "./Card";

export interface KpiCardProps {
  label: string;
  value: string;
  /** One-line context under the value (kept muted). */
  sub?: string;
  /** Smaller honest-microcopy helper (e.g. how a number is learned). */
  note?: string;
  /** Optional delta chip next to the value, e.g. { text: "+3 vs last week", direction: "up" }. */
  trend?: { text: string; direction: "up" | "down" | "flat" };
}

export default function KpiCard({ label, value, sub, note, trend }: KpiCardProps) {
  return (
    <Card>
      <div className="ui-kpi-label">{label}</div>
      <div className="ui-kpi-value">
        {value}
        {trend && (
          <span className={`ui-kpi-trend ui-kpi-trend-${trend.direction}`}>
            {" "}
            {trend.text}
          </span>
        )}
      </div>
      {sub && <div className="ui-kpi-sub">{sub}</div>}
      {note && <div className="ui-kpi-note">{note}</div>}
    </Card>
  );
}
