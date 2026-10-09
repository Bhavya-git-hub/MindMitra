"use client";

import { Menu } from "lucide-react";
import * as React from "react";

import { Logo } from "@/components/brand/logo";
import { SidebarNav } from "@/components/layout/sidebar";
import { GetHelpButton } from "@/components/safety/get-help-button";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import type { Role } from "@/lib/auth/roles";

/** Slide-in navigation for small screens. Closes itself after a link is chosen. */
export function MobileNav({ role }: { role: Role }) {
  const [open, setOpen] = React.useState(false);
  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <Button variant="ghost" size="icon" className="md:hidden" aria-label="Open menu">
          <Menu className="size-5" aria-hidden="true" />
        </Button>
      </SheetTrigger>
      <SheetContent side="left" className="w-72 bg-sidebar p-4">
        <SheetHeader className="p-0">
          <SheetTitle>
            <Logo />
          </SheetTitle>
          <SheetDescription className="sr-only">Main navigation</SheetDescription>
        </SheetHeader>
        <SidebarNav role={role} onNavigate={() => setOpen(false)} className="mt-6 flex-1" />
        {role === "student" && <GetHelpButton className="mt-auto w-full" />}
      </SheetContent>
    </Sheet>
  );
}
