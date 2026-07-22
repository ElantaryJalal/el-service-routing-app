"use client";

import { useEffect, useRef, useState } from "react";
import { Input } from "@/components/ui";
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
  /** Bubble header edits up so the workspace title/subtitle stay in sync. */
  onTourChange?: (tour: Tour) => void;
}

/** Row cells, in the paper Tourenplan's column order. Datum & Tag lead, then
 * Kunde, Auftrag/VST, the address (Ort/Straße/PLZ) and Bemerkung. Tasks and
 * Min follow — not on the paper, but the app needs them downstream. */
type EditableField =
  | "date"
  | "customer"
  | "order_no"
  | "city"
  | "street"
  | "postal_code"
  | "remarks"
  | "tasks"
  | "service_minutes";

type ColKind = "date" | "text" | "number" | "derived";

interface Column {
  field: EditableField | "weekday";
  label: string;
  kind: ColKind;
  /** Type-ahead against the store catalog (name / order no. / address). */
  suggest?: boolean;
  width?: number;
}

const COLUMNS: Column[] = [
  { field: "date", label: "Datum", kind: "date", width: 150 },
  { field: "weekday", label: "Tag", kind: "derived", width: 48 },
  { field: "customer", label: "Kunde", kind: "text", suggest: true },
  { field: "order_no", label: "Auftrag/VST", kind: "text", suggest: true, width: 110 },
  { field: "city", label: "Ort", kind: "text", suggest: true, width: 120 },
  { field: "street", label: "Straße", kind: "text", suggest: true },
  { field: "postal_code", label: "PLZ", kind: "text", width: 72 },
  { field: "remarks", label: "Bemerkung", kind: "text" },
  { field: "tasks", label: "Tasks", kind: "text" },
  { field: "service_minutes", label: "Min", kind: "number", width: 58 },
];

/** Cells that share the type-ahead dropdown. */
const SUGGEST_FIELDS: EditableField[] = ["customer", "order_no", "city", "street"];

const LOW_CONFIDENCE = 0.75;

const WEEKDAYS_DE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];

/** The paper's "Tag" — derived from the ISO date, matching the backend. */
function weekdayDe(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso + "T00:00:00");
  if (Number.isNaN(d.getTime())) return "";
  return WEEKDAYS_DE[(d.getDay() + 6) % 7];
}

type NewRow = Record<EditableField, string>;
const EMPTY_ROW: NewRow = {
  date: "",
  customer: "",
  order_no: "",
  city: "",
  street: "",
  postal_code: "",
  remarks: "",
  tasks: "",
  service_minutes: "",
};

/** Enter & correct the tour's rows before commit, in the same columns and
 * order as the office's paper Tourenplan. The dispatcher keys a whole week
 * quickly (Tab across cells, Enter for the next row); known stores drop in
 * from the catalog via type-ahead so verified addresses are never re-typed.
 * Photo extraction is a mobile-only path, so drafts arriving from there can
 * still carry confidence flags. */
