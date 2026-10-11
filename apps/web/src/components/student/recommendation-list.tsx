"use client";

import { Check, ThumbsDown, ThumbsUp, X } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { FeedbackRating, FeedbackReason, Recommendation } from "@/lib/api/student-schemas";
import { FEEDBACK_REASONS } from "@/lib/api/student-schemas";
import { FEEDBACK_REASON_LABELS, RESOURCE_TYPE_LABELS } from "@/lib/student-options";
import { cn } from "@/lib/utils";

export type RecommendationAction = "viewed" | "dismissed" | "completed";

const NEXT_STEP: Record<string, { href: string; label: string }> = {
  book_counselling: { href: "/student/therapists", label: "Book a counselling session" },
  set_goal: { href: "/student/goals", label: "Set a goal" },
  check_in: { href: "/student/check-in", label: "Check in now" },
};

/**
 * Suggestions with the reason for each. Compact mode (the dashboard) is read-only; the full
 * list lets the student mark one done or dismiss it, and say whether it was helpful.
 */
export function RecommendationList({
  items,
  compact = false,
  onRespond,
  onRate,
  onClearRating,
  busyId,
}: {
  items: Recommendation[];
  compact?: boolean;
  onRespond?: (id: string, action: RecommendationAction) => void;
  onRate?: (id: string, rating: FeedbackRating, reason?: FeedbackReason) => void;
  onClearRating?: (id: string) => void;
  busyId?: string | null;
}) {
  return (
    <ul className="grid gap-3">
      {items.map((rec) => {
        const step = NEXT_STEP[rec.action];
        return (
          <li key={rec.id} className="rounded-xl border bg-card p-4">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <h3 className="font-medium">{rec.title}</h3>
              {rec.source === "therapist" && <Badge variant="info">From your therapist</Badge>}
              {rec.status === "completed" && <Badge variant="success">Done</Badge>}
              {rec.status === "dismissed" && <Badge variant="outline">Set aside</Badge>}
              {!onRate && rec.feedback?.rating === "helpful" && (
                <Badge variant="success">You found this helpful</Badge>
              )}
              {!onRate && rec.feedback?.rating === "not_helpful" && (
                <Badge variant="outline">You said not helpful</Badge>
              )}
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
            {step && !compact && (rec.status === "pending" || rec.status === "viewed") && (
              <p className="mt-2 text-sm">
                <Link href={step.href} className="font-medium underline underline-offset-4">
                  {step.label}
                </Link>
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
            {!compact && onRate && (
              <FeedbackControls
                rec={rec}
                busy={busyId === rec.id}
                onRate={onRate}
                onClear={onClearRating}
              />
            )}
          </li>
        );
      })}
    </ul>
  );
}

/**
 * "Was this helpful?" The answer only tunes this student's own future suggestions. "Not
 * helpful" opens a short list of reasons, each optional, so it never asks for free text.
 */
function FeedbackControls({
  rec,
  busy,
  onRate,
  onClear,
}: {
  rec: Recommendation;
  busy: boolean;
  onRate: (id: string, rating: FeedbackRating, reason?: FeedbackReason) => void;
  onClear?: (id: string) => void;
}) {
  const [asking, setAsking] = React.useState(false);
  const rating = rec.feedback?.rating ?? null;
  const labelId = React.useId();

  function choose(next: FeedbackRating) {
    if (rating === next) {
      setAsking(false);
      onClear?.(rec.id);
      return;
    }
    if (next === "not_helpful") {
      setAsking(true);
      return;
    }
    setAsking(false);
    onRate(rec.id, next);
  }

  return (
    <div className="mt-3 space-y-2 border-t pt-3">
      <div role="group" aria-labelledby={labelId} className="flex flex-wrap items-center gap-2">
        <span id={labelId} className="text-sm text-muted-foreground">
          Was this helpful?
        </span>
        <Button
          size="sm"
          variant={rating === "helpful" ? "default" : "outline"}
          aria-pressed={rating === "helpful"}
          disabled={busy}
          onClick={() => choose("helpful")}
        >
          <ThumbsUp aria-hidden="true" />
          Helpful
        </Button>
        <Button
          size="sm"
          variant={rating === "not_helpful" || asking ? "default" : "outline"}
          aria-pressed={rating === "not_helpful"}
          disabled={busy}
          onClick={() => choose("not_helpful")}
        >
          <ThumbsDown aria-hidden="true" />
          Not helpful
        </Button>
      </div>
      {(asking || rating === "not_helpful") && (
        <fieldset className="space-y-2">
          <legend className="text-sm font-medium">What didn&apos;t work? (optional)</legend>
          <div className="flex flex-wrap gap-2">
            {FEEDBACK_REASONS.map((reason) => {
              const selected = rec.feedback?.reason === reason;
              return (
                <button
                  key={reason}
                  type="button"
                  aria-pressed={selected}
                  disabled={busy}
                  onClick={() => {
                    setAsking(false);
                    onRate(rec.id, "not_helpful", reason);
                  }}
                  className={cn(
                    "inline-flex min-h-10 items-center gap-1.5 rounded-full border px-4 text-sm transition-colors",
                    "focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none",
                    selected
                      ? "border-primary bg-primary text-primary-foreground"
                      : "bg-card hover:bg-accent",
                  )}
                >
                  {selected && <Check className="size-4" aria-hidden="true" />}
                  {FEEDBACK_REASON_LABELS[reason]}
                </button>
              );
            })}
            {asking && rating !== "not_helpful" && (
              <Button
                size="sm"
                variant="ghost"
                disabled={busy}
                onClick={() => {
                  setAsking(false);
                  onRate(rec.id, "not_helpful");
                }}
              >
                Skip
              </Button>
            )}
          </div>
        </fieldset>
      )}
    </div>
  );
}
