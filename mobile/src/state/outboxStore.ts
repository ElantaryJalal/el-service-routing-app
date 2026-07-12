/**
 * Web (and fallback) outbox storage: a JSON table in AsyncStorage, which is
 * localStorage on web — durable across reloads. Native devices get the real
 * SQLite driver in outboxStore.native.ts (Metro picks it automatically);
 * both expose the same OutboxStore contract.
 */
import AsyncStorage from '@react-native-async-storage/async-storage';

import type { OutboxRow, OutboxStatus, OutboxStore } from './outboxTypes';

const KEY = 'outbox:v1';

interface Table {
  nextId: number;
  rows: OutboxRow[];
}

async function load(): Promise<Table> {
  try {
    const raw = await AsyncStorage.getItem(KEY);
    if (raw) return JSON.parse(raw) as Table;
  } catch {
    // fall through to a fresh table
  }
  return { nextId: 1, rows: [] };
}

async function save(table: Table): Promise<void> {
  await AsyncStorage.setItem(KEY, JSON.stringify(table));
}

export const outboxStore: OutboxStore = {
  async insert(row) {
    const table = await load();
    const id = table.nextId++;
    table.rows.push({ ...row, id });
    await save(table);
    return id;
  },

  async pending() {
    const table = await load();
    return table.rows
      .filter((r) => r.status === 'pending')
      .sort((a, b) => a.id - b.id);
  },

  async get(id) {
    const table = await load();
    return table.rows.find((r) => r.id === id) ?? null;
  },

  async setStatus(id, status) {
    const table = await load();
    const row = table.rows.find((r) => r.id === id);
    if (row) {
      row.status = status;
      await save(table);
    }
  },

  async bumpRetry(id, attempts, nextAttemptAt) {
    const table = await load();
    const row = table.rows.find((r) => r.id === id);
    if (row) {
      row.attempts = attempts;
      row.next_attempt_at = nextAttemptAt;
      await save(table);
    }
  },

  async pruneSynced(olderThanMs) {
    const table = await load();
    const cutoff = Date.now() - olderThanMs;
    const kept = table.rows.filter(
      (r) => r.status !== 'synced' || r.created_at >= cutoff,
    );
    if (kept.length !== table.rows.length) {
      table.rows = kept;
      await save(table);
    }
  },

  async countByStatus(status: OutboxStatus) {
    const table = await load();
    return table.rows.filter((r) => r.status === status).length;
  },
};
