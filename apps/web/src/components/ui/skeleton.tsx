import { cn } from "@/lib/utils";

/** A calm placeholder block. Decorative: pair with a labelled `role="status"` region. */
function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="skeleton"
      aria-hidden="true"
      className={cn("animate-pulse rounded-lg bg-muted", className)}
      {...props}
    />
  );
}

export { Skeleton };
