"use client";

import type { ConversationPage, ConversationView } from "@moneymoney/contracts";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { api, unwrap } from "@/lib/api";
import { keys, useQueryClient } from "@/lib/queries";

/**
 * /chat opens an unused conversation if there is one, so visiting it never piles up empties.
 *
 * Next.js keeps this page alive between visits (React <Activity>): its state survives, and its
 * effect runs again each time it is shown. So the effect below works on every visit, and asks
 * the server each time, because the cached list can still show a conversation as unused after
 * the user has written in it.
 */
export function ChatIndex() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  // The lookup in progress. React may run the effect twice in a row; both runs share this one
  // lookup, so they can't create two conversations.
  const opening = useRef<Promise<string> | null>(null);

  useEffect(() => {
    let leftThePage = false;
    opening.current ??= findOrCreateUnusedConversation().finally(() => {
      opening.current = null;
    });
    opening.current
      .then(async (id) => {
        await queryClient.invalidateQueries({ queryKey: keys.conversations });
        if (!leftThePage) router.replace(`/chat/${id}`);
      })
      .catch((caught: Error) => {
        if (!leftThePage) setError(caught.message);
      });
    return () => {
      leftThePage = true;
    };
  }, [router, queryClient]);

  if (error) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-4 px-6 text-center">
        <p className="text-ink-soft">{error}</p>
        <Button variant="primary" onClick={() => window.location.reload()}>
          Try again
        </Button>
      </div>
    );
  }
  return <div className="flex flex-1 items-center justify-center text-sm text-ink-faint">Opening chat…</div>;
}

/** The id of a conversation with no messages yet (it has no title), creating one if needed. */
async function findOrCreateUnusedConversation(): Promise<string> {
  const page = await unwrap<ConversationPage>(
    api.GET("/api/v1/conversations", { params: { query: { limit: 30 } } }),
  );
  const unused = page.items.find((conversation) => conversation.title === null);
  if (unused) return unused.id;
  const created = await unwrap<ConversationView>(api.POST("/api/v1/conversations", { body: {} }));
  return created.id;
}
