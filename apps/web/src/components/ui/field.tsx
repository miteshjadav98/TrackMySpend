import { type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, useId } from "react";

const CONTROL =
  "w-full rounded-[10px] border border-line-strong bg-surface px-3 text-[15px] text-ink placeholder:text-ink-faint/80 transition-colors hover:border-lavender focus:border-lavender-deep focus:outline-none focus:ring-2 focus:ring-lavender/30 disabled:bg-paper disabled:text-ink-faint aria-[invalid=true]:border-danger";

export function Field({
  label,
  hint,
  error,
  children,
}: {
  label: string;
  hint?: string;
  error?: string | null;
  children: (props: { id: string; describedBy?: string; invalid: boolean }) => ReactNode;
}) {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined;
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium text-ink-soft">
        {label}
      </label>
      {children({ id, describedBy, invalid: Boolean(error) })}
      {hint && !error ? (
        <p id={hintId} className="text-xs text-ink-faint">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} role="alert" className="text-sm text-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
}

export function Input({ className = "", ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`${CONTROL} h-10 ${className}`} />;
}

export function Select({
  className = "",
  children,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select {...props} className={`${CONTROL} h-10 pr-8 ${className}`}>
      {children}
    </select>
  );
}
