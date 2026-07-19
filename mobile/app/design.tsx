/** Component preview — every ui/ part with sample data. Dev reference only;
 * navigate to /design directly (not linked from the app). */

import { ScrollView, StyleSheet, Text, View } from 'react-native';

import {
  ActionBar,
  Button,
  EmptyState,
  Input,
  Loading,
  StatusChip,
  StopCard,
  SyncState,
} from '../src/components/ui';
import { color, font, space } from '../src/theme';
import { dayColor } from '../src/domain/optimisedTour';

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>{title}</Text>
      {children}
    </View>
  );
}

const STATUSES = ['draft', 'planned', 'assigned', 'in_progress', 'done', 'overdue'] as const;

export default function DesignPreview() {
  return (
    <View style={styles.screen}>
      <ScrollView contentContainerStyle={styles.content}>
        <Section title="Buttons">
          <View style={styles.row}>
            <Button title="Mark done" variant="primary" />
            <Button title="Secondary" />
          </View>
          <View style={styles.row}>
            <Button title="Ghost" variant="ghost" />
            <Button title="Danger" variant="danger" />
            <Button title="Loading" loading />
          </View>
        </Section>

        <Section title="Status chips — shared vocabulary">
          <View style={styles.row}>
            {STATUSES.map((s) => (
              <StatusChip key={s} status={s} />
            ))}
          </View>
        </Section>

        <Section title="Stop cards">
          <StopCard
            seq={1}
            accent={dayColor(0)}
            title="ALDI Leipzig-Plagwitz"
            subtitle="Karl-Heine-Straße 88, 04229 Leipzig"
            status="done"
            onPress={() => {}}
          />
          <StopCard
            seq={2}
            accent={dayColor(0)}
            title="ALDI Nova Eventis"
            subtitle="Merseburger Str. 17, 06237 Günthersdorf"
            status="in_progress"
            onPress={() => {}}
          />
          <StopCard
            seq={7}
            accent={dayColor(2)}
            title="HIT Meinerzhagen"
            subtitle="Bahnhofstraße 9"
            status="planned"
            onPress={() => {}}
          />
        </Section>

        <Section title="Sync state">
          <View style={styles.rowWrapGap}>
            <SyncState state="synced" />
            <SyncState state="pending" />
            <SyncState state="offline" />
          </View>
        </Section>

        <Section title="Input">
          <Input label="Note" placeholder="e.g. Kühlregal defekt" />
          <Input label="Postal code" defaultValue="not-a-plz" error="Enter a 5-digit postal code." />
        </Section>

        <Section title="Empty state">
          <EmptyState title="No tours assigned" hint="Your dispatcher assigns tours here.">
            <Button title="Refresh" />
          </EmptyState>
        </Section>

        <Section title="Loading">
          <Loading label="Loading tour…" />
        </Section>
      </ScrollView>

      <ActionBar>
        <Button title="Primary action bar" variant="primary" style={styles.flex} />
      </ActionBar>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: color.bg },
  content: { padding: space.s4, gap: space.s5 },
  section: { gap: space.s2 },
  sectionTitle: {
    fontSize: font.size.label,
    fontWeight: font.weight.semibold,
    color: color.textMuted,
    textTransform: 'uppercase',
    letterSpacing: font.trackingLabel,
  },
  row: { flexDirection: 'row', flexWrap: 'wrap', gap: space.s2, alignItems: 'center' },
  rowWrapGap: { gap: space.s2, alignItems: 'flex-start' },
  flex: { flex: 1 },
});
