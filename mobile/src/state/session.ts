/**
 * Signed-in session (JWT + user), persisted securely and mirrored in memory
 * so the API client can read the token synchronously on every request.
 * The root layout gates navigation on `useSession()`.
 *
 * At rest the session lives in the OS keychain/keystore (expo-secure-store)
 * on device; the web build falls back to AsyncStorage (localStorage) because
 * SecureStore does not exist in the browser.
 */
import { useSyncExternalStore } from 'react';
import { Platform } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as SecureStore from 'expo-secure-store';

import type { components } from '../api/types';

export type User = components['schemas']['UserRead'];
export type Role = components['schemas']['Role'];

// SecureStore keys only allow [A-Za-z0-9._-] — no colons.
const TOKEN_KEY = 'session.token';
const USER_KEY = 'session.user';

const storage =
  Platform.OS === 'web'
    ? {
        get: (key: string) => AsyncStorage.getItem(key),
        set: (key: string, value: string) => AsyncStorage.setItem(key, value),
        remove: (key: string) => AsyncStorage.removeItem(key),
      }
    : {
        get: (key: string) => SecureStore.getItemAsync(key),
        set: (key: string, value: string) => SecureStore.setItemAsync(key, value),
        remove: (key: string) => SecureStore.deleteItemAsync(key),
      };

export interface SessionSnapshot {
  /** false until the persisted session has been read once at startup. */
  ready: boolean;
  token: string | null;
  user: User | null;
}

let snapshot: SessionSnapshot = { ready: false, token: null, user: null };

type Listener = () => void;
const listeners = new Set<Listener>();

function setSnapshot(next: SessionSnapshot): void {
  snapshot = next;
  for (const fn of listeners) fn();
}

let loadPromise: Promise<void> | null = null;

/** Read the persisted session once; concurrent callers share the load. */
function load(): Promise<void> {
  if (!loadPromise) {
    loadPromise = (async () => {
      try {
        const [token, rawUser] = await Promise.all([
          storage.get(TOKEN_KEY),
          storage.get(USER_KEY),
        ]);
        const user = rawUser ? (JSON.parse(rawUser) as User) : null;
        setSnapshot({
          ready: true,
          token: token ?? null,
          user: token ? user : null,
        });
      } catch {
        setSnapshot({ ready: true, token: null, user: null });
      }
    })();
  }
  return loadPromise;
}

export const session = {
  /** Synchronous token for the API client (null while logged out/loading). */
  getToken(): string | null {
    return snapshot.token;
  },

  getUser(): User | null {
    return snapshot.user;
  },

  async signIn(token: string, user: User): Promise<void> {
    setSnapshot({ ready: true, token, user });
    await Promise.all([
      storage.set(TOKEN_KEY, token),
      storage.set(USER_KEY, JSON.stringify(user)),
    ]);
  },

  /** Also invoked by the API client on a 401 from an expired/revoked token. */
  async signOut(): Promise<void> {
    if (snapshot.ready && !snapshot.token && !snapshot.user) return;
    setSnapshot({ ready: true, token: null, user: null });
    await Promise.all([storage.remove(TOKEN_KEY), storage.remove(USER_KEY)]);
  },

  subscribe(listener: Listener): () => void {
    listeners.add(listener);
    load().catch(() => {});
    return () => listeners.delete(listener);
  },
};

/** React view of the session; mounting it kicks off the initial load. */
export function useSession(): SessionSnapshot {
  return useSyncExternalStore(
    session.subscribe,
    () => snapshot,
    () => snapshot,
  );
}
