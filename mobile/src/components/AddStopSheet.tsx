/**
 * "Add another stop" — worker-initiated smart pull-forward. Shows the nearest
 * feasible later-day stops (ranked by real drive time from the worker's
 * position) so someone who finishes early can pick up one or two more. Routing
 * needs a connection; offline the action is disabled with a short note.
 */
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import type { PullCandidate } from '../api/client';
import { SheetShell } from './SheetShell';
import { Button } from './ui';
import { color as tk } from '../theme';

function toHHMM(time: string): string {
  const m = /^(\d{1,2}):(\d{2})/.exec(time);
  return m ? `${m[1].padStart(2, '0')}:${m[2]}` : time;
}

export function AddStopSheet({
  loading,
  candidates,
  error,
  online,
  addingId,
  onAdd,
  onClose,
}: {
  loading: boolean;
  candidates: PullCandidate[] | null;
  error: string | null;
  online: boolean;
  addingId: number | null;
  onAdd: (stopId: number) => void;
  onClose: () => void;
}) {
  return (
    <SheetShell onClose={onClose}>
      <View style={styles.card}>
        <View style={styles.grabber} />
        <View style={styles.header}>
          <View style={styles.flex}>
            <Text style={styles.title}>Add another stop</Text>
            <Text style={styles.subtitle}>Nearest stops you can still finish today.</Text>
          </View>
          <Pressable onPress={onClose} hitSlop={12} accessibilityLabel="Close">
            <Text style={styles.close}>✕</Text>
          </Pressable>
        </View>

        {!online ? (
          <Text style={styles.note}>
            Needs signal — adding a stop uses live driving directions.
          </Text>
        ) : loading ? (
          <View style={styles.centered}>
            <ActivityIndicator color={tk.brand} />
            <Text style={styles.muted}>Finding the nearest stop…</Text>
          </View>
        ) : error ? (
          <Text style={styles.error}>{error}</Text>
        ) : candidates && candidates.length === 0 ? (
          <Text style={styles.muted}>
            No more stops you could finish today. Enjoy the early finish.
          </Text>
        ) : (
          <ScrollView style={styles.list} contentContainerStyle={styles.listContent}>
            {(candidates ?? []).map((c) => (
              <View key={c.stop_id} style={styles.row}>
                <View style={styles.flex}>
                  <Text style={styles.store} numberOfLines={1}>
                    {c.store_name}
                  </Text>
                  <Text style={styles.meta}>
                    {c.drive_minutes} min away · done by {toHHMM(c.projected_arrival)}
                    {' + '}
                    {c.service_minutes} min on site
                  </Text>
                </View>
                <Button
                  title={addingId === c.stop_id ? 'Adding…' : 'Add'}
                  variant="primary"
                  onPress={() => onAdd(c.stop_id)}
                  disabled={addingId !== null}
                  style={styles.addBtn}
                />
              </View>
            ))}
          </ScrollView>
        )}
      </View>
    </SheetShell>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  card: {
    backgroundColor: tk.surface,
    borderTopLeftRadius: 18,
    borderTopRightRadius: 18,
    paddingHorizontal: 18,
    paddingTop: 8,
    paddingBottom: 18,
    gap: 12,
    maxHeight: '70%',
  },
  grabber: {
    alignSelf: 'center',
    width: 40,
    height: 4,
    borderRadius: 2,
    backgroundColor: tk.border,
    marginBottom: 4,
  },
  header: { flexDirection: 'row', alignItems: 'flex-start', gap: 8 },
  title: { fontSize: 18, fontWeight: '700', color: tk.text },
  subtitle: { fontSize: 13, color: tk.textMuted, marginTop: 2 },
  close: { fontSize: 18, color: tk.textFaint, paddingHorizontal: 4 },
  note: { fontSize: 14, color: tk.warningText, backgroundColor: tk.warningBg, borderRadius: 8, padding: 12 },
  error: { fontSize: 14, color: tk.danger },
  muted: { fontSize: 14, color: tk.textMuted, textAlign: 'center' },
  centered: { alignItems: 'center', gap: 8, paddingVertical: 20 },
  list: { flexGrow: 0 },
  listContent: { gap: 10 },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: tk.border,
  },
  store: { fontSize: 15, fontWeight: '700', color: tk.text },
  meta: { fontSize: 13, color: tk.textMuted, marginTop: 2 },
  addBtn: { minWidth: 88 },
});
