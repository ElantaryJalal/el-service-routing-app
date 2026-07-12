/**
 * Thin, typed API client. Response/request shapes come from the generated
 * `types.ts` (run `npm run gen:api`) wherever the backend already exposes them.
 *
 * A few methods target endpoints that are on the roadmap but not yet in the
 * backend OpenAPI (extract, draft). Those use the small provisional types below
 * and should switch to generated types once the backend adds the endpoints.
 */
import { Platform } from 'react-native';

import { API_BASE_URL } from './config';
import type { components } from './types';

type CommitResult = components['schemas']['CommitResult'];
type OptimiseResult = components['schemas']['OptimiseResult'];
type StopUpdate = components['schemas']['StopUpdate'];
type StopRead = components['schemas']['StopRead'];
type TourRead = components['schemas']['TourRead'];
type TourUpdate = components['schemas']['TourUpdate'];
type StoreRead = components['schemas']['StoreRead'];
type StoreAttributesUpdate = components['schemas']['StoreAttributesUpdate'];
type FeedbackRead = components['schemas']['FeedbackRead'];

/** Committed stop with address, task labels, and geocoded coordinate. */
export type StopDetail = components['schemas']['StopDetail'];

/** Whether the plan's dates bind ('fixed') or the optimiser assigns days. */
export type DateMode = components['schemas']['DateMode'];

/** Controlled vocabulary for visit-feedback tags. */
export type FeedbackTag = components['schemas']['FeedbackTag'];

/** POST /feedback body (client_uuid is the offline idempotency key). */
export type FeedbackCreate = components['schemas']['FeedbackCreate'];

// --- Provisional types (endpoints not yet in the backend OpenAPI) ----------
// TODO(backend): implement POST /tours/extract, GET /tours/{id}/draft,
// PATCH /tours/{id}/draft/stops/{stop_id}, and the duplicate_groups shape on
// POST /tours/{id}/commit. Once the backend exposes these, regenerate
// `types.ts` and switch to the generated `components['schemas'][...]` types.
export interface ImageFile {
  uri: string;
  name: string;
  type: string;
}

/** service_minutes bounds and fallback shared with the Confirm UI. */
export const SERVICE_MINUTES_MIN = 30;
export const SERVICE_MINUTES_MAX = 600;
export const SERVICE_MINUTES_DEFAULT = 45;

/** Editable, extraction-time fields of a draft stop (pre-commit). */
export interface DraftStopFields {
  street: string | null;
  postal_code: string | null;
  city: string | null;
  order_no: string | null;
  tasks: string | null;
  service_minutes: number | null;
}

/**
 * Per-field extraction confidence in [0, 1]. Absent = not scored (treated as
 * confident). The Confirm screen flags any field < 0.6.
 */
export type DraftConfidence = Partial<Record<keyof DraftStopFields, number>>;

export interface DraftStop extends DraftStopFields {
  id: number;
  /** Free-text instructions from the plan's remark column (read-only). */
  remarks: string | null;
  confidence: DraftConfidence;
}

export interface TourDraft {
  tour_id: number;
  /** Set client-side to the captured/picked photo so Confirm can cross-check. */
  photo_uri?: string;
  stops: DraftStop[];
}

/** PATCH body for a draft stop — only provided fields are applied. */
export type DraftStopUpdate = Partial<DraftStopFields>;

/** A set of draft stops the backend suspects are the same market. */
export interface DuplicateGroup {
  /** Stable key for the group (used by the merge/keep prompt). */
  key: string;
  /** Human label, e.g. the shared address. */
  label: string;
  stop_ids: number[];
}

/** How the user resolved one duplicate group at commit time. */
export interface DuplicateResolution {
  key: string;
  /** 'merge' → collapse into the first stop; 'keep' → leave all as separate. */
  action: 'merge' | 'keep';
}

/**
 * Commit response. When `duplicate_groups` is non-empty the tour is NOT yet
 * committed — the client must prompt, then re-POST with resolutions.
 */
export type CommitResponse = CommitResult & {
  duplicate_groups?: DuplicateGroup[];
};

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly body?: unknown,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

function parseBody(text: string): unknown {
  if (!text) return undefined;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: { Accept: 'application/json', ...(init?.headers ?? {}) },
    });
  } catch (err) {
    throw new ApiError(0, `Network error: ${String(err)}`);
  }

  const body = parseBody(await res.text());
  if (!res.ok) {
    const detail =
      body && typeof body === 'object' && 'detail' in body
        ? String((body as { detail: unknown }).detail)
        : res.statusText || 'request failed';
    throw new ApiError(res.status, `${res.status} ${detail}`, body);
  }
  return body as T;
}

