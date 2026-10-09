import type { Metadata } from "next";

import { LoginForm } from "@/components/auth/login-form";

export const metadata: Metadata = { title: "Sign in" };

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { next } = await searchParams;
  return <LoginForm next={typeof next === "string" ? next : undefined} />;
}
