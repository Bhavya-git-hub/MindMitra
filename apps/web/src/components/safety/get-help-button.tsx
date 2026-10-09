import { LifeBuoy } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * Always-available route to support (CLAUDE.md: a persistent GetHelpButton on student pages).
 * It links to /help, which lists the institution's own contacts; no phone numbers live here.
 */
export function GetHelpButton({
  className,
  compact = false,
}: {
  className?: string;
  compact?: boolean;
}) {
  return (
    <Button asChild variant="secondary" size={compact ? "sm" : "default"} className={cn(className)}>
      <Link href="/help">
        <LifeBuoy aria-hidden="true" />
        <span>{compact ? "Get help" : "Get help now"}</span>
      </Link>
    </Button>
  );
}
