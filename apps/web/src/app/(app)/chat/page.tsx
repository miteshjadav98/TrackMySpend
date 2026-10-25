import type { Metadata } from "next";

import { ChatIndex } from "@/components/chat/chat-index";

export const metadata: Metadata = { title: "Chat" };

export default function ChatPage() {
  return <ChatIndex />;
}
