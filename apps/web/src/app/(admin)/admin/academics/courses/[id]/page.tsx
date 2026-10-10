import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { CourseDetailView } from "@/components/admin/academics-views";
import { isUuid } from "@/lib/validation";

export const metadata: Metadata = { title: "Course" };

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!isUuid(id)) notFound();
  return <CourseDetailView id={id} />;
}
