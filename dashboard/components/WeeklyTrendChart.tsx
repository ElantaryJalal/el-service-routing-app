"use client";

/** Six-week trend as two stacked small multiples sharing the week axis (two
 * measures of different scale get two plots, never a dual axis): stops per
 * week as columns (planned = light track shade behind completed = primary,
 * the WeekLoadChart pairing), and the on-time completion rate as a line on
 * its own 0–100 % scale. One hover band spans both panels. */

import { useState } from "react";

export interface WeekTrendPoint {
  label: string; // "KW 26"
  planned: number;
  completed: number;
  onTimeRate: number | null; // 0..1, null = no timed completions that week
}

const PLANNED = "#bccff7";
const COMPLETED = "#1e40af";
const LINE = "#1e40af";
const GRID = "#e6ebf3";
const TEXT_MUTED = "#5b6b84";
const TEXT_STRONG = "#16233a";
const SURFACE = "#ffffff";

const WIDTH = 640;
const BAR = 14;
const GAP = 2; // surface gap between the paired columns
const PAD = { top: 16, right: 8, left: 34 };
const COLS_H = 132; // column plot height
const PANEL_GAP = 34; // room for the columns' x-strip title of panel 2
const LINE_H = 96; // line plot height
const BOTTOM = 26; // week labels
const HEIGHT = PAD.top + COLS_H + PANEL_GAP + LINE_H + BOTTOM;

function niceMax(n: number): number {
  if (n <= 4) return 4;
  const step = n <= 10 ? 2 : n <= 20 ? 5 : n <= 50 ? 10 : 25;
  return Math.ceil(n / step) * step;
}

export default function WeeklyTrendChart({ weeks }: { weeks: WeekTrendPoint[] }) {
  const [hover, setHover] = useState<number | null>(null);

  if (weeks.length === 0) return null;

  const plotW = WIDTH - PAD.left - PAD.right;
  const band = plotW / weeks.length;
  const bandCenter = (i: number) => PAD.left + i * band + band / 2;

  // Panel 1 — stop columns.
  const colsTop = PAD.top;
  const max = niceMax(Math.max(1, ...weeks.map((w) => Math.max(w.planned, w.completed))));
  const yCol = (v: number) => colsTop + COLS_H - (v / max) * COLS_H;

  // Panel 2 — on-time rate line (its own axis, 0–100 %).
  const lineTop = colsTop + COLS_H + PANEL_GAP;
  const yRate = (r: number) => lineTop + LINE_H - r * LINE_H;
  const linePoints = weeks
    .map((w, i) => ({ i, rate: w.onTimeRate }))
    .filter((p): p is { i: number; rate: number } => p.rate !== null);

  // 4px rounded data-end, square at the baseline (WeekLoadChart idiom).
  function column(cx: number, value: number, fill: string, key: string) {
    const h = (value / max) * COLS_H;
    const r = Math.min(4, h);
    const top = yCol(value);
    return (
      <path
        key={key}
        d={`M ${cx} ${colsTop + COLS_H}
            L ${cx} ${top + r}
            Q ${cx} ${top} ${cx + r} ${top}
            L ${cx + BAR - r} ${top}
            Q ${cx + BAR} ${top} ${cx + BAR} ${top + r}
            L ${cx + BAR} ${colsTop + COLS_H} Z`}
        fill={fill}
      />
    );
  }

  const hovered = hover !== null ? weeks[hover] : null;

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
        aria-label="Stops per week and on-time completion rate, last weeks"
      >
        {/* panel 1 grid + axis */}
        {[0, max / 2, max].map((t) => (
          <g key={`c${t}`}>
            <line x1={PAD.left} x2={WIDTH - PAD.right} y1={yCol(t)} y2={yCol(t)} stroke={GRID} />
            <text x={PAD.left - 6} y={yCol(t) + 4} textAnchor="end" fontSize={11} fill={TEXT_MUTED}>
              {t}
            </text>
          </g>
        ))}

        {weeks.map((w, i) => {
          const groupW = BAR * 2 + GAP;
          const x0 = PAD.left + i * band + (band - groupW) / 2;
          return (
            <g key={w.label}>
              {column(x0, w.planned, PLANNED, `${w.label}-p`)}
              {column(x0 + BAR + GAP, w.completed, COMPLETED, `${w.label}-c`)}
              {w.completed > 0 && (
                <text
                  x={x0 + BAR + GAP + BAR / 2}
                  y={yCol(w.completed) - 5}
                  textAnchor="middle"
                  fontSize={11}
                  fontWeight={600}
                  fill={TEXT_STRONG}
                >
                  {w.completed}
                </text>
              )}
            </g>
          );
        })}

        {/* panel 2 title, grid + axis */}
        <text x={PAD.left} y={lineTop - 12} fontSize={12} fontWeight={600} fill={TEXT_STRONG}>
          On-time completion rate
        </text>
        {[0, 0.5, 1].map((t) => (
          <g key={`r${t}`}>
            <line x1={PAD.left} x2={WIDTH - PAD.right} y1={yRate(t)} y2={yRate(t)} stroke={GRID} />
            <text x={PAD.left - 6} y={yRate(t) + 4} textAnchor="end" fontSize={11} fill={TEXT_MUTED}>
              {Math.round(t * 100)}%
            </text>
          </g>
        ))}

        {linePoints.length > 1 && (
          <polyline
            points={linePoints.map((p) => `${bandCenter(p.i)},${yRate(p.rate)}`).join(" ")}
            fill="none"
            stroke={LINE}
            strokeWidth={2}
            strokeLinejoin="round"
          />
        )}
        {linePoints.map((p) => (
          <g key={`pt${p.i}`}>
            {/* 2px surface ring so markers stay separable on the line */}
            <circle cx={bandCenter(p.i)} cy={yRate(p.rate)} r={6} fill={SURFACE} />
            <circle cx={bandCenter(p.i)} cy={yRate(p.rate)} r={4} fill={LINE} />
            <text
              x={bandCenter(p.i)}
              y={yRate(p.rate) - 10}
              textAnchor="middle"
              fontSize={11}
              fontWeight={600}
              fill={TEXT_STRONG}
            >
              {Math.round(p.rate * 100)}%
            </text>
          </g>
        ))}

        {/* shared labels + hover bands */}
        {weeks.map((w, i) => (
          <g key={`x${w.label}`}>
            <text
              x={bandCenter(i)}
              y={HEIGHT - 8}
              textAnchor="middle"
              fontSize={11}
              fill={TEXT_MUTED}
            >
              {w.label}
            </text>
            <rect
              x={PAD.left + i * band}
              y={PAD.top}
              width={band}
              height={HEIGHT - PAD.top - BOTTOM}
              fill="transparent"
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover(null)}
            />
          </g>
        ))}
      </svg>

      {hovered !== null && hover !== null && (
        <div
          style={{
            position: "absolute",
            left: `${(bandCenter(hover) / WIDTH) * 100}%`,
            top: 24,
            transform: "translateX(-50%)",
            background: TEXT_STRONG,
            color: "#fff",
            borderRadius: 6,
            padding: "5px 9px",
            fontSize: 12.5,
            pointerEvents: "none",
            whiteSpace: "nowrap",
            zIndex: 10,
          }}
        >
          <strong>{hovered.label}</strong> · planned {hovered.planned} · completed{" "}
          {hovered.completed} · on-time{" "}
          {hovered.onTimeRate !== null ? `${Math.round(hovered.onTimeRate * 100)}%` : "—"}
        </div>
      )}
    </div>
  );
}
