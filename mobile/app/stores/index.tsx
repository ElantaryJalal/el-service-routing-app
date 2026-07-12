/**
 * Office view: the store catalog, A-Z, with a "Needs attributes" filter so
 * the office sees which markets are still missing their crowdsourced facts
 * (size / mall / parking). Rows open the per-store detail page.
 */
import { useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { router } from 'expo-router';

import { ApiError, api, type StoreRead } from '../../src/api/client';

type Load =
  | { state: 'loading' }
  | { state: 'ready'; stores: StoreRead[] }
  | { state: 'error'; message: string };

function attributeSummary(s: StoreRead): string {
  const parts: string[] = [];
  if (s.size) parts.push(s.size);
  if (s.in_mall !== null) parts.push(s.in_mall ? 'mall' : 'standalone');
  if (s.has_parking !== null) parts.push(s.has_parking ? 'parking' : 'no parking');
  return parts.join(' · ');
}

export default function StoresScreen() {
  const [needsOnly, setNeedsOnly] = useState(false);
  const [load, setLoad] = useState<Load>({ state: 'loading' });

  useEffect(() => {
    let alive = true;
    setLoad({ state: 'loading' });
    api
      .getStores(needsOnly ? true : undefined)
      .then((stores) => alive && setLoad({ state: 'ready', stores }))
      .catch((err) => {
        if (!alive) return;
        const message = err instanceof ApiError ? err.message : String(err);
        setLoad({ state: 'error', message });
      });
    return () => {
      alive = false;
    };
  }, [needsOnly]);

  return (
    <View style={styles.flex}>
      <View style={styles.header}>
        <Text style={styles.title}>Stores</Text>
        <Pressable
          style={[styles.filterChip, needsOnly && styles.filterChipActive]}
          onPress={() => setNeedsOnly((v) => !v)}
        >
          <Text
            style={[styles.filterText, needsOnly && styles.filterTextActive]}
          >
            Needs attributes
          </Text>
        </Pressable>
      </View>

      {load.state === 'loading' && (
        <View style={styles.centered}>
          <ActivityIndicator size="large" />
        </View>
      )}
      {load.state === 'error' && (
        <View style={styles.centered}>
          <Text style={styles.error}>{load.message}</Text>
        </View>
      )}
      {load.state === 'ready' && (
        <ScrollView contentContainerStyle={styles.list}>
          <Text style={styles.count}>
            {load.stores.length} store{load.stores.length === 1 ? '' : 's'}
            {needsOnly ? ' missing attributes' : ''}
          </Text>
          {load.stores.map((s) => (
            <Pressable
              key={s.id}
              style={styles.row}
              onPress={() => router.push(`/stores/${s.id}`)}
            >
              <View style={styles.flex}>
                <Text style={styles.name}>{s.name}</Text>
                <Text style={styles.address}>
                  {[s.street, [s.postal_code, s.city].filter(Boolean).join(' ')]
                    .filter(Boolean)
                    .join(', ')}
                </Text>
              </View>
              {s.attributes_complete ? (
                <Text style={styles.summary}>{attributeSummary(s)}</Text>
              ) : (
                <View style={styles.needsBadge}>
                  <Text style={styles.needsBadgeText}>needs attributes</Text>
                </View>
              )}
            </Pressable>
          ))}
        </ScrollView>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  centered: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24 },
  error: { color: '#b00020', fontSize: 15, textAlign: 'center' },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: 16,
    gap: 12,
  },
  title: { fontSize: 24, fontWeight: '700' },
  filterChip: {
    borderRadius: 18,
    paddingVertical: 8,
    paddingHorizontal: 14,
    borderWidth: 1,
    borderColor: '#ddd',
    backgroundColor: '#fff',
  },
  filterChipActive: { backgroundColor: '#b45309', borderColor: '#b45309' },
  filterText: { fontWeight: '600', color: '#333', fontSize: 13 },
  filterTextActive: { color: '#fff' },
  list: { paddingHorizontal: 16, paddingBottom: 24 },
  count: { color: '#777', fontSize: 13, marginBottom: 8 },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#eee',
  },
  name: { fontSize: 16, fontWeight: '600' },
  address: { fontSize: 13, color: '#777', marginTop: 2 },
  summary: { fontSize: 12, color: '#1a7f37', fontWeight: '600' },
  needsBadge: {
    backgroundColor: '#fff8e8',
    borderColor: '#f0b429',
    borderWidth: 1,
    borderRadius: 8,
    paddingVertical: 4,
    paddingHorizontal: 8,
  },
  needsBadgeText: { color: '#8a6d00', fontSize: 12, fontWeight: '600' },
});
