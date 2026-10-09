import * as React from "react";

import { cn } from "@/lib/utils";

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        "flex h-10 w-full min-w-0 rounded-lg border border-input bg-card px-3 py-2 text-base shadow-xs transition-colors outline-none md:text-sm",
        "placeholder:text-muted-foreground file:border-0 file:bg-transparent file:text-sm file:font-medium",
        "focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
        "disabled:cursor-not-allowed disabled:opacity-50",
        "aria-invalid:border-destructive aria-invalid:focus-visible:ring-destructive",
        className,
      )}
      {...props}
    />
  );
}

export { Input };
