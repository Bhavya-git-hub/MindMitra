import { Info } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { cn } from "@/lib/utils";

/**
 * Honest framing for anything AI-assisted (CLAUDE.md: never imply diagnosis). Shown wherever
 * the companion or insights appear.
 */
export function DisclaimerBanner({ className }: { className?: string }) {
  return (
    <Alert variant="info" className={cn(className)}>
      <Info aria-hidden="true" />
      <AlertDescription className="text-info">
        MindMitra offers supportive conversation and gentle patterns, not a diagnosis or medical
        advice. If you are in danger or need someone right now, use Get help.
      </AlertDescription>
    </Alert>
  );
}
