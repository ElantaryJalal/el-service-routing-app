"use client";

/** Component preview — every ui/ part with sample data. Dev reference only;
 * not linked from the app nav. */

import { useState } from "react";
import {
  Button,
  Card,
  EmptyState,
  Input,
  KpiCard,
  PageShell,
  Select,
  Skeleton,
  Spinner,
  StatusChip,
  STATUSES,
  Table,
  Td,
  Th,
  ToastProvider,
  useToast,
  Textarea,
} from "@/components/ui";

function ToastDemo() {
  const toast = useToast();
  return (
    <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
      <Button size="sm" onClick={() => toast("Tour saved.", "success")}>
        Success toast
      </Button>
      <Button size="sm" onClick={() => toast("OSRM is still warming up.", "warning")}>
        Warning toast
      </Button>
      <Button size="sm" onClick={() => toast("Could not reach the server.", "danger")}>
        Danger toast
      </Button>
      <Button size="sm" onClick={() => toast("3 stops moved to Tuesday.")}>
        Info toast
      </Button>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Card title={title} style={{ marginBottom: "var(--space-4)" }}>
      {children}
    </Card>
  );
}

export default function DesignPreview() {
  const [name, setName] = useState("");
  return (
    <ToastProvider>
      <PageShell
        brand="EL Service · Office"
        nav={[
          { href: "/design", label: "Components" },
          { href: "/overview", label: "Overview" },
        ]}
        user={<span>Preview</span>}
        title="Component library"
        subtitle="Every ui/ part, rendered from tokens only"
        actions={<Button variant="primary">Primary action</Button>}
      >
        <Section title="Buttons">
          <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
            <Button variant="primary">Assign tour</Button>
            <Button>Secondary</Button>
            <Button variant="ghost">Ghost</Button>
            <Button variant="danger">Delete row</Button>
            <Button loading>Optimising…</Button>
            <Button disabled>Disabled</Button>
            <Button size="sm">Small</Button>
            <Button size="sm" variant="ghost">
              Small ghost
            </Button>
          </div>
        </Section>

        <Section title="Status chips — the shared vocabulary">
          <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
            {STATUSES.map((s) => (
              <StatusChip key={s} status={s} />
            ))}
          </div>
        </Section>

        <Section title="KPI cards">
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
              gap: "var(--space-3)",
            }}
          >
            <KpiCard
              label="On-time completions"
              value="67%"
              sub="Ø +22 min vs ETA · ±30 min tolerance · 24 timed"
              note="ETAs seed from a 45-min default until a store has enough visits to be learned from history. Accuracy improves as more stores are modelled."
            />
            <KpiCard
              label="Stops completed"
              value="24 / 24"
              trend={{ text: "+24", direction: "up" }}
              sub="vs last week"
            />
            <KpiCard label="Tours underway" value="2" sub="1 in progress" />
          </div>
        </Section>

        <Section title="Table">
          <Table>
            <thead>
              <tr>
                <Th>Market</Th>
                <Th>City</Th>
                <Th>Status</Th>
                <Th numeric>Learned</Th>
                <Th numeric>Samples</Th>
              </tr>
            </thead>
            <tbody>
              <tr className="ui-row-click">
                <Td>ALDI Leipzig-Plagwitz</Td>
                <Td>Leipzig</Td>
                <Td>
                  <StatusChip status="done" />
                </Td>
                <Td numeric>73 min</Td>
                <Td numeric>3</Td>
              </tr>
              <tr className="ui-row-click">
                <Td>ALDI Nova Eventis</Td>
                <Td>Günthersdorf</Td>
                <Td>
                  <StatusChip status="in_progress" />
                </Td>
                <Td numeric>81 min</Td>
                <Td numeric>3</Td>
              </tr>
              <tr className="ui-row-click">
                <Td>HIT Meinerzhagen</Td>
                <Td>Meinerzhagen</Td>
                <Td>
                  <StatusChip status="planned" />
                </Td>
                <Td numeric>—</Td>
                <Td numeric>0</Td>
              </tr>
            </tbody>
          </Table>
        </Section>

        <Section title="Form fields">
          <div style={{ maxWidth: 360 }}>
            <Input
              label="Store name"
              placeholder="e.g. ALDI Leipzig-Plagwitz"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <Select label="Size">
              <option>small</option>
              <option>medium</option>
              <option>large</option>
            </Select>
            <Input
              label="Postal code"
              defaultValue="not-a-plz"
              error="Enter a 5-digit postal code."
            />
            <Textarea label="Note" placeholder="Optional remark" rows={2} />
          </div>
        </Section>

        <Section title="Empty state">
          <EmptyState
            title="Nothing outstanding"
            hint="The week's work is complete."
            action={<Button size="sm">Plan next week</Button>}
          />
        </Section>

        <Section title="Loading">
          <div style={{ display: "grid", gap: "var(--space-2)", maxWidth: 420 }}>
            <Skeleton width="40%" height={24} />
            <Skeleton />
            <Skeleton width="80%" />
            <div style={{ marginTop: "var(--space-2)" }}>
              <Spinner />
            </div>
          </div>
        </Section>

        <Section title="Toasts">
          <ToastDemo />
        </Section>
      </PageShell>
    </ToastProvider>
  );
}
