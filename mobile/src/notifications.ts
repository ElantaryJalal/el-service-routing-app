/**
 * Expo push notifications: tour-assignment alerts for workers.
 *
 * The backend pushes "New tour assigned" / "Tour reassigned" / "Tour
 * unassigned" (each carrying `data.tour_id`) to every device token a user
 * registered. This module owns the device side:
 *
 * - `registerForPushNotifications()` after sign-in / on app start with a
 *   restored session: ask permission, fetch the Expo token, POST it to
 *   `/me/push-tokens`.
 * - `unregisterPushToken()` before sign-out, so a returned/handed-over device
 *   stops receiving the previous owner's alerts (needs the still-valid JWT,
 *   hence *before* the session is dropped).
 * - `addNotificationTapListener()` deep-links a tapped alert to the tour map.
 *
 * Everything is native-only and best-effort: web has no Expo push (the list
 * refreshes on focus there anyway), Android emulators without Play services
 * and permission denials just resolve to null. Notifications are a courtesy
 * on top of the pull-based refresh, never load-bearing.
 *
 * expo-notifications is require()d lazily inside the Platform guards so the
 * web bundle neither ships nor warns about the unsupported module.
 */
import { Platform } from 'react-native';
import Constants from 'expo-constants';

import { api } from './api/client';

type NotificationsModule = typeof import('expo-notifications');

let cachedModule: NotificationsModule | null = null;

function native(): NotificationsModule | null {
  if (Platform.OS === 'web') return null;
  if (!cachedModule) {
    // Lazy so the web bundle never ships the unsupported module (see module
    // docstring).
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    cachedModule = require('expo-notifications') as NotificationsModule;
  }
  return cachedModule;
}

/** The token registered in this app run; lets sign-out delete the right row. */
let registeredToken: string | null = null;

async function expoPushToken(
  Notifications: NotificationsModule,
): Promise<string | null> {
  // Simulators/emulators have no push transport; asking would throw.
  // eslint-disable-next-line @typescript-eslint/no-require-imports -- native-only
  const Device = require('expo-device') as typeof import('expo-device');
  if (!Device.isDevice) return null;

  const existing = await Notifications.getPermissionsAsync();
  let status = existing.status;
  if (status !== 'granted') {
    status = (await Notifications.requestPermissionsAsync()).status;
  }
  if (status !== 'granted') return null;

  // EAS builds resolve the project id from config; Expo Go dev works without.
  const projectId: string | undefined =
    Constants.expoConfig?.extra?.eas?.projectId ?? Constants.easConfig?.projectId;
  const token = await Notifications.getExpoPushTokenAsync(
    projectId ? { projectId } : undefined,
  );
  return token.data;
}

/**
 * Ask permission, fetch this device's Expo token, and register it with the
 * backend. Safe to call repeatedly (server-side upsert); resolves quietly on
 * web, denial, or any failure.
 */
export async function registerForPushNotifications(): Promise<void> {
  const Notifications = native();
  if (!Notifications) return;

  try {
    // Alerts arriving while the app is open should still show.
    Notifications.setNotificationHandler({
      handleNotification: async () => ({
        shouldShowBanner: true,
        shouldShowList: true,
        shouldPlaySound: true,
        shouldSetBadge: false,
      }),
    });
    if (Platform.OS === 'android') {
      await Notifications.setNotificationChannelAsync('default', {
        name: 'Tour alerts',
        importance: Notifications.AndroidImportance.HIGH,
      });
    }

    const token = await expoPushToken(Notifications);
    if (!token) return;
    await api.registerPushToken(token, Platform.OS as 'ios' | 'android');
    registeredToken = token;
  } catch (err) {
    console.warn('push registration skipped:', err);
  }
}

/**
 * Delete this device's token server-side. Call while still authenticated,
 * i.e. before `session.signOut()`.
 */
export async function unregisterPushToken(): Promise<void> {
  const Notifications = native();
  if (!Notifications) return;

  try {
    // Fall back to re-reading the token (registration may have happened in a
    // previous app run, so the in-memory copy can be empty).
    const token = registeredToken ?? (await expoPushToken(Notifications));
    if (!token) return;
    await api.unregisterPushToken(token);
    registeredToken = null;
  } catch (err) {
    console.warn('push unregistration skipped:', err);
  }
}

/**
 * Invoke `onTourTap(tourId)` when the user taps a tour alert (also fires for
 * the notification that cold-started the app). Returns an unsubscribe.
 */
export function addNotificationTapListener(
  onTourTap: (tourId: number) => void,
): () => void {
  const Notifications = native();
  if (!Notifications) return () => {};

  const handle = (response: {
    notification: { request: { content: { data?: Record<string, unknown> } } };
  }) => {
    const tourId = Number(response.notification.request.content.data?.tour_id);
    if (Number.isFinite(tourId) && tourId > 0) onTourTap(tourId);
  };

  const sub = Notifications.addNotificationResponseReceivedListener(handle);
  // The tap that launched a cold app precedes the listener; replay it.
  Notifications.getLastNotificationResponseAsync?.()
    .then((response) => {
      if (response) handle(response);
    })
    .catch(() => {});
  return () => sub.remove();
}
