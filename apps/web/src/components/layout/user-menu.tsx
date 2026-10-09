"use client";

import { LogOut, UserRound } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useAuth } from "@/lib/auth/auth-context";
import { PORTAL_PATHS, ROLE_LABELS } from "@/lib/auth/roles";
import { notify } from "@/lib/toast";

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  const first = parts[0]?.[0] ?? "";
  const last = parts.length > 1 ? (parts[parts.length - 1]?.[0] ?? "") : "";
  return (first + last).toUpperCase() || "?";
}

export function UserMenu() {
  const { user, logout } = useAuth();
  const router = useRouter();
  const [signingOut, setSigningOut] = React.useState(false);
  if (!user) return null;

  async function signOut() {
    setSigningOut(true);
    await logout();
    notify.success("You're signed out", "Take care of yourself.");
    router.replace("/login");
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" className="h-10 gap-2 px-1.5 sm:px-2" aria-label="Account menu">
          <Avatar className="size-8">
            <AvatarFallback>{initials(user.full_name)}</AvatarFallback>
          </Avatar>
          <span className="hidden max-w-32 truncate text-sm sm:inline">{user.full_name}</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60">
        <DropdownMenuLabel className="space-y-0.5">
          <span className="block truncate">{user.full_name}</span>
          <span className="block truncate text-xs font-normal text-muted-foreground">
            {user.email}
          </span>
          <span className="block text-xs font-normal text-muted-foreground">
            {ROLE_LABELS[user.role]}
          </span>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link href={`${PORTAL_PATHS[user.role]}/account`}>
            <UserRound aria-hidden="true" />
            Account
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem disabled={signingOut} onSelect={() => void signOut()}>
          <LogOut aria-hidden="true" />
          Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
