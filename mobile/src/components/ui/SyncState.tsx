/** Always-visible answer to "did my tap save?" — pending / synced / offline. */

import { StyleSheet, Text, View } from 'react-native';

import { color, font, radius, space } from '../../theme';

export type SyncStateKind = 'pending' | 'synced' | 'offline';

const STYLE: Record<SyncStateKind, { dot: string; bg: string; text: string; label: string }> = {
  pending: {
    dot: color.warning,
    bg: color.warningBg,
    text: color.warningText,
    label: 'Saved on this phone — will sync',
  },
  synced: {
    dot: color.success,
    bg: color.successBg,
    text: color.successText,
    label: 'Synced',
  },
  offline: {
    dot: color.status.draft,
    bg: color.status.draftSoft,
    text: color.text,
    label: 'Offline — changes are queued',
  },
};

export default function SyncState({
  state,
  label,
}: {
  state: SyncStateKind;
  label?: string;
}) {
  const s = STYLE[state];
  return (
    <View style={[styles.pill, { backgroundColor: s.bg }]}>
      <View style={[styles.dot, { backgroundColor: s.dot }]} />
      <Text style={[styles.label, { color: s.text }]}>{label ?? s.label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  pill: {
    flexDirection: 'row',
    alignItems: 'center',
    alignSelf: 'flex-start',
    gap: space.s2,
    paddingHorizontal: space.s3,
    paddingVertical: space.s1,
    borderRadius: radius.full,
  },
  dot: { width: space.s2, height: space.s2, borderRadius: radius.full },
  label: { fontSize: font.size.sm, fontWeight: font.weight.semibold },
});
