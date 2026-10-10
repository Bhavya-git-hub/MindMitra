import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { ConversationView } from "@/components/student/messages-views";
import { isUuid } from "@/lib/validation";

export const metadata: Metadata = { title: "Conversation" };

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!isUuid(id)) notFound();
  return <ConversationView otherId={id} />;
}
