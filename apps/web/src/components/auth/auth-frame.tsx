import type { ReactNode } from "react";

/** Split layout: the product's whole idea on the left, the form on the right. */
export function AuthFrame({ children }: { children: ReactNode }) {
  return (
    <main className="grid min-h-dvh lg:grid-cols-[1.1fr_1fr]">
      <section
        aria-hidden
        className="relative hidden overflow-hidden bg-night px-14 py-16 text-white lg:flex lg:flex-col lg:justify-between"
      >
        <p className="display text-xl font-semibold tracking-tight">MoneyMoney</p>
        <div className="max-w-md">
          <p className="display text-[2.6rem] leading-[1.08] font-semibold">
            Say what you spent.
            <br />
            <span className="text-lavender">It&apos;s in your books.</span>
          </p>
          <div className="mt-10 space-y-3">
            <div className="ml-auto w-fit max-w-[85%] rounded-2xl rounded-br-md bg-lavender-fill px-4 py-2.5 text-[15px]">
              ₹350 on dinner yesterday, paid by UPI
            </div>
            <div className="w-[88%] rounded-2xl rounded-bl-md bg-white/[0.07] p-4 ring-1 ring-white/10">
              <div className="flex items-baseline justify-between">
                <span className="text-sm text-white/70">Dinner · Food &amp; Dining</span>
                <span className="figure text-2xl font-semibold">₹350.00</span>
              </div>
              <div className="mt-2 flex gap-3 text-xs text-white/55">
                <span>Yesterday</span>
                <span>UPI</span>
                <span className="text-turmeric">Saved</span>
              </div>
            </div>
          </div>
        </div>
        <p className="text-sm text-white/50">
          Totals are added up from your saved entries, never guessed.
        </p>
      </section>
      <section className="flex items-center justify-center px-5 py-12">
        <div className="w-full max-w-sm">
          <p className="display mb-10 text-xl font-semibold lg:hidden">MoneyMoney</p>
          {children}
        </div>
      </section>
    </main>
  );
}
