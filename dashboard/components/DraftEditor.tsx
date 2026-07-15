"use client";

import { useEffect, useRef, useState } from "react";
import {
  api,
  type CommitResult,
  type DraftStop,
  type StopSuggestion,
  type Tour,
} from "@/lib/api";

interface Props {
  tour: Tour;
  onCommitted: (result: CommitResult) => void;
}

const EDITABLE = [
  "customer",
  "street",
  "postal_code",
  "city",
  "order_no",
  "tasks",
  "service_minutes",
] as const;
type EditableField = (typeof EDITABLE)[number];

const COLUMNS: { field: EditableField; label: string; width?: number }[] = [
  { field: "customer", label: "Market" },
  { field: "street", label: "Street" },
  { field: "postal_code", label: "PLZ", width: 70 },
  { field: "city", label: "City", width: 110 },
  { field: "order_no", label: "Order no.", width: 100 },
  { field: "tasks", label: "Tasks" },
  { field: "service_minutes", label: "Min", width: 60 },
];

const LOW_CONFIDENCE = 0.75;

const EMPTY_ROW: Record<EditableField, string> = {
  customer: "",
  street: "",
  postal_code: "",
  city: "",
  order_no: "",
  tasks: "",
  service_minutes: "",
};

/** Enter & correct the tour's rows before commit. The office keys the plan
 * in from their Excel sheet (same columns); photo extraction is a mobile-only
 * path, so drafts arriving from there can still carry confidence flags. */
