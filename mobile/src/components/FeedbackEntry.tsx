/** One visit-feedback entry (date, employee, tag chips, note, photo) —
 * shared by the mobile history sheet and the office store detail page. */
import { Image, StyleSheet, Text, View } from 'react-native';

import type { FeedbackRead } from '../api/client';
import { API_BASE_URL } from '../api/config';
import { tagLabel } from '../domain/feedbackTags';

export function formatWhen(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const dd = String(d.getDate()).padStart(2, '0');
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  return `${dd}.${mm}.${d.getFullYear()}`;
}

export function FeedbackEntry({ row }: { row: FeedbackRead }) {
  return (
    <View style={styles.entry}>
      <View style={styles.entryHeader}>
        <Text style={styles.when}>{formatWhen(row.created_at)}</Text>
        {row.employee && <Text style={styles.employee}>{row.employee}</Text>}
      </View>
      {row.tags.length > 0 && (
        <View style={styles.tagWrap}>
          {row.tags.map((t) => (
            <View key={t} style={styles.tag}>
              <Text style={styles.tagText}>{tagLabel(t)}</Text>
            </View>
          ))}
        </View>
      )}
      {row.note && <Text style={styles.note}>{row.note}</Text>}
      {row.photo_path && (
        <Image
          source={{ uri: `${API_BASE_URL}/${row.photo_path}` }}
          style={styles.photo}
          resizeMode="cover"
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  entry: {
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#eee',
    gap: 6,
  },
  entryHeader: { flexDirection: 'row', justifyContent: 'space-between' },
  when: { fontSize: 13, fontWeight: '700', color: '#444' },
  employee: { fontSize: 13, color: '#777' },
  tagWrap: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  tag: {
    backgroundColor: '#eef2f7',
    borderRadius: 12,
    paddingVertical: 3,
    paddingHorizontal: 10,
  },
  tagText: { fontSize: 12, color: '#334', fontWeight: '600' },
  note: { fontSize: 14, color: '#222' },
  photo: { width: '100%', height: 160, borderRadius: 8, backgroundColor: '#eee' },
});
