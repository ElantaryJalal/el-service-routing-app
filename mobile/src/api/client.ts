/**
 * Thin, typed API client. Response/request shapes come from the generated
 * `types.ts` (run `npm run gen:api`) wherever the backend already exposes them.
 *
 * A few methods target endpoints that are on the roadmap but not yet in the
 * backend OpenAPI (extract, draft). Those use the small provisional types below
 * and should switch to generated types once the backend adds the endpoints.
 */
import { API_BASE_URL } from './config';
import type { components } from './types';

type CommitResult = components['schemas']['CommitResult'];
type OptimiseResult = components['schemas']['OptimiseResult'];
type StopUpdate = components['schemas']['StopUpdate'];
type StopRead = components['schemas']['StopRead'];

// --- Provisional types (endpoints not yet in the backend OpenAPI) ----------
// TODO(backend): add POST /tours/extract and GET /tours/{id}/draft, then drop
// these in favour of the generated `components['schemas'][...]` types.
export interface ImageFile {
  uri: string;
  name: string;
  type: string;
}
export interface ExtractResult {
  tour_id: number;
}
export interface TourDraft {
  tour_id: number;
  stops: unknown[];
}

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

  /** POST /tours/extract (multipart). Provisional until the backend adds it. */
  extractPlan(image: ImageFile): Promise<ExtractResult> {
    const form = new FormData();
    // React Native's FormData accepts a { uri, name, type } file object.
    form.append('image', image as unknown as Blob);
    return request('/tours/extract', { method: 'POST', body: form });
  },

  /** GET /tours/{id}/draft. Provisional until the backend adds it. */
  getDraft(tourId: number): Promise<TourDraft> {
    return request(`/tours/${tourId}/draft`);
  },

  patchStop(
    tourId: number,
    stopId: number,
    fields: StopUpdate,
  ): Promise<StopRead> {
    return request(`/tours/${tourId}/stops/${stopId}`, jsonInit('PATCH', fields));
  },

  commitTour(tourId: number): Promise<CommitResult> {
    return request(`/tours/${tourId}/commit`, jsonInit('POST'));
  },

  optimiseTour(tourId: number): Promise<OptimiseResult> {
    return request(`/tours/${tourId}/optimise`, jsonInit('POST'));
  },
};
