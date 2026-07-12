/**
 * Tiny offline outbox for field mutations. Marking a stop done must work with
 * no signal: the change is applied to local state (and the tour cache)
 * immediately, and when the API call fails transiently it is parked here and
 * replayed the next time the Map screen loads.
 *
 * Replays are safe by construction: complete/uncomplete are idempotent
 * server-side and feedback dedupes on client_uuid. A completion replayed
 * later stamps completed_at at sync time, not tap time — acceptable for a
 * progress checkmark.
 */
import AsyncStorage from '@react-native-async-storage/async-storage';

import { ApiError, api, type FeedbackCreate } from '../api/client';

export type Mutation =
  | { kind: 'complete'; stopId: number }
  | { kind: 'uncomplete'; stopId: number }
  | { kind: 'feedback'; payload: FeedbackCreate };

const KEY = 'mutationQueue:v1';

async function loadQueue(): Promise<Mutation[]> {
  try {
    const raw = await AsyncStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Mutation[]) : [];
  } catch {
    return [];
  }
}

async function saveQueue(queue: Mutation[]): Promise<void> {
  await AsyncStorage.setItem(KEY, JSON.stringify(queue));
}

async function perform(mutation: Mutation): Promise<void> {
  switch (mutation.kind) {
    case 'complete':
      await api.completeStop(mutation.stopId);
      return;
    case 'uncomplete':
      await api.uncompleteStop(mutation.stopId);
      return;
    case 'feedback':
      await api.postFeedback(mutation.payload);
      return;
  }
}

/** "Try again later" (offline, backend down) vs. "rejected, don't retry". */
function isTransient(err: unknown): boolean {
  return err instanceof ApiError && (err.status === 0 || err.status >= 500);
}

let flushing = false;

export const mutationQueue = {
  /**
   * Run the mutation now; on a transient failure park it for later replay.
   * Returns how it went so the UI can say "will sync when online".
   * Non-transient rejections (4xx) throw — the caller must surface those.
   */
  async run(mutation: Mutation): Promise<'done' | 'queued'> {
    try {
      await perform(mutation);
      return 'done';
    } catch (err) {
      if (!isTransient(err)) throw err;
      const queue = await loadQueue();
      queue.push(mutation);
      await saveQueue(queue);
      return 'queued';
    }
  },

  /**
   * Replay parked mutations in order. Stops at the first transient failure
   * (still offline); drops mutations the backend permanently rejects.
   */
  async flush(): Promise<void> {
    if (flushing) return;
    flushing = true;
    try {
      let queue = await loadQueue();
      while (queue.length > 0) {
        try {
          await perform(queue[0]);
        } catch (err) {
          if (isTransient(err)) return;
          // Permanently rejected (e.g. the stop was deleted): drop it.
        }
        queue = queue.slice(1);
        await saveQueue(queue);
      }
    } finally {
      flushing = false;
    }
  },

  /** Pending count, for tests / a future sync indicator. */
  async size(): Promise<number> {
    return (await loadQueue()).length;
  },
};
