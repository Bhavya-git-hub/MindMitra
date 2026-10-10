import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { CompanionChatView } from "@/components/student/companion-views";
import { isUuid } from "@/lib/validation";

export const metadata: Metadata = { title: "Companion conversation" };

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!isUuid(id)) notFound();
  return <CompanionChatView conversationId={id} />;
}
