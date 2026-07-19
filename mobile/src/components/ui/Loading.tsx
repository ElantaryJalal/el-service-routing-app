import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';

import { color, font, space } from '../../theme';

export default function Loading({ label }: { label?: string }) {
  return (
    <View style={styles.wrap} accessibilityRole="progressbar">
      <ActivityIndicator size="large" color={color.brand} />
      {label ? <Text style={styles.label}>{label}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { alignItems: 'center', padding: space.s8, gap: space.s3 },
  label: { fontSize: font.size.sm, color: color.textMuted },
});