export default function DraftEditor({ tour, onCommitted }: Props) {
  const [rows, setRows] = useState<DraftStop[] | null>(null);
  const [committing, setCommitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [newRow, setNewRow] = useState({ ...EMPTY_ROW });
  const [adding, setAdding] = useState(false);
  // Type-ahead on the Market cell: known stores + markets from past tours.
  const [suggestions, setSuggestions] = useState<StopSuggestion[]>([]);
  const [suggestOpen, setSuggestOpen] = useState(false);
  const [highlighted, setHighlighted] = useState(0);
  // Viewport position for the dropdown: position:fixed escapes the table's
  // overflow-x scroll container, which would otherwise clip the list.
  const [suggestPos, setSuggestPos] = useState({ top: 0, left: 0 });
  const suggestTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    api
      .getDraft(tour.id)
      .then((d) => setRows(d.stops))
      .catch((e) => setError(String(e.message ?? e)));
  }, [tour.id]);

  function cellValue(stop: DraftStop, field: EditableField): string {
    const v = stop[field];
    return v === null || v === undefined ? "" : String(v);
  }

  async function saveCell(stopId: number, field: EditableField, raw: string) {
    const current = rows?.find((r) => r.id === stopId);
    if (!current) return;
    if (cellValue(current, field) === raw) return; // unchanged

    const value =
      field === "service_minutes"
        ? raw === ""
          ? null
          : Number(raw)
        : raw === ""
          ? null
          : raw;
    try {
      const updated = await api.patchDraftStop(tour.id, stopId, {
        [field]: value,
      });
      setRows((prev) =>
        (prev ?? []).map((r) => (r.id === stopId ? updated : r)),
      );
    } catch (e) {
      setError(`Could not save: ${String((e as Error).message ?? e)}`);
    }
  }

  async function removeRow(stopId: number) {
    try {
      await api.deleteStop(stopId);
      setRows((prev) => (prev ?? []).filter((r) => r.id !== stopId));
    } catch (e) {
      setError(String((e as Error).message ?? e));
    }
  }

  function onMarketTyped(value: string, input: HTMLInputElement) {
    const rect = input.getBoundingClientRect();
    setSuggestPos({ top: rect.bottom + 2, left: rect.left });
    setNewRow((prev) => ({ ...prev, customer: value }));
    if (suggestTimer.current) clearTimeout(suggestTimer.current);
    const q = value.trim();
    if (q.length < 2) {
      setSuggestOpen(false);
      setSuggestions([]);
      return;
    }
    suggestTimer.current = setTimeout(() => {
      api
        .suggestStops(q)
        .then((items) => {
          setSuggestions(items);
          setHighlighted(0);
          setSuggestOpen(items.length > 0);
        })
        .catch(() => setSuggestOpen(false));
    }, 200);
  }

  function pickSuggestion(s: StopSuggestion) {
    setNewRow((prev) => ({
      ...prev,
      customer: s.name,
      street: s.street ?? "",
      postal_code: s.postal_code ?? "",
      city: s.city ?? "",
      tasks: prev.tasks || (s.tasks ?? ""),
      service_minutes:
        prev.service_minutes ||
        (s.service_minutes != null ? String(s.service_minutes) : ""),
    }));
    setSuggestOpen(false);
  }

  function onMarketKeyDown(e: React.KeyboardEvent) {
    if (!suggestOpen) {
      if (e.key === "Enter") void addRow();
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlighted((h) => (h + 1) % suggestions.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlighted((h) => (h - 1 + suggestions.length) % suggestions.length);
    } else if (e.key === "Enter") {
      e.preventDefault();
      pickSuggestion(suggestions[highlighted]);
    } else if (e.key === "Escape") {
      setSuggestOpen(false);
    }
  }

  async function addRow() {
    if (!newRow.customer && !newRow.street) return;
    setAdding(true);
    setError(null);
    try {
      const created = await api.addStop(tour.id, {
        customer: newRow.customer || null,
        street: newRow.street || null,
        postal_code: newRow.postal_code || null,
        city: newRow.city || null,
        order_no: newRow.order_no || null,
        tasks: newRow.tasks || null,
        service_minutes: newRow.service_minutes
          ? Number(newRow.service_minutes)
          : null,
      });
      setRows((prev) => [...(prev ?? []), created]);
      setNewRow({ ...EMPTY_ROW });
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setAdding(false);
    }
  }

  async function commit() {
    setCommitting(true);
    setError(null);
    try {
      onCommitted(await api.commit(tour.id));
    } catch (e) {
      setError(`Commit failed: ${String((e as Error).message ?? e)}`);
      setCommitting(false);
    }
  }

  const hasLowConfidence = (rows ?? []).some((r) =>
    Object.values(r.confidence).some((c) => c < LOW_CONFIDENCE),
  );

  return (
    <>
      <div className="card" style={{ paddingBottom: 8 }}>
        <h2>1 · Add stops</h2>
        <p className="muted small" style={{ marginTop: 0 }}>
          Enter the plan rows just like in the Excel sheet — market, address,
          order no., tasks. Known stores are matched against the catalog on
          commit, so a name and PLZ are usually enough.
        </p>
        {hasLowConfidence && (
          <div className="banner banner-warn">
            Highlighted fields were hard to read on the photo — please verify
            them. Editing a field clears its flag.
          </div>
        )}
        {error && <div className="banner banner-error">{error}</div>}
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th style={{ width: 30 }}>#</th>
                {COLUMNS.map((c) => (
                  <th key={c.field} style={c.width ? { width: c.width } : {}}>
                    {c.label}
                  </th>
                ))}
                <th>Remarks</th>
                <th style={{ width: 40 }} />
              </tr>
            </thead>
            <tbody>
              {rows === null ? (
                <tr>
                  <td colSpan={COLUMNS.length + 3} className="muted">
                    Loading…
                  </td>
                </tr>
              ) : rows.length === 0 ? (
                <tr>
                  <td colSpan={COLUMNS.length + 3} className="muted">
                    No stops yet — add the first row below.
                  </td>
                </tr>
              ) : (
                rows.map((stop, i) => (
                  <tr key={stop.id}>
                    <td className="num muted">{i + 1}</td>
                    {COLUMNS.map((col) => {
                      const conf = stop.confidence[col.field];
                      const low = conf !== undefined && conf < LOW_CONFIDENCE;
                      return (
                        <td key={col.field}>
                          <input
                            className={`cell-input${low ? " cell-low-confidence" : ""}`}
                            defaultValue={cellValue(stop, col.field)}
                            title={
                              low
                                ? `Low extraction confidence (${Math.round(conf * 100)}%) — please verify`
                                : undefined
                            }
                            aria-label={`${col.label} for row ${i + 1}`}
                            onBlur={(e) =>
                              void saveCell(stop.id, col.field, e.target.value.trim())
                            }
                          />
                        </td>
                      );
                    })}
                    <td className="muted small">{stop.remarks ?? ""}</td>
                    <td>
                      <button
                        className="btn btn-sm btn-danger"
                        aria-label={`Delete row ${i + 1}`}
                        onClick={() => void removeRow(stop.id)}
                      >
                        ✕
                      </button>
                    </td>
                  </tr>
                ))
              )}
              {/* manual add row */}
              <tr>
                <td className="muted">+</td>
                {COLUMNS.map((col) =>
                  col.field === "customer" ? (
                    <td key={col.field} className="suggest-wrap">
                      <input
                        className="cell-input"
                        placeholder="Market"
                        aria-label="New stop Market"
                        aria-autocomplete="list"
                        aria-expanded={suggestOpen}
                        value={newRow.customer}
                        onChange={(e) => onMarketTyped(e.target.value, e.target)}
                        onKeyDown={onMarketKeyDown}
                        onBlur={() => setTimeout(() => setSuggestOpen(false), 150)}
                      />
                      {suggestOpen && (
                        <div
                          className="suggest-list"
                          role="listbox"
                          style={{ top: suggestPos.top, left: suggestPos.left }}
                        >
                          {suggestions.map((s, i) => (
                            <div
                              key={`${s.name}|${s.street}|${s.postal_code}`}
                              role="option"
                              aria-selected={i === highlighted}
                              className={`suggest-item${i === highlighted ? " active" : ""}`}
                              onMouseDown={(e) => {
                                e.preventDefault();
                                pickSuggestion(s);
                              }}
                              onMouseEnter={() => setHighlighted(i)}
                            >
                              <div>
                                {s.name}
                                {s.source === "history" && (
                                  <span className="chip" style={{ marginLeft: 6 }}>
                                    previous tour
                                  </span>
                                )}
                              </div>
                              <div className="sub">
                                {[s.street, [s.postal_code, s.city].filter(Boolean).join(" ")]
                                  .filter(Boolean)
                                  .join(", ") || "no address on file"}
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </td>
                  ) : (
                    <td key={col.field}>
                      <input
                        className="cell-input"
                        placeholder={col.label}
                        aria-label={`New stop ${col.label}`}
                        value={newRow[col.field]}
                        onChange={(e) =>
                          setNewRow((prev) => ({
                            ...prev,
                            [col.field]: e.target.value,
                          }))
                        }
                        onKeyDown={(e) => {
                          if (e.key === "Enter") void addRow();
                        }}
                      />
                    </td>
                  ),
                )}
                <td />
                <td>
                  <button
                    className="btn btn-sm"
                    disabled={adding || (!newRow.customer && !newRow.street)}
                    onClick={() => void addRow()}
                  >
                    Add
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <h2>2 · Commit</h2>
        <p className="muted small" style={{ marginTop: 0 }}>
          Commit confirms the stops, geocodes anything still missing a
          location, fetches opening hours, and flags suspected duplicates.
        </p>
        <button
          className="btn btn-primary"
          disabled={committing || !rows || rows.length === 0}
          onClick={() => void commit()}
        >
          {committing ? <span className="spinner" /> : null}
          Commit tour
        </button>
      </div>
    </>
  );
}
