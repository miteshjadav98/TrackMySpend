import type { Metadata } from "next";
import { Suspense } from "react";

import { TransactionsScreen } from "@/components/transactions/transactions-screen";

export const metadata: Metadata = { title: "Transactions" };

export default function TransactionsPage() {
  return <Suspense fallback={<p role="status" className="p-8 text-ink-soft">Loading transactions…</p>}><TransactionsScreen /></Suspense>;
}
