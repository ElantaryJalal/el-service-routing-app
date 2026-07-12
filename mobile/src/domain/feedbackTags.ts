/** Display labels for the controlled visit-feedback vocabulary (shared by the
 * capture form and the history list). */
import type { FeedbackTag } from '../api/client';

export const FEEDBACK_TAGS: { value: FeedbackTag; label: string }[] = [
  { value: 'parking_full', label: 'Parking full' },
  { value: 'access_problem', label: 'Access problem' },
  { value: 'took_longer', label: 'Took longer than expected' },
  { value: 'store_condition', label: 'Store condition issue' },
  { value: 'other', label: 'Other' },
];

export function tagLabel(tag: string): string {
  return FEEDBACK_TAGS.find((t) => t.value === tag)?.label ?? tag;
}
