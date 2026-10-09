import { HeartHandshake, LockKeyhole, Sparkles } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { Logo } from "@/components/brand/logo";
import { SkipLink } from "@/components/layout/skip-link";

const PROMISES = [
  { icon: LockKeyhole, text: "Your conversations stay private to you." },
  { icon: HeartHandshake, text: "Real people, close by, when you want support." },
  { icon: Sparkles, text: "Gentle tools. No scores, no judgement." },
] as const;

/** Shared frame for sign-in, sign-up and password pages. */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="bg-calm min-h-dvh lg:grid lg:grid-cols-[minmax(0,1fr)_minmax(0,32rem)]">
      <SkipLink />
      <aside className="hidden flex-col justify-between p-12 lg:flex">
        <Logo />
        <div className="max-w-md space-y-8">
          <h2 className="text-4xl leading-tight font-semibold">
            A calm place to check in with yourself.
          </h2>
          <ul className="space-y-4">
            {PROMISES.map(({ icon: Icon, text }) => (
              <li key={text} className="flex items-center gap-3 text-lg text-secondary-foreground">
                <span className="grid size-10 shrink-0 place-items-center rounded-full bg-secondary">
                  <Icon className="size-5" aria-hidden="true" />
                </span>
                {text}
              </li>
            ))}
          </ul>
        </div>
        <p className="text-sm text-muted-foreground">
          Need help right now?{" "}
          <Link href="/help" className="font-medium text-primary underline underline-offset-4">
            Get help
          </Link>
        </p>
      </aside>
      <div className="flex min-h-dvh flex-col items-center justify-center gap-6 px-4 py-10 lg:bg-background/70">
        <Link href="/login" className="rounded-lg lg:hidden" aria-label="MindMitra home">
          <Logo />
        </Link>
        <main id="main-content" tabIndex={-1} className="w-full max-w-md outline-none">
          {children}
        </main>
        <p className="text-sm text-muted-foreground lg:hidden">
          Need help right now?{" "}
          <Link href="/help" className="font-medium text-primary underline underline-offset-4">
            Get help
          </Link>
        </p>
      </div>
    </div>
  );
}