export default function DraftEditor({ tour, onCommitted, onTourChange }: Props) {
  const [rows, setRows] = useState<DraftStop[] | null>(null);
  const [committing, setCommitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [newRow, setNewRow] = useState<NewRow>({ ...EMPTY_ROW });
  // The catalog store picked for the add row (null once a field is retyped).
  const [pickedStoreId, setPickedStoreId] = useState<number | null>(null);
  const [adding, setAdding] = useState(false);

  // Header (paper Kopfdaten): local mirror, patched on blur.
  const [header, setHeader] = useState({
    customer: tour.customer,
    calendar_week: String(tour.calendar_week),
    date_from: tour.date_from,
    date_to: tour.date_to,
    team_lead: tour.team_lead ?? "",
    employee: tour.employee ?? "",
    team_no: tour.team_no ?? "",
    vehicle: tour.vehicle ?? "",
  });

  // Type-ahead: one dropdown shared across the suggestable add-row cells.
  const [suggestions, setSuggestions] = useState<StopSuggestion[]>([]);
  const [suggestOpen, setSuggestOpen] = useState(false);
  const [highlighted, setHighlighted] = useState(0);
  // Viewport position for the dropdown: position:fixed escapes the table's
  // overflow-x scroll container, which would otherwise clip the list.
  const [suggestPos, setSuggestPos] = useState({ top: 0, left: 0 });
  const suggestTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const firstAddCell = useRef<HTMLInputElement>(null);

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

  // --- Header -------------------------------------------------------------

  async function saveHeader(
    field: keyof typeof header,
    raw: string,
  ): Promise<void> {
    const value = raw.trim();
    if (field === "customer") {
      if (!value || value === tour.customer) return;
      await patchHeader({ customer: value });
    } else if (field === "calendar_week") {
      const n = Number(value);
      if (!value || Number.isNaN(n) || n === tour.calendar_week) return;
      await patchHeader({ calendar_week: n });
    } else if (field === "date_from" || field === "date_to") {
      if (!value || value === tour[field]) return;
      await patchHeader({ [field]: value });
    } else {
      // team_lead / employee / team_no / vehicle — empty clears (send null).
      if (value === (tour[field] ?? "")) return;
      await patchHeader({ [field]: value || null });
    }
  }

  async function patchHeader(
    body: Parameters<typeof api.updateTour>[1],
  ): Promise<void> {
    try {
      const updated = await api.updateTour(tour.id, body);
      onTourChange?.(updated);
    } catch (e) {
      setError(`Could not save the header: ${String((e as Error).message ?? e)}`);
    }
  }

  // --- Existing rows ------------------------------------------------------

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

  // --- Add row + type-ahead ----------------------------------------------

  function onSuggestTyped(
    field: EditableField,
    value: string,
    input: HTMLInputElement,
  ) {
    const rect = input.getBoundingClientRect();
    setSuggestPos({ top: rect.bottom + 2, left: rect.left });
    setNewRow((prev) => ({ ...prev, [field]: value }));
    // Editing an identifying field breaks any earlier catalog pick.
    setPickedStoreId(null);
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
      order_no: (s.order_no ?? prev.order_no) || "",
      street: s.street ?? prev.street,
      postal_code: s.postal_code ?? prev.postal_code,
      city: s.city ?? prev.city,
      tasks: prev.tasks || (s.tasks ?? ""),
      service_minutes:
        prev.service_minutes ||
        (s.service_minutes != null ? String(s.service_minutes) : ""),
    }));
    // Link the catalog store so commit inherits its verified data verbatim.
    setPickedStoreId(s.store_id);
    setSuggestOpen(false);
  }

  function onSuggestKeyDown(field: EditableField, e: React.KeyboardEvent) {
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
    if (!newRow.customer && !newRow.street && !newRow.order_no) return;
    setAdding(true);
    setError(null);
    try {
      const created = await api.addStop(tour.id, {
        date: newRow.date || null,
        customer: newRow.customer || null,
        order_no: newRow.order_no || null,
        city: newRow.city || null,
        street: newRow.street || null,
        postal_code: newRow.postal_code || null,
        remarks: newRow.remarks || null,
        tasks: newRow.tasks || null,
        service_minutes: newRow.service_minutes
          ? Number(newRow.service_minutes)
          : null,
        store_id: pickedStoreId,
      });
      setRows((prev) => [...(prev ?? []), created]);
      // Keep the date so a whole day's rows share it; reset the rest.
      setNewRow({ ...EMPTY_ROW, date: newRow.date });
      setPickedStoreId(null);
      firstAddCell.current?.focus();
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
      <div className="card">
        <h2>Tourenplan — Kopfdaten</h2>
        <div className="form-row">
          <Input
            label="Kunde"
            value={header.customer}
            onChange={(e) =>
              setHeader((h) => ({ ...h, customer: e.target.value }))
            }
            onBlur={(e) => void saveHeader("customer", e.target.value)}
          />
          <Input
            label="KW"
            type="number"
            min={1}
            max={53}
            style={{ maxWidth: 90 }}
            value={header.calendar_week}
            onChange={(e) =>
              setHeader((h) => ({ ...h, calendar_week: e.target.value }))
            }
            onBlur={(e) => void saveHeader("calendar_week", e.target.value)}
          />
          <Input
            label="Zeitraum von"
            type="date"
            value={header.date_from}
            onChange={(e) =>
              setHeader((h) => ({ ...h, date_from: e.target.value }))
            }
            onBlur={(e) => void saveHeader("date_from", e.target.value)}
          />
          <Input
            label="bis"
            type="date"
            value={header.date_to}
            onChange={(e) =>
              setHeader((h) => ({ ...h, date_to: e.target.value }))
            }
            onBlur={(e) => void saveHeader("date_to", e.target.value)}
          />
        </div>
        <div className="form-row">
          <Input
            label="Teamleiter"
            value={header.team_lead}
            onChange={(e) =>
              setHeader((h) => ({ ...h, team_lead: e.target.value }))
            }
            onBlur={(e) => void saveHeader("team_lead", e.target.value)}
          />
          <Input
            label="Mitarbeiter"
            value={header.employee}
            onChange={(e) =>
              setHeader((h) => ({ ...h, employee: e.target.value }))
            }
            onBlur={(e) => void saveHeader("employee", e.target.value)}
          />
          <Input
            label="Team-Nr."
            style={{ maxWidth: 110 }}
            value={header.team_no}
            onChange={(e) =>
              setHeader((h) => ({ ...h, team_no: e.target.value }))
            }
            onBlur={(e) => void saveHeader("team_no", e.target.value)}
          />
          <Input
            label="Fahrzeug"
            value={header.vehicle}
            onChange={(e) =>
              setHeader((h) => ({ ...h, vehicle: e.target.value }))
            }
            onBlur={(e) => void saveHeader("vehicle", e.target.value)}
          />
        </div>
      </div>

      <div className="card" style={{ paddingBottom: 8 }}>
        <h2>1 · Stops eintragen</h2>
        <p className="muted small" style={{ marginTop: 0 }}>
          Enter the plan rows in the paper&apos;s columns — Datum, Kunde,
          Auftrag/VST, Ort, Straße, PLZ, Bemerkung. Type a name or order number
          and pick the known store from the list to fill its verified address
          in one click. Tab moves across cells, Enter starts the next row.
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
                <th style={{ width: 40 }} />
              </tr>
            </thead>
            <tbody>
              {rows === null ? (
                <tr>
                  <td colSpan={COLUMNS.length + 2} className="muted">
                    Loading…
                  </td>
                </tr>
              ) : rows.length === 0 ? (
                <tr>
                  <td colSpan={COLUMNS.length + 2} className="muted">
                    No stops yet — add the first row below.
                  </td>
                </tr>
              ) : (
                rows.map((stop, i) => (
                  <tr key={stop.id}>
                    <td className="num muted">{i + 1}</td>
                    {COLUMNS.map((col) => {
                      if (col.field === "weekday") {
                        return (
                          <td key={col.field} className="muted small">
                            {stop.weekday ?? weekdayDe(stop.date ?? "")}
                          </td>
                        );
                      }
                      const field = col.field as EditableField;
                      const conf = stop.confidence[field];
                      const low = conf !== undefined && conf < LOW_CONFIDENCE;
                      return (
                        <td key={col.field}>
                          <input
                            className={`cell-input${low ? " cell-low-confidence" : ""}`}
                            type={
                              col.kind === "date"
                                ? "date"
                                : col.kind === "number"
                                  ? "number"
                                  : "text"
                            }
                            defaultValue={cellValue(stop, field)}
                            title={
                              low
                                ? `Low extraction confidence (${Math.round(conf * 100)}%) — please verify`
                                : undefined
                            }
                            aria-label={`${col.label} for row ${i + 1}`}
                            onBlur={(e) =>
                              void saveCell(
                                stop.id,
                                field,
                                col.kind === "date"
                                  ? e.target.value
                                  : e.target.value.trim(),
                              )
                            }
                          />
                        </td>
                      );
                    })}
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
                {COLUMNS.map((col, ci) => {
                  if (col.field === "weekday") {
                    return (
                      <td key={col.field} className="muted small">
                        {weekdayDe(newRow.date)}
                      </td>
                    );
                  }
                  const field = col.field as EditableField;
                  const isSuggest = SUGGEST_FIELDS.includes(field) && col.suggest;
                  const isFirst = ci === 0;
                  return (
                    <td
                      key={col.field}
                      className={isSuggest ? "suggest-wrap" : undefined}
                    >
                      <input
                        ref={isFirst ? firstAddCell : undefined}
                        className="cell-input"
                        type={
                          col.kind === "date"
                            ? "date"
                            : col.kind === "number"
                              ? "number"
                              : "text"
                        }
                        placeholder={col.label}
                        aria-label={`New stop ${col.label}`}
                        aria-autocomplete={isSuggest ? "list" : undefined}
                        aria-expanded={isSuggest ? suggestOpen : undefined}
                        value={newRow[field]}
                        onChange={(e) =>
                          isSuggest
                            ? onSuggestTyped(field, e.target.value, e.target)
                            : setNewRow((prev) => ({
                                ...prev,
                                [field]: e.target.value,
                              }))
                        }
                        onKeyDown={(e) => {
                          if (isSuggest) {
                            onSuggestKeyDown(field, e);
                          } else if (e.key === "Enter") {
                            void addRow();
                          }
                        }}
                        onBlur={
                          isSuggest
                            ? () => setTimeout(() => setSuggestOpen(false), 150)
                            : undefined
                        }
                      />
                    </td>
                  );
                })}
                <td>
                  <button
                    className="btn btn-sm"
                    disabled={
                      adding ||
                      (!newRow.customer && !newRow.street && !newRow.order_no)
                    }
                    onClick={() => void addRow()}
                  >
                    Add
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
          {suggestOpen && (
            <div
              className="suggest-list"
              role="listbox"
              style={{ top: suggestPos.top, left: suggestPos.left }}
            >
              {suggestions.map((s, i) => (
                <div
                  key={`${s.store_id ?? "h"}|${s.name}|${s.order_no ?? ""}`}
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
                    {s.order_no && (
                      <span className="chip" style={{ marginLeft: 6 }}>
                        VST {s.order_no}
                      </span>
                    )}
                    {s.source === "history" && (
                      <span className="chip" style={{ marginLeft: 6 }}>
                        previous tour
                      </span>
                    )}
                  </div>
                  <div className="sub">
                    {[
                      s.street,
                      [s.postal_code, s.city].filter(Boolean).join(" "),
                    ]
                      .filter(Boolean)
                      .join(", ") || "no address on file"}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="card">
        <h2>2 · Commit</h2>
        <p className="muted small" style={{ marginTop: 0 }}>
          Commit confirms the stops, matches each row to the catalog, geocodes
          anything still missing a location, fetches opening hours, and flags
          suspected duplicates. Unrecognised addresses become new stores for
          review.
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
