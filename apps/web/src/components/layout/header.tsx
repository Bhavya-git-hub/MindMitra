import Link from "next/link";

import { Logo } from "@/components/brand/logo";
import { MobileNav } from "@/components/layout/mobile-nav";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import { UserMenu } from "@/components/layout/user-menu";
import { GetHelpButton } from "@/components/safety/get-help-button";
import { PORTAL_PATHS, type Role } from "@/lib/auth/roles";

export function Header({ role }: { role: Role }) {
  return (
    <header className="sticky top-0 z-30 flex h-16 items-center gap-1 border-b bg-background/90 px-2 backdrop-blur sm:gap-2 sm:px-6">
      <MobileNav role={role} />
      <Link href={PORTAL_PATHS[role]} className="rounded-lg md:hidden" aria-label="MindMitra home">
        <Logo showName={false} />
      </Link>
      <div className="flex-1" />
      {role === "student" && <GetHelpButton compact className="md:hidden" />}
      <ThemeToggle />
      <UserMenu />
    </header>
  );
}
