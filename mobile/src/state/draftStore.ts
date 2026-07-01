/**
 * Tiny in-memory store for the tour draft in flight between the Capture and
 * Confirm screens. expo-router only passes string params, so rather than
 * serialise the whole parsed payload (plus photo uri) through the URL we stash
 * it here keyed by tour id and pass just the id. Confirm reads it back, and
 * falls back to `api.getDraft(tourId)` if the store is empty (e.g. after a
 * reload or deep link).
 *
 * This is deliberately not persisted — a draft only lives until it's committed.
 */
import type { DraftStop, TourDraft } from '../api/client';

const drafts = new Map<number, TourDraft>();

export const draftStore = {
  set(draft: TourDraft): void {
    drafts.set(draft.tour_id, draft);
  },

  get(tourId: number): TourDraft | undefined {
    return drafts.get(tourId);
  },

  /** Replace a single stop in a stored draft (no-op if the draft is absent). */
  setStop(tourId: number, stop: DraftStop): void {
    const draft = drafts.get(tourId);
    if (!draft) return;
    drafts.set(tourId, {
      ...draft,
      stops: draft.stops.map((s) => (s.id === stop.id ? stop : s)),
    });
  },

  clear(tourId: number): void {
    drafts.delete(tourId);
  },
};
