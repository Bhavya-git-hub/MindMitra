import { LifeBuoy } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";

/** Kind words and a way to reach someone, shown after a check-in or message that suggests it. */
export function SupportCallout({ message }: { message: string }) {
  return (
    <div role="status" className="space-y-3 rounded-xl border border-info/30 bg-info-soft p-5">
      <p className="flex items-start gap-3 text-info">
        <LifeBuoy className="mt-0.5 size-5 shrink-0" aria-hidden="true" />
        <span>{message}</span>
      </p>
      <div className="flex flex-wrap gap-2">
        <Button asChild>
          <Link href="/student/emergency">See ways to get support</Link>
        </Button>
      </div>
    </div>
  );
}
