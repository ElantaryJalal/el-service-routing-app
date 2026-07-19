/** Field-app button: large touch targets, one primary action per screen. */

import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  type StyleProp,
  type ViewStyle,
} from 'react-native';

import { color, font, radius, size, space } from '../../theme';

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger';

export default function Button({
  title,
  onPress,
  variant = 'secondary',
  disabled = false,
  loading = false,
  style,
}: {
  title: string;
  onPress?: () => void;
  /** Defaults to secondary — a screen gets ONE primary action, in the ActionBar. */
  variant?: Variant;
  disabled?: boolean;
  loading?: boolean;
  style?: StyleProp<ViewStyle>;
}) {
  const blocked = disabled || loading;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled: blocked }}
      onPress={blocked ? undefined : onPress}
      style={({ pressed }) => [
        styles.base,
        variants[variant],
        pressed && !blocked && pressedStyles[variant],
        blocked && styles.disabled,
        style,
      ]}
    >
      {loading && (
        <ActivityIndicator
          size="small"
          color={variant === 'primary' ? color.onBrand : color.brand}
        />
      )}
      <Text style={[styles.label, labelStyles[variant]]}>{title}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  base: {
    minHeight: size.touch,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: space.s2,
    paddingHorizontal: space.s5,
    paddingVertical: space.s3,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: 'transparent',
  },
  label: { fontSize: font.size.md, fontWeight: font.weight.semibold },
  disabled: { opacity: 0.5 },
});

const variants = StyleSheet.create({
  primary: { backgroundColor: color.brand, borderColor: color.brand },
  secondary: { backgroundColor: color.surface, borderColor: color.borderStrong },
  ghost: { backgroundColor: 'transparent' },
  danger: { backgroundColor: color.surface, borderColor: color.dangerBorder },
});

const pressedStyles = StyleSheet.create({
  primary: { backgroundColor: color.brandHover },
  secondary: { backgroundColor: color.bg },
  ghost: { backgroundColor: color.brandSoft },
  danger: { backgroundColor: color.dangerBg },
});

const labelStyles = StyleSheet.create({
  primary: { color: color.onBrand },
  secondary: { color: color.text },
  ghost: { color: color.brand },
  danger: { color: color.danger },
});
