import { StyleSheet, Text, View } from 'react-native';
import { Link } from 'expo-router';

export default function ConfirmScreen() {
  return (
    <View style={styles.container}>
      <Text style={styles.title}>Confirm</Text>
      <Text style={styles.subtitle}>
        Review extracted stops, edit service time and closing time (M2).
      </Text>
      <Link href="/review" style={styles.link}>
        → Review
      </Link>
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
