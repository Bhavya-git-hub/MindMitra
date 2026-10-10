import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { StudentProfileView } from "@/components/therapist/students-views";
import { isUuid } from "@/lib/validation";

export const metadata: Metadata = { title: "Student" };

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!isUuid(id)) notFound();
  return <StudentProfileView id={id} />;
}
