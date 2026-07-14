"use client";

import dynamic from "next/dynamic";

/** Leaflet touches `window` at import time — client-only. */
const TourMap = dynamic(() => import("./TourMapInner"), {
  ssr: false,
  loading: () => <div className="tour-map muted" style={{ padding: 16 }}>Loading map…</div>,
});

export default TourMap;
