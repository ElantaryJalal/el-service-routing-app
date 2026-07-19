import { useState } from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import { ApiError, api } from '../src/api/client';
import { Button, Input } from '../src/components/ui';
import { outbox } from '../src/state/outbox';
import { session } from '../src/state/session';
import { color, font, space } from '../src/theme';

export default function LoginScreen() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSubmit = email.trim().length > 0 && password.length > 0 && !busy;

  async function submit() {
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.login(email.trim(), password);
      await session.signIn(result.access_token, result.user);
      // Writes queued while signed out (401s) are due again immediately.
      outbox.retryNow().catch(() => {});
      // The root layout's auth gate navigates home once the session lands.
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
      setBusy(false);
    }
  }

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <View style={styles.card}>
        <Text style={styles.title}>EL Service</Text>
        <Text style={styles.subtitle}>Sign in to see your tours.</Text>

        <Input
          placeholder="Email"
          autoCapitalize="none"
          autoComplete="email"
          keyboardType="email-address"
          value={email}
          onChangeText={setEmail}
          editable={!busy}
        />
        <Input
          placeholder="Password"
          secureTextEntry
          autoComplete="password"
          value={password}
          onChangeText={setPassword}
          editable={!busy}
          onSubmitEditing={submit}
        />

        {error && <Text style={styles.error}>{error}</Text>}

        <Button
          title="Sign in"
          variant="primary"
          onPress={submit}
          disabled={!canSubmit}
          loading={busy}
        />
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    justifyContent: 'center',
    padding: space.s6,
    backgroundColor: color.bg,
  },
  card: { gap: space.s1 },
  title: {
    fontSize: font.size.kpi,
    fontWeight: font.weight.bold,
    textAlign: 'center',
    color: color.text,
  },
  subtitle: {
    fontSize: font.size.md,
    color: color.textMuted,
    textAlign: 'center',
    marginBottom: space.s3,
  },
  error: {
    color: color.danger,
    fontSize: font.size.base,
    textAlign: 'center',
    marginBottom: space.s2,
  },
});
