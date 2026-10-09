import { CircleAlert, CircleCheck, Info, TriangleAlert, type LucideIcon } from "lucide-react";
import * as React from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

type Tone = "info" | "success" | "warning" | "destructive";

const ICONS: Record<Tone, LucideIcon> = {
  info: Info,
  success: CircleCheck,
  warning: TriangleAlert,
  destructive: CircleAlert,
};

/** A message inside the page flow (form errors, confirmations). Icon plus text, never colour alone. */
export function InlineAlert({
  tone = "info",
  title,
  children,
  className,
}: {
  tone?: Tone;
  title?: string;
  children?: React.ReactNode;
  className?: string;
}) {
  const Icon = ICONS[tone];
  return (
    <Alert variant={tone} className={className}>
      <Icon aria-hidden="true" />
      {title && <AlertTitle>{title}</AlertTitle>}
      {children && <AlertDescription className="text-current">{children}</AlertDescription>}
    </Alert>
  );
}
