"use client";

import { Check, Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import * as React from "react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

const OPTIONS = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "Match my device", icon: Monitor },
] as const;

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  // false on the server and during hydration, true afterwards (the stored theme is unknown
  // until then, so the checkmark would otherwise mismatch).
  const mounted = React.useSyncExternalStore(
    () => () => {},
    () => true,
    () => false,
  );
  const current = mounted ? (theme ?? "system") : "system";

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label="Change colour theme">
          <Sun className="size-5 dark:hidden" aria-hidden="true" />
          <Moon className="hidden size-5 dark:block" aria-hidden="true" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {OPTIONS.map(({ value, label, icon: Icon }) => (
          <DropdownMenuItem key={value} onSelect={() => setTheme(value)}>
            <Icon aria-hidden="true" />
            <span className="flex-1">{label}</span>
            {current === value && <Check aria-label="Selected" className="size-4" />}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
