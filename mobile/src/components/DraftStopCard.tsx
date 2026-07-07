import { useState } from 'react';
import { StyleSheet, Text, TextInput, View } from 'react-native';

import {
  SERVICE_MINUTES_DEFAULT,
  SERVICE_MINUTES_MAX,
  SERVICE_MINUTES_MIN,
  type DraftConfidence,
  type DraftStop,
  type DraftStopUpdate,
} from '../api/client';

const LOW_CONFIDENCE = 0.6;

function isLow(confidence: DraftConfidence, field: keyof DraftConfidence): boolean {
  const c = confidence[field];
  return typeof c === 'number' && c < LOW_CONFIDENCE;
}

function clampMinutes(raw: string): number {
  const n = parseInt(raw.replace(/[^0-9]/g, ''), 10);
  if (Number.isNaN(n)) return SERVICE_MINUTES_DEFAULT;
  return Math.min(SERVICE_MINUTES_MAX, Math.max(SERVICE_MINUTES_MIN, n));
}

type TextField = 'street' | 'postal_code' | 'city' | 'order_no' | 'tasks';

interface Props {
  index: number;
  stop: DraftStop;
  /** Persist changed fields; resolves when saved (or rejects on failure). */
  onPatch: (fields: DraftStopUpdate) => Promise<void>;
}

export function DraftStopCard({ index, stop, onPatch }: Props) {
  // Local mirror so typing stays snappy; we persist on blur.
  const [values, setValues] = useState({
    street: stop.street ?? '',
    postal_code: stop.postal_code ?? '',
    city: stop.city ?? '',
    order_no: stop.order_no ?? '',
    tasks: stop.tasks ?? '',
    service_minutes: String(stop.service_minutes ?? SERVICE_MINUTES_DEFAULT),
  });

  function set(field: keyof typeof values, value: string) {
    setValues((v) => ({ ...v, [field]: value }));
  }

  /** Persist a text field on blur if it actually changed. */
  function commitText(field: TextField) {
    const next = values[field].trim();
    const prev = (stop[field] ?? '').trim();
    if (next === prev) return;
    onPatch({ [field]: next === '' ? null : next });
  }

  function commitMinutes() {
    const clamped = clampMinutes(values.service_minutes);
    set('service_minutes', String(clamped));
    if (clamped !== stop.service_minutes) onPatch({ service_minutes: clamped });
  }

  const row = (
    label: string,
    field: TextField,
    opts?: { placeholder?: string; keyboard?: 'default' | 'numeric'; multiline?: boolean },
  ) => (
    <View style={styles.field}>
      <Text style={styles.label}>{label}</Text>
      <TextInput
        style={[
          styles.input,
          opts?.multiline && styles.inputMultiline,
          isLow(stop.confidence, field) && styles.inputLow,
        ]}
        value={values[field]}
        placeholder={opts?.placeholder}
        placeholderTextColor="#aaa"
        keyboardType={opts?.keyboard ?? 'default'}
        multiline={opts?.multiline}
        onChangeText={(t) => set(field, t)}
        onEndEditing={() => commitText(field)}
      />
      {isLow(stop.confidence, field) && (
        <Text style={styles.lowHint}>Low confidence — please check</Text>
      )}
    </View>
  );

  return (
    <View style={styles.card}>
      <Text style={styles.cardTitle}>Stop {index + 1}</Text>

      {stop.remarks && (
        <View style={styles.remarksBox}>
          <Text style={styles.remarksLabel}>Remark on plan</Text>
          <Text style={styles.remarksText}>{stop.remarks}</Text>
        </View>
      )}

      {row('Street', 'street', { placeholder: 'Street and number' })}
      <View style={styles.pair}>
        <View style={styles.pairItem}>{row('Postal code', 'postal_code', { keyboard: 'numeric' })}</View>
        <View style={styles.pairItemWide}>{row('City', 'city')}</View>
      </View>
      {row('Order no.', 'order_no', { placeholder: 'e.g. 4711' })}
      {row('Tasks', 'tasks', { placeholder: 'What to do here', multiline: true })}

      {/* service_minutes: the main driver of the plan — kept prominent. */}
      <View style={styles.serviceBox}>
        <Text style={styles.serviceLabel}>How long this market takes</Text>
        <Text style={styles.serviceHelp}>
          Minutes on site ({SERVICE_MINUTES_MIN}–{SERVICE_MINUTES_MAX})
        </Text>
        <TextInput
          style={[
            styles.serviceInput,
            isLow(stop.confidence, 'service_minutes') && styles.inputLow,
          ]}
          value={values.service_minutes}
          keyboardType="numeric"
          onChangeText={(t) => set('service_minutes', t)}
          onEndEditing={commitMinutes}
        />
        {isLow(stop.confidence, 'service_minutes') && (
          <Text style={styles.lowHint}>Low confidence — please check</Text>
        )}
      </View>
    </View>
  );
}

const AMBER = '#f6a609';

const styles = StyleSheet.create({
  card: {
    borderWidth: 1,
    borderColor: '#e2e2e2',
    borderRadius: 12,
    padding: 16,
    gap: 10,
    backgroundColor: '#fff',
  },
  cardTitle: { fontSize: 15, fontWeight: '700', color: '#333' },
  remarksBox: {
    backgroundColor: '#fff8e8',
    borderLeftWidth: 3,
    borderLeftColor: AMBER,
    borderRadius: 6,
    paddingHorizontal: 10,
    paddingVertical: 6,
    gap: 2,
  },
  remarksLabel: { fontSize: 11, fontWeight: '700', color: '#b8860b', textTransform: 'uppercase' },
  remarksText: { fontSize: 14, color: '#5c4a12' },
  field: { gap: 4 },
  label: { fontSize: 13, color: '#666', fontWeight: '600' },
  input: {
    borderWidth: 1,
    borderColor: '#ccc',
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 10,
    fontSize: 15,
  },
  inputMultiline: { minHeight: 60, textAlignVertical: 'top' },
  inputLow: { borderColor: AMBER, backgroundColor: '#fff8e8' },
  lowHint: { fontSize: 12, color: '#b8860b' },
  pair: { flexDirection: 'row', gap: 10 },
  pairItem: { flex: 1 },
  pairItemWide: { flex: 2 },
  serviceBox: {
    borderWidth: 1,
    borderColor: '#1f6feb',
    backgroundColor: '#f0f6ff',
    borderRadius: 10,
    padding: 12,
    gap: 4,
    marginTop: 2,
  },
  serviceLabel: { fontSize: 15, fontWeight: '700', color: '#0b3d91' },
  serviceHelp: { fontSize: 12, color: '#3a5a8c' },
  serviceInput: {
    borderWidth: 1,
    borderColor: '#9bbcf0',
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 10,
    fontSize: 20,
    fontWeight: '700',
    backgroundColor: '#fff',
  },
});
