import Constants from 'expo-constants';

const extra = (Constants.expoConfig?.extra ?? {}) as { apiBaseUrl?: string };

// Prefer the runtime env var (EXPO_PUBLIC_* are inlined at build time), then the
// value baked into app.config.ts's `extra`, then a localhost default.
export const API_BASE_URL: string =
  process.env.EXPO_PUBLIC_API_BASE_URL ??
  extra.apiBaseUrl ??
  'http://localhost:8000';
