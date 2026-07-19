import type { CSSProperties } from "react";

/** Loading placeholder block. Size it with width/height (tokens preferred). */
export function Skeleton({
  width,
  height = 16,
  style,
}: {
  width?: CSSProperties["width"];
  height?: CSSProperties["height"];
  style?: CSSProperties;
}) {
  return <div className="ui-skeleton" aria-hidden style={{ width, height, ...style }} />;
}

/** Standard inline loading indicator. */
export function Spinner() {
  return <span className="ui-spinner" role="status" aria-label="Loading" />;
}
