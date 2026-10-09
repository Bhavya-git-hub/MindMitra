"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { Logo } from "@/components/brand/logo";
import { GetHelpButton } from "@/components/safety/get-help-button";
import { Badge } from "@/components/ui/badge";
import { activeHref, NAVIGATION } from "@/lib/navigation";
import type { Role } from "@/lib/auth/roles";
import { PORTAL_PATHS, ROLE_LABELS } from "@/lib/auth/roles";
import { cn } from "@/lib/utils";

/** The portal menu. Rendered in the desktop sidebar and again inside the mobile sheet. */
export function SidebarNav({
  role,
  onNavigate,
  className,
}: {
  role: Role;
  onNavigate?: () => void;
  className?: string;
}) {
  const pathname = usePathname();
  const items = NAVIGATION[role];
  const active = activeHref(items, pathname);

  return (
    <nav aria-label={`${ROLE_LABELS[role]} navigation`} className={className}>
      <ul className="grid gap-1">
        {items.map(({ label, href, icon: Icon, soon }) => {
          const base =
            "flex min-h-10 items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors";
          if (soon) {
            return (
              <li key={href}>
                <span
                  aria-disabled="true"
                  className={cn(base, "cursor-not-allowed text-muted-foreground")}
                >
                  <Icon className="size-5 shrink-0" aria-hidden="true" />
                  <span className="flex-1">{label}</span>
                  <Badge variant="outline">Soon</Badge>
                </span>
              </li>
            );
          }
          const isActive = href === active;
          return (
            <li key={href}>
              <Link
                href={href}
                onClick={onNavigate}
                aria-current={isActive ? "page" : undefined}
                className={cn(
                  base,
                  isActive
                    ? "bg-sidebar-accent text-sidebar-accent-foreground"
                    : "text-sidebar-foreground hover:bg-sidebar-accent/60",
                )}
              >
                <Icon className="size-5 shrink-0" aria-hidden="true" />
                {label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

export function Sidebar({ role }: { role: Role }) {
  return (
    <aside className="sticky top-0 hidden h-dvh flex-col gap-6 border-r border-sidebar-border bg-sidebar p-4 md:flex">
      <Link href={PORTAL_PATHS[role]} className="rounded-lg px-2 py-1" aria-label="MindMitra home">
        <Logo />
      </Link>
      <SidebarNav role={role} className="flex-1 overflow-y-auto" />
      {role === "student" && <GetHelpButton className="w-full" />}
    </aside>
  );
}
