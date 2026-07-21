/**
 * Mobile-first stop detail as a bottom sheet (web Map). Rendered as an absolute
 * overlay INSIDE the map view (not an RN Modal, which portals to a full-window
 * fixed layer and would escape the mobile frame) so it stays within the app's
 * width. Dismissible (X or tapping the backdrop), scrolls internally when tall,
 * never exceeds the frame width. Mirrors the native map's StopDetailCard.
 */
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { SheetShell } from './SheetShell';
import { Button, SyncState } from './ui';
import { dayColor, etaNearClosing, type OptimisedStop } from '../domain/optimisedTour';
import { color as tk } from '../theme';

function toHHMM(time: string): string {
  const m = /^(\d{1,2}):(\d{2})/.exec(time);
  return m ? `${m[1].padStart(2, '0')}:${m[2]}` : time;
}

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
}) {
  const urgent = etaNearClosing(stop.eta, stop.closing_time);
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
                {stop.customer ?? `Stop ${stop.stop_id}`}
              </Text>
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

            <View style={[styles.etaRow, urgent && styles.etaRowUrgent]}>
              <Text style={styles.etaLabel}>ETA</Text>
              <Text style={[styles.etaValue, urgent && styles.etaValueUrgent]}>
                {stop.eta ? toHHMM(stop.eta) : '—'}
              </Text>
              <Text style={styles.etaLabel}>Closes</Text>
              <Text style={[styles.etaValue, urgent && styles.etaValueUrgent]}>
                {stop.closing_time ? toHHMM(stop.closing_time) : '—'}
              </Text>
              <Text style={styles.etaLabel}>{stop.service_minutes ?? '—'} min on site</Text>
            </View>
            {urgent && (
              <Text style={styles.urgentHint}>
                Tight — arrives close to closing time.
              </Text>
            )}

            {stop.remarks ? <Text style={styles.remarks}>{stop.remarks}</Text> : null}

            {stop.tasks.length > 0 && (
              <View style={styles.taskChips}>
                {stop.tasks.map((t, i) => (
                  <View key={i} style={styles.taskChip}>
                    <Text style={styles.taskChipText}>{t}</Text>
                  </View>
                ))}
              </View>
            )}
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
  scrollContent: { gap: 10, paddingBottom: 4 },
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
  etaRow: {
    flexDirection: 'row',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: 6,
    backgroundColor: tk.soft,
    borderRadius: 10,
    paddingVertical: 8,
    paddingHorizontal: 10,
  },
  etaRowUrgent: { backgroundColor: tk.warningBg },
  etaLabel: { fontSize: 12, color: tk.textMuted },
  etaValue: { fontSize: 13, fontWeight: '700', color: tk.text, marginRight: 6 },
  etaValueUrgent: { color: tk.danger },
  urgentHint: { fontSize: 12, color: tk.danger, fontWeight: '600' },
  remarks: {
    fontSize: 13,
    color: tk.warningText,
    backgroundColor: tk.warningBg,
    borderLeftWidth: 3,
    borderLeftColor: tk.warning,
    paddingVertical: 6,
    paddingHorizontal: 10,
    borderRadius: 6,
  },
  taskChips: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  taskChip: {
    backgroundColor: tk.soft,
    borderRadius: 10,
    paddingVertical: 3,
    paddingHorizontal: 9,
  },
  taskChipText: { fontSize: 12, color: tk.text },
  actionRow: { flexDirection: 'row', gap: 10 },
});
