/** Field-app text input: glove-sized target, label + error state. */

import {
  StyleSheet,
  Text,
  TextInput,
  View,
  type TextInputProps,
} from 'react-native';

import { color, font, radius, size, space } from '../../theme';

export default function Input({
  label,
  error,
  style,
  ...rest
}: TextInputProps & { label?: string; error?: string }) {
  return (
    <View style={styles.field}>
      {label ? <Text style={styles.label}>{label}</Text> : null}
      <TextInput
        placeholderTextColor={color.textFaint}
        {...rest}
        style={[styles.input, error != null && styles.inputError, style]}
      />
      {error ? <Text style={styles.error}>{error}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  field: { gap: space.s1, marginBottom: space.s3 },
  label: {
    fontSize: font.size.sm,
    fontWeight: font.weight.semibold,
    color: color.textMuted,
  },
  input: {
    minHeight: size.touch,
    fontSize: font.size.md,
    paddingHorizontal: space.s3,
    paddingVertical: space.s2,
    borderWidth: 1,
    borderColor: color.borderStrong,
    borderRadius: radius.sm,
    backgroundColor: color.surface,
    color: color.text,
  },
  inputError: { borderColor: color.danger },
  error: { fontSize: font.size.sm, color: color.dangerText },
});
