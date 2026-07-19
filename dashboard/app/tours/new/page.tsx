"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import AppShell from "@/components/AppShell";
import { Button, Card, Input } from "@/components/ui";
import { Protected } from "@/lib/auth";
import { api } from "@/lib/api";

/** ISO week number for a date (KW on German plans). */
function isoWeek(dateStr: string): number {
  const d = new Date(dateStr + "T00:00:00");
  const day = (d.getDay() + 6) % 7;
  d.setDate(d.getDate() - day + 3);
  const firstThursday = new Date(d.getFullYear(), 0, 4);
  const diff = d.getTime() - firstThursday.getTime();
  return 1 + Math.round(diff / (7 * 24 * 3600 * 1000));
}

function NewTourPage() {
  const router = useRouter();
  const [customer, setCustomer] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [week, setWeek] = useState<number | "">("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function onFromChange(value: string) {
    setDateFrom(value);
    if (value) {
      setWeek(isoWeek(value));
      if (!dateTo) {
        // A tour week: Monday..Friday by default.
        const d = new Date(value + "T00:00:00");
        d.setDate(d.getDate() + 4);
        setDateTo(d.toISOString().slice(0, 10));
      }
    }
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!dateFrom || !dateTo || dateTo < dateFrom) {
      setError("Check the date range.");
      return;
    }
    setBusy(true);
    try {
      const tour = await api.createTour({
        customer,
        calendar_week: week === "" ? isoWeek(dateFrom) : week,
        date_from: dateFrom,
        date_to: dateTo,
      });
      router.replace(`/tours/${tour.id}`);
    } catch (err) {
      setError(String((err as Error).message ?? err));
      setBusy(false);
    }
  }

  return (
    <AppShell title="New tour">
      <Card style={{ maxWidth: 560 }}>
        <form onSubmit={onSubmit}>
          <Input
            label="Customer"
            required
            placeholder="e.g. ALDI Nord Beucha"
            value={customer}
            onChange={(e) => setCustomer(e.target.value)}
          />
          <div className="form-row">
            <Input
              label="From"
              type="date"
              required
              value={dateFrom}
              onChange={(e) => onFromChange(e.target.value)}
            />
            <Input
              label="To"
              type="date"
              required
              value={dateTo}
              onChange={(e) => setDateTo(e.target.value)}
            />
            <Input
              label="Week (KW)"
              type="number"
              min={1}
              max={53}
              required
              style={{ maxWidth: 120 }}
              value={week}
              onChange={(e) =>
                setWeek(e.target.value === "" ? "" : Number(e.target.value))
              }
            />
          </div>
          {error && <p className="form-error">{error}</p>}
          <p className="muted small">
            Next you enter the plan&apos;s stops — same columns as the Excel
            sheet.
          </p>
          <Button variant="primary" type="submit" loading={busy}>
            Create tour
          </Button>
        </form>
      </Card>
    </AppShell>
  );
}

export default function Page() {
  return (
    <Protected roles={["dispatcher", "admin"]}>
      <NewTourPage />
    </Protected>
  );
}
