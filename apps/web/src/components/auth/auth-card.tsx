import * as React from "react";

import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

/** The card every authentication page sits in: one <h1>, a short promise, then the form. */
export function AuthCard({
  title,
  description,
  children,
  footer,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
}) {
  return (
    <Card className="shadow-soft">
      <CardHeader className="space-y-1.5">
        <CardTitle>
          <h1 className="text-2xl font-semibold">{title}</h1>
        </CardTitle>
        {description && <CardDescription className="text-base">{description}</CardDescription>}
      </CardHeader>
      <CardContent className="space-y-5">{children}</CardContent>
      {footer && (
        <CardFooter className="flex-col items-start gap-2 text-sm text-muted-foreground">
          {footer}
        </CardFooter>
      )}
    </Card>
  );
}
