/** Shared contract between the outbox logic and its per-platform storage
 * drivers (expo-sqlite on native, localStorage-backed on web). */

export type OutboxKind = 'complete' | 'start' | 'attributes' | 'feedback';
export type OutboxStatus = 'pending' | 'synced' | 'failed';

export interface OutboxRow {
  id: number;
  kind: OutboxKind;
  /** JSON-serialised write payload (see OutboxWrite in outbox.ts). */
  payload: string;
  /** Idempotency key. For feedback it doubles as the server dedupe key. */
  client_uuid: string;
  status: OutboxStatus;
  attempts: number;
  /** Epoch ms before which this row must not be retried (backoff). */
  next_attempt_at: number;
  created_at: number;
}

export interface OutboxStore {
  /** Insert a new row; returns its id. */
  insert(row: Omit<OutboxRow, 'id'>): Promise<number>;
  /** All pending rows, oldest first (FIFO replay order). */
  pending(): Promise<OutboxRow[]>;
  get(id: number): Promise<OutboxRow | null>;
  setStatus(id: number, status: OutboxStatus): Promise<void>;
  bumpRetry(id: number, attempts: number, nextAttemptAt: number): Promise<void>;
  /** Drop synced rows older than the cutoff so the table stays small. */
  pruneSynced(olderThanMs: number): Promise<void>;
  countByStatus(status: OutboxStatus): Promise<number>;
}
