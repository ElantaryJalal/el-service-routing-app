/**
 * Bottom sheet shown when the crew marks a stop done. Three tiers:
 *
 * 1. Completion itself is already handled by the opener (local state +
 *    POST /stops/{id}/complete via the offline queue) — the sheet only
 *    reports whether it synced or is parked for later.
 * 2. If the stop's catalog store is missing crowdsourced attributes, a short
 *    form asks for size / mall / parking. Always skippable; completion never
 *    blocks on it — skipping leaves them null so the next visitor is asked.
 * 3. Optional visit feedback (tag chips + note), deduped offline-safely via
 *    client_uuid.
 */
import { useState } from 'react';
import {
  ActivityIndicator,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

import { api, type FeedbackTag } from '../api/client';
import type { OptimisedStop } from '../domain/optimisedTour';
import { uuidv4 } from '../domain/uuid';
import { mutationQueue } from '../state/mutationQueue';

/** How the tier-1 completion call went (owned by the opener). */
export type CompletionSync = 'pending' | 'done' | 'queued';

type StoreSize = 'small' | 'medium' | 'large';

const SIZES: { value: StoreSize; label: string }[] = [
  { value: 'small', label: 'Small' },
  { value: 'medium', label: 'Medium' },
  { value: 'large', label: 'Large' },
];

const TAGS: { value: FeedbackTag; label: string }[] = [
  { value: 'parking_full', label: 'Parking full' },
  { value: 'access_problem', label: 'Access problem' },
  { value: 'took_longer', label: 'Took longer' },
  { value: 'store_condition', label: 'Store condition' },
  { value: 'other', label: 'Other' },
];

export function CompletionSheet({
  stop,
  sync,
  onClose,
  onAttributesSaved,
}: {
  stop: OptimisedStop;
  sync: CompletionSync;
  onClose: () => void;
  /** Called after a successful attribute save so the screen can stop asking. */
  onAttributesSaved: (storeId: number) => void;
}) {
  // --- Tier 2 state ---
  const askAttributes =
    stop.store_id !== null && stop.store_attributes_complete === false;
  const [attrPhase, setAttrPhase] = useState<'form' | 'saving' | 'saved' | 'skipped'>(
    'form',
  );
  const [attrError, setAttrError] = useState<string | null>(null);
  const [size, setSize] = useState<StoreSize | null>(null);
  const [inMall, setInMall] = useState<boolean | null>(null);
  const [hasParking, setHasParking] = useState<boolean | null>(null);

  // --- Tier 3 state ---
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const [tags, setTags] = useState<FeedbackTag[]>([]);
  const [note, setNote] = useState('');
  const [feedbackPhase, setFeedbackPhase] = useState<
    'idle' | 'sending' | 'sent' | 'queued'
  >('idle');
  const [feedbackError, setFeedbackError] = useState<string | null>(null);

  async function saveAttributes() {
    if (stop.store_id === null) return;
    setAttrPhase('saving');
    setAttrError(null);
    try {
      await api.patchStoreAttributes(stop.store_id, {
        ...(size !== null && { size }),
        ...(inMall !== null && { in_mall: inMall }),
        ...(hasParking !== null && { has_parking: hasParking }),
      });
      setAttrPhase('saved');
      onAttributesSaved(stop.store_id);
    } catch {
      // Never block completion on this form: offer retry, keep Skip working.
      setAttrPhase('form');
      setAttrError('Could not save — try again or skip.');
    }
  }

  async function sendFeedback() {
    setFeedbackPhase('sending');
    setFeedbackError(null);
    try {
      const outcome = await mutationQueue.run({
        kind: 'feedback',
        payload: {
          stop_id: stop.stop_id,
          client_uuid: uuidv4(),
          tags,
          note: note.trim() || null,
        },
      });
      setFeedbackPhase(outcome === 'done' ? 'sent' : 'queued');
    } catch {
      setFeedbackPhase('idle');
      setFeedbackError('Could not send feedback.');
    }
  }

  const attrDirty = size !== null || inMall !== null || hasParking !== null;
  const feedbackDirty = tags.length > 0 || note.trim().length > 0;

  return (
    <Modal visible transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.backdrop}>
        <View style={styles.sheet}>
          <ScrollView contentContainerStyle={styles.content}>
            {/* Tier 1: completion status */}
            <View style={styles.header}>
              <View style={styles.flex}>
                <Text style={styles.title}>
                  ✓ {stop.customer ?? `Stop ${stop.stop_id}`}
                </Text>
                <Text style={styles.syncText}>
                  {sync === 'queued'
                    ? 'Saved on this phone — will sync when online.'
                    : sync === 'pending'
                      ? 'Marking done…'
                      : 'Marked done.'}
                </Text>
              </View>
              <Pressable onPress={onClose} hitSlop={10}>
                <Text style={styles.close}>✕</Text>
              </Pressable>
            </View>

            {/* Tier 2: store attributes (only while missing; always skippable) */}
            {askAttributes && attrPhase !== 'skipped' && attrPhase !== 'saved' && (
              <View style={styles.section}>
                <Text style={styles.sectionTitle}>Quick store info</Text>
                <Text style={styles.sectionHint}>
                  One-time questions about this market — you can skip.
                </Text>

                <Text style={styles.fieldLabel}>Size</Text>
                <View style={styles.optionRow}>
                  {SIZES.map((o) => (
                    <OptionButton
                      key={o.value}
                      label={o.label}
                      active={size === o.value}
                      onPress={() => setSize(size === o.value ? null : o.value)}
                    />
                  ))}
                </View>

                <Text style={styles.fieldLabel}>In a mall/center?</Text>
                <View style={styles.optionRow}>
                  <OptionButton
                    label="Yes"
                    active={inMall === true}
                    onPress={() => setInMall(inMall === true ? null : true)}
                  />
                  <OptionButton
                    label="No"
                    active={inMall === false}
                    onPress={() => setInMall(inMall === false ? null : false)}
                  />
                </View>

                <Text style={styles.fieldLabel}>Parking?</Text>
                <View style={styles.optionRow}>
                  <OptionButton
                    label="Yes"
                    active={hasParking === true}
                    onPress={() => setHasParking(hasParking === true ? null : true)}
                  />
                  <OptionButton
                    label="No"
                    active={hasParking === false}
                    onPress={() => setHasParking(hasParking === false ? null : false)}
                  />
                </View>

                {attrError && <Text style={styles.error}>{attrError}</Text>}

                <View style={styles.actionRow}>
                  <Pressable
                    style={[styles.primary, (!attrDirty || attrPhase === 'saving') && styles.disabled]}
                    disabled={!attrDirty || attrPhase === 'saving'}
                    onPress={saveAttributes}
                  >
                    {attrPhase === 'saving' ? (
                      <ActivityIndicator size="small" color="#fff" />
                    ) : (
                      <Text style={styles.primaryText}>Save</Text>
                    )}
                  </Pressable>
                  <Pressable
                    style={styles.secondary}
                    onPress={() => setAttrPhase('skipped')}
                  >
                    <Text style={styles.secondaryText}>Skip</Text>
                  </Pressable>
                </View>
              </View>
            )}
            {attrPhase === 'saved' && (
              <Text style={styles.savedNote}>Store info saved — thanks!</Text>
            )}

            {/* Tier 3: optional visit feedback */}
            {feedbackPhase === 'sent' || feedbackPhase === 'queued' ? (
              <Text style={styles.savedNote}>
                {feedbackPhase === 'sent'
                  ? 'Feedback saved — thanks!'
                  : 'Feedback saved — will sync when online.'}
              </Text>
            ) : !feedbackOpen ? (
              <Pressable style={styles.feedbackToggle} onPress={() => setFeedbackOpen(true)}>
                <Text style={styles.feedbackToggleText}>
                  Add feedback about this visit ▸
                </Text>
              </Pressable>
            ) : (
              <View style={styles.section}>
                <Text style={styles.sectionTitle}>Feedback about this visit</Text>
                <View style={styles.tagWrap}>
                  {TAGS.map((t) => {
                    const active = tags.includes(t.value);
                    return (
                      <OptionButton
                        key={t.value}
                        label={t.label}
                        active={active}
                        onPress={() =>
                          setTags(
                            active
                              ? tags.filter((x) => x !== t.value)
                              : [...tags, t.value],
                          )
                        }
                      />
                    );
                  })}
                </View>
                <TextInput
                  style={styles.noteInput}
                  placeholder="Note (optional)"
                  placeholderTextColor="#999"
                  value={note}
                  onChangeText={setNote}
                  multiline
                />
                {feedbackError && <Text style={styles.error}>{feedbackError}</Text>}
                <Pressable
                  style={[
                    styles.primary,
                    (!feedbackDirty || feedbackPhase === 'sending') && styles.disabled,
                  ]}
                  disabled={!feedbackDirty || feedbackPhase === 'sending'}
                  onPress={sendFeedback}
                >
                  {feedbackPhase === 'sending' ? (
                    <ActivityIndicator size="small" color="#fff" />
                  ) : (
                    <Text style={styles.primaryText}>Send feedback</Text>
                  )}
                </Pressable>
              </View>
            )}

            <Pressable style={styles.doneButton} onPress={onClose}>
              <Text style={styles.doneButtonText}>Done</Text>
            </Pressable>
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

function OptionButton({
  label,
  active,
  onPress,
}: {
  label: string;
  active: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable
      style={[styles.option, active && styles.optionActive]}
      onPress={onPress}
    >
      <Text style={[styles.optionText, active && styles.optionTextActive]}>
        {label}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  backdrop: { flex: 1, backgroundColor: '#00000088', justifyContent: 'flex-end' },
  sheet: {
    backgroundColor: '#fff',
    borderTopLeftRadius: 16,
    borderTopRightRadius: 16,
    maxHeight: '85%',
  },
  content: { padding: 20, gap: 14 },
  header: { flexDirection: 'row', alignItems: 'flex-start', gap: 8 },
  title: { fontSize: 19, fontWeight: '700', color: '#1a7f37' },
  syncText: { fontSize: 13, color: '#666', marginTop: 2 },
  close: { fontSize: 18, color: '#999', paddingHorizontal: 4 },

  section: {
    backgroundColor: '#f7f9fc',
    borderRadius: 12,
    padding: 14,
    gap: 8,
  },
  sectionTitle: { fontSize: 15, fontWeight: '700' },
  sectionHint: { fontSize: 12, color: '#777' },
  fieldLabel: { fontSize: 13, fontWeight: '600', color: '#444', marginTop: 4 },
  optionRow: { flexDirection: 'row', gap: 8 },
  tagWrap: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
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

  actionRow: { flexDirection: 'row', gap: 10, marginTop: 6 },
  primary: {
    backgroundColor: '#1f6feb',
    borderRadius: 8,
    paddingVertical: 11,
    paddingHorizontal: 22,
    alignItems: 'center',
    minWidth: 100,
  },
  primaryText: { color: '#fff', fontWeight: '700', fontSize: 15 },
  secondary: {
    borderRadius: 8,
    paddingVertical: 11,
    paddingHorizontal: 22,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: '#ccc',
  },
  secondaryText: { color: '#555', fontWeight: '600', fontSize: 15 },
  disabled: { opacity: 0.45 },
  error: { color: '#b00020', fontSize: 13 },
  savedNote: { color: '#1a7f37', fontSize: 14, fontWeight: '600' },

  feedbackToggle: { paddingVertical: 4 },
  feedbackToggleText: { color: '#1f6feb', fontWeight: '600', fontSize: 14 },
  noteInput: {
    backgroundColor: '#fff',
    borderWidth: 1,
    borderColor: '#ccc',
    borderRadius: 8,
    padding: 10,
    minHeight: 60,
    fontSize: 14,
    color: '#222',
    textAlignVertical: 'top',
  },

  doneButton: {
    backgroundColor: '#1a7f37',
    paddingVertical: 13,
    borderRadius: 8,
    alignItems: 'center',
  },
  doneButtonText: { color: '#fff', fontWeight: '700', fontSize: 16 },
});
