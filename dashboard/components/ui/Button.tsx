"use client";

import { useEffect } from "react";
import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** Defaults to secondary — a view gets ONE primary action, chosen on purpose. */
  variant?: Variant;
  size?: "md" | "sm";
  loading?: boolean;
}

export default function Button({
  variant = "secondary",
  size = "md",
  loading = false,
  disabled,
  children,
  className,
  ...rest
}: ButtonProps) {
  // Design rule: one primary action per view. Warn (dev only) when several
  // primary buttons are mounted at once so the violation is caught early.
  useEffect(() => {
    if (process.env.NODE_ENV === "production" || variant !== "primary") return;
    const count = document.querySelectorAll('[data-ui-button="primary"]').length;
    if (count > 1) {
      console.warn(
        `[ui/Button] ${count} primary buttons mounted — a view should have exactly one primary action.`,
      );
    }
  }, [variant]);

  return (
    <button
      {...rest}
      data-ui-button={variant}
      disabled={disabled || loading}
      className={[
        "ui-btn",
        `ui-btn-${variant}`,
        size === "sm" && "ui-btn-sm",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {loading && <span className="ui-spinner" aria-hidden />}
      {children}
    </button>
  );
}
