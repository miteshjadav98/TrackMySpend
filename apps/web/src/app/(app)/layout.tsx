import { Suspense } from "react";

import { AppShell } from "@/components/shell/app-shell";

// The signed-in app is personal and rendered on the client; the boundary lets the static
// shell prerender while the URL-dependent parts stream in.
export default function AppLayout({ children }: LayoutProps<"/">) {
  return (
    <Suspense
      fallback={
        <div className="flex h-dvh items-center justify-center">
          <span className="display text-lg text-ink-faint">MoneyMoney</span>
        </div>
      }
    >
      <AppShell>{children}</AppShell>
    </Suspense>
  );
}
