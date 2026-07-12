/** RFC4122 v4 id. Prefers the platform's crypto; falls back to Math.random
 * on JS engines without randomUUID (older Hermes). Used as the idempotency
 * key for offline-retryable POSTs. */
export function uuidv4(): string {
  const c = (globalThis as { crypto?: { randomUUID?: () => string } }).crypto;
  if (c?.randomUUID) return c.randomUUID();
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (ch) => {
    const r = (Math.random() * 16) | 0;
    const v = ch === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}
