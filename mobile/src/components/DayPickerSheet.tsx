/**
 * Bottom-sheet day picker shared by the Map screens' two plan-editing flows:
 * "re-plan the rest of the week from day X" and "move this stop to day Y /
 * take it off the plan". Pure presentation — the caller runs the API call
 * and keeps `busy` true for the round-trip.
 */
import { ActivityIndicator, Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

export interface DayOption {
  /** ISO date to pick, or null for the destructive "off the plan" row. */
  value: string | null;
  label: string;
  caption?: string;
  destructive?: boolean;
}

export function DayPickerSheet({
  title,
  message,
  options,
  busy,
  onSelect,
  onClose,
}: {
  title: string;
  message: string;
  options: DayOption[];
  busy: boolean;
  onSelect: (value: string | null) => void;
  onClose: () => void;
}) {
  return (
    <Modal visible transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.backdrop}>
        <View style={styles.card}>
          <View style={styles.header}>
            <Text style={styles.title}>{title}</Text>
            <Pressable onPress={onClose} hitSlop={10} disabled={busy}>
              <Text style={styles.close}>✕</Text>
            </Pressable>
          </View>
          <Text style={styles.message}>{message}</Text>

          {busy ? (
            <View style={styles.busyRow}>
              <ActivityIndicator size="small" color="#1f6feb" />
              <Text style={styles.busyText}>Updating the plan…</Text>
            </View>
          ) : (
            <ScrollView style={styles.list}>
              {options.map((option) => (
                <Pressable
                  key={option.value ?? 'none'}
                  style={styles.option}
                  onPress={() => onSelect(option.value)}
                >
                  <Text
                    style={[
                      styles.optionLabel,
                      option.destructive && styles.optionDestructive,
                    ]}
                  >
                    {option.label}
                  </Text>
                  {option.caption && (
                    <Text style={styles.optionCaption}>{option.caption}</Text>
                  )}
                </Pressable>
              ))}
            </ScrollView>
          )}
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: '#00000088', justifyContent: 'flex-end' },
  card: {
    backgroundColor: '#fff',
    borderTopLeftRadius: 16,
    borderTopRightRadius: 16,
    padding: 20,
    gap: 10,
    maxHeight: '70%',
  },
  header: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  title: { fontSize: 18, fontWeight: '700', flex: 1 },
  close: { fontSize: 18, color: '#999', paddingHorizontal: 4 },
  message: { fontSize: 13, color: '#666' },
  list: { flexGrow: 0 },
  option: {
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#eee',
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 8,
  },
  optionLabel: { fontSize: 15, fontWeight: '600', color: '#1f6feb' },
  optionDestructive: { color: '#b00020' },
  optionCaption: { fontSize: 12, color: '#999' },
  busyRow: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingVertical: 16 },
  busyText: { fontSize: 14, color: '#555' },
});
