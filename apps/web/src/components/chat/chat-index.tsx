"use client";

import type { ConversationView } from "@moneymoney/contracts";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { api, unwrap } from "@/lib/api";
import { keys, useConversations, useQueryClient } from "@/lib/queries";

/** /chat opens an unused conversation if there is one, so visiting it never piles up empties. */
export function ChatIndex() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const conversations = useConversations();
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);

  useEffect(() => {
    if (!conversations.data || started.current) return;
    started.current = true;
    const empty = conversations.data.items.find((conversation) => conversation.title === null);
    if (empty) {
      router.replace(`/chat/${empty.id}`);
      return;
    }
    unwrap<ConversationView>(api.POST("/api/v1/conversations", { body: {} }))
      .then(async (created) => {
        await queryClient.invalidateQueries({ queryKey: keys.conversations });
        router.replace(`/chat/${created.id}`);
      })
      .catch((caught: Error) => setError(caught.message));
  }, [conversations.data, router, queryClient]);

  if (error || conversations.isError) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-4 px-6 text-center">
        <p className="text-ink-soft">{error ?? conversations.error?.message}</p>
        <Button variant="primary" onClick={() => window.location.reload()}>
          Try again
        </Button>
      </div>
    );
  }
  return <div className="flex flex-1 items-center justify-center text-sm text-ink-faint">Opening chat…</div>;
}
