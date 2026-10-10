import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { ReferralDetailView } from "@/components/teacher/referrals-views";
import { isUuid } from "@/lib/validation";

export const metadata: Metadata = { title: "Referral" };

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!isUuid(id)) notFound();
  return <ReferralDetailView id={id} />;
}
