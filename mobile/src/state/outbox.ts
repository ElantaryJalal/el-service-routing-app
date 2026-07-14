/**
 * Durable offline write queue (outbox pattern). Every field mutation —
 * completion, store attributes, visit feedback — is written to local storage
 * FIRST (SQLite on device, localStorage on web), applied to the UI
 * optimistically, and then synced: an immediate attempt, and a background
 * loop that retries with exponential backoff whenever connectivity returns.
 *
 * Replays are safe by the server's design: complete/uncomplete are
 * idempotent per stop, attributes are last-write-wins, and feedback dedupes
 * on client_uuid (append-only, never merged). Rows are replayed strictly in
 * FIFO order so e.g. complete→uncomplete for the same stop lands in the
 * order the worker did it.
 */
import { Platform } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as Network from 'expo-network';

import {
  ApiError,
  api,
  type FeedbackCreate,
  type StoreAttributesUpdate,
} from '../api/client';
import { uuidv4 } from '../domain/uuid';
import { outboxStore } from './outboxStore';
import type { OutboxRow } from './outboxTypes';

export type OutboxWrite =
  | { kind: 'complete'; payload: { stop_id: number; completed: boolean } }
  | {
      kind: 'attributes';
      payload: { store_id: number; fields: StoreAttributesUpdate };
    }
  /** photo_local_uri: picker file uploaded lazily when the row syncs, so the
   * queued document stays plain JSON. */
  | { kind: 'feedback'; payload: FeedbackCreate & { photo_local_uri?: string } };

export interface OutboxStatusSnapshot {
  /** Queued writes not yet on the server ("N changes pending sync"). */
  pending: number;
  /** Writes the backend permanently rejected (kept for diagnosis). */
  failed: number;
  /** Stops with a pending completion/feedback ("not yet synced" marker). */
  pendingStopIds: Set<number>;
}

const BACKOFF_BASE_MS = 5_000;
const BACKOFF_MAX_MS = 5 * 60_000;
const SYNC_INTERVAL_MS = 15_000;
const PRUNE_SYNCED_AFTER_MS = 7 * 24 * 60 * 60_000;
const LEGACY_QUEUE_KEY = 'mutationQueue:v1';

function backoffMs(attempts: number): number {
  return Math.min(BACKOFF_BASE_MS * 2 ** (attempts - 1), BACKOFF_MAX_MS);
}

/** "Try again later" (offline, backend down) vs. "rejected, don't retry".
 * 401 is transient: the token expired or the worker was signed out — the
 * write itself is fine and must survive until they log back in. */
function isTransient(err: unknown): boolean {
  return (
    err instanceof ApiError &&
    (err.status === 0 || err.status === 401 || err.status >= 500)
  );
}

async function perform(row: OutboxRow): Promise<void> {
  const write = { kind: row.kind, payload: JSON.parse(row.payload) } as OutboxWrite;
  switch (write.kind) {
    case 'complete':
      if (write.payload.completed) await api.completeStop(write.payload.stop_id);
      else await api.uncompleteStop(write.payload.stop_id);
      return;
    case 'attributes':
      await api.patchStoreAttributes(write.payload.store_id, write.payload.fields);
      return;
    case 'feedback': {
      const { photo_local_uri, ...payload } = write.payload;
      let body: FeedbackCreate = payload;
      if (photo_local_uri && !body.photo_path) {
        try {
          const png = photo_local_uri.toLowerCase().includes('.png');
          const { photo_path } = await api.uploadFeedbackPhoto({
            uri: photo_local_uri,
            name: png ? 'visit.png' : 'visit.jpg',
            type: png ? 'image/png' : 'image/jpeg',
          });
          body = { ...body, photo_path };
        } catch (err) {
          // Still offline: retry the whole row later. Anything else (picker
          // file evicted, upload rejected) must not sink the note — send the
          // feedback without the photo.
          if (isTransient(err)) throw err;
        }
      }
      await api.postFeedback(body);
      return;
    }
  }
}

// --- reactive status ---------------------------------------------------------

type Listener = () => void;
const listeners = new Set<Listener>();

function notify(): void {
  for (const fn of listeners) fn();
}

/** Errors from permanently rejected rows, kept in memory so the enqueuing UI
 * can surface them (the row itself is marked failed in storage). */
const rejectionById = new Map<number, unknown>();

// --- one-time init -----------------------------------------------------------

let initPromise: Promise<void> | null = null;

/** Import any writes parked by the pre-SQLite AsyncStorage queue. */
async function migrateLegacyQueue(): Promise<void> {
  try {
    const raw = await AsyncStorage.getItem(LEGACY_QUEUE_KEY);
    if (!raw) return;
    const legacy = JSON.parse(raw) as {
      kind: string;
      stopId?: number;
      payload?: FeedbackCreate;
      photoUri?: string;
    }[];
    for (const item of legacy) {
      let write: OutboxWrite | null = null;
      if (item.kind === 'complete' && item.stopId != null) {
        write = { kind: 'complete', payload: { stop_id: item.stopId, completed: true } };
      } else if (item.kind === 'uncomplete' && item.stopId != null) {
        write = { kind: 'complete', payload: { stop_id: item.stopId, completed: false } };
      } else if (item.kind === 'feedback' && item.payload) {
        write = {
          kind: 'feedback',
          payload: { ...item.payload, photo_local_uri: item.photoUri },
        };
      }
      if (write) {
        await outboxStore.insert({
          kind: write.kind,
          payload: JSON.stringify(write.payload),
          client_uuid:
            write.kind === 'feedback' ? write.payload.client_uuid : uuidv4(),
          status: 'pending',
          attempts: 0,
          next_attempt_at: 0,
          created_at: Date.now(),
        });
      }
    }
    await AsyncStorage.removeItem(LEGACY_QUEUE_KEY);
  } catch {
    // Never block the outbox on a broken legacy queue.
  }
}

