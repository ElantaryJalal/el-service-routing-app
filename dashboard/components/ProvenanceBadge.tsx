import type { Provenance, Store } from "@/lib/api";

const LABEL: Record<Provenance, string> = {
  printed: "printed",
  geocoded: "geocoded",
  verified: "verified",
  field_confirmed: "field-confirmed",
};

// Badge tone reuses the status palette: weak evidence reads as "attention".
const TONE: Record<Provenance, string> = {
  printed: "badge-in_progress",
  geocoded: "badge-assigned",
  verified: "badge-done",
  field_confirmed: "badge-done",
};

/** How much to trust the store's address/pin: the strongest evidence wins —
 * a field-confirmed pin (a worker physically stood there) beats the paper
 * trail behind the address text. */
export default function ProvenanceBadge({ store }: { store: Store }) {
  const level: Provenance =
    store.geom_provenance === "field_confirmed"
      ? "field_confirmed"
      : store.address_provenance;
  const title = store.verified_at
    ? `${LABEL[level]} · ${new Date(store.verified_at).toLocaleDateString("de-DE")}${
        store.verified_by ? ` by ${store.verified_by}` : ""
      }`
    : LABEL[level];
  return (
    <span className={`badge ${TONE[level]}`} title={title}>
      {LABEL[level]}
    </span>
  );
}
