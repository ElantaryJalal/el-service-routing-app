/**
 * The meaningful middle of a stop's detail card, shared by the web bottom
 * sheet (StopDetailSheet) and the native card (map.tsx StopDetailCard) so both
 * surfaces show the same real data and never a bare "—":
 *
 *  - the store's closing time — the only schedule fact that constrains the
 *    worker (they can start whenever, so no "planned start" is shown);
 *  - service time as the learned estimate for THIS visit's task set, with the
 *    tasks shown, or an honestly-labelled default;
 *  - the real task list, with Nachbessern (rework) shown alongside it.
 *
 * Store attributes (size / parking / mall) are NOT captured here — they're
 * asked once on the completion sheet after the stop is marked done, so the
 * worker is never asked for the same thing twice.
 */
import { StyleSheet, Text, View } from 'react-native';

import { type OptimisedStop } from '../domain/optimisedTour';
import { color as tk } from '../theme';

function toHHMM(time: string): string {
  const m = /^(\d{1,2}):(\d{2})/.exec(time);
  return m ? `${m[1].padStart(2, '0')}:${m[2]}` : time;
}

/** Headline + caption for the service-time estimate, honest about its source. */
function serviceLine(stop: OptimisedStop): { minutes: string; caption: string } {
  const m = stop.service_estimate_minutes;
  const src = stop.service_estimate_source;
  const isDefault = src === 'default' || src === 'store_default';
  const minutes = `${src === 'override' ? '' : '~'}${m} min${isDefault ? ' (default)' : ''}`;
  if (src === 'profile' && stop.tasks.length > 0) {
    const shown = stop.tasks.slice(0, 3).join(', ');
    const extra = stop.tasks.length > 3 ? ` +${stop.tasks.length - 3}` : '';
    return { minutes, caption: `for ${shown}${extra}` };
  }
  const caption =
    src === 'profile'
      ? 'learned for this visit'
      : src === 'store_learned'
        ? 'learned from past visits'
        : src === 'override'
          ? 'set for this stop'
          : 'default — no history for this store yet';
  return { minutes, caption };
}

export function StopFacts({ stop }: { stop: OptimisedStop }) {
  const rework = stop.status_hint === 'rework';
  const service = serviceLine(stop);

  return (
    <>
      {/* Closing time — the worker starts whenever, so only the store's
          deadline matters here. */}
      <View style={styles.timeRow}>
        <View style={styles.timeCell}>
          <Text style={styles.timeLabel}>Closes</Text>
          <Text style={styles.timeValue}>
            {stop.closing_time ? toHHMM(stop.closing_time) : 'Not set'}
          </Text>
        </View>
      </View>

      {/* Service time linked to THIS visit's task set. */}
      <View style={styles.serviceRow}>
        <Text style={styles.serviceIcon}>⏱</Text>
        <View style={styles.flex}>
          <Text style={styles.serviceMinutes}>{service.minutes} on site</Text>
          <Text style={styles.serviceCaption}>{service.caption}</Text>
        </View>
      </View>

      {stop.remarks ? <Text style={styles.remarks}>{stop.remarks}</Text> : null}

      {/* Tasks: the real mission. Nachbessern (rework) sits alongside. */}
      {(stop.tasks.length > 0 || rework) && (
        <View>
          <Text style={styles.tasksLabel}>Tasks</Text>
          <View style={styles.taskChips}>
            {rework && (
              <View style={[styles.taskChip, styles.reworkChip]}>
                <Text style={styles.reworkChipText}>↻ Nachbessern</Text>
              </View>
            )}
            {stop.tasks.map((t, i) => (
              <View key={i} style={styles.taskChip}>
                <Text style={styles.taskChipText}>{t}</Text>
              </View>
            ))}
          </View>
        </View>
      )}
    </>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },

  // Schedule (closing only)
  timeRow: {
    flexDirection: 'row',
    alignItems: 'stretch',
    backgroundColor: tk.soft,
    borderRadius: 10,
    paddingVertical: 8,
    paddingHorizontal: 12,
  },
  timeCell: { flex: 1, gap: 2 },
  timeLabel: {
    fontSize: 11,
    color: tk.textMuted,
    textTransform: 'uppercase',
    letterSpacing: 0.4,
  },
  timeValue: { fontSize: 16, fontWeight: '700', color: tk.text },

  // Service estimate
  serviceRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    backgroundColor: tk.brandSoft,
    borderRadius: 10,
    paddingVertical: 10,
    paddingHorizontal: 12,
  },
  serviceIcon: { fontSize: 20 },
  serviceMinutes: { fontSize: 15, fontWeight: '700', color: tk.text },
  serviceCaption: { fontSize: 12, color: tk.textMuted, marginTop: 1 },

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

  tasksLabel: { fontSize: 12, color: tk.textMuted, marginBottom: 6 },
  taskChips: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  taskChip: {
    backgroundColor: tk.soft,
    borderRadius: 10,
    paddingVertical: 3,
    paddingHorizontal: 9,
  },
  taskChipText: { fontSize: 12, color: tk.text },
  reworkChip: { backgroundColor: tk.warningBg },
  reworkChipText: { fontSize: 12, fontWeight: '700', color: tk.warningText },
});
