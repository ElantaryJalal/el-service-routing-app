/**
 * A store's full visit-feedback history, newest first (GET
 * /stores/{id}/feedback). Read-only by design: feedback is append-only — a
 * wrong store *fact* is corrected via the attribute form, anything about a
 * *visit* is a new entry.
 */
import { useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Image,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import { ApiError, api, type FeedbackRead } from '../api/client';
import { API_BASE_URL } from '../api/config';
import { tagLabel } from '../domain/feedbackTags';

type State =
  | { status: 'loading' }
  | { status: 'ready'; rows: FeedbackRead[] }
  | { status: 'error'; message: string };

function formatWhen(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const dd = String(d.getDate()).padStart(2, '0');
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  return `${dd}.${mm}.${d.getFullYear()}`;
}

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
                <View key={row.id} style={styles.entry}>
                  <View style={styles.entryHeader}>
                    <Text style={styles.when}>{formatWhen(row.created_at)}</Text>
                    {row.employee && (
                      <Text style={styles.employee}>{row.employee}</Text>
                    )}
                  </View>
                  {row.tags.length > 0 && (
                    <View style={styles.tagWrap}>
                      {row.tags.map((t) => (
                        <View key={t} style={styles.tag}>
                          <Text style={styles.tagText}>{tagLabel(t)}</Text>
                        </View>
                      ))}
                    </View>
                  )}
                  {row.note && <Text style={styles.note}>{row.note}</Text>}
                  {row.photo_path && (
                    <Image
                      source={{ uri: `${API_BASE_URL}/${row.photo_path}` }}
                      style={styles.photo}
                      resizeMode="cover"
                    />
                  )}
                </View>
              ))}
            </ScrollView>
          )}
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: '#00000088', justifyContent: 'flex-end' },
  sheet: {
    backgroundColor: '#fff',
    borderTopLeftRadius: 16,
    borderTopRightRadius: 16,
    padding: 20,
    gap: 12,
    maxHeight: '80%',
  },
  header: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  title: { fontSize: 18, fontWeight: '700', flex: 1 },
  close: { fontSize: 18, color: '#999', paddingHorizontal: 4 },
  centered: { alignItems: 'center', gap: 8, paddingVertical: 24 },
  error: { color: '#b00020', fontSize: 14, textAlign: 'center' },
  muted: { color: '#777', fontSize: 14 },
  list: { gap: 4 },
  entry: {
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#eee',
    gap: 6,
  },
  entryHeader: { flexDirection: 'row', justifyContent: 'space-between' },
  when: { fontSize: 13, fontWeight: '700', color: '#444' },
  employee: { fontSize: 13, color: '#777' },
  tagWrap: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  tag: {
    backgroundColor: '#eef2f7',
    borderRadius: 12,
    paddingVertical: 3,
    paddingHorizontal: 10,
  },
  tagText: { fontSize: 12, color: '#334', fontWeight: '600' },
  note: { fontSize: 14, color: '#222' },
  photo: { width: '100%', height: 160, borderRadius: 8, backgroundColor: '#eee' },
});
