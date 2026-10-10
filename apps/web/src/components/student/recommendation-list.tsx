"use client";

import { Check, X } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { Recommendation } from "@/lib/api/student-schemas";
import { RESOURCE_TYPE_LABELS } from "@/lib/student-options";

export type RecommendationAction = "viewed" | "dismissed" | "completed";

/**
 * Suggestions with the reason for each. Compact mode (the dashboard) is read-only; the full
 * list lets the student mark one done or dismiss it.
 */
export function RecommendationList({
  items,
  compact = false,
  onRespond,
  busyId,
}: {
  items: Recommendation[];
  compact?: boolean;
  onRespond?: (id: string, action: RecommendationAction) => void;
  busyId?: string | null;
}) {
  return (
    <ul className="grid gap-3">
      {items.map((rec) => (
        <li key={rec.id} className="rounded-xl border bg-card p-4">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <h3 className="font-medium">{rec.title}</h3>
            {rec.source === "therapist" && <Badge variant="info">From your therapist</Badge>}
            {rec.status === "completed" && <Badge variant="success">Done</Badge>}
            {rec.status === "dismissed" && <Badge variant="outline">Dismissed</Badge>}
          </div>
          <p className="mt-1 text-sm text-muted-foreground">{rec.rationale}</p>
          {rec.resource && (
            <p className="mt-2 text-sm">
              <Link
                href={`/student/resources/${rec.resource.id}`}
                className="font-medium underline underline-offset-4"
                onClick={() => {
                  if (rec.status === "pending") onRespond?.(rec.id, "viewed");
                }}
              >
                {rec.resource.title}
              </Link>{" "}
              <span className="text-muted-foreground">
                ({RESOURCE_TYPE_LABELS[rec.resource.resource_type] ?? rec.resource.resource_type}
                {rec.resource.duration_minutes ? `, ${rec.resource.duration_minutes} min` : ""})
              </span>
            </p>
          )}
          {!compact && onRespond && (rec.status === "pending" || rec.status === "viewed") && (
            <div className="mt-3 flex flex-wrap gap-2">
              <Button
                size="sm"
                variant="outline"
                disabled={busyId === rec.id}
                onClick={() => onRespond(rec.id, "completed")}
              >
                <Check aria-hidden="true" />
                Mark as done
              </Button>
              <Button
                size="sm"
                variant="ghost"
                disabled={busyId === rec.id}
                onClick={() => onRespond(rec.id, "dismissed")}
              >
                <X aria-hidden="true" />
                Not for me
              </Button>
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}
