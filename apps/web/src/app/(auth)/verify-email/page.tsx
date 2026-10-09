import type { Metadata } from "next";

import { VerifyEmailView } from "@/components/auth/verify-email-view";

export const metadata: Metadata = { title: "Verify email" };

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { token } = await searchParams;
  return <VerifyEmailView token={typeof token === "string" ? token : undefined} />;
}
