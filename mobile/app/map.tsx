import { StyleSheet, Text, View } from 'react-native';
import { Link } from 'expo-router';

export default function MapScreen() {
  return (
    <View style={styles.container}>
      <Text style={styles.title}>Map</Text>
      <Text style={styles.subtitle}>
        Day-filtered optimised route with ETAs (M2).
      </Text>
      <Link href="/" style={styles.link}>
        ← Capture
      </Link>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: 20, gap: 12 },
  title: { fontSize: 28, fontWeight: '700' },
  subtitle: { fontSize: 15, color: '#555' },
  link: { fontSize: 16, color: '#1f6feb' },
});
