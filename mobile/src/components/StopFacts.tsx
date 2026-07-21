/**
 * The meaningful middle of a stop's detail card, shared by the web bottom
 * sheet (StopDetailSheet) and the native card (map.tsx StopDetailCard) so both
 * surfaces show the same real data and never a bare "—":
 *
 *  - schedule as a "Planned start" (a suggestion, not a hard ETA) + closing;
 *  - service time as the learned estimate for THIS visit's task set, with the
 *    tasks shown, or an honestly-labelled default;
 *  - the store's size / parking / mall attributes as badges, with a
 *    quick-capture control in place of any value still missing;
 *  - the real task list, with Nachbessern (rework) shown alongside it.
 */
import { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { outbox } from '../state/outbox';
import { Button } from './ui';
import { etaNearClosing, type OptimisedStop, type StoreSize } from '../domain/optimisedTour';
import { color as tk } from '../theme';

function toHHMM(time: string): string {
  const m = /^(\d{1,2}):(\d{2})/.exec(time);
  return m ? `${m[1].padStart(2, '0')}:${m[2]}` : time;
}

const SIZE_LABELS: Record<StoreSize, string> = {
  small: 'Small',
  medium: 'Medium',
  large: 'Large',
};
const SIZE_OPTIONS: StoreSize[] = ['small', 'medium', 'large'];

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

export function StopFacts({
  stop,
  onAttributesSaved,
}: {
  stop: OptimisedStop;
  /** Reflect just-captured store attributes into the cached tour. */
  onAttributesSaved: (
    storeId: number,
    fields: { size?: StoreSize; in_mall?: boolean; has_parking?: boolean },
  ) => void;
}) {
  const urgent = etaNearClosing(stop.eta, stop.closing_time);
  const rework = stop.status_hint === 'rework';
  const service = serviceLine(stop);

  const [size, setSize] = useState<StoreSize | null>(stop.store_size);
  const [inMall, setInMall] = useState<boolean | null>(stop.store_in_mall);
  const [hasParking, setHasParking] = useState<boolean | null>(stop.store_has_parking);
  const [attrPhase, setAttrPhase] = useState<'idle' | 'saving' | 'saved'>('idle');
  const [attrQueued, setAttrQueued] = useState(false);
  const [attrError, setAttrError] = useState<string | null>(null);

  const attrDirty =
    size !== stop.store_size ||
    inMall !== stop.store_in_mall ||
    hasParking !== stop.store_has_parking;
  // A value shows as a badge once it's known (was set, or just saved here);
  // otherwise the capture control takes its place.
  const settled = attrPhase === 'saved';
  const sizeBadge = stop.store_size !== null || (settled && size !== null);
  const mallBadge = stop.store_in_mall !== null || (settled && inMall !== null);
  const parkBadge = stop.store_has_parking !== null || (settled && hasParking !== null);

  async function saveAttributes() {
    if (stop.store_id === null) return;
    setAttrPhase('saving');
    setAttrError(null);
    const fields = {
      ...(size !== stop.store_size && size !== null && { size }),
      ...(inMall !== stop.store_in_mall && inMall !== null && { in_mall: inMall }),
      ...(hasParking !== stop.store_has_parking &&
        hasParking !== null && { has_parking: hasParking }),
    };
    try {
      const outcome = await outbox.enqueue({
        kind: 'attributes',
        payload: { store_id: stop.store_id, fields },
      });
      setAttrQueued(outcome === 'queued');
      setAttrPhase('saved');
      onAttributesSaved(stop.store_id, fields);
    } catch {
      setAttrPhase('idle');
      setAttrError('Could not save — try again.');
    }
  }

  return (
    <>
      {/* Schedule: a suggested start (not a hard ETA) + closing time. */}
      <View style={[styles.timeRow, urgent && styles.timeRowUrgent]}>
        <View style={styles.timeCell}>
          <Text style={styles.timeLabel}>Planned start</Text>
          <Text style={[styles.timeValue, urgent && styles.timeValueUrgent]}>
            {stop.eta ? toHHMM(stop.eta) : 'Flexible'}
          </Text>
        </View>
        <View style={styles.timeDivider} />
        <View style={styles.timeCell}>
          <Text style={styles.timeLabel}>Closes</Text>
          <Text style={[styles.timeValue, urgent && styles.timeValueUrgent]}>
            {stop.closing_time ? toHHMM(stop.closing_time) : 'Not set'}
          </Text>
        </View>
      </View>
      {urgent && (
        <Text style={styles.urgentHint}>
          Tight — planned start is close to closing time.
        </Text>
      )}

      {/* Service time linked to THIS visit's task set. */}
      <View style={styles.serviceRow}>
        <Text style={styles.serviceIcon}>⏱</Text>
        <View style={styles.flex}>
          <Text style={styles.serviceMinutes}>{service.minutes} on site</Text>
          <Text style={styles.serviceCaption}>{service.caption}</Text>
        </View>
      </View>

      {/* Store attributes: captured once, shown to every later visitor. */}
      {stop.store_id !== null && (
        <View style={styles.attrSection}>
          <Text style={styles.attrTitle}>Store info</Text>
          <View style={styles.attrGrid}>
            <AttrField label="Size">
              {sizeBadge && size !== null ? (
                <Badge text={SIZE_LABELS[size]} />
              ) : (
                <View style={styles.optionRow}>
                  {SIZE_OPTIONS.map((o) => (
                    <OptionButton
                      key={o}
                      label={SIZE_LABELS[o]}
                      active={size === o}
                      onPress={() => setSize(size === o ? null : o)}
                    />
                  ))}
                </View>
              )}
            </AttrField>

            <AttrField label="Parking">
              {parkBadge && hasParking !== null ? (
                <Badge text={hasParking ? '🅿️ Parking' : '🚫 No parking'} />
              ) : (
                <YesNo
                  value={hasParking}
                  onChange={(v) => setHasParking(hasParking === v ? null : v)}
                />
              )}
            </AttrField>

            <AttrField label="Mall / center">
              {mallBadge && inMall !== null ? (
                <Badge text={inMall ? '🏬 In mall' : '🏪 Standalone'} />
              ) : (
                <YesNo
                  value={inMall}
                  onChange={(v) => setInMall(inMall === v ? null : v)}
                />
              )}
            </AttrField>
          </View>

          {attrError && <Text style={styles.error}>{attrError}</Text>}
          {attrDirty && (
            <Button
              title="Save store info"
              variant="primary"
              loading={attrPhase === 'saving'}
              onPress={saveAttributes}
            />
          )}
          {settled && !attrDirty && (
            <Text style={styles.savedNote}>
              {attrQueued
                ? 'Store info saved — will sync when online.'
                : 'Store info saved — thanks!'}
            </Text>
          )}
        </View>
      )}

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

function AttrField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <View style={styles.attrField}>
      <Text style={styles.attrFieldLabel}>{label}</Text>
      {children}
    </View>
  );
}

function Badge({ text }: { text: string }) {
  return (
    <View style={styles.attrBadge}>
      <Text style={styles.attrBadgeText}>{text}</Text>
    </View>
  );
}

function YesNo({
  value,
  onChange,
}: {
  value: boolean | null;
  onChange: (v: boolean) => void;
}) {
  return (
    <View style={styles.optionRow}>
      <OptionButton label="Yes" active={value === true} onPress={() => onChange(true)} />
      <OptionButton label="No" active={value === false} onPress={() => onChange(false)} />
    </View>
  );
}

function OptionButton({
  label,
  active,
  onPress,
}: {
  label: string;
  active: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable
      style={[styles.option, active && styles.optionActive]}
      onPress={onPress}
      hitSlop={6}
    >
      <Text style={[styles.optionText, active && styles.optionTextActive]}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },

  // Schedule
  timeRow: {
    flexDirection: 'row',
    alignItems: 'stretch',
    backgroundColor: tk.soft,
    borderRadius: 10,
    paddingVertical: 8,
    paddingHorizontal: 12,
  },
  timeRowUrgent: { backgroundColor: tk.warningBg },
  timeCell: { flex: 1, gap: 2 },
  timeDivider: { width: 1, backgroundColor: tk.border, marginHorizontal: 12 },
  timeLabel: {
    fontSize: 11,
    color: tk.textMuted,
    textTransform: 'uppercase',
    letterSpacing: 0.4,
  },
  timeValue: { fontSize: 16, fontWeight: '700', color: tk.text },
  timeValueUrgent: { color: tk.danger },
  urgentHint: { fontSize: 12, color: tk.danger, fontWeight: '600' },

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

  // Attributes
  attrSection: { backgroundColor: tk.soft, borderRadius: 10, padding: 12, gap: 10 },
  attrTitle: { fontSize: 13, fontWeight: '700', color: tk.text },
  attrGrid: { gap: 10 },
  attrField: { flexDirection: 'row', alignItems: 'center', gap: 10, flexWrap: 'wrap' },
  attrFieldLabel: { fontSize: 13, color: tk.textMuted, width: 84 },
  attrBadge: {
    backgroundColor: tk.surface,
    borderRadius: 12,
    paddingVertical: 4,
    paddingHorizontal: 10,
    borderWidth: 1,
    borderColor: tk.border,
  },
  attrBadgeText: { fontSize: 13, fontWeight: '600', color: tk.text },
  optionRow: { flexDirection: 'row', gap: 6, flexWrap: 'wrap' },
  option: {
    backgroundColor: tk.surface,
    borderRadius: 14,
    paddingVertical: 6,
    paddingHorizontal: 12,
    borderWidth: 1,
    borderColor: tk.borderStrong,
  },
  optionActive: { backgroundColor: tk.brand, borderColor: tk.brand },
  optionText: { fontWeight: '600', color: tk.text, fontSize: 13 },
  optionTextActive: { color: tk.onBrand },
  error: { color: tk.danger, fontSize: 13 },
  savedNote: { color: tk.status.done, fontSize: 13, fontWeight: '600' },

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
