import type { Metadata } from "next";
import { Suspense } from "react";

import { ReportsScreen } from "@/components/reports/reports-screen";

export const metadata: Metadata = { title: "Reports" };

export default function ReportsPage() {
  return (
    <Suspense fallback={<p role="status" className="p-8 text-ink-soft">Loading reports…</p>}>
      <ReportsScreen />
    </Suspense>
  );
}
