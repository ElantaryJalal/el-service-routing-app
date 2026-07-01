import { StyleSheet, Text, View } from 'react-native';
import { Link } from 'expo-router';

export default function ReviewScreen() {
  return (
    <View style={styles.container}>
      <Text style={styles.title}>Review</Text>
      <Text style={styles.subtitle}>
        Commit the tour, then optimise into a per-day plan (M2).
      </Text>
      <Link href="/map" style={styles.link}>
        → Map
      </Link>
      <Link href="/confirm" style={styles.link}>
        ← Confirm
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
