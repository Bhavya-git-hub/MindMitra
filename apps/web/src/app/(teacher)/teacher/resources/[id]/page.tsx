import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { TeacherResourceDetailView } from "@/components/teacher/resources-views";
import { isUuid } from "@/lib/validation";

export const metadata: Metadata = { title: "Resource" };

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!isUuid(id)) notFound();
  return <TeacherResourceDetailView id={id} />;
}
