import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { ResourceDetailView } from "@/components/student/resources-views";
import { isUuid } from "@/lib/validation";

export const metadata: Metadata = { title: "Resource" };

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!isUuid(id)) notFound();
  return <ResourceDetailView id={id} />;
}
