import { useState } from 'react';
import { StyleSheet, Text, TextInput, View } from 'react-native';

import type { StopDetail } from '../api/client';
import type { components } from '../api/types';

type StopUpdate = components['schemas']['StopUpdate'];

/** Trim a "HH:MM:SS" backend time to "HH:MM" for display. */
function toHHMM(time: string | null): string {
  if (!time) return '';
  const m = /^(\d{1,2}):(\d{2})/.exec(time);
  return m ? `${m[1].padStart(2, '0')}:${m[2]}` : time;
}

const SOURCE_LABEL: Record<StopDetail['hours_source'], { text: string; tone: 'osm' | 'manual' | 'none' }> = {
  osm: { text: 'from map data (check me)', tone: 'osm' },
  manual: { text: 'set by you', tone: 'manual' },
  default: { text: 'not set', tone: 'none' },
};

function addressLine(stop: StopDetail): string {
  return [stop.street, [stop.postal_code, stop.city].filter(Boolean).join(' ')]
    .filter(Boolean)
    .join(', ');
}

interface Props {
  stop: StopDetail;
  onPatch: (fields: StopUpdate) => Promise<void>;
}

export function ReviewStopCard({ stop, onPatch }: Props) {
  const [closing, setClosing] = useState(toHHMM(stop.closing_time));
  const [minutes, setMinutes] = useState(String(stop.service_minutes ?? ''));

  function commitClosing() {
    const text = closing.trim();
    if (text === '') {
      if (stop.closing_time) onPatch({ closing_time: null });
      return;
    }
    const m = /^(\d{1,2}):(\d{2})$/.exec(text);
    if (!m) {
      setClosing(toHHMM(stop.closing_time)); // revert unparseable input
      return;
    }
    const normalized = `${m[1].padStart(2, '0')}:${m[2]}`;
    setClosing(normalized);
    if (normalized !== toHHMM(stop.closing_time)) {
      onPatch({ closing_time: `${normalized}:00` });
    }
  }

  function commitMinutes() {
    const n = parseInt(minutes.replace(/[^0-9]/g, ''), 10);
    if (Number.isNaN(n)) {
      setMinutes(String(stop.service_minutes ?? ''));
      return;
    }
    setMinutes(String(n));
    if (n !== stop.service_minutes) onPatch({ service_minutes: n });
  }

  const source = SOURCE_LABEL[stop.hours_source];
  const addr = addressLine(stop);

  return (
    <View style={styles.card}>
      <Text style={styles.customer}>{stop.customer ?? `Stop ${stop.id}`}</Text>
      {addr ? <Text style={styles.address}>{addr}</Text> : null}

      <View style={styles.fields}>
        <View style={styles.field}>
          <View style={styles.labelRow}>
            <Text style={styles.label}>Closing time</Text>
            <View
              style={[
                styles.badge,
                source.tone === 'osm' && styles.badgeOsm,
                source.tone === 'manual' && styles.badgeManual,
              ]}
            >
              <Text
                style={[
                  styles.badgeText,
                  source.tone === 'osm' && styles.badgeTextOsm,
                  source.tone === 'manual' && styles.badgeTextManual,
                ]}
              >
                {source.text}
              </Text>
            </View>
          </View>
          <TextInput
            style={[styles.input, source.tone === 'osm' && styles.inputOsm]}
            value={closing}
            placeholder="HH:MM"
            placeholderTextColor="#aaa"
            keyboardType="numbers-and-punctuation"
            onChangeText={setClosing}
            onEndEditing={commitClosing}
          />
        </View>

        <View style={styles.fieldNarrow}>
          <Text style={styles.label}>Service (min)</Text>
          <TextInput
            style={styles.input}
            value={minutes}
            placeholder="min"
            placeholderTextColor="#aaa"
            keyboardType="numeric"
            onChangeText={setMinutes}
            onEndEditing={commitMinutes}
          />
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    borderWidth: 1,
    borderColor: '#e2e2e2',
    borderRadius: 12,
    padding: 14,
    gap: 6,
    backgroundColor: '#fff',
  },
  customer: { fontSize: 16, fontWeight: '700' },
  address: { fontSize: 13, color: '#666' },
  fields: { flexDirection: 'row', gap: 12, marginTop: 6 },
  field: { flex: 2, gap: 4 },
  fieldNarrow: { flex: 1, gap: 4 },
  labelRow: { flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap' },
  label: { fontSize: 13, color: '#666', fontWeight: '600' },
  input: {
    borderWidth: 1,
    borderColor: '#ccc',
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 10,
    fontSize: 16,
  },
  inputOsm: { borderColor: '#f6a609', backgroundColor: '#fff8e8' },
  badge: {
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 10,
    backgroundColor: '#eee',
  },
  badgeOsm: { backgroundColor: '#fff1cc' },
  badgeManual: { backgroundColor: '#e6f4ea' },
  badgeText: { fontSize: 11, color: '#777', fontWeight: '600' },
  badgeTextOsm: { color: '#8a6100' },
  badgeTextManual: { color: '#137333' },
});
