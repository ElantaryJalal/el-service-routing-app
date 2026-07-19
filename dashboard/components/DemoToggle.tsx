"use client";

import { useEffect, useState } from "react";

const KEY = "office:showDemo";
const EVENT = "office:showDemo-changed";

function read(): boolean {
  if (typeof window === "undefined") return false;
  return localStorage.getItem(KEY) === "true";
}

/** Whether demo/seeded data should be included in dashboard queries.
 * Off by default and per-browser only — a real viewer never sees demo rows
 * unless they flip the switch themselves. */
export function useShowDemo(): boolean {
  const [show, setShow] = useState(false);
  useEffect(() => {
    setShow(read());
    const onChange = () => setShow(read());
    window.addEventListener(EVENT, onChange);
    return () => window.removeEventListener(EVENT, onChange);
  }, []);
  return show;
}

export default function DemoToggle() {
  const show = useShowDemo();
  return (
    <label
      className="muted small"
      style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
      title="Include seeded/simulated rows (demo tours, test users) in this view"
    >
      <input
        type="checkbox"
        checked={show}
        onChange={(e) => {
          localStorage.setItem(KEY, String(e.target.checked));
          window.dispatchEvent(new Event(EVENT));
        }}
      />
      Show demo data
    </label>
  );
}
