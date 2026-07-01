import { useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { Link } from 'expo-router';

import { API_BASE_URL } from '../src/api/config';
import { ApiError, api } from '../src/api/client';

type Probe =
  | { state: 'idle' }
  | { state: 'loading' }
  | { state: 'ok'; body: Record<string, string> }
  | { state: 'error'; message: string };

export default function CaptureScreen() {
  const [probe, setProbe] = useState<Probe>({ state: 'idle' });

  async function testConnection() {
    setProbe({ state: 'loading' });
    try {
      const body = await api.health();
      setProbe({ state: 'ok', body });
    } catch (err) {
      const message = err instanceof ApiError ? err.message : String(err);
      setProbe({ state: 'error', message });
    }
  }

  return (
    <ScrollView contentContainerStyle={styles.container}>
      <Text style={styles.title}>Capture</Text>
      <Text style={styles.subtitle}>Photograph the paper tour plan (coming soon).</Text>

      {/* Temporary end-to-end wiring check — keep until M2. */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>Backend connection</Text>
        <Text style={styles.mono}>{API_BASE_URL}</Text>
        <Pressable
          style={styles.button}
          onPress={testConnection}
          disabled={probe.state === 'loading'}
        >
          <Text style={styles.buttonText}>Test connection</Text>
        </Pressable>
        {probe.state === 'loading' && <ActivityIndicator style={styles.spacer} />}
        {probe.state === 'ok' && (
          <Text style={[styles.result, styles.ok]}>
            OK — {JSON.stringify(probe.body)}
          </Text>
        )}
        {probe.state === 'error' && (
          <Text style={[styles.result, styles.error]}>{probe.message}</Text>
        )}
      </View>

      <View style={styles.nav}>
        <Link href="/confirm" style={styles.link}>
          → Confirm
        </Link>
        <Link href="/review" style={styles.link}>
          → Review
        </Link>
        <Link href="/map" style={styles.link}>
          → Map
        </Link>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { padding: 20, gap: 16 },
  title: { fontSize: 28, fontWeight: '700' },
  subtitle: { fontSize: 15, color: '#555' },
  card: {
    borderWidth: 1,
    borderColor: '#ddd',
    borderRadius: 12,
    padding: 16,
    gap: 10,
  },
  cardTitle: { fontSize: 16, fontWeight: '600' },
  mono: { fontFamily: 'monospace', color: '#333' },
  button: {
    backgroundColor: '#1f6feb',
    paddingVertical: 12,
    borderRadius: 8,
    alignItems: 'center',
  },
  buttonText: { color: '#fff', fontWeight: '600' },
  spacer: { marginTop: 4 },
  result: { fontSize: 14 },
  ok: { color: '#137333' },
  error: { color: '#b00020' },
  nav: { gap: 8, marginTop: 8 },
  link: { fontSize: 16, color: '#1f6feb' },
});
