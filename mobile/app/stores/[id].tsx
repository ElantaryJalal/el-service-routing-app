/**
 * Office view: everything captured about one store.
 * - Attributes (size / mall / parking) with audit line and inline edit.
 * - Visit history: predicted ETA vs actual completion and the drift delta.
 * - Feedback log with tag-frequency summary and a recurring-issues callout.
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
import { useLocalSearchParams } from 'expo-router';

import {
  ApiError,
  api,
  type FeedbackRead,
  type StoreRead,
  type StoreVisit,
} from '../../src/api/client';
import { FeedbackEntry, formatWhen } from '../../src/components/FeedbackEntry';
import { tagLabel } from '../../src/domain/feedbackTags';

type StoreSize = 'small' | 'medium' | 'large';

const SIZES: StoreSize[] = ['small', 'medium', 'large'];

function formatDate(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(`${iso}T00:00:00`);
  return `${String(d.getDate()).padStart(2, '0')}.${String(d.getMonth() + 1).padStart(2, '0')}.`;
}

/**
 * Wall-clock minutes for the two timestamps. The optimiser's ETAs use a
 * "UTC as local clock" convention (09:30Z means 09:30 on site), while
 * completed_at is a real instant — so read ETA with UTC getters and
 * completed_at with local ones before comparing.
 */
function etaMinutes(iso: string | null): number | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d.getUTCHours() * 60 + d.getUTCMinutes();
}

function completedMinutes(iso: string | null): number | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d.getHours() * 60 + d.getMinutes();
}

const toHHMM = (mins: number | null): string =>
  mins === null
    ? '—'
    : `${String(Math.floor(mins / 60)).padStart(2, '0')}:${String(mins % 60).padStart(2, '0')}`;

