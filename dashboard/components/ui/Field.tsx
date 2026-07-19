"use client";

import { useId } from "react";
import type {
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from "react";

function fieldClass(error: boolean, extra?: string): string {
  return ["ui-input", error && "ui-input-error", extra].filter(Boolean).join(" ");
}

interface FieldChrome {
  label?: ReactNode;
  error?: string;
}

/** Text input with label + error state. */
export function Input({
  label,
  error,
  className,
  ...rest
}: InputHTMLAttributes<HTMLInputElement> & FieldChrome) {
  const id = useId();
  return (
    <div className="ui-field">
      {label && (
        <label className="ui-field-label" htmlFor={id}>
          {label}
        </label>
      )}
      <input id={id} {...rest} className={fieldClass(Boolean(error), className)} />
      {error && <div className="ui-field-error">{error}</div>}
    </div>
  );
}

export function Select({
  label,
  error,
  className,
  children,
  ...rest
}: SelectHTMLAttributes<HTMLSelectElement> & FieldChrome) {
  const id = useId();
  return (
    <div className="ui-field">
      {label && (
        <label className="ui-field-label" htmlFor={id}>
          {label}
        </label>
      )}
      <select id={id} {...rest} className={fieldClass(Boolean(error), className)}>
        {children}
      </select>
      {error && <div className="ui-field-error">{error}</div>}
    </div>
  );
}

export function Textarea({
  label,
  error,
  className,
  ...rest
}: TextareaHTMLAttributes<HTMLTextAreaElement> & FieldChrome) {
  const id = useId();
  return (
    <div className="ui-field">
      {label && (
        <label className="ui-field-label" htmlFor={id}>
          {label}
        </label>
      )}
      <textarea id={id} {...rest} className={fieldClass(Boolean(error), className)} />
      {error && <div className="ui-field-error">{error}</div>}
    </div>
  );
}
