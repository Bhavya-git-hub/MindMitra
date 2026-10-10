"use client";

import { Sprout } from "lucide-react";
import * as React from "react";

import { SectionCard } from "@/components/cards/section-card";
import { PageHeader } from "@/components/layout/page-header";
import { DisclaimerBanner } from "@/components/safety/disclaimer-banner";
import { Badge } from "@/components/ui/badge";
import { useAuth } from "@/lib/auth/auth-context";
import { ROLE_LABELS, type Role } from "@/lib/auth/roles";
import { firstName } from "@/lib/format";

export interface PlannedArea {
  title: string;
  description: string;
}

/**
 * Placeholder landing page for a portal. The real dashboards come later; this proves the
 * shell, the guard and the user's identity, and shows what is planned.
 */
export function PortalOverview({
  role,
  description,
  planned,
}: {
  role: Role;
  description: string;
  planned: PlannedArea[];
}) {
  const { user } = useAuth();
  return (
    <>
      <PageHeader
        title={user ? `Welcome, ${firstName(user.full_name)}` : "Welcome"}
        description={description}
        actions={<Badge variant="accent">{ROLE_LABELS[role]} space</Badge>}
      />
      {role === "student" && <DisclaimerBanner />}
      <section aria-labelledby="planned-heading" className="space-y-4">
        <h2 id="planned-heading" className="text-lg font-semibold">
          Coming soon
        </h2>
        <ul className="grid gap-4 sm:grid-cols-2">
          {planned.map((area) => (
            <li key={area.title}>
              <SectionCard
                title={area.title}
                description={area.description}
                headingLevel="h3"
                className="h-full"
                action={<Sprout className="size-5 text-muted-foreground" aria-hidden="true" />}
              />
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}
