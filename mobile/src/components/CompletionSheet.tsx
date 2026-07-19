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
  Image,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import * as ImagePicker from 'expo-image-picker';

import type { FeedbackTag } from '../api/client';
import { FEEDBACK_TAGS } from '../domain/feedbackTags';
import type { OptimisedStop } from '../domain/optimisedTour';
import { uuidv4 } from '../domain/uuid';
import { outbox } from '../state/outbox';
import { Button, SyncState } from './ui';

import { color as tk } from '../theme';

/** How the tier-1 completion call went (owned by the opener). */
export type CompletionSync = 'pending' | 'done' | 'queued';

type StoreSize = 'small' | 'medium' | 'large';

const SIZES: { value: StoreSize; label: string }[] = [
  { value: 'small', label: 'Small' },
  { value: 'medium', label: 'Medium' },
  { value: 'large', label: 'Large' },
];

export function CompletionSheet({
  stop,
  sync,
  onClose,
  onAttributesSaved,
  onFeedbackSent,
}: {
  stop: OptimisedStop;
  sync: CompletionSync;
  onClose: () => void;
  /** Called after a successful attribute save so the screen can stop asking. */
  onAttributesSaved: (storeId: number) => void;
  /** Called once feedback is stored/queued, e.g. to bump the notes count. */
  onFeedbackSent?: (stop: OptimisedStop) => void;
}) {
  // --- Tier 2 state ---
  const askAttributes =
    stop.store_id !== null && stop.store_attributes_complete === false;
  const [attrPhase, setAttrPhase] = useState<'form' | 'saving' | 'saved' | 'skipped'>(
    'form',
  );
  const [attrQueued, setAttrQueued] = useState(false);
  const [attrError, setAttrError] = useState<string | null>(null);
  const [size, setSize] = useState<StoreSize | null>(null);
  const [inMall, setInMall] = useState<boolean | null>(null);
  const [hasParking, setHasParking] = useState<boolean | null>(null);

  // --- Tier 3 state ---
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const [tags, setTags] = useState<FeedbackTag[]>([]);
  const [note, setNote] = useState('');
  const [photoUri, setPhotoUri] = useState<string | null>(null);
  const [feedbackPhase, setFeedbackPhase] = useState<
    'idle' | 'sending' | 'sent' | 'queued'
  >('idle');
  const [feedbackError, setFeedbackError] = useState<string | null>(null);

  async function pickPhoto() {
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'],
      quality: 0.7,
    });
    if (!result.canceled && result.assets[0]) {
      setPhotoUri(result.assets[0].uri);
    }
  }

  async function saveAttributes() {
    if (stop.store_id === null) return;
    setAttrPhase('saving');
    setAttrError(null);
    try {
      // Outbox-first: works offline; attributes are last-write-wins on the
      // server so a delayed sync is safe.
      const outcome = await outbox.enqueue({
        kind: 'attributes',
        payload: {
          store_id: stop.store_id,
          fields: {
            ...(size !== null && { size }),
            ...(inMall !== null && { in_mall: inMall }),
            ...(hasParking !== null && { has_parking: hasParking }),
          },
        },
      });
      setAttrQueued(outcome === 'queued');
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
      const outcome = await outbox.enqueue({
        kind: 'feedback',
        payload: {
          stop_id: stop.stop_id,
          client_uuid: uuidv4(),
          tags,
          note: note.trim() || null,
          ...(photoUri && { photo_local_uri: photoUri }),
        },
      });
      setFeedbackPhase(outcome === 'done' ? 'sent' : 'queued');
      onFeedbackSent?.(stop);
    } catch {
      setFeedbackPhase('idle');
      setFeedbackError('Could not send feedback.');
    }
  }

  const attrDirty = size !== null || inMall !== null || hasParking !== null;
  const feedbackDirty =
    tags.length > 0 || note.trim().length > 0 || photoUri !== null;

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
                <View style={styles.syncRow}>
                  {sync === 'queued' ? (
                    <SyncState
                      state="pending"
                      label="Saved on this phone — will sync when online."
                    />
                  ) : sync === 'pending' ? (
                    <SyncState state="pending" label="Marking done…" />
                  ) : (
                    <SyncState state="synced" label="Marked done." />
                  )}
                </View>
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
                  <Button
                    title="Save"
                    variant="primary"
                    disabled={!attrDirty}
                    loading={attrPhase === 'saving'}
                    onPress={saveAttributes}
                    style={styles.flex}
                  />
                  <Button
                    title="Skip"
                    variant="ghost"
                    onPress={() => setAttrPhase('skipped')}
                  />
                </View>
              </View>
            )}
            {attrPhase === 'saved' && (
              <Text style={styles.savedNote}>
                {attrQueued
                  ? 'Store info saved — will sync when online.'
                  : 'Store info saved — thanks!'}
              </Text>
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
                  {FEEDBACK_TAGS.map((t) => {
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
                  placeholderTextColor={tk.textFaint}
                  value={note}
                  onChangeText={setNote}
                  multiline
                />

                {photoUri ? (
                  <View style={styles.photoRow}>
                    <Image source={{ uri: photoUri }} style={styles.photoThumb} />
                    <Pressable onPress={() => setPhotoUri(null)} hitSlop={10}>
                      <Text style={styles.photoRemove}>Remove ✕</Text>
                    </Pressable>
                  </View>
                ) : (
                  <Pressable style={styles.photoButton} onPress={pickPhoto}>
                    <Text style={styles.photoButtonText}>📷 Add photo</Text>
                  </Pressable>
                )}

                {feedbackError && <Text style={styles.error}>{feedbackError}</Text>}
                <Button
                  title="Send feedback"
                  variant="primary"
                  disabled={!feedbackDirty}
                  loading={feedbackPhase === 'sending'}
                  onPress={sendFeedback}
                />
              </View>
            )}

            <Button title="Done" onPress={onClose} />
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
  backdrop: { flex: 1, backgroundColor: tk.scrim, justifyContent: 'flex-end' },
  sheet: {
    backgroundColor: tk.surface,
    borderTopLeftRadius: 16,
    borderTopRightRadius: 16,
    maxHeight: '85%',
  },
  content: { padding: 20, gap: 14 },
  header: { flexDirection: 'row', alignItems: 'flex-start', gap: 8 },
  syncRow: { marginTop: 6, alignItems: 'flex-start' },
  title: { fontSize: 19, fontWeight: '700', color: tk.status.done },
  close: { fontSize: 18, color: tk.textFaint, paddingHorizontal: 4 },

  section: {
    backgroundColor: tk.bg,
    borderRadius: 12,
    padding: 14,
    gap: 8,
  },
  sectionTitle: { fontSize: 15, fontWeight: '700' },
  sectionHint: { fontSize: 12, color: tk.textMuted },
  fieldLabel: { fontSize: 13, fontWeight: '600', color: tk.text, marginTop: 4 },
  optionRow: { flexDirection: 'row', gap: 8 },
  tagWrap: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  option: {
    backgroundColor: tk.surface,
    borderRadius: 16,
    paddingVertical: 8,
    paddingHorizontal: 16,
    borderWidth: 1,
    borderColor: tk.borderStrong,
  },
  optionActive: { backgroundColor: tk.brand, borderColor: tk.brand },
  optionText: { fontWeight: '600', color: tk.text, fontSize: 14 },
  optionTextActive: { color: tk.onBrand },

  actionRow: { flexDirection: 'row', gap: 10, marginTop: 6 },
  error: { color: tk.danger, fontSize: 13 },
  savedNote: { color: tk.status.done, fontSize: 14, fontWeight: '600' },

  feedbackToggle: { paddingVertical: 4 },
  feedbackToggleText: { color: tk.brand, fontWeight: '600', fontSize: 14 },
  photoRow: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  photoThumb: { width: 72, height: 72, borderRadius: 8, backgroundColor: tk.border },
  photoRemove: { color: tk.danger, fontWeight: '600', fontSize: 13 },
  photoButton: {
    alignSelf: 'flex-start',
    borderWidth: 1,
    borderColor: tk.borderStrong,
    borderRadius: 8,
    paddingVertical: 8,
    paddingHorizontal: 14,
    backgroundColor: tk.surface,
  },
  photoButtonText: { color: tk.text, fontWeight: '600', fontSize: 14 },
  noteInput: {
    backgroundColor: tk.surface,
    borderWidth: 1,
    borderColor: tk.borderStrong,
    borderRadius: 8,
    padding: 10,
    minHeight: 60,
    fontSize: 14,
    color: tk.text,
    textAlignVertical: 'top',
  },

});
