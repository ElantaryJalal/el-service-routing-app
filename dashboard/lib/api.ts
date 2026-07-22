/** Typed client for the EL Service backend. Browser-only (Bearer token from
 * localStorage); every page in this app is a client component. */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export type Role = "worker" | "dispatcher" | "manager" | "admin";
export type TourStatus =
  | "draft"
  | "planned"
  | "assigned"
  | "in_progress"
  | "done";
export type DateMode = "fixed" | "optimized";

export interface User {
  id: number;
  email: string;
  name: string;
  role: Role;
  is_active: boolean;
}

export interface Tour {
  id: number;
  customer: string;
  calendar_week: number;
  date_from: string;
  date_to: string;
  status: TourStatus;
  date_mode: DateMode;
  assigned_user_id: number | null;
}

export interface DraftStop {
  id: number;
  customer: string | null;
  street: string | null;
  postal_code: string | null;
  city: string | null;
  order_no: string | null;
  tasks: string | null;
  remarks: string | null;
  service_minutes: number | null;
  confidence: Record<string, number>;
}

export interface TourDraft {
  tour_id: number;
  stops: DraftStop[];
}

export interface CommitResult {
  tour_id: number;
  status: string;
  stops_total: number;
  stops_enriched: number;
  stops_matched: number;
  new_stores: { stop_id: number; store_id: number; name: string }[];
  review_items: {
    stop_id: number;
    customer: string | null;
    reason: string;
    candidates: { store_id: number; name: string; score: number; rule: string }[];
  }[];
  address_mismatches: {
    stop_id: number;
    store_id: number;
    claimed: string;
    verified: string;
  }[];
  duplicates: number[][];
}

/** How much the address/pin has been checked, weakest to strongest. */
export type Provenance = "printed" | "geocoded" | "verified" | "field_confirmed";

export interface StopDetail {
  id: number;
  tour_id: number;
  /** The plan's printed claim for this row — the audit trail. Can be wrong
   * (some plans stamp one chain name on every row); prefer store_name to
   * display a matched stop. */
  customer: string | null;
  /** The linked store's real name (source of truth); null when unmatched. */
  store_name: string | null;
  opening_time: string | null;
  closing_time: string | null;
  service_minutes: number | null;
  status: string;
  completed_at: string | null;
  assigned_day: string | null;
  sequence: number | null;
  eta: string | null;
  unassigned_reason: string | null;
  /** Effective address: the linked store's verified data when there is one. */
  street: string | null;
  postal_code: string | null;
  city: string | null;
  /** What the printed plan said — the audit trail, never used for routing. */
  claimed_street: string | null;
  claimed_postal_code: string | null;
  claimed_city: string | null;
  /** false = the plan disagrees with the store (a review row); null = unchecked. */
  address_matches_store: boolean | null;
  address_review_resolved_at: string | null;
  address_review_resolved_by: string | null;
  /** 'printed'/'geocoded' marks a new-store candidate awaiting verification. */
  store_address_provenance: Provenance | null;
  tasks: string | null;
  remarks: string | null;
  lat: number | null;
  lng: number | null;
  store_id: number | null;
}

export interface PlanDayStop {
  stop_id: number;
  sequence: number;
  eta: string | null;
}

export interface PlanDay {
  date: string;
  stops: PlanDayStop[];
  drive_seconds: number;
  service_seconds: number;
  day_end: string | null;
  near_limit: boolean;
}

export interface Plan {
  tour_id: number;
  date_mode: DateMode;
  days: PlanDay[];
  unassigned: { stop_id: number; reason: string }[];
}

export interface ServiceProfileTime {
  /** Canonical key of the visit's task set (sorted, case-folded). */
  task_signature: string;
  tasks_label: string | null;
  samples: number;
  learned_minutes: number | null;
}

