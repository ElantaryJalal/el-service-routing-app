import { useEffect } from 'react';
import { Pressable, Text } from 'react-native';
import { Stack, router, useSegments } from 'expo-router';

import {
  addNotificationTapListener,
  registerForPushNotifications,
  unregisterPushToken,
} from '../src/notifications';
import { session, useSession } from '../src/state/session';

function SignOutButton() {
  return (
    <Pressable
      onPress={() =>
        // The token delete needs the JWT, so it runs before the sign-out;
        // both are best-effort (a dead network must not trap the user).
        void unregisterPushToken().finally(() => void session.signOut())
      }
      hitSlop={8}
    >
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

  // Push alerts (assignment changes): register this device whenever a session
  // exists — covers fresh logins and restored sessions alike. Native no-op on
  // web / permission denial.
  useEffect(() => {
    if (user) void registerForPushNotifications();
  }, [user]);

  // A tapped alert opens the tour it is about.
  useEffect(
    () =>
      addNotificationTapListener((tourId) =>
        router.push({ pathname: '/map', params: { tourId: String(tourId) } }),
      ),
    [],
  );

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
