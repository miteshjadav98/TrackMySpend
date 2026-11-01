import type { Metadata } from "next";
import { Suspense } from "react";

import { FriendDetailScreen } from "@/components/friends/friend-detail-screen";

export const metadata: Metadata = { title: "Friend" };

export default function FriendPage({ params }: PageProps<"/friends/[id]">) {
  return (
    <Suspense fallback={<div className="flex-1" />}>
      <Friend params={params} />
    </Suspense>
  );
}

async function Friend({ params }: { params: PageProps<"/friends/[id]">["params"] }) {
  const { id } = await params;
  return <FriendDetailScreen key={id} friendId={id} />;
}
