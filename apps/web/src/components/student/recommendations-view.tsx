"use client";

import { RefreshCw, Sparkles } from "lucide-react";
import * as React from "react";

import { SectionCard } from "@/components/cards/section-card";
import { PageHeader } from "@/components/layout/page-header";
import { EmptyState } from "@/components/states/empty-state";
import { InlineAlert } from "@/components/states/inline-alert";
import { DataView } from "@/components/student/data-view";
import { useSubmit } from "@/components/student/form-bits";
import { RecommendationPreferencesCard } from "@/components/student/recommendation-preferences";
import {
  RecommendationList,
  type RecommendationAction,
} from "@/components/student/recommendation-list";
import { Button } from "@/components/ui/button";
import type { FeedbackRating, FeedbackReason } from "@/lib/api/student-schemas";
import { useQuery } from "@/lib/hooks/use-query";
import { useStudentApi } from "@/lib/hooks/use-student-api";

export function RecommendationsView() {
  const api = useStudentApi();
  const open = useQuery("recommendations", () => api.recommendations());
  const history = useQuery("recommendation-history", () => api.recommendationHistory());
  const [busyId, setBusyId] = React.useState<string | null>(null);
  const refresh = useSubmit();
  const respond = useSubmit();

  async function reloadAll() {
    await Promise.all([open.reload(), history.reload()]);
  }

  function onRespond(id: string, action: RecommendationAction) {
    setBusyId(id);
    void respond
      .run(async () => {
        await api.respondToRecommendation(id, action);
        await reloadAll();
      }, "We couldn't update that suggestion.")
      .finally(() => setBusyId(null));
  }

  function onRate(id: string, rating: FeedbackRating, reason?: FeedbackReason) {
    setBusyId(id);
    void respond
      .run(async () => {
        await api.rateRecommendation(id, rating, reason);
        await reloadAll();
      }, "We couldn't save your answer.")
      .finally(() => setBusyId(null));
  }

  function onClearRating(id: string) {
    setBusyId(id);
    void respond
      .run(async () => {
        await api.clearRecommendationRating(id);
        await reloadAll();
      }, "We couldn't take back your answer.")
      .finally(() => setBusyId(null));
  }

  return (
    <>
      <PageHeader
        title="Suggestions"
        description="Ideas based on what you've shared with MindMitra. They're optional, and they aren't medical advice."
        actions={
          <Button
            variant="outline"
            disabled={refresh.pending}
            onClick={() =>
              void refresh.run(async () => {
                await api.refreshRecommendations();
                await reloadAll();
              }, "We couldn't look for new suggestions.")
            }
          >
            <RefreshCw
              className={refresh.pending ? "animate-spin" : undefined}
              aria-hidden="true"
            />
            Look for new ones
          </Button>
        }
      />
      {refresh.error && <InlineAlert tone="destructive">{refresh.error}</InlineAlert>}
      {respond.error && <InlineAlert tone="destructive">{respond.error}</InlineAlert>}
      <DataView query={open}>
        {(items) =>
          items.length === 0 ? (
            <EmptyState
              icon={Sparkles}
              title="No suggestions right now"
              description="Check in for a few days and ideas will appear here."
            />
          ) : (
            <RecommendationList
              items={items}
              onRespond={onRespond}
              onRate={onRate}
              onClearRating={onClearRating}
              busyId={busyId}
            />
          )
        }
      </DataView>
      <DataView query={history} skeleton={null}>
        {(items) => {
          const earlier = items.filter((i) => i.status === "completed" || i.status === "dismissed");
          return earlier.length === 0 ? null : (
            <SectionCard
              title="Earlier"
              description="Ones you've finished or set aside. Your answers help MindMitra suggest better ideas, and only you can see them."
            >
              <RecommendationList
                items={earlier}
                onRate={onRate}
                onClearRating={onClearRating}
                busyId={busyId}
              />
            </SectionCard>
          );
        }}
      </DataView>
      <RecommendationPreferencesCard />
    </>
  );
}
