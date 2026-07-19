import { StyleSheet, Text, View } from 'react-native';

import { color, font, space } from '../../theme';

export default function EmptyState({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: string;
  /** Usually a secondary Button. */
  children?: React.ReactNode;
}) {
  return (
    <View style={styles.wrap}>
      <Text style={styles.title}>{title}</Text>
      {hint ? <Text style={styles.hint}>{hint}</Text> : null}
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { alignItems: 'center', padding: space.s12, gap: space.s2 },
  title: {
    fontSize: font.size.md,
    fontWeight: font.weight.semibold,
    color: color.text,
    textAlign: 'center',
  },
  hint: { fontSize: font.size.sm, color: color.textMuted, textAlign: 'center' },
});
