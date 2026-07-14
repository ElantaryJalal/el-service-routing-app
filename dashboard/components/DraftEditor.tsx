"use client";

import { useEffect, useRef, useState } from "react";
import {
  api,
  type CommitResult,
  type DraftStop,
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

/** Review & correct: the extracted (or hand-entered) rows before commit. */
export default function DraftEditor({ tour, onCommitted }: Props) {
  const [rows, setRows] = useState<DraftStop[] | null>(null);
  const [extracting, setExtracting] = useState(false);
  const [committing, setCommitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [newRow, setNewRow] = useState({ ...EMPTY_ROW });
  const [adding, setAdding] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api
      .getDraft(tour.id)
      .then((d) => setRows(d.stops))
      .catch((e) => setError(String(e.message ?? e)));
  }, [tour.id]);

  async function onPhotoChosen(file: File) {
    setError(null);
    setExtracting(true);
    try {
      const draft = await api.extract(tour.id, file);
      setRows(draft.stops);
    } catch (e) {
      setError(`Extraction failed: ${String((e as Error).message ?? e)}`);
    } finally {
      setExtracting(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

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
      <div className="card">
        <h2>1 · Add stops</h2>
        <p className="muted small" style={{ marginTop: 0 }}>
          Upload the photographed plan — every readable row is extracted,
          matched against the store catalog, and geocoded. Or add stops by hand
          below.
        </p>
        <input
          ref={fileRef}
          type="file"
          accept="image/*"
          hidden
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void onPhotoChosen(f);
          }}
        />
        <button
          className="btn btn-primary"
          disabled={extracting}
          onClick={() => fileRef.current?.click()}
        >
          {extracting ? <span className="spinner" /> : null}
          {extracting ? "Extracting… this can take a minute" : "Upload plan photo"}
        </button>
      </div>

      <div className="card" style={{ paddingBottom: 8 }}>
        <h2>2 · Review &amp; correct</h2>
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
                    No stops yet — upload a plan photo or add rows below.
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
                {COLUMNS.map((col) => (
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
                ))}
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
        <h2>3 · Commit</h2>
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
