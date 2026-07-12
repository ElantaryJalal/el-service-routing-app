/**
 * Per-tour Date mode control for the Map screens. Collapsed, it is a single
 * chip naming the current mode; expanded, it offers both modes. Picking the
 * other mode calls onChange, and the screen PATCHes the tour, re-runs
 * optimise, and refreshes the map — `busy` covers that round-trip.
 */
import { useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';

import type { DateMode } from '../api/client';

const OPTIONS: { mode: DateMode; label: string; caption?: string }[] = [
  { mode: 'fixed', label: 'Plan dates (recommended)' },
  {
    mode: 'optimized',
    label: 'Let the app choose days (experimental)',
    caption: 'May leave stops unassigned if the week is too full.',
  },
];

export function DateModeControl({
  mode,
  busy,
  onChange,
}: {
  mode: DateMode;
  busy: boolean;
  onChange: (mode: DateMode) => void;
}) {
  const [open, setOpen] = useState(false);
  const current = OPTIONS.find((o) => o.mode === mode) ?? OPTIONS[0];

  if (!open) {
    return (
      <Pressable
        style={styles.chip}
        onPress={() => setOpen(true)}
        disabled={busy}
        accessibilityRole="button"
        accessibilityLabel="Change date mode"
      >
        {busy ? (
          <ActivityIndicator size="small" color="#1f6feb" />
        ) : (
          <Text style={styles.chipIcon}>📅</Text>
        )}
        <Text style={styles.chipText}>
          {busy ? 'Rescheduling…' : current.label}
        </Text>
        <Text style={styles.caret}>▾</Text>
      </Pressable>
    );
  }

  return (
    <View style={styles.card}>
      <View style={styles.header}>
        <Text style={styles.title}>Date mode</Text>
        <Pressable onPress={() => setOpen(false)} hitSlop={10}>
          <Text style={styles.caret}>▴</Text>
        </Pressable>
      </View>
      {OPTIONS.map((option) => {
        const active = option.mode === mode;
        return (
          <Pressable
            key={option.mode}
            style={styles.option}
            disabled={busy}
            onPress={() => {
              setOpen(false);
              if (!active) onChange(option.mode);
            }}
          >
            <Text style={[styles.radio, active && styles.radioActive]}>
              {active ? '◉' : '○'}
            </Text>
            <View style={styles.optionBody}>
              <Text style={[styles.optionLabel, active && styles.optionLabelActive]}>
                {option.label}
              </Text>
              {option.caption && <Text style={styles.caption}>{option.caption}</Text>}
            </View>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  chip: {
    flexDirection: 'row',
    alignItems: 'center',
    alignSelf: 'flex-start',
    gap: 6,
    backgroundColor: '#fff',
    borderRadius: 18,
    paddingVertical: 8,
    paddingHorizontal: 14,
    borderWidth: 1,
    borderColor: '#ddd',
    elevation: 2,
  },
  chipIcon: { fontSize: 13 },
  chipText: { fontWeight: '600', color: '#333', fontSize: 13 },
  caret: { color: '#999', fontSize: 12 },

  card: {
    backgroundColor: '#fff',
    borderRadius: 12,
    padding: 12,
    gap: 8,
    borderWidth: 1,
    borderColor: '#ddd',
    elevation: 2,
  },
  header: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  title: { fontSize: 13, fontWeight: '700', color: '#666', textTransform: 'uppercase' },
  option: { flexDirection: 'row', alignItems: 'flex-start', gap: 8 },
  radio: { fontSize: 16, color: '#999', lineHeight: 20 },
  radioActive: { color: '#1f6feb' },
  optionBody: { flex: 1, gap: 2 },
  optionLabel: { fontSize: 14, color: '#333' },
  optionLabelActive: { fontWeight: '700', color: '#1f6feb' },
  caption: { fontSize: 12, color: '#8a6d00' },
});