export interface Store {
  id: number;
  name: string;
  street: string | null;
  postal_code: string | null;
  city: string | null;
  lat: number | null;
  lng: number | null;
  address_provenance: Provenance;
  geom_provenance: Exclude<Provenance, "printed"> | null;
  verified_at: string | null;
  verified_by: string | null;
  opening_time: string | null;
  closing_time: string | null;
  hours_source: "osm" | "manual" | "default" | null;
  default_tasks: string[] | null;
  default_service_minutes: number | null;
  learned_service_minutes: number | null;
  service_time_samples: number;
  /** Learned per service profile; the store-wide value is the fallback. */
  service_times: ServiceProfileTime[];
  /** Total recorded time spent at this store, across the service ledger. */
  total_service_minutes: number;
  services_recorded: number;
  size: "small" | "medium" | "large" | null;
  in_mall: boolean | null;
  has_parking: boolean | null;
  attributes_updated_at: string | null;
  attributes_updated_by: string | null;
  attributes_complete: boolean;
}

export interface StopSuggestion {
  name: string;
  street: string | null;
  postal_code: string | null;
  city: string | null;
  service_minutes: number | null;
  tasks: string | null;
  source: "catalog" | "history";
}

export interface StoreServiceTime {
  store_id: number;
  name: string;
  samples: number;
  learned_service_minutes: number | null;
}

export interface StoreVisit {
  stop_id: number;
  tour_id: number;
  calendar_week: number;
  date: string | null;
  employee: string | null;
  service_minutes: number | null;
  eta: string | null;
  completed_at: string | null;
  /** From the service ledger (null until a recompute derived this visit). */
  tasks: string | null;
  duration_minutes: number | null;
}

export interface Feedback {
  id: number;
  store_id: number | null;
  /** Display identity — never show the raw store id to people. */
  store_name: string | null;
  store_city: string | null;
  tour_id: number | null;
  stop_id: number | null;
  employee: string | null;
  is_demo: boolean;
  tags: string[];
  note: string | null;
  photo_path: string | null;
  created_at: string;
}

export interface DayLoad {
  day: string;
  planned: number;
  completed: number;
}

export interface OverviewReport {
  date_from: string;
  date_to: string;
  tours: {
    total: number;
    draft: number;
    planned: number;
    assigned: number;
    in_progress: number;
    done: number;
  };
  stops_planned: number;
  stops_completed: number;
  days: DayLoad[];
  on_time: {
    sample_count: number;
    on_time_count: number;
    on_time_rate: number | null;
    average_delta_minutes: number | null;
    tolerance_minutes: number;
  };
  outstanding: {
    stop_id: number;
    tour_id: number;
    customer: string | null;
    /** The linked store's real name (source of truth); null when unmatched. */
    store_name: string | null;
    city: string | null;
    assigned_day: string | null;
    eta: string | null;
  }[];
}

const TOKEN_KEY = "office:token";
const USER_KEY = "office:user";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function getStoredUser(): User | null {
  if (typeof window === "undefined") return null;
  const raw = localStorage.getItem(USER_KEY);
  return raw ? (JSON.parse(raw) as User) : null;
}

