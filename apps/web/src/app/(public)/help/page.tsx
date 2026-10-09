import { LifeBuoy, Phone, Users } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { Logo } from "@/components/brand/logo";
import { SkipLink } from "@/components/layout/skip-link";
import { SectionCard } from "@/components/cards/section-card";
import { InlineAlert } from "@/components/states/inline-alert";
import { Button } from "@/components/ui/button";

export const metadata: Metadata = { title: "Get help" };

/**
 * Public on purpose: it must work when someone is signed out or cannot sign in. It carries no
 * hard-coded phone numbers; the institution's own crisis contacts are configured per
 * institution and will be listed here once that setting exists.
 */
export default function HelpPage() {
  return (
    <div className="bg-calm min-h-dvh">
      <SkipLink />
      <header className="mx-auto flex max-w-3xl items-center justify-between px-4 py-6">
        <Link href="/" aria-label="MindMitra home">
          <Logo />
        </Link>
        <Button asChild variant="ghost">
          <Link href="/login">Sign in</Link>
        </Button>
      </header>
      <main
        id="main-content"
        tabIndex={-1}
        className="mx-auto max-w-3xl space-y-6 px-4 pb-16 outline-none"
      >
        <div className="space-y-2">
          <h1 className="text-3xl font-semibold">You don&apos;t have to handle this alone</h1>
          <p className="text-lg text-muted-foreground">
            If something feels like too much, reaching out is a strong thing to do. Here is where to
            start.
          </p>
        </div>

        <InlineAlert tone="warning" title="If you or someone else is in immediate danger">
          Call your local emergency number now, or go to the nearest emergency department. If you
          can, tell someone near you.
        </InlineAlert>

        <SectionCard
          title="Talk to someone at your institution"
          description="Counsellors are here for students, and conversations are confidential."
        >
          <div className="flex items-start gap-3 text-sm text-muted-foreground">
            <Users className="mt-0.5 size-5 shrink-0" aria-hidden="true" />
            <p>
              Your institution&apos;s counselling team and crisis contacts will be listed on this
              page once your institution has added them. Until then, ask your department office or
              student services for the counselling centre.
            </p>
          </div>
        </SectionCard>

        <SectionCard title="Crisis lines" description="Free, private, and available to anyone.">
          <div className="flex items-start gap-3 text-sm text-muted-foreground">
            <Phone className="mt-0.5 size-5 shrink-0" aria-hidden="true" />
            <p>
              Search for a crisis or suicide-prevention helpline in your country, or ask a trusted
              adult to help you find one. MindMitra does not replace these services.
            </p>
          </div>
        </SectionCard>

        <SectionCard
          title="About MindMitra"
          description="So you know what this tool is, and isn't."
        >
          <div className="flex items-start gap-3 text-sm text-muted-foreground">
            <LifeBuoy className="mt-0.5 size-5 shrink-0" aria-hidden="true" />
            <p>
              MindMitra is a supportive tool. It does not diagnose, treat or monitor emergencies,
              and it is not a substitute for a professional or for emergency services.
            </p>
          </div>
        </SectionCard>
      </main>
    </div>
  );
}
