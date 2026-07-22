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
  // Paper Tourenplan header, in the office's order.
  const [customer, setCustomer] = useState("");
  const [week, setWeek] = useState<number | "">("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [teamLead, setTeamLead] = useState("");
  const [employee, setEmployee] = useState("");
  const [teamNo, setTeamNo] = useState("");
  const [vehicle, setVehicle] = useState("");
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
        team_lead: teamLead.trim() || null,
        employee: employee.trim() || null,
        team_no: teamNo.trim() || null,
        vehicle: vehicle.trim() || null,
      });
      router.replace(`/tours/${tour.id}`);
    } catch (err) {
      setError(String((err as Error).message ?? err));
      setBusy(false);
    }
  }

  return (
    <AppShell title="New tour" subtitle="Tourenplan — Kopfdaten">
      <Card style={{ maxWidth: 640 }}>
        <form onSubmit={onSubmit}>
          <Input
            label="Kunde"
            required
            placeholder="e.g. ALDI Nord Beucha"
            value={customer}
            onChange={(e) => setCustomer(e.target.value)}
          />
          <div className="form-row">
            <Input
              label="Kalenderwoche (KW)"
              type="number"
              min={1}
              max={53}
              required
              style={{ maxWidth: 160 }}
              value={week}
              onChange={(e) =>
                setWeek(e.target.value === "" ? "" : Number(e.target.value))
              }
            />
            <Input
              label="Zeitraum von"
              type="date"
              required
              value={dateFrom}
              onChange={(e) => onFromChange(e.target.value)}
            />
            <Input
              label="bis"
              type="date"
              required
              value={dateTo}
              onChange={(e) => setDateTo(e.target.value)}
            />
          </div>
          <div className="form-row">
            <Input
              label="Teamleiter"
              placeholder="optional"
              value={teamLead}
              onChange={(e) => setTeamLead(e.target.value)}
            />
            <Input
              label="Mitarbeiter"
              placeholder="optional"
              value={employee}
              onChange={(e) => setEmployee(e.target.value)}
            />
          </div>
          <div className="form-row">
            <Input
              label="Team-Nr."
              placeholder="optional"
              style={{ maxWidth: 160 }}
              value={teamNo}
              onChange={(e) => setTeamNo(e.target.value)}
            />
            <Input
              label="Fahrzeug"
              placeholder="optional"
              value={vehicle}
              onChange={(e) => setVehicle(e.target.value)}
            />
          </div>
          {error && <p className="form-error">{error}</p>}
          <p className="muted small">
            Next you enter the plan&apos;s rows in the same columns as the paper
            Tourenplan — Datum, Kunde, Auftrag/VST, address, Bemerkung.
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
