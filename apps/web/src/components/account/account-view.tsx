"use client";

import { LogOut } from "lucide-react";
import { useRouter } from "next/navigation";
import * as React from "react";

import { SectionCard } from "@/components/cards/section-card";
import { PageHeader } from "@/components/layout/page-header";
import { useModal } from "@/components/providers/modal-provider";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth/auth-context";
import { ROLE_LABELS } from "@/lib/auth/roles";
import { notify } from "@/lib/toast";

/** The signed-in person's own details and sign-out. Shared by all four portals. */
export function AccountView() {
  const { user, logout } = useAuth();
  const modal = useModal();
  const router = useRouter();
  if (!user) return null;

  async function signOut() {
    const ok = await modal.confirm({
      title: "Sign out of MindMitra?",
      description: "You'll need to sign in again to get back to your space.",
      confirmLabel: "Sign out",
    });
    if (!ok) return;
    await logout();
    notify.success("You're signed out", "Take care of yourself.");
    router.replace("/login");
  }

  const rows: [string, string][] = [
    ["Name", user.full_name],
    ["Email", user.email],
    ["Role", ROLE_LABELS[user.role]],
    ["Account status", user.status.charAt(0).toUpperCase() + user.status.slice(1)],
  ];

  return (
    <>
      <PageHeader title="Account" description="The details MindMitra has for you." />
      <SectionCard title="Your details">
        <dl className="grid gap-4 sm:grid-cols-2">
          {rows.map(([term, detail]) => (
            <div key={term} className="space-y-1">
              <dt className="text-sm text-muted-foreground">{term}</dt>
              <dd className="font-medium break-words">{detail}</dd>
            </div>
          ))}
        </dl>
      </SectionCard>
      <SectionCard title="Session" description="Signing out ends this session on this device.">
        <Button variant="outline" onClick={() => void signOut()}>
          <LogOut aria-hidden="true" />
          Sign out
        </Button>
      </SectionCard>
    </>
  );
}
