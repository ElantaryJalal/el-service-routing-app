/**
 * Bottom-sheet shell shared by the Map screens' sheets. On web it renders an
 * absolute overlay INSIDE the map view so the sheet stays within the app frame
 * (an RN Modal portals to a full-window fixed layer and would spill past the
 * mobile frame). On native it keeps the platform Modal (there is no frame — the
 * app owns the whole screen — and Modal handles the Android back button).
 *
 * Children are the sheet card; it renders above the backdrop, so tapping the
 * card does nothing while tapping the dimmed backdrop closes the sheet.
 */
import type { ReactNode } from 'react';
import { Modal, Platform, Pressable, StyleSheet, View } from 'react-native';

import { color as tk } from '../theme';

export function SheetShell({
  onClose,
  children,
}: {
  onClose: () => void;
  children: ReactNode;
}) {
  const content = (
    <>
      <Pressable style={styles.backdrop} onPress={onClose} accessibilityLabel="Dismiss" />
      {children}
    </>
  );

  if (Platform.OS === 'web') {
    return <View style={styles.overlayWeb}>{content}</View>;
  }
  return (
    <Modal visible transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.overlayNative}>{content}</View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlayWeb: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    justifyContent: 'flex-end',
    zIndex: 2000,
  },
  overlayNative: { flex: 1, justifyContent: 'flex-end' },
  backdrop: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: tk.scrim,
  },
});
