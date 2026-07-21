import { useEffect } from 'react';
import { Platform, Pressable, Text } from 'react-native';
import { Stack, router, useSegments } from 'expo-router';

import {
  addNotificationTapListener,
  registerForPushNotifications,
  unregisterPushToken,
} from '../src/notifications';
import { session, useSession } from '../src/state/session';

import { color as tk } from '../src/theme';

// On web the app otherwise fills the whole desktop window. Constrain the
// mounted RN-web root to a phone-sized column, centred on a dark "device
// tray" page, so opening it in a browser mirrors how it looks on a handset.
// Native builds never see this (the app already owns the full screen).
const MOBILE_FRAME_WIDTH = 390;
function useWebMobileFrame() {
  useEffect(() => {
    if (Platform.OS !== 'web') return;
    const id = 'el-mobile-frame';
    if (document.getElementById(id)) return;
    const style = document.createElement('style');
    style.id = id;
    style.textContent = `
      html, body { background: #14161a; margin: 0; }
      #root {
        max-width: ${MOBILE_FRAME_WIDTH}px;
        margin: 0 auto;
        min-height: 100vh;
        height: 100vh;
        overflow: hidden;
        background: #fff;
        box-shadow: 0 0 0 1px rgba(255,255,255,0.06), 0 24px 64px rgba(0,0,0,0.55);
      }
    `;
    document.head.appendChild(style);
  }, []);
}

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
      <Text style={{ color: tk.brand, fontWeight: '600', fontSize: 15 }}>
        Sign out
      </Text>
    </Pressable>
  );
}

export default function RootLayout() {
  const { user, ready } = useSession();
  const segments = useSegments();

  useWebMobileFrame();

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
      <Stack.Screen name="design" options={{ title: 'Components' }} />
    </Stack>
  );
}
