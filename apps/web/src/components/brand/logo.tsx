import { cn } from "@/lib/utils";

/** The MindMitra mark: two soft arcs holding a small circle ("a friend beside you"). */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 32 32"
      aria-hidden="true"
      focusable="false"
      className={cn("size-8 shrink-0", className)}
    >
      <rect width="32" height="32" rx="9" className="fill-primary" />
      <path
        d="M7 20c0-5 4-9 9-9s9 4 9 9"
        fill="none"
        strokeWidth="2.4"
        strokeLinecap="round"
        className="stroke-primary-foreground"
      />
      <circle cx="16" cy="19" r="3" className="fill-primary-foreground" />
    </svg>
  );
}

export function Logo({ className, showName = true }: { className?: string; showName?: boolean }) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <LogoMark />
      {showName ? (
        <span className="text-lg font-semibold tracking-tight text-foreground">MindMitra</span>
      ) : (
        <span className="sr-only">MindMitra</span>
      )}
    </span>
  );
}
