import { StyleSheet, Text, View } from 'react-native';
import { Link, useLocalSearchParams } from 'expo-router';

export default function ReviewScreen() {
  const { tourId } = useLocalSearchParams<{ tourId?: string }>();

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Review</Text>
      {tourId ? (
        <Text style={styles.ok}>Tour #{tourId} committed ✓</Text>
      ) : null}
      <Text style={styles.subtitle}>
        Next: optimise the committed tour into a per-day plan (M2).
      </Text>
      <Link href="/" style={styles.link}>
        ← New capture
      </Link>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: 20, gap: 12 },
  title: { fontSize: 28, fontWeight: '700' },
  ok: { fontSize: 16, color: '#137333', fontWeight: '600' },
  subtitle: { fontSize: 15, color: '#555' },
  link: { fontSize: 16, color: '#1f6feb' },
});
