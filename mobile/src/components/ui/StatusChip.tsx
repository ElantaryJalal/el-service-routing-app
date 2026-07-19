/** Same status vocabulary and colors as the office dashboard
 * (dashboard/components/ui/status.ts) — a "done" is one green everywhere. */

import { StyleSheet, Text, View } from 'react-native';

import { color, font, radius, space } from '../../theme';

export type Status =
  | 'draft'
  | 'planned'
  | 'assigned'
  | 'in_progress'
  | 'done'
  | 'overdue';

export const STATUS_LABELS: Record<Status, string> = {
  draft: 'Draft',
  planned: 'Planned',
  assigned: 'Assigned',
  in_progress: 'In progress',
  done: 'Done',
  overdue: 'Overdue',
};

const STRONG: Record<Status, string> = {
  draft: color.status.draft,
  planned: color.status.planned,
  assigned: color.status.assigned,
  in_progress: color.status.inProgress,
  done: color.status.done,
  overdue: color.status.overdue,
};

const SOFT: Record<Status, string> = {
  draft: color.status.draftSoft,
  planned: color.status.plannedSoft,
  assigned: color.status.assignedSoft,
  in_progress: color.status.inProgressSoft,
  done: color.status.doneSoft,
  overdue: color.status.overdueSoft,
};

export default function StatusChip({
  status,
  label,
}: {
  status: Status;
  label?: string;
}) {
  return (
    <View style={[styles.chip, { backgroundColor: SOFT[status] }]}>
      <View style={[styles.dot, { backgroundColor: STRONG[status] }]} />
      <Text style={[styles.label, { color: STRONG[status] }]}>
        {label ?? STATUS_LABELS[status]}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  chip: {
    flexDirection: 'row',
    alignItems: 'center',
    alignSelf: 'flex-start',
    gap: space.s1,
    paddingHorizontal: space.s3,
    paddingVertical: space.s1,
    borderRadius: radius.full,
  },
  dot: { width: space.s2, height: space.s2, borderRadius: radius.full },
  /* A step larger than the office chip — sunlight legibility. */
  label: { fontSize: font.size.sm, fontWeight: font.weight.bold },
});
