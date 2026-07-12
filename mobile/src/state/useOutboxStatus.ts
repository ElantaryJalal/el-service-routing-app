/** Reactive view of the outbox for the sync indicators. */
import { useEffect, useState } from 'react';

import { outbox, type OutboxStatusSnapshot } from './outbox';

const EMPTY: OutboxStatusSnapshot = {
  pending: 0,
  failed: 0,
  pendingStopIds: new Set<number>(),
};

export function useOutboxStatus(): OutboxStatusSnapshot {
  const [snapshot, setSnapshot] = useState<OutboxStatusSnapshot>(EMPTY);

  useEffect(() => {
    let alive = true;
    const refresh = () => {
      outbox
        .status()
        .then((s) => alive && setSnapshot(s))
        .catch(() => {});
    };
    refresh();
    const unsubscribe = outbox.subscribe(refresh);
    return () => {
      alive = false;
      unsubscribe();
    };
  }, []);

  return snapshot;
}
