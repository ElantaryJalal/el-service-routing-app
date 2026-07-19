import type { ReactNode } from "react";

export default function EmptyState({
  title,
  hint,
  action,
}: {
  title: string;
  hint?: string;
  /** Usually a secondary Button. */
  action?: ReactNode;
}) {
  return (
    <div className="ui-empty">
      <p className="ui-empty-title">{title}</p>
      {hint && <p className="ui-empty-hint">{hint}</p>}
      {action}
    </div>
  );
}
