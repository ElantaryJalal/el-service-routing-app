/**
 * A store's full visit-feedback history, newest first (GET
 * /stores/{id}/feedback). Read-only by design: feedback is append-only — a
 * wrong store *fact* is corrected via the attribute form, anything about a
 * *visit* is a new entry.
 */
import { useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import { ApiError, api, type FeedbackRead } from '../api/client';
import { FeedbackEntry } from './FeedbackEntry';

import { color as tk } from '../theme';

type State =
  | { status: 'loading' }
  | { status: 'ready'; rows: FeedbackRead[] }
  | { status: 'error'; message: string };

export function FeedbackHistorySheet({
  storeId,
  title,
  onClose,
}: {
  storeId: number;
  title: string;
  onClose: () => void;
}) {
  const [state, setState] = useState<State>({ status: 'loading' });

  useEffect(() => {
    let alive = true;
    api
      .getStoreFeedback(storeId)
      .then((rows) => alive && setState({ status: 'ready', rows }))
      .catch((err) => {
        if (!alive) return;
        const message = err instanceof ApiError ? err.message : String(err);
        setState({ status: 'error', message });
      });
    return () => {
      alive = false;
    };
  }, [storeId]);

  return (
    <Modal visible transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.backdrop}>
        <View style={styles.sheet}>
          <View style={styles.header}>
            <Text style={styles.title} numberOfLines={1}>
              Past notes — {title}
            </Text>
            <Pressable onPress={onClose} hitSlop={10}>
              <Text style={styles.close}>✕</Text>
            </Pressable>
          </View>

          {state.status === 'loading' && (
            <View style={styles.centered}>
              <ActivityIndicator />
            </View>
          )}
          {state.status === 'error' && (
            <View style={styles.centered}>
              <Text style={styles.error}>{state.message}</Text>
              <Text style={styles.muted}>History needs a connection.</Text>
            </View>
          )}
          {state.status === 'ready' && (
            <ScrollView contentContainerStyle={styles.list}>
              {state.rows.length === 0 && (
                <Text style={styles.muted}>No feedback for this market yet.</Text>
              )}
              {state.rows.map((row) => (
                <FeedbackEntry key={row.id} row={row} />
              ))}
            </ScrollView>
          )}
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: tk.scrim, justifyContent: 'flex-end' },
  sheet: {
    backgroundColor: tk.surface,
    borderTopLeftRadius: 16,
    borderTopRightRadius: 16,
    padding: 20,
    gap: 12,
    maxHeight: '80%',
  },
  header: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  title: { fontSize: 18, fontWeight: '700', flex: 1 },
  close: { fontSize: 18, color: tk.textFaint, paddingHorizontal: 4 },
  centered: { alignItems: 'center', gap: 8, paddingVertical: 24 },
  error: { color: tk.danger, fontSize: 14, textAlign: 'center' },
  muted: { color: tk.textMuted, fontSize: 14 },
  list: { gap: 4 },
});
