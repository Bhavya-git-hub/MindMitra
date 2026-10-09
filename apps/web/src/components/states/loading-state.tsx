import { Loader2 } from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/** A polite, announced spinner. `page` centres it in the available space. */
export function LoadingState({
  label = "Loading…",
  page = false,
  className,
}: {
  label?: string;
  page?: boolean;
  className?: string;
}) {
  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        "flex items-center justify-center gap-3 text-muted-foreground",
        page ? "min-h-[50dvh] flex-col" : "py-6",
        className,
      )}
    >
      <Loader2 className={cn("animate-spin", page ? "size-8" : "size-5")} aria-hidden="true" />
      <span className="text-sm">{label}</span>
    </div>
  );
}

/** Placeholder for a portal page while its content loads (used by every `loading.tsx`). */
export function PageSkeleton() {
  return (
    <div role="status" aria-live="polite" className="space-y-8">
      <span className="sr-only">Loading your page…</span>
      <div className="space-y-3">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-4 w-96 max-w-full" />
      </div>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <Skeleton className="h-32" />
        <Skeleton className="h-32" />
        <Skeleton className="h-32 sm:col-span-2 xl:col-span-1" />
      </div>
      <Skeleton className="h-64" />
    </div>
  );
}
