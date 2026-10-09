import { Sprout } from "lucide-react";

import { EmptyState } from "@/components/states/empty-state";

/** Honest placeholder for dashboard areas that are planned but not built yet. */
export function ComingSoon({ what }: { what: string }) {
  return (
    <EmptyState
      icon={Sprout}
      title={`${what} is on its way`}
      description="We're building this step by step. Nothing here needs your attention yet."
    />
  );
}
