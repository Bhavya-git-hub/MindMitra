import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { TherapistProfileView } from "@/components/student/care-views";
import { isUuid } from "@/lib/validation";

export const metadata: Metadata = { title: "Therapist" };

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!isUuid(id)) notFound();
  return <TherapistProfileView id={id} />;
}
