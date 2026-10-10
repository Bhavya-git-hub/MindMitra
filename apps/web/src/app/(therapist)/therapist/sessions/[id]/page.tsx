import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { SessionDetailView } from "@/components/therapist/sessions-views";
import { isUuid } from "@/lib/validation";

export const metadata: Metadata = { title: "Session" };

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!isUuid(id)) notFound();
  return <SessionDetailView id={id} />;
}
