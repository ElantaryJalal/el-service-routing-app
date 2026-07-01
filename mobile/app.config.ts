import type { ExpoConfig } from 'expo/config';

// API base URL is read from EXPO_PUBLIC_API_BASE_URL and surfaced via
// expo-constants (Constants.expoConfig.extra.apiBaseUrl). See src/api/config.ts.
const config: ExpoConfig = {
  name: 'EL Service',
  slug: 'el-service-routing',
  scheme: 'elservice',
  version: '0.1.0',
  orientation: 'portrait',
  userInterfaceStyle: 'automatic',
  ios: {
    supportsTablet: true,
    bundleIdentifier: 'de.elservice.routing',
  },
  android: {
    package: 'de.elservice.routing',
  },
  plugins: ['expo-router'],
  extra: {
    apiBaseUrl: process.env.EXPO_PUBLIC_API_BASE_URL ?? 'http://localhost:8000',
  },
};

export default config;
