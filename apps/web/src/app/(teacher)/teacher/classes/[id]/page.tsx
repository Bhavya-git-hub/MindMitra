import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { ClassDetailView } from "@/components/teacher/classes-views";
import { isUuid } from "@/lib/validation";

export const metadata: Metadata = { title: "Class" };

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!isUuid(id)) notFound();
  return <ClassDetailView id={id} />;
}
