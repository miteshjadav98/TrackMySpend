"use client";

import { useEffect, useMemo, useRef, useState } from "react";

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/**
 * An exact amount (integer minor units) that rolls to its new value. Screen readers get
 * only the final value; the animation is visual and skipped under reduced motion.
 */
export function AnimatedMoney({
  minor,
  currency,
  locale = "en-IN",
  className = "",
}: {
  minor: number;
  currency: string;
  locale?: string;
  className?: string;
}) {
  const formatter = useMemo(
    () => new Intl.NumberFormat(locale, { style: "currency", currency }),
    [locale, currency],
  );
  const scale = 10 ** (formatter.resolvedOptions().maximumFractionDigits ?? 2);
  const [shown, setShown] = useState(minor);
  const previous = useRef(minor);

  useEffect(() => {
    const from = previous.current;
    previous.current = minor;
    if (from === minor || prefersReducedMotion()) {
      setShown(minor);
      return;
    }
    const started = performance.now();
    const duration = 750;
    let frame = 0;
    const tick = (now: number) => {
      const t = Math.min(1, (now - started) / duration);
      const eased = 1 - (1 - t) ** 3;
      setShown(Math.round(from + (minor - from) * eased));
      if (t < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [minor]);

  return (
    <span className={className}>
      <span aria-hidden>{formatter.format(shown / scale)}</span>
      <span className="sr-only">{formatter.format(minor / scale)}</span>
    </span>
  );
}
