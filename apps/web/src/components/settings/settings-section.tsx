import { type ReactNode, useId } from "react";

/**
 * The frame every settings section shares: a heading, a one-line description, and the
 * section's own content on a card. Sections pass their content as children, so they all look
 * alike without repeating the layout.
 */
export function SettingsSection({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: ReactNode;
}) {
  const headingId = useId();
  return (
    <section aria-labelledby={headingId}>
      <h2 id={headingId} className="display text-lg font-semibold">
        {title}
      </h2>
      <p className="mt-1 text-ink-soft">{description}</p>
      <div className="mt-4 rounded-[var(--radius-card)] border border-line bg-surface p-5 shadow-[var(--shadow-card)]">
        {children}
      </div>
    </section>
  );
}