function jsonInit(method: string, payload?: unknown): RequestInit {
  return {
    method,
    headers: payload !== undefined ? { 'Content-Type': 'application/json' } : {},
    body: payload !== undefined ? JSON.stringify(payload) : undefined,
  };
}

export const api = {
  /** Temporary health probe used by the Capture screen's Test connection button. */
  health(): Promise<Record<string, string>> {
    return request('/health');
  },

  /**
   * POST /tours/extract (multipart). Uploads the photographed plan and returns
   * the parsed draft (tour id + stops with per-field confidence). Provisional.
   */
  async extractPlan(image: ImageFile): Promise<TourDraft> {
    const form = new FormData();
    if (Platform.OS === 'web') {
      // On web the picked uri is a blob:/data: URL; send the real Blob so the
      // multipart file part is well-formed. The { uri, name, type } object form
      // is a React Native-only idiom that would stringify in the browser.
      const blob = await (await fetch(image.uri)).blob();
      form.append('image', blob, image.name);
    } else {
      form.append('image', image as unknown as Blob);
    }
    return request('/tours/extract', { method: 'POST', body: form });
  },

  /** GET /tours/{id}/draft. Provisional until the backend adds it. */
  getDraft(tourId: number): Promise<TourDraft> {
    return request(`/tours/${tourId}/draft`);
  },

  /** PATCH a draft (pre-commit) stop's extracted fields. Provisional. */
  patchDraftStop(
    tourId: number,
    stopId: number,
    fields: DraftStopUpdate,
  ): Promise<DraftStop> {
    return request(
      `/tours/${tourId}/draft/stops/${stopId}`,
      jsonInit('PATCH', fields),
    );
  },

  /** PATCH a committed stop's schedule fields (generated contract). */
  patchStop(stopId: number, fields: StopUpdate): Promise<StopRead> {
    return request(`/stops/${stopId}`, jsonInit('PATCH', fields));
  },

  /**
   * POST /tours/{id}/commit. If `resolutions` is omitted and the backend finds
   * possible duplicates, the response carries `duplicate_groups` and the tour
   * stays uncommitted; re-call with resolutions to finish. Provisional body.
   */
  commitTour(
    tourId: number,
    resolutions?: DuplicateResolution[],
  ): Promise<CommitResponse> {
    return request(
      `/tours/${tourId}/commit`,
      jsonInit('POST', resolutions ? { resolutions } : undefined),
    );
  },

  /**
   * GET /tours/{id}/stops — committed stops with coordinates + address + tasks.
   * Used by Review (edit hours) and Map (markers + detail).
   */
  getStops(tourId: number): Promise<StopDetail[]> {
    return request(`/tours/${tourId}/stops`);
  },

  optimiseTour(tourId: number): Promise<OptimiseResult> {
    return request(`/tours/${tourId}/optimise`, jsonInit('POST'));
  },

  getTour(tourId: number): Promise<TourRead> {
    return request(`/tours/${tourId}`);
  },

  /** PATCH per-tour settings (date_mode). Re-run optimise afterwards. */
  patchTour(tourId: number, fields: TourUpdate): Promise<TourRead> {
    return request(`/tours/${tourId}`, jsonInit('PATCH', fields));
  },

  /** Mark a stop done (sets completed_at server-side; idempotent). */
  completeStop(stopId: number): Promise<StopRead> {
    return request(`/stops/${stopId}/complete`, jsonInit('POST'));
  },

  /** Undo a mis-tapped completion (clears completed_at; idempotent). */
  uncompleteStop(stopId: number): Promise<StopRead> {
    return request(`/stops/${stopId}/complete`, { method: 'DELETE' });
  },

  /** Capture crowdsourced store attributes (size / in_mall / has_parking). */
  patchStoreAttributes(
    storeId: number,
    fields: StoreAttributesUpdate,
  ): Promise<StoreRead> {
    return request(`/stores/${storeId}/attributes`, jsonInit('PATCH', fields));
  },

  /** Record after-visit feedback. Dedupes server-side on client_uuid. */
  postFeedback(payload: FeedbackCreate): Promise<FeedbackRead> {
    return request('/feedback', jsonInit('POST', payload));
  },
};