export function storeSession(token: string, user: User) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (options.body && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  const resp = await fetch(`${API_BASE}${path}`, { ...options, headers });

  if (resp.status === 401 && typeof window !== "undefined") {
    clearSession();
    if (!window.location.pathname.startsWith("/login")) {
      window.location.href = "/login";
    }
  }
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = await resp.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(resp.status, detail);
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

export const api = {
  // auth
  login: (email: string, password: string) =>
    request<{ access_token: string; user: User }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  // users
  listUsers: (role?: Role) =>
    request<User[]>(`/users${role ? `?role=${role}` : ""}`),

  // tours
  listTours: () => request<Tour[]>("/tours"),
  getTour: (id: number) => request<Tour>(`/tours/${id}`),
  createTour: (body: {
    customer: string;
    calendar_week: number;
    date_from: string;
    date_to: string;
  }) => request<Tour>("/tours", { method: "POST", body: JSON.stringify(body) }),
  updateTour: (id: number, body: { date_mode?: DateMode }) =>
    request<Tour>(`/tours/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  getDraft: (id: number) => request<TourDraft>(`/tours/${id}/draft`),
  patchDraftStop: (
    tourId: number,
    stopId: number,
    body: Partial<Omit<DraftStop, "id" | "confidence" | "remarks">>,
  ) =>
    request<DraftStop>(`/tours/${tourId}/draft/stops/${stopId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  addStop: (
    tourId: number,
    body: Partial<Omit<DraftStop, "id" | "confidence" | "remarks">>,
  ) =>
    request<DraftStop>(`/tours/${tourId}/stops`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  deleteStop: (stopId: number) =>
    request<void>(`/stops/${stopId}`, { method: "DELETE" }),
  resolveAddress: (stopId: number, action: "keep_store" | "use_claim") =>
    request<unknown>(`/stops/${stopId}/resolve-address`, {
      method: "POST",
      body: JSON.stringify({ action }),
    }),
  commit: (tourId: number) =>
    request<CommitResult>(`/tours/${tourId}/commit`, { method: "POST" }),
  optimise: (tourId: number) =>
    request<Plan>(`/tours/${tourId}/optimise`, { method: "POST" }),
  getPlan: (tourId: number) => request<Plan>(`/tours/${tourId}/plan`),
  /** Download the plan as a handout; resolves to the served filename. */
  exportPlan: async (
    tourId: number,
    format: "pdf" | "xlsx",
  ): Promise<{ blob: Blob; filename: string }> => {
    const headers = new Headers();
    const token = getToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
    const resp = await fetch(
      `${API_BASE}/tours/${tourId}/plan/export?format=${format}`,
      { headers },
    );
    if (!resp.ok) throw new ApiError(resp.status, resp.statusText);
    const match = /filename="([^"]+)"/.exec(
      resp.headers.get("content-disposition") ?? "",
    );
    return {
      blob: await resp.blob(),
      filename: match?.[1] ?? `tour-${tourId}-plan.${format}`,
    };
  },
  listStops: (tourId: number) => request<StopDetail[]>(`/tours/${tourId}/stops`),
  assign: (tourId: number, userId: number) =>
    request<Tour>(`/tours/${tourId}/assign`, {
      method: "POST",
      body: JSON.stringify({ user_id: userId }),
    }),
  unassign: (tourId: number) =>
    request<Tour>(`/tours/${tourId}/unassign`, { method: "POST" }),

  // reports
  overview: (dateFrom?: string, dateTo?: string, includeDemo?: boolean) => {
    const q = new URLSearchParams();
    if (dateFrom && dateTo) {
      q.set("date_from", dateFrom);
      q.set("date_to", dateTo);
    }
    if (includeDemo) q.set("include_demo", "true");
    const qs = q.toString();
    return request<OverviewReport>(`/reports/overview${qs ? `?${qs}` : ""}`);
  },

  // feedback
  listFeedback: (params: {
    tourId?: number;
    stopId?: number;
    includeDemo?: boolean;
  }) => {
    const q = new URLSearchParams();
    if (params.tourId !== undefined) q.set("tour_id", String(params.tourId));
    if (params.stopId !== undefined) q.set("stop_id", String(params.stopId));
    if (params.includeDemo) q.set("include_demo", "true");
    const qs = q.toString();
    return request<Feedback[]>(`/feedback${qs ? `?${qs}` : ""}`);
  },

  // stores
  listStores: (needsAttributes?: boolean, includeDemo?: boolean) => {
    const q = new URLSearchParams();
    if (needsAttributes !== undefined)
      q.set("needs_attributes", String(needsAttributes));
    if (includeDemo) q.set("include_demo", "true");
    const qs = q.toString();
    return request<Store[]>(`/stores${qs ? `?${qs}` : ""}`);
  },
  getStore: (id: number, includeDemo?: boolean) =>
    request<Store>(`/stores/${id}${includeDemo ? "?include_demo=true" : ""}`),
  recomputeServiceTimes: () =>
    request<StoreServiceTime[]>("/stores/service-times/recompute", {
      method: "POST",
    }),
  suggestStops: (q: string) =>
    request<StopSuggestion[]>(`/stores/suggest?q=${encodeURIComponent(q)}`),
  storeVisits: (id: number, includeDemo?: boolean) =>
    request<StoreVisit[]>(
      `/stores/${id}/visits${includeDemo ? "?include_demo=true" : ""}`,
    ),
  storeFeedback: (id: number, includeDemo?: boolean) =>
    request<Feedback[]>(
      `/stores/${id}/feedback${includeDemo ? "?include_demo=true" : ""}`,
    ),
  updateStoreAttributes: (
    id: number,
    body: {
      size?: Store["size"];
      in_mall?: boolean | null;
      has_parking?: boolean | null;
    },
  ) =>
    request<Store>(`/stores/${id}/attributes`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
};
