"use client";

import type { ConversationView, MeView } from "@moneymoney/contracts";
import { List, LogOut, MessageSquare, Plus, Settings, X } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";

import { useToast } from "@/components/ui/toast";
import { api, unwrap } from "@/lib/api";
import { formatRelative } from "@/lib/format";
import { keys, useConversations, useQueryClient } from "@/lib/queries";

const NAV = [
  { href: "/chat", label: "Chat", icon: MessageSquare },
  { href: "/transactions", label: "Transactions", icon: List },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function Sidebar({ me, open, onClose }: { me: MeView; open: boolean; onClose: () => void }) {
  const pathname = usePathname();
  const router = useRouter();
  const queryClient = useQueryClient();
  const conversations = useConversations();
  const toast = useToast();
  const [creating, setCreating] = useState(false);

  async function newChat() {
    setCreating(true);
    try {
      const created = await unwrap<ConversationView>(api.POST("/api/v1/conversations", { body: {} }));
      await queryClient.invalidateQueries({ queryKey: keys.conversations });
      onClose();
      router.push(`/chat/${created.id}`);
    } catch (error) {
      toast((error as Error).message, { tone: "error" });
    } finally {
      setCreating(false);
    }
  }

  async function signOut() {
    await api.POST("/api/v1/auth/logout").catch(() => undefined);
    queryClient.clear();
    router.replace("/login");
  }

  return (
    <>
      <div
        className={`fixed inset-0 z-30 bg-ink/30 md:hidden ${open ? "block" : "hidden"}`}
        onClick={onClose}
        aria-hidden
      />
      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-72 flex-col border-r border-line bg-surface transition-transform md:static md:translate-x-0 ${
          open ? "translate-x-0" : "-translate-x-full"
        }`}
        aria-label="Navigation"
      >
        <div className="flex items-center justify-between px-5 pt-5 pb-4">
          <Link href="/chat" className="display text-xl font-semibold tracking-tight">
            MoneyMoney
          </Link>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-ink-faint hover:bg-lavender-wash md:hidden"
            aria-label="Close navigation"
          >
            <X className="size-5" aria-hidden />
          </button>
        </div>

        <div className="px-3">
          <button
            type="button"
            onClick={newChat}
            disabled={creating}
            className="flex w-full items-center gap-2 rounded-[10px] border border-dashed border-line-strong px-3 py-2.5 text-[15px] font-medium text-lavender-deep transition-colors hover:border-lavender-deep hover:bg-lavender-wash disabled:opacity-60"
          >
            <Plus className="size-4" aria-hidden />
            New chat
          </button>
        </div>

        <nav className="mt-4 flex flex-col gap-0.5 px-3" aria-label="Main">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = pathname === href || pathname.startsWith(`${href}/`);
            return (
              <Link
                key={href}
                href={href}
                onClick={onClose}
                aria-current={active ? "page" : undefined}
                className={`flex items-center gap-3 rounded-[10px] px-3 py-2 text-[15px] transition-colors ${
                  active
                    ? "bg-lavender-wash font-medium text-lavender-ink"
                    : "text-ink-soft hover:bg-paper hover:text-ink"
                }`}
              >
                <Icon className="size-4" aria-hidden />
                {label}
              </Link>
            );
          })}
        </nav>

        <div className="mt-6 min-h-0 flex-1 overflow-y-auto px-3">
          <h2 className="px-3 pb-2 text-xs font-semibold tracking-wide text-ink-faint uppercase">
            Recent chats
          </h2>
          {conversations.data?.items.length ? (
            <ul className="flex flex-col gap-0.5">
              {conversations.data.items.map((conversation) => {
                const href = `/chat/${conversation.id}`;
                const active = pathname === href;
                return (
                  <li key={conversation.id}>
                    <Link
                      href={href}
                      onClick={onClose}
                      aria-current={active ? "page" : undefined}
                      className={`block rounded-[10px] px-3 py-2 transition-colors ${
                        active ? "bg-paper" : "hover:bg-paper"
                      }`}
                    >
                      <span className="block truncate text-sm text-ink">
                        {conversation.title ?? "New chat"}
                      </span>
                      <span className="block text-xs text-ink-faint">
                        {formatRelative(conversation.lastMessageAt)}
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="px-3 text-sm text-ink-faint">
              {conversations.isPending ? "Loading…" : "Your chats will appear here."}
            </p>
          )}
        </div>

        <div className="flex items-center justify-between gap-2 border-t border-line px-5 py-3">
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">{me.user.displayName}</p>
            <p className="truncate text-xs text-ink-faint">{me.user.email}</p>
          </div>
          <button
            type="button"
            onClick={signOut}
            className="rounded-lg p-2 text-ink-faint hover:bg-lavender-wash hover:text-ink"
            aria-label="Sign out"
            title="Sign out"
          >
            <LogOut className="size-4" aria-hidden />
          </button>
        </div>
      </aside>
    </>
  );
}