export default function StoreDetailScreen() {
  const params = useLocalSearchParams<{ id?: string }>();
  const storeId = Number(params.id);

  const [store, setStore] = useState<StoreRead | null>(null);
  const [visits, setVisits] = useState<StoreVisit[] | null>(null);
  const [feedback, setFeedback] = useState<FeedbackRead[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Staged attribute edits (initialised from the store, saved via PATCH).
  const [size, setSize] = useState<StoreSize | null>(null);
  const [inMall, setInMall] = useState<boolean | null>(null);
  const [hasParking, setHasParking] = useState<boolean | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    if (!Number.isFinite(storeId)) {
      setError('Missing store id.');
      return;
    }
    let alive = true;
    Promise.all([
      api.getStore(storeId),
      api.getStoreVisits(storeId),
      api.getStoreFeedback(storeId),
    ])
      .then(([s, v, f]) => {
        if (!alive) return;
        setStore(s);
        setSize((s.size as StoreSize | null) ?? null);
        setInMall(s.in_mall);
        setHasParking(s.has_parking);
        setVisits(v);
        setFeedback(f);
      })
      .catch((err) => {
        if (alive) setError(err instanceof ApiError ? err.message : String(err));
      });
    return () => {
      alive = false;
    };
  }, [storeId]);

  const dirty =
    store !== null &&
    (size !== (store.size ?? null) ||
      inMall !== store.in_mall ||
      hasParking !== store.has_parking);

  async function saveAttributes() {
    if (!store || !dirty) return;
    setSaving(true);
    setSaveError(null);
    try {
      const updated = await api.patchStoreAttributes(store.id, {
        size,
        in_mall: inMall,
        has_parking: hasParking,
        updated_by: 'Office',
      });
      setStore(updated);
      setSize((updated.size as StoreSize | null) ?? null);
      setInMall(updated.in_mall);
      setHasParking(updated.has_parking);
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  // Tag frequency across all feedback, most frequent first.
  const tagCounts = (feedback ?? []).reduce((acc, row) => {
    for (const t of row.tags) acc.set(t, (acc.get(t) ?? 0) + 1);
    return acc;
  }, new Map<string, number>());
  const tagSummary = [...tagCounts.entries()].sort((a, b) => b[1] - a[1]);
  const recurring = tagSummary.filter(([, n]) => n >= 3);

  if (error) {
    return (
      <View style={styles.centered}>
        <Text style={styles.error}>{error}</Text>
      </View>
    );
  }
  if (!store || visits === null || feedback === null) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator size="large" />
      </View>
    );
  }

  return (
    <ScrollView contentContainerStyle={styles.page}>
      <Text style={styles.title}>{store.name}</Text>
      <Text style={styles.address}>
        {[store.street, [store.postal_code, store.city].filter(Boolean).join(' ')]
          .filter(Boolean)
          .join(', ')}
      </Text>

      {/* --- Attributes ------------------------------------------------- */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>Store facts</Text>

        <Text style={styles.fieldLabel}>Size</Text>
        <View style={styles.optionRow}>
          {SIZES.map((v) => (
            <Option
              key={v}
              label={v[0].toUpperCase() + v.slice(1)}
              active={size === v}
              onPress={() => setSize(size === v ? null : v)}
            />
          ))}
        </View>

        <Text style={styles.fieldLabel}>In a mall/center?</Text>
        <View style={styles.optionRow}>
          <Option label="Yes" active={inMall === true} onPress={() => setInMall(inMall === true ? null : true)} />
          <Option label="No" active={inMall === false} onPress={() => setInMall(inMall === false ? null : false)} />
        </View>

        <Text style={styles.fieldLabel}>Parking?</Text>
        <View style={styles.optionRow}>
          <Option label="Yes" active={hasParking === true} onPress={() => setHasParking(hasParking === true ? null : true)} />
          <Option label="No" active={hasParking === false} onPress={() => setHasParking(hasParking === false ? null : false)} />
        </View>

        {saveError && <Text style={styles.error}>{saveError}</Text>}
        <View style={styles.attrFooter}>
          <Text style={styles.audit}>
            {store.attributes_updated_at
              ? `Updated ${formatWhen(store.attributes_updated_at)}${store.attributes_updated_by ? ` by ${store.attributes_updated_by}` : ''}`
              : 'Not captured yet'}
          </Text>
          <Pressable
            style={[styles.saveButton, (!dirty || saving) && styles.disabled]}
            disabled={!dirty || saving}
            onPress={saveAttributes}
          >
            {saving ? (
              <ActivityIndicator size="small" color="#fff" />
            ) : (
              <Text style={styles.saveButtonText}>Save</Text>
            )}
          </Pressable>
        </View>
      </View>

      {/* --- Visit history ---------------------------------------------- */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>Visit history</Text>
        {visits.length === 0 && <Text style={styles.muted}>No visits yet.</Text>}
        {visits.length > 0 && (
          <View>
            <View style={[styles.visitRow, styles.visitHeader]}>
              <Text style={[styles.visitCell, styles.visitHead]}>Date</Text>
              <Text style={[styles.visitCellWide, styles.visitHead]}>Employee</Text>
              <Text style={[styles.visitCell, styles.visitHead]}>ETA</Text>
              <Text style={[styles.visitCell, styles.visitHead]}>Done</Text>
              <Text style={[styles.visitCell, styles.visitHead]}>Δ</Text>
            </View>
            {visits.map((v) => {
              const eta = etaMinutes(v.eta);
              const done = completedMinutes(v.completed_at);
              const delta = eta !== null && done !== null ? done - eta : null;
              return (
                <View key={v.stop_id} style={styles.visitRow}>
                  <Text style={styles.visitCell}>
                    {formatDate(v.date)} KW{v.calendar_week}
                  </Text>
                  <Text style={styles.visitCellWide} numberOfLines={1}>
                    {v.employee ?? '—'}
                  </Text>
                  <Text style={styles.visitCell}>{toHHMM(eta)}</Text>
                  <Text style={styles.visitCell}>{toHHMM(done)}</Text>
                  <Text
                    style={[
                      styles.visitCell,
                      styles.delta,
                      delta !== null && delta > 0 && styles.deltaLate,
                      delta !== null && delta <= 0 && styles.deltaEarly,
                    ]}
                  >
                    {delta === null ? '—' : `${delta > 0 ? '+' : ''}${delta} min`}
                  </Text>
                </View>
              );
            })}
          </View>
        )}
      </View>

      {/* --- Feedback ---------------------------------------------------- */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>Feedback</Text>

        {recurring.length > 0 && (
          <View style={styles.recurring}>
            <Text style={styles.recurringText}>
              ⚠︎ Recurring issue{recurring.length === 1 ? '' : 's'}:{' '}
              {recurring
                .map(([t, n]) => `${tagLabel(t)} reported ${n}×`)
                .join(', ')}
            </Text>
          </View>
        )}

        {tagSummary.length > 0 && (
          <View style={styles.tagSummary}>
            {tagSummary.map(([t, n]) => (
              <View key={t} style={styles.summaryChip}>
                <Text style={styles.summaryChipText}>
                  {tagLabel(t)} ×{n}
                </Text>
              </View>
            ))}
          </View>
        )}

        {feedback.length === 0 && (
          <Text style={styles.muted}>No feedback for this market yet.</Text>
        )}
        {feedback.map((row) => (
          <FeedbackEntry key={row.id} row={row} />
        ))}
      </View>
    </ScrollView>
  );
}

function Option({
  label,
  active,
  onPress,
}: {
  label: string;
  active: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable style={[styles.option, active && styles.optionActive]} onPress={onPress}>
      <Text style={[styles.optionText, active && styles.optionTextActive]}>
        {label}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  centered: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24 },
  page: { padding: 16, gap: 14, maxWidth: 760, width: '100%', alignSelf: 'center' },
  title: { fontSize: 24, fontWeight: '700' },
  address: { fontSize: 14, color: '#666' },
  error: { color: '#b00020', fontSize: 14 },
  muted: { color: '#777', fontSize: 14 },

  card: {
    backgroundColor: '#f7f9fc',
    borderRadius: 12,
    padding: 16,
    gap: 8,
  },
  cardTitle: { fontSize: 16, fontWeight: '700', marginBottom: 4 },

  fieldLabel: { fontSize: 13, fontWeight: '600', color: '#444', marginTop: 4 },
  optionRow: { flexDirection: 'row', gap: 8 },
  option: {
    backgroundColor: '#fff',
    borderRadius: 16,
    paddingVertical: 8,
    paddingHorizontal: 16,
    borderWidth: 1,
    borderColor: '#ccc',
  },
  optionActive: { backgroundColor: '#1f6feb', borderColor: '#1f6feb' },
  optionText: { fontWeight: '600', color: '#333', fontSize: 14 },
  optionTextActive: { color: '#fff' },
  attrFooter: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: 6,
    gap: 10,
  },
  audit: { fontSize: 12, color: '#777', flex: 1 },
  saveButton: {
    backgroundColor: '#1f6feb',
    borderRadius: 8,
    paddingVertical: 10,
    paddingHorizontal: 24,
    alignItems: 'center',
    minWidth: 90,
  },
  saveButtonText: { color: '#fff', fontWeight: '700', fontSize: 15 },
  disabled: { opacity: 0.45 },

  visitRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: '#e6eaf0',
    gap: 6,
  },
  visitHeader: { borderBottomColor: '#c9d2de' },
  visitHead: { fontWeight: '700', color: '#555' },
  visitCell: { flex: 1, fontSize: 13, color: '#222' },
  visitCellWide: { flex: 1.4, fontSize: 13, color: '#222' },
  delta: { fontWeight: '700' },
  deltaLate: { color: '#b00020' },
  deltaEarly: { color: '#1a7f37' },

  recurring: {
    backgroundColor: '#fff8e8',
    borderColor: '#f0b429',
    borderWidth: 1,
    borderRadius: 10,
    padding: 10,
  },
  recurringText: { color: '#8a6d00', fontWeight: '600', fontSize: 13 },
  tagSummary: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  summaryChip: {
    backgroundColor: '#eef2f7',
    borderRadius: 12,
    paddingVertical: 4,
    paddingHorizontal: 10,
  },
  summaryChipText: { fontSize: 12, color: '#334', fontWeight: '700' },
});
