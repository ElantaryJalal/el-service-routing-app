/**
 * Mobile-first stop detail as a bottom sheet (web Map). Rendered as an absolute
 * overlay INSIDE the map view (not an RN Modal, which portals to a full-window
 * fixed layer and would escape the mobile frame) so it stays within the app's
 * width. Dismissible (X or tapping the backdrop), scrolls internally when tall,
 * never exceeds the frame width. Mirrors the native map's StopDetailCard.
 *
 * The meaningful body — schedule, task-linked service time, store attributes,
 * task list — is the shared StopFacts (identical on native), so neither
 * surface ever shows a bare "—".
 */
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { SheetShell } from './SheetShell';
import { StopFacts } from './StopFacts';
import { Button, SyncState } from './ui';
import {
  dayColor,
  stopClient,
  stopTitle,
  type OptimisedStop,
  type StoreSize,
} from '../domain/optimisedTour';
import { color as tk } from '../theme';

function formatDay(date: string): string {
  const d = new Date(`${date}T00:00:00`);
  const wd = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][d.getDay()];
  return `${wd} ${String(d.getDate()).padStart(2, '0')}.${String(d.getMonth() + 1).padStart(2, '0')}`;
}

export function StopDetailSheet({
  stop,
  pendingSync,
  showMove = true,
  onClose,
  onMarkDone,
  onMarkNotDone,
  onMove,
  onShowHistory,
  onAttributesSaved,
}: {
  stop: OptimisedStop;
  pendingSync: boolean;
  /** Manual reschedule is a per-stop execution edit; hidden if not permitted. */
  showMove?: boolean;
  onClose: () => void;
  onMarkDone: () => void;
  onMarkNotDone: () => void;
  onMove: () => void;
  onShowHistory: () => void;
  /** Reflect just-captured store attributes into the cached tour. */
  onAttributesSaved: (
    storeId: number,
    fields: { size?: StoreSize; in_mall?: boolean; has_parking?: boolean },
  ) => void;
}) {
  const address = [
    stop.street,
    [stop.postal_code, stop.city].filter(Boolean).join(' '),
  ]
    .filter(Boolean)
    .join(', ');
  const done = stop.completed_at !== null;

  function navigate() {
    const url = `https://www.google.com/maps/dir/?api=1&destination=${stop.lat},${stop.lng}`;
    if (typeof window !== 'undefined') window.open(url, '_blank', 'noopener');
  }

  return (
    <SheetShell onClose={onClose}>
      {/* The card sits at the bottom; taps on it don't dismiss. */}
      <View style={styles.card}>
        <View style={styles.grabber} />

        <View style={styles.header}>
          <View style={styles.headerText}>
            <Text style={styles.title} numberOfLines={2}>
              {stopTitle(stop)}
            </Text>
            {stopClient(stop) ? (
              <Text style={styles.address} numberOfLines={1}>
                Kunde: {stopClient(stop)}
              </Text>
            ) : null}
            {stop.order_no ? (
              <Text style={styles.address} numberOfLines={1}>
                Auftrag {stop.order_no}
              </Text>
            ) : null}
            {address ? (
              <Text style={styles.address} numberOfLines={3}>
                {address}
              </Text>
            ) : null}
          </View>
          <Pressable onPress={onClose} hitSlop={12} accessibilityLabel="Close">
            <Text style={styles.close}>✕</Text>
          </Pressable>
        </View>

        <ScrollView
          style={styles.scroll}
          contentContainerStyle={styles.scrollContent}
          showsVerticalScrollIndicator
        >
          <View style={styles.metaRow}>
            <View
              style={[styles.dayBadge, { backgroundColor: dayColor(stop.dayIndex) }]}
            >
              <Text style={styles.dayBadgeText}>
                {formatDay(stop.assigned_day)} · #{stop.sequence}
              </Text>
            </View>
            {stop.store_id !== null && stop.store_feedback_count > 0 && (
              <Pressable style={styles.notesBadge} onPress={onShowHistory}>
                <Text style={styles.notesBadgeText}>
                  🗒 {stop.store_feedback_count} past note
                  {stop.store_feedback_count === 1 ? '' : 's'}
                </Text>
              </Pressable>
            )}
            {done && <Text style={styles.doneTag}>✓ Completed</Text>}
            {pendingSync && <SyncState state="pending" label="Not yet synced" />}
          </View>

          <StopFacts stop={stop} onAttributesSaved={onAttributesSaved} />
        </ScrollView>

        {/* Pinned actions: the screen's ONE primary action beside Navigate. */}
        <View style={styles.actionRow}>
          <Button title="Navigate" onPress={navigate} style={styles.flex} />
          {!done && (
            <Button
              title="Mark done ✓"
              variant="primary"
              onPress={onMarkDone}
              style={styles.flex}
            />
          )}
        </View>
        {!done && showMove && (
          <Button title="Move to another day…" variant="ghost" onPress={onMove} />
        )}
        {done && (
          <Button
            title="Completed — mark as not done"
            variant="ghost"
            onPress={onMarkNotDone}
          />
        )}
      </View>
    </SheetShell>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  card: {
    width: '100%',
    maxWidth: '100%',
    backgroundColor: tk.surface,
    borderTopLeftRadius: 18,
    borderTopRightRadius: 18,
    paddingHorizontal: 18,
    paddingTop: 8,
    paddingBottom: 18,
    gap: 10,
    maxHeight: '82%',
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
  headerText: { flex: 1 },
  title: { fontSize: 18, fontWeight: '700', color: tk.text },
  address: { fontSize: 13, color: tk.textMuted, marginTop: 2 },
  close: { fontSize: 18, color: tk.textFaint, paddingHorizontal: 4 },
  scroll: { flexGrow: 0 },
  scrollContent: { gap: 12, paddingBottom: 4 },
  metaRow: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 8 },
  dayBadge: { borderRadius: 12, paddingVertical: 4, paddingHorizontal: 10 },
  dayBadgeText: { color: tk.onBrand, fontWeight: '700', fontSize: 12 },
  notesBadge: {
    backgroundColor: tk.brandSoft,
    borderRadius: 12,
    paddingVertical: 4,
    paddingHorizontal: 10,
  },
  notesBadgeText: { color: tk.brand, fontWeight: '600', fontSize: 12 },
  doneTag: { color: tk.status.done, fontWeight: '700', fontSize: 12 },
  actionRow: { flexDirection: 'row', gap: 10 },
});
