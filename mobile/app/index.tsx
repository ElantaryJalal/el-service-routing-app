import { useRef, useState } from 'react';
import {
  ActivityIndicator,
  Image,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { CameraView, useCameraPermissions } from 'expo-camera';
import * as ImagePicker from 'expo-image-picker';
import { router } from 'expo-router';

import { ApiError, api, type ImageFile } from '../src/api/client';
import { draftStore } from '../src/state/draftStore';

type Phase =
  | { name: 'idle' }
  | { name: 'camera' }
  | { name: 'uploading'; uri: string }
  | { name: 'error'; uri: string; message: string };

/** Derive a FormData file descriptor from a local image uri. */
function toImageFile(uri: string): ImageFile {
  const base = uri.split('/').pop() || 'plan.jpg';
  const ext = base.includes('.') ? base.split('.').pop()!.toLowerCase() : 'jpg';
  const type = ext === 'png' ? 'image/png' : 'image/jpeg';
  const name = base.includes('.') ? base : `${base}.jpg`;
  return { uri, name, type };
}

export default function CaptureScreen() {
  const [phase, setPhase] = useState<Phase>({ name: 'idle' });
  const [permission, requestPermission] = useCameraPermissions();
  const cameraRef = useRef<CameraView>(null);

  async function upload(uri: string) {
    setPhase({ name: 'uploading', uri });
    try {
      const draft = await api.extractPlan(toImageFile(uri));
      // Stash the parsed payload + photo so Confirm can read it without
      // re-fetching, then hand off with just the tour id.
      draftStore.set({ ...draft, photo_uri: uri });
      setPhase({ name: 'idle' });
      router.push({
        pathname: '/confirm',
        params: { tourId: String(draft.tour_id) },
      });
    } catch (err) {
      const message = err instanceof ApiError ? err.message : String(err);
      setPhase({ name: 'error', uri, message });
    }
  }

  async function openCamera() {
    if (!permission?.granted) {
      const res = await requestPermission();
      if (!res.granted) return;
    }
    setPhase({ name: 'camera' });
  }

  async function takePhoto() {
    const photo = await cameraRef.current?.takePictureAsync({ quality: 0.7 });
    if (photo?.uri) await upload(photo.uri);
  }

  async function pickFromLibrary() {
    const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) return;
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'],
      quality: 0.7,
    });
    if (!result.canceled && result.assets[0]?.uri) {
      await upload(result.assets[0].uri);
    }
  }

  // --- Full-screen camera ---------------------------------------------------
  if (phase.name === 'camera') {
    return (
      <View style={styles.cameraFill}>
        <CameraView ref={cameraRef} style={styles.cameraFill} facing="back" />
        <View style={styles.cameraControls}>
          <Pressable
            style={styles.cameraCancel}
            onPress={() => setPhase({ name: 'idle' })}
          >
            <Text style={styles.cameraCancelText}>Cancel</Text>
          </Pressable>
          <Pressable style={styles.shutter} onPress={takePhoto} />
          <View style={styles.cameraCancel} />
        </View>
      </View>
    );
  }

  // --- Uploading ------------------------------------------------------------
  if (phase.name === 'uploading') {
    return (
      <View style={styles.centered}>
        <Image source={{ uri: phase.uri }} style={styles.preview} />
        <ActivityIndicator size="large" style={styles.spacer} />
        <Text style={styles.muted}>Reading the tour plan…</Text>
      </View>
    );
  }

  // --- Idle / error ---------------------------------------------------------
  return (
    <View style={styles.container}>
      <Text style={styles.title}>Capture</Text>
      <Text style={styles.subtitle}>
        Photograph the printed tour plan, or pick an existing photo.
      </Text>

      {phase.name === 'error' && (
        <View style={styles.errorBox}>
          <Image source={{ uri: phase.uri }} style={styles.previewSmall} />
          <Text style={styles.errorText}>Couldn’t read the plan.</Text>
          <Text style={styles.errorDetail}>{phase.message}</Text>
          <Pressable
            style={styles.button}
            onPress={() => upload(phase.uri)}
          >
            <Text style={styles.buttonText}>Retry</Text>
          </Pressable>
        </View>
      )}

      <Pressable style={styles.button} onPress={openCamera}>
        <Text style={styles.buttonText}>Take photo</Text>
      </Pressable>
      <Pressable style={styles.buttonSecondary} onPress={pickFromLibrary}>
        <Text style={styles.buttonSecondaryText}>Choose from library</Text>
      </Pressable>

      {/* Office view: the captured business data per store. */}
      <Pressable onPress={() => router.push('/stores')}>
        <Text style={styles.storesLink}>Stores →</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: 20, gap: 14 },
  centered: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 12, padding: 20 },
  title: { fontSize: 28, fontWeight: '700' },
  subtitle: { fontSize: 15, color: '#555', marginBottom: 8 },
  muted: { fontSize: 15, color: '#555' },
  spacer: { marginTop: 4 },
  button: {
    backgroundColor: '#1f6feb',
    paddingVertical: 14,
    borderRadius: 8,
    alignItems: 'center',
  },
  buttonText: { color: '#fff', fontWeight: '600', fontSize: 16 },
  buttonSecondary: {
    borderWidth: 1,
    borderColor: '#1f6feb',
    paddingVertical: 14,
    borderRadius: 8,
    alignItems: 'center',
  },
  buttonSecondaryText: { color: '#1f6feb', fontWeight: '600', fontSize: 16 },
  storesLink: {
    color: '#1f6feb',
    fontWeight: '600',
    fontSize: 15,
    textAlign: 'center',
    marginTop: 18,
  },
  preview: { width: 200, height: 260, borderRadius: 8, resizeMode: 'cover' },
  previewSmall: { width: 120, height: 150, borderRadius: 6, resizeMode: 'cover' },
  errorBox: {
    borderWidth: 1,
    borderColor: '#f2c1c1',
    backgroundColor: '#fdf3f3',
    borderRadius: 12,
    padding: 16,
    gap: 8,
    alignItems: 'center',
  },
  errorText: { fontSize: 16, fontWeight: '600', color: '#b00020' },
  errorDetail: { fontSize: 13, color: '#8a2b2b', textAlign: 'center' },
  cameraFill: { flex: 1 },
  cameraControls: {
    position: 'absolute',
    bottom: 40,
    left: 0,
    right: 0,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 32,
  },
  shutter: {
    width: 72,
    height: 72,
    borderRadius: 36,
    backgroundColor: '#fff',
    borderWidth: 4,
    borderColor: '#00000055',
  },
  cameraCancel: { width: 72, alignItems: 'center' },
  cameraCancelText: { color: '#fff', fontSize: 16, fontWeight: '600' },
});
