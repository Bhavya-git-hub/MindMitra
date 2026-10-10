import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { EditResourceView } from "@/components/admin/resources-views";
import { isUuid } from "@/lib/validation";

export const metadata: Metadata = { title: "Edit resource" };

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!isUuid(id)) notFound();
  return <EditResourceView id={id} />;
}
