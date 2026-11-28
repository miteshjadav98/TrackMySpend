import type { Metadata } from "next";
import { Suspense } from "react";
import { AccountsScreen } from "@/components/accounts/accounts-screen";

export const metadata: Metadata = { title: "Accounts" };

export default function AccountsPage() {
  return <Suspense fallback={<p role="status" className="p-6">Loading accounts…</p>}><AccountsScreen /></Suspense>;
}
