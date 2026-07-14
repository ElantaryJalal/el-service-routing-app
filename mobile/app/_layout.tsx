import { useEffect } from 'react';
import { Pressable, Text } from 'react-native';
import { Stack, router, useSegments } from 'expo-router';

import { session, useSession } from '../src/state/session';

function SignOutButton() {
  return (
    <Pressable onPress={() => void session.signOut()} hitSlop={8}>
      <Text style={{ color: '#1f6feb', fontWeight: '600', fontSize: 15 }}>
        Sign out
      </Text>
    </Pressable>
  );
}

export default function RootLayout() {
  const { user, ready } = useSession();
  const segments = useSegments();

  // Auth gate: everything except /login needs a session. Also covers the API
  // client's sign-out on 401 (expired token) — the session change lands here.
  useEffect(() => {
    if (!ready) return;
    const onLogin = segments[0] === 'login';
    if (!user && !onLogin) router.replace('/login');
    else if (user && onLogin) router.replace('/');
  }, [ready, user, segments]);

  if (!ready) return null;

  return (
    <Stack>
      <Stack.Screen name="login" options={{ headerShown: false }} />
      <Stack.Screen
        name="index"
        options={{
          title: user?.role === 'worker' ? 'My tours' : 'Capture',
          headerRight: user ? () => <SignOutButton /> : undefined,
        }}
      />
      <Stack.Screen name="confirm" options={{ title: 'Confirm' }} />
      <Stack.Screen name="review" options={{ title: 'Review' }} />
      <Stack.Screen name="map" options={{ title: 'Map' }} />
      <Stack.Screen name="stores/index" options={{ title: 'Stores' }} />
      <Stack.Screen name="stores/[id]" options={{ title: 'Store' }} />
    </Stack>
  );
}
