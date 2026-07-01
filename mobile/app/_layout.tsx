import { Stack } from 'expo-router';

export default function RootLayout() {
  return (
    <Stack>
      <Stack.Screen name="index" options={{ title: 'Capture' }} />
      <Stack.Screen name="confirm" options={{ title: 'Confirm' }} />
      <Stack.Screen name="review" options={{ title: 'Review' }} />
      <Stack.Screen name="map" options={{ title: 'Map' }} />
    </Stack>
  );
}
