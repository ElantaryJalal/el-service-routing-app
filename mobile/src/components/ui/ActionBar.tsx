/** Thumb-reachable bottom bar for THE primary action of a screen (plus at
 * most one quiet secondary beside it). Sits above the safe area. */

import { StyleSheet, View, type ViewStyle } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { color, space } from '../../theme';

export default function ActionBar({
  children,
  style,
}: {
  children: React.ReactNode;
  style?: ViewStyle;
}) {
  const insets = useSafeAreaInsets();
  return (
    <View style={[styles.bar, { paddingBottom: space.s3 + insets.bottom }, style]}>
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  bar: {
    flexDirection: 'row',
    gap: space.s3,
    paddingHorizontal: space.s4,
    paddingTop: space.s3,
    backgroundColor: color.surface,
    borderTopWidth: 1,
    borderTopColor: color.border,
  },
});
