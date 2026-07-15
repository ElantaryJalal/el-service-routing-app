"use client";

/** Per-day stops planned vs completed, as grouped columns in two shades of
 * the app blue (planned = light track shade, completed = primary). Completed
 * isn't a strict subset of planned per day (planned counts by assigned day,
 * completed by completion day), hence grouped columns, not a stack. */

import { useState } from "react";
import type { DayLoad } from "@/lib/api";

const PLANNED = "#bccff7";
const COMPLETED = "#1e40af";
const GRID = "#e6ebf3";
const TEXT_MUTED = "#5b6b84";

const WIDTH = 640;
const HEIGHT = 200;
const PAD = { top: 16, right: 8, bottom: 24, left: 30 };
const BAR = 14; // ≤ 24px, air in the band comes from the group layout
const GAP = 2; // surface gap between the pair

function niceMax(n: number): number {
  if (n <= 4) return 4;
  const step = n <= 10 ? 2 : n <= 20 ? 5 : 10;
  return Math.ceil(n / step) * step;
}

function dayLabel(iso: string): string {
  const d = new Date(`${iso}T00:00:00`);
  return `${d.toLocaleDateString("de-DE", { weekday: "short" })} ${d.getDate()}.${d.getMonth() + 1}.`;
}

export default function WeekLoadChart({ days }: { days: DayLoad[] }) {
  const [hover, setHover] = useState<number | null>(null);

  if (days.length === 0) return null;

  const plotW = WIDTH - PAD.left - PAD.right;
  const plotH = HEIGHT - PAD.top - PAD.bottom;
  const max = niceMax(Math.max(1, ...days.map((d) => Math.max(d.planned, d.completed))));
  const band = plotW / days.length;
  const y = (v: number) => PAD.top + plotH - (v / max) * plotH;
  const barH = (v: number) => (v / max) * plotH;
  const ticks = [0, max / 2, max];

  // 4px rounded data-end, square at the baseline.
  function column(cx: number, value: number, fill: string, key: string) {
    const h = barH(value);
    const r = Math.min(4, h);
    const top = y(value);
    return (
      <path
        key={key}
        d={`M ${cx} ${PAD.top + plotH}
            L ${cx} ${top + r}
            Q ${cx} ${top} ${cx + r} ${top}
            L ${cx + BAR - r} ${top}
            Q ${cx + BAR} ${top} ${cx + BAR} ${top + r}
            L ${cx + BAR} ${PAD.top + plotH} Z`}
        fill={fill}
      />
    );
  }

  return (
    <div style={{ position: "relative" }}>
      <div
        style={{ display: "flex", gap: 16, fontSize: 12.5, color: TEXT_MUTED, marginBottom: 6 }}
        aria-hidden
      >
        {(
          [
            [PLANNED, "Planned"],
            [COMPLETED, "Completed"],
          ] as const
        ).map(([color, label]) => (
          <span key={label} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
            <span
              style={{ width: 10, height: 10, borderRadius: 3, background: color, display: "inline-block" }}
            />
            {label}
          </span>
        ))}
      </div>

      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        style={{ width: "100%", height: "auto", display: "block" }}
        role="img"
        aria-label="Stops planned and completed per day"
      >
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD.left} x2={WIDTH - PAD.right} y1={y(t)} y2={y(t)} stroke={GRID} strokeWidth={1} />
            <text x={PAD.left - 6} y={y(t) + 4} textAnchor="end" fontSize={11} fill={TEXT_MUTED}>
              {t}
            </text>
          </g>
        ))}

        {days.map((d, i) => {
          const groupW = BAR * 2 + GAP;
          const x0 = PAD.left + i * band + (band - groupW) / 2;
          return (
            <g key={d.day}>
              {column(x0, d.planned, PLANNED, `${d.day}-p`)}
              {column(x0 + BAR + GAP, d.completed, COMPLETED, `${d.day}-c`)}
              {d.completed > 0 && (
                <text
                  x={x0 + BAR + GAP + BAR / 2}
                  y={y(d.completed) - 5}
                  textAnchor="middle"
                  fontSize={11}
                  fontWeight={600}
                  fill="#16233a"
                >
                  {d.completed}
                </text>
              )}
              <text
                x={PAD.left + i * band + band / 2}
                y={HEIGHT - 8}
                textAnchor="middle"
                fontSize={11}
                fill={TEXT_MUTED}
              >
                {dayLabel(d.day)}
              </text>
              {/* hover hit target: the whole day band */}
              <rect
                x={PAD.left + i * band}
                y={PAD.top}
                width={band}
                height={plotH}
                fill="transparent"
                onMouseEnter={() => setHover(i)}
                onMouseLeave={() => setHover(null)}
              />
            </g>
          );
        })}
      </svg>

      {hover !== null && (
        <div
          style={{
            position: "absolute",
            left: `${((PAD.left + hover * band + band / 2) / WIDTH) * 100}%`,
            top: 20,
            transform: "translateX(-50%)",
            background: "#16233a",
            color: "#fff",
            borderRadius: 6,
            padding: "5px 9px",
            fontSize: 12.5,
            pointerEvents: "none",
            whiteSpace: "nowrap",
            zIndex: 10,
          }}
        >
          <strong>{dayLabel(days[hover].day)}</strong> · planned {days[hover].planned} · completed{" "}
          {days[hover].completed}
        </div>
      )}
    </div>
  );
}
