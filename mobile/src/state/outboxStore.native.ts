/**
 * Native outbox storage: a real SQLite table via expo-sqlite, so queued
 * writes survive app restarts and crashes on the field devices. Metro
 * resolves this file on iOS/Android; the web build uses outboxStore.ts.
 */
import * as SQLite from 'expo-sqlite';

import type { OutboxRow, OutboxStatus, OutboxStore } from './outboxTypes';

let dbPromise: Promise<SQLite.SQLiteDatabase> | null = null;

function db(): Promise<SQLite.SQLiteDatabase> {
  if (!dbPromise) {
    dbPromise = (async () => {
      const handle = await SQLite.openDatabaseAsync('outbox.db');
      await handle.execAsync(`
        CREATE TABLE IF NOT EXISTS outbox (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          kind TEXT NOT NULL,
          payload TEXT NOT NULL,
          client_uuid TEXT NOT NULL UNIQUE,
          status TEXT NOT NULL DEFAULT 'pending',
          attempts INTEGER NOT NULL DEFAULT 0,
          next_attempt_at INTEGER NOT NULL DEFAULT 0,
          created_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_outbox_status ON outbox (status, id);
      `);
      return handle;
    })();
  }
  return dbPromise;
}

export const outboxStore: OutboxStore = {
  async insert(row) {
    const handle = await db();
    const result = await handle.runAsync(
      `INSERT INTO outbox (kind, payload, client_uuid, status, attempts, next_attempt_at, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?)`,
      [
        row.kind,
        row.payload,
        row.client_uuid,
        row.status,
        row.attempts,
        row.next_attempt_at,
        row.created_at,
      ],
    );
    return result.lastInsertRowId;
  },

  async pending() {
    const handle = await db();
    return handle.getAllAsync<OutboxRow>(
      `SELECT * FROM outbox WHERE status = 'pending' ORDER BY id`,
    );
  },

  async get(id) {
    const handle = await db();
    return handle.getFirstAsync<OutboxRow>(`SELECT * FROM outbox WHERE id = ?`, [
      id,
    ]);
  },

  async setStatus(id, status) {
    const handle = await db();
    await handle.runAsync(`UPDATE outbox SET status = ? WHERE id = ?`, [
      status,
      id,
    ]);
  },

  async bumpRetry(id, attempts, nextAttemptAt) {
    const handle = await db();
    await handle.runAsync(
      `UPDATE outbox SET attempts = ?, next_attempt_at = ? WHERE id = ?`,
      [attempts, nextAttemptAt, id],
    );
  },

  async pruneSynced(olderThanMs) {
    const handle = await db();
    await handle.runAsync(
      `DELETE FROM outbox WHERE status = 'synced' AND created_at < ?`,
      [Date.now() - olderThanMs],
    );
  },

  async countByStatus(status: OutboxStatus) {
    const handle = await db();
    const row = await handle.getFirstAsync<{ n: number }>(
      `SELECT COUNT(*) AS n FROM outbox WHERE status = ?`,
      [status],
    );
    return row?.n ?? 0;
  },
};
