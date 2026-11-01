"use client";

import type { NoticeView } from "@moneymoney/contracts";
import { Users } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { markNoticesRead, useNotices, useQueryClient } from "@/lib/queries";

/**
 * The "Shared with you" card: what friends changed in shared records since the last visit.
 *
 * Next.js keeps pages alive between visits (React `<Activity>`), so state survives and an effect
 * runs again each time the page shows. The first effect therefore asks the server on every show,
 * and clears what the last visit left behind when the page hides.
 *
 * Notices are marked read as soon as they appear, but stay on the card for this visit, so the
 * user can read them even though the nav badge has already cleared.
 */
export function SharedWithYouCard() {
  const queryClient = useQueryClient();
  const notices = useNotices();
  const [shown, setShown] = useState<NoticeView[]>([]);

  useEffect(() => {
    void queryClient.invalidateQueries({ queryKey: ["notices"] });
    return () => setShown([]);
  }, [queryClient]);

  const unread = notices.data?.items.filter((notice) => !notice.isRead) ?? [];
  // Set during render, not in an effect: React re-renders at once with the new notices kept.
  const fresh = unread.filter((notice) => !shown.some((seen) => seen.id === notice.id));
  if (fresh.length > 0) setShown([...fresh, ...shown]);

  const unreadKey = unread.map((notice) => notice.id).join(",");
  useEffect(() => {
    if (unreadKey) void markNoticesRead(queryClient, unreadKey.split(","));
  }, [unreadKey, queryClient]);

  if (shown.length === 0) return null;
  return (
    <section
      aria-labelledby="shared-with-you-heading"
      className="rounded-[var(--radius-card)] border border-line bg-lavender-wash px-5 py-4 shadow-[var(--shadow-card)]"
    >
      <h2 id="shared-with-you-heading" className="flex items-center gap-2 text-sm font-semibold text-lavender-ink">
        <Users className="size-4" aria-hidden />
        Shared with you
      </h2>
      <ul className="mt-2 flex flex-col gap-1.5">
        {shown.map((notice) => (
          <li key={notice.id} className="text-[15px]">
            <Link
              href={notice.friendId ? `/friends/${notice.friendId}` : "/friends"}
              className="text-ink hover:text-lavender-deep hover:underline"
            >
              {notice.message}
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
