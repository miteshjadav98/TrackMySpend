import { LoaderCircle } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "chip";

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-lavender-deep text-white hover:bg-lavender-ink disabled:bg-lavender-deep/50 shadow-sm",
  secondary:
    "bg-surface text-ink border border-line-strong hover:border-lavender hover:bg-lavender-wash/50 disabled:opacity-50",
  ghost: "text-ink-soft hover:bg-lavender-wash/70 hover:text-ink disabled:opacity-50",
  danger: "bg-danger text-white hover:bg-danger/90 disabled:opacity-50",
  chip: "bg-surface text-ink border border-line-strong hover:border-lavender-deep hover:bg-lavender-wash rounded-full disabled:opacity-50",
};

const SIZES = {
  sm: "h-8 px-3 text-sm gap-1.5",
  md: "h-10 px-4 text-[15px] gap-2",
};

export function Button({
  variant = "secondary",
  size = "md",
  busy = false,
  icon,
  children,
  className = "",
  disabled,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: keyof typeof SIZES;
  busy?: boolean;
  icon?: ReactNode;
}) {
  return (
    <button
      type="button"
      {...props}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      className={`inline-flex items-center justify-center font-medium transition-colors ${
        variant === "chip" ? "" : "rounded-[10px]"
      } ${VARIANTS[variant]} ${SIZES[size]} disabled:cursor-not-allowed ${className}`}
    >
      {busy ? <LoaderCircle aria-hidden className="size-4 animate-spin" /> : icon}
      {children}
    </button>
  );
}