function init(): Promise<void> {
  if (!initPromise) {
    initPromise = (async () => {
      await migrateLegacyQueue();
      await outboxStore.pruneSynced(PRUNE_SYNCED_AFTER_MS);
      startSyncLoop();
    })();
  }
  return initPromise;
}

// --- background sync ---------------------------------------------------------

let syncLoopStarted = false;

function startSyncLoop(): void {
  if (syncLoopStarted) return;
  syncLoopStarted = true;

  // Steady heartbeat: catches backend-down periods (device online, API not).
  setInterval(() => {
    outbox.flush().catch(() => {});
  }, SYNC_INTERVAL_MS);

  // Connectivity returned: flush immediately instead of waiting for the tick.
  try {
    Network.addNetworkStateListener((state) => {
      if (state.isConnected) outbox.flush().catch(() => {});
    });
  } catch {
    // expo-network unavailable (e.g. SSR); the heartbeat still covers us.
  }
  if (Platform.OS === 'web' && typeof window !== 'undefined') {
    window.addEventListener('online', () => {
      outbox.flush().catch(() => {});
    });
  }
}

// --- public API ----------------------------------------------------------------

let flushing = false;

export const outbox = {
  /**
   * Durably queue a write, then try to sync right away. Resolves 'done' when
   * the write reached the server, 'queued' when it is parked for background
   * sync. Throws (and marks the row failed) when the backend permanently
   * rejected it — the caller should roll back its optimistic update.
   */
  async enqueue(write: OutboxWrite): Promise<'done' | 'queued'> {
    await init();
    const id = await outboxStore.insert({
      kind: write.kind,
      payload: JSON.stringify(write.payload),
      client_uuid:
        write.kind === 'feedback' ? write.payload.client_uuid : uuidv4(),
      status: 'pending',
      attempts: 0,
      next_attempt_at: 0,
      created_at: Date.now(),
    });
    notify();

    await this.flush();

    const row = await outboxStore.get(id);
    if (row?.status === 'synced') return 'done';
    if (row?.status === 'failed') {
      throw rejectionById.get(id) ?? new ApiError(400, 'write rejected');
    }
    return 'queued';
  },

  /**
   * Replay pending rows strictly in FIFO order. Stops at the first transient
   * failure (still offline) after arming its backoff; permanently rejected
   * rows are marked failed and skipped. Safe to call at any time.
   */
  async flush(): Promise<void> {
    await init();
    if (flushing) return;
    flushing = true;
    let changed = false;
    try {
      const rows = await outboxStore.pending();
      for (const row of rows) {
        // FIFO is part of the contract (complete→uncomplete ordering), so a
        // head row still in backoff blocks the queue until it is due.
        if (row.next_attempt_at > Date.now()) break;
        try {
          await perform(row);
          await outboxStore.setStatus(row.id, 'synced');
          changed = true;
        } catch (err) {
          if (isTransient(err)) {
            const attempts = row.attempts + 1;
            await outboxStore.bumpRetry(
              row.id,
              attempts,
              Date.now() + backoffMs(attempts),
            );
            changed = true;
            break;
          }
          rejectionById.set(row.id, err);
          await outboxStore.setStatus(row.id, 'failed');
          changed = true;
        }
      }
    } finally {
      flushing = false;
      if (changed) notify();
    }
  },

  /** Clear any armed backoff and sync now — rows parked by 401s while signed
   * out shouldn't keep waiting out their backoff after a successful login. */
  async retryNow(): Promise<void> {
    await init();
    const now = Date.now();
    for (const row of await outboxStore.pending()) {
      if (row.next_attempt_at > now) {
        await outboxStore.bumpRetry(row.id, row.attempts, 0);
      }
    }
    await this.flush();
  },

  async status(): Promise<OutboxStatusSnapshot> {
    await init();
    const rows = await outboxStore.pending();
    const pendingStopIds = new Set<number>();
    for (const row of rows) {
      if (row.kind === 'complete' || row.kind === 'feedback') {
        const payload = JSON.parse(row.payload) as { stop_id?: number };
        if (payload.stop_id != null) pendingStopIds.add(payload.stop_id);
      }
    }
    return {
      pending: rows.length,
      failed: await outboxStore.countByStatus('failed'),
      pendingStopIds,
    };
  },

  /** Notifies whenever queue contents change. Returns the unsubscriber. */
  subscribe(listener: Listener): () => void {
    listeners.add(listener);
    init().catch(() => {});
    return () => listeners.delete(listener);
  },
};
