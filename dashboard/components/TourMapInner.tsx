"use client";

import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { Plan, StopDetail } from "@/lib/api";
import { dayColor } from "@/lib/planView";

interface Props {
  stops: StopDetail[];
  plan: Plan | null;
}

/** Day-by-day route preview: numbered day-colored markers + per-day
 * polylines, mirroring the mobile map's scheme. */
export default function TourMapInner({ stops, plan }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const layerRef = useRef<L.LayerGroup | null>(null);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = L.map(containerRef.current, { zoomControl: true }).setView(
      [51.34, 12.37],
      9,
    );
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "&copy; OpenStreetMap contributors",
      maxZoom: 19,
    }).addTo(map);
    mapRef.current = map;
    layerRef.current = L.layerGroup().addTo(map);
    return () => {
      map.remove();
      mapRef.current = null;
      layerRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    const layer = layerRef.current;
    if (!map || !layer) return;
    layer.clearLayers();

    const byId = new Map(stops.map((s) => [s.id, s]));
    const bounds: L.LatLngTuple[] = [];

    const renderStop = (
      stop: StopDetail,
      color: string,
      label: string,
      opacity = 1,
    ) => {
      if (stop.lat == null || stop.lng == null) return;
      const pos: L.LatLngTuple = [stop.lat, stop.lng];
      bounds.push(pos);
      const icon = L.divIcon({
        className: "",
        iconSize: [24, 24],
        iconAnchor: [12, 12],
        html: `<div class="marker-day" style="background:${color};opacity:${opacity}">${label}</div>`,
      });
      const address = [stop.street, [stop.postal_code, stop.city].filter(Boolean).join(" ")]
        .filter(Boolean)
        .join(", ");
      L.marker(pos, { icon })
        .bindPopup(
          `<strong>${stop.store_name ?? stop.customer ?? "Stop " + stop.id}</strong>` +
            (address
              ? `<br><span style="color:var(--color-text-muted)">${address}</span>`
              : "") +
            (stop.tasks
              ? `<br><span style="font-size:var(--text-label)">${stop.tasks}</span>`
              : "") +
            (stop.completed_at
              ? `<br><span style="color:var(--color-success);font-weight:600">✓ completed</span>`
              : ""),
        )
        .addTo(layer);
    };

    if (plan && plan.days.length > 0) {
      plan.days.forEach((day, dayIndex) => {
        const color = dayColor(dayIndex);
        const line: L.LatLngTuple[] = [];
        for (const planStop of day.stops) {
          const stop = byId.get(planStop.stop_id);
          if (!stop || stop.lat == null || stop.lng == null) continue;
          line.push([stop.lat, stop.lng]);
          renderStop(
            stop,
            stop.completed_at ? "var(--color-text-faint)" : color,
            String(planStop.sequence),
          );
        }
        if (line.length > 1) {
          L.polyline(line, { color, weight: 3, opacity: 0.8 }).addTo(layer);
        }
      });
    } else {
      // No plan yet: show every geocoded stop neutrally.
      stops.forEach((s, i) =>
        renderStop(s, "var(--color-text-muted)", String(i + 1)),
      );
    }

    if (bounds.length > 0) {
      map.fitBounds(L.latLngBounds(bounds).pad(0.15));
    }
  }, [stops, plan]);

  return <div ref={containerRef} className="tour-map" />;
}
