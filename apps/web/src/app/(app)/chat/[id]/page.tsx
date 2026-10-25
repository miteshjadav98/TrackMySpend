import type { Metadata } from "next";
import { Suspense } from "react";

import { ChatView } from "@/components/chat/chat-view";

export const metadata: Metadata = { title: "Chat" };

export default function ConversationPage({ params }: PageProps<"/chat/[id]">) {
  return (
    <Suspense fallback={<div className="flex-1" />}>
      <Conversation params={params} />
    </Suspense>
  );
}

async function Conversation({ params }: { params: PageProps<"/chat/[id]">["params"] }) {
  const { id } = await params;
  return <ChatView key={id} conversationId={id} />;
}
