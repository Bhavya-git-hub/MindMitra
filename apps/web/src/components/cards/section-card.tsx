import * as React from "react";

import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";

/** The standard content block: a titled card with optional action and footer. */
export function SectionCard({
  title,
  description,
  action,
  footer,
  children,
  className,
  headingLevel: Heading = "h2",
}: {
  title: string;
  description?: string;
  action?: React.ReactNode;
  footer?: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
  headingLevel?: "h2" | "h3";
}) {
  return (
    <Card className={cn("shadow-soft", className)}>
      <CardHeader>
        <CardTitle>
          <Heading>{title}</Heading>
        </CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
        {action && <CardAction>{action}</CardAction>}
      </CardHeader>
      {children && <CardContent>{children}</CardContent>}
      {footer && <CardFooter>{footer}</CardFooter>}
    </Card>
  );
}
