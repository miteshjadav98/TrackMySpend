"use client";

import { Menu } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { type ReactNode, useEffect, useState } from "react";

import { Sidebar } from "@/components/shell/sidebar";
import { Button } from "@/components/ui/button";
import { isUnauthenticated } from "@/lib/api";
import { useMe } from "@/lib/queries";

export function AppShell({ children }: { children: ReactNode }) {
  const me = useMe();
  const router = useRouter();
  const pathname = usePathname();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const signedOut = isUnauthenticated(me.error);

  useEffect(() => {
    if (signedOut) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
  }, [signedOut, pathname, router]);


  if (me.isPending || signedOut) {
    return (
      <div className="flex h-dvh items-center justify-center" aria-busy>
        <span className="display text-lg text-ink-faint">MoneyMoney</span>
      </div>
    );
  }
  if (me.isError) {
    return (
      <div className="flex h-dvh flex-col items-center justify-center gap-4 px-6 text-center">
        <p className="text-ink-soft">{me.error.message}</p>
        <Button variant="primary" onClick={() => me.refetch()}>
          Try again
        </Button>
      </div>
    );
  }

  return (
    <div className="flex h-dvh overflow-hidden">
      <Sidebar me={me.data} open={drawerOpen} onClose={() => setDrawerOpen(false)} />
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex h-12 items-center border-b border-line bg-surface px-3 md:hidden">
          <button
            type="button"
            onClick={() => setDrawerOpen(true)}
            className="rounded-lg p-2 text-ink-soft hover:bg-lavender-wash"
            aria-label="Open navigation"
          >
            <Menu className="size-5" aria-hidden />
          </button>
          <span className="display ml-2 font-semibold">MoneyMoney</span>
        </div>
        <main className="flex min-h-0 flex-1 flex-col">{children}</main>
      </div>
    </div>
  );
}
