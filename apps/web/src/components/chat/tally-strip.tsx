"use client";

import { useEffect, useRef, useState } from "react";

import { AnimatedMoney } from "@/components/chat/animated-money";
import { useMe, useSummary } from "@/lib/queries";

/**
 * The month so far, always in view while chatting. When a message records money the
 * figures roll forward and the change is called out, so every entry visibly lands in
 * the books.
 */
export function TallyStrip() {
  const me = useMe();
  const summary = useSummary("this_month");
  const locale = me.data?.profile.locale ?? "en-IN";
  const base = me.data?.profile.baseCurrency ?? "INR";
  const totals = summary.data?.currencies.find((c) => c.currency === base);
  const spent = totals?.expense.amountMinor ?? 0;
  const received = totals?.income.amountMinor ?? 0;
  const others = summary.data?.currencies.filter((c) => c.currency !== base) ?? [];

  const [delta, setDelta] = useState<number | null>(null);
  const previous = useRef<number | null>(null);
  useEffect(() => {
    if (summary.data === undefined) return;
    if (previous.current !== null && spent > previous.current) {
      setDelta(spent - previous.current);
      const timer = window.setTimeout(() => setDelta(null), 2600);
      previous.current = spent;
      return () => window.clearTimeout(timer);
    }
    previous.current = spent;
    return undefined;
  }, [spent, summary.data]);

  const scale = 10 ** (new Intl.NumberFormat(locale, { style: "currency", currency: base }).resolvedOptions().maximumFractionDigits ?? 2);

  return (
    <section
      aria-label="This month so far"
      className="flex flex-wrap items-end gap-x-8 gap-y-2 border-b border-line bg-surface px-5 py-3 md:px-8"
    >
      <div className="min-w-0">
        <p className="text-xs font-semibold tracking-wide text-ink-faint uppercase">
          {summary.data?.period.label ?? "This month"} · spent
        </p>
        <div className="flex items-baseline gap-3">
          <AnimatedMoney
            minor={spent}
            currency={base}
            locale={locale}
            className="figure text-[1.9rem] leading-none font-semibold text-ink"
          />
          {delta ? (
            <span className="rise-in rounded-full bg-turmeric-wash px-2 py-0.5 text-xs font-semibold text-turmeric-ink">
              +{new Intl.NumberFormat(locale, { style: "currency", currency: base }).format(delta / scale)}
            </span>
          ) : null}
        </div>
      </div>
      <div>
        <p className="text-xs font-semibold tracking-wide text-ink-faint uppercase">Received</p>
        <AnimatedMoney
          minor={received}
          currency={base}
          locale={locale}
          className="figure text-xl leading-none font-semibold text-income"
        />
      </div>
      {others.length ? (
        <p className="pb-0.5 text-xs text-ink-faint">
          Also: {others.map((c) => `${c.expense.formatted} spent in ${c.currency}`).join(", ")}
        </p>
      ) : null}
    </section>
  );
}
