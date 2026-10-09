import * as React from "react";

import { cn } from "@/lib/utils";

function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        "flex min-h-24 w-full rounded-lg border border-input bg-card px-3 py-2 text-base shadow-xs transition-colors outline-none md:text-sm",
        "placeholder:text-muted-foreground",
        "focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
        "disabled:cursor-not-allowed disabled:opacity-50",
        "aria-invalid:border-destructive aria-invalid:focus-visible:ring-destructive",
        className,
      )}
      {...props}
    />
  );
}

export { Textarea };
