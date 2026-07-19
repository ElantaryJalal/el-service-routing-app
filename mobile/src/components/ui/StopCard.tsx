/** Big tappable stop/tour row: sequence marker, unmistakable status, minimal
 * secondary chrome. */

import { Pressable, StyleSheet, Text, View } from 'react-native';

import { color, font, radius, shadow, size, space } from '../../theme';
import StatusChip, { type Status } from './StatusChip';

export default function StopCard({
  title,
  subtitle,
  status,
  statusLabel,
  /** Sequence circle content (e.g. stop order); colored with `accent`. */
  seq,
  /** Circle color — usually dayColor(dayIndex); defaults to brand. */
  accent = color.brand,
  onPress,
  children,
}: {
  title: string;
  subtitle?: string;
  status?: Status;
  statusLabel?: string;
  seq?: string | number;
  accent?: string;
  onPress?: () => void;
  children?: React.ReactNode;
}) {
  return (
    <Pressable
      accessibilityRole={onPress ? 'button' : undefined}
      onPress={onPress}
      style={({ pressed }) => [styles.card, pressed && onPress && styles.pressed]}
    >
      {seq !== undefined && (
        <View style={[styles.seq, { backgroundColor: accent }]}>
          <Text style={styles.seqText}>{seq}</Text>
        </View>
      )}
      <View style={styles.body}>
        <Text style={styles.title} numberOfLines={2}>
          {title}
        </Text>
        {subtitle ? (
          <Text style={styles.subtitle} numberOfLines={2}>
            {subtitle}
          </Text>
        ) : null}
        {children}
      </View>
      {status && <StatusChip status={status} label={statusLabel} />}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: {
    minHeight: size.touch + space.s3,
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.s3,
    backgroundColor: color.surface,
    borderWidth: 1,
    borderColor: color.border,
    borderRadius: radius.md,
    paddingHorizontal: space.s4,
    paddingVertical: space.s3,
    marginBottom: space.s2,
    ...shadow.sm,
  },
  pressed: { backgroundColor: color.bg },
  seq: {
    width: space.s8,
    height: space.s8,
    borderRadius: radius.full,
    alignItems: 'center',
    justifyContent: 'center',
  },
  seqText: { color: color.onBrand, fontWeight: font.weight.bold, fontSize: font.size.md },
  body: { flex: 1, gap: space.s1 },
  title: { fontSize: font.size.md, fontWeight: font.weight.bold, color: color.text },
  subtitle: { fontSize: font.size.sm, color: color.textMuted },
});
